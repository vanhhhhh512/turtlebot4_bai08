import json, math, time, os, signal
from collections import Counter
from pathlib import Path
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rosgraph_msgs.msg import Clock
from irobot_create_msgs.msg import HazardDetectionVector
from std_msgs.msg import String
from .core import Controller
from .ipc import atomic, read


class Motion(Node):
    def __init__(self):
        super().__init__("bai08_controller")
        self.declare_parameter("run_dir", "/tmp/bai08_run")
        self.declare_parameter("allow_test", False)
        self.run = Path(self.get_parameter("run_dir").value)
        self.run.mkdir(parents=True, exist_ok=True)
        self.session = self.run.name
        self.core = Controller(
            self.session,
            read(self.run / "control_config.json"),
            self.get_parameter("allow_test").value,
        )
        atomic(self.run / "effective_config.json", self.core.cfg)
        self.log = (self.run / "control.jsonl").open("a", buffering=1)
        self.odom_log = (self.run / "odom.jsonl").open("a", buffering=1)
        self.pub = self.create_publisher(Twist, "/cmd_vel", 10)
        self.create_subscription(
            Odometry, "/odom", self.on_odom, qos_profile_sensor_data
        )
        self.create_subscription(
            Clock, "/clock", self.on_clock, qos_profile_sensor_data
        )
        self.create_subscription(
            HazardDetectionVector,
            "/hazard_detection",
            self.on_hazard,
            qos_profile_sensor_data,
        )
        self.create_subscription(String, "/simulation_ready", self.on_ready, 10)
        self.last_clock = None
        self.last_command = None
        self.path = []
        self.hazard_types = []
        self.tick_count = 0
        self.cmd_seq = -1
        self.clock_publishers = 0
        # Default wall/steady timer: do not enable use_sim_time on this node.
        self.create_timer(0.05, self.tick)
        self.create_timer(0.5, self.check_graph)

    def on_ready(self, m):
        try:
            self.core.prepared = bool(json.loads(m.data)["ready"])
        except (ValueError, KeyError):
            self.core.prepared = False

    def on_clock(self, m):
        stamp = m.clock.sec + m.clock.nanosec / 1e9
        if self.last_clock != stamp:
            self.core.clock_at = time.monotonic()
        self.last_clock = stamp

    def on_hazard(self, m):
        self.hazard_types = [int(d.type) for d in m.detections]
        # 0 BACKUP_LIMIT is bypassed only for this simulation via backup_only;
        # bump/cliff/stall/wheel-drop/object proximity still stop here.
        self.core.hazard = any(t != 0 for t in self.hazard_types)

    def on_odom(self, m):
        now = time.monotonic()
        p = m.pose.pose
        q = p.orientation
        yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
        x, y = p.position.x, p.position.y
        self.core.odom(x, y, yaw, m.twist.twist.linear.x, m.twist.twist.angular.z, now)
        self.odom_log.write(
            json.dumps(
                dict(
                    monotonic=now,
                    wall=time.time(),
                    ros_stamp=m.header.stamp.sec + m.header.stamp.nanosec / 1e9,
                    x=x,
                    y=y,
                    yaw=yaw,
                    v=m.twist.twist.linear.x,
                    w=m.twist.twist.angular.z,
                )
            )
            + "\n"
        )
        if (
            not self.path
            or math.hypot(x - self.path[-1][0], y - self.path[-1][1]) > 0.008
        ):
            self.path.append((x, y))
            self.path = self.path[-3000:]

    def check_graph(self):
        infos = self.get_publishers_info_by_topic("/cmd_vel")
        self.core.external_publisher = len(infos) != 1 or any(
            i.node_name != "bai08_controller" for i in infos
        )
        self.clock_publishers = len(self.get_publishers_info_by_topic("/clock"))
        self.core.external_clock = self.clock_publishers != 1

    def publish(self, v, w):
        msg = Twist()
        msg.linear.x = v
        msg.angular.z = w
        self.pub.publish(msg)

    def tick(self):
        now = time.monotonic()
        # STOP latch is independent of ML. START consumes new command only.
        cmd = read(self.run / "ui_command.json")
        if (self.run / "STOP").exists():
            self.core.enabled = False
        if cmd.get("session") == self.session and cmd.get("seq", -1) > self.cmd_seq:
            self.cmd_seq = cmd["seq"]
            if cmd.get("command") == "START" and now - cmd.get("monotonic", 0) < 1:
                self.core.enabled = True
                (self.run / "STOP").unlink(missing_ok=True)
                self.core.cancel("START_REQUIRE_NEUTRAL", now)
        p = read(self.run / "prediction.json")
        self.core.prediction(p, now) if p else None
        v, w = self.core.tick(now)
        self.publish(v, w)
        while self.core.events:
            e = self.core.events.pop(0)
            e.update(wall=time.time(), session=self.session,
                     source=p.get("source") if isinstance(p, dict) else None)
            self.log.write(json.dumps(e) + "\n")
        self.tick_count += 1
        status = dict(
            session=self.session,
            monotonic=now,
            wall=time.time(),
            state=self.core.state,
            reason=self.core.reason,
            raw=self.core.raw,
            stable=self.core.stable,
            vote_counts=dict(Counter(k for _, k in self.core.votes if k)),
            vote_min=self.core.cfg["vote_min"],
            vote_window=self.core.cfg["vote_window"],
            decision_mode=self.core.cfg["decision_mode"],
            armed=self.core.armed,
            enabled=self.core.enabled,
            permit_remaining_s=(
                max(0.0, self.core.armed_until - now) if self.core.armed else 0.0
            ),
            prepared=self.core.prepared,
            odom_age=now - self.core.odom_at,
            clock_age=now - self.core.clock_at,
            prediction_age=now - self.core.capture_at,
            v=v,
            w=w,
            pose=self.core.pose,
            measured=getattr(self.core, "measured", None),
            action=self.core.action,
            hazards=self.hazard_types,
            cmd_publishers=len(self.get_publishers_info_by_topic("/cmd_vel")),
            clock_publishers=self.clock_publishers,
        )
        self.log.write(json.dumps(dict(event="CONTROL", **status)) + "\n")
        if self.tick_count % 2 == 0:
            atomic(self.run / "status.json", dict(**status, path=self.path))


def main():
    rclpy.init()
    node = Motion()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if rclpy.ok():
            for _ in range(5):
                node.publish(0.0, 0.0)
        node.log.close()
        node.odom_log.close()
        node.destroy_node()
        rclpy.try_shutdown()
