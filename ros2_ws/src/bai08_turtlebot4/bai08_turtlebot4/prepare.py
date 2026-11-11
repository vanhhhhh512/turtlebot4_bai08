"""Prepare only this Gazebo session: active wheel controllers, then undock."""
import json
import time

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from controller_manager_msgs.srv import ConfigureController, ListControllers, LoadController, SwitchController
from rcl_interfaces.srv import GetParameters
from irobot_create_msgs.action import Undock
from irobot_create_msgs.msg import DockStatus
from nav_msgs.msg import Odometry
from std_msgs.msg import String


class SimulationReadyNode(Node):
    def __init__(self):
        super().__init__('simulation_ready_node')
        self.pub = self.create_publisher(String, '/simulation_ready', 1)
        self.docked = None
        self.odom_at = -1e9
        self.initialized = False
        self.reason = 'WAITING_FOR_CONTROLLERS'
        self.create_subscription(DockStatus, '/dock_status', self.on_dock, qos_profile_sensor_data)
        self.create_subscription(Odometry, '/odom', self.on_odom, qos_profile_sensor_data)
        self.create_timer(0.2, self.publish)
        self.service_clients = {
            'list': self.create_client(ListControllers, '/controller_manager/list_controllers'),
            'load': self.create_client(LoadController, '/controller_manager/load_controller'),
            'configure': self.create_client(ConfigureController, '/controller_manager/configure_controller'),
            'switch': self.create_client(SwitchController, '/controller_manager/switch_controller'),
            'config': self.create_client(GetParameters, '/motion_control/get_parameters'),
        }
        self.undock = ActionClient(self, Undock, '/undock')

    def on_dock(self, msg):
        self.docked = msg.is_docked

    def on_odom(self, msg):
        self.odom_at = time.monotonic()

    def publish(self):
        ready = self.initialized and self.docked is False and time.monotonic() - self.odom_at < 1.0
        reason = ('READY' if ready else 'DOCKED' if self.initialized and self.docked
                  else 'WAITING_FOR_ODOM' if self.initialized else self.reason)
        self.pub.publish(String(data=json.dumps(dict(ready=ready, reason=reason))))

    def pump(self, seconds):
        until = time.monotonic() + seconds
        while rclpy.ok() and time.monotonic() < until:
            rclpy.spin_once(self, timeout_sec=min(0.1, max(0.0, until - time.monotonic())))

    def await_future(self, future, timeout=20):
        until = time.monotonic() + timeout
        while rclpy.ok() and not future.done() and time.monotonic() < until:
            rclpy.spin_once(self, timeout_sec=0.1)
        if not future.done():
            future.cancel()
            return None
        return future.result()

    def call(self, key, request):
        client = self.service_clients[key]
        if not client.service_is_ready():
            return None
        return self.await_future(client.call_async(request))

    def prepare(self):
        deadline = time.monotonic() + 180
        names = ('joint_state_broadcaster', 'diffdrive_controller')
        while rclpy.ok() and time.monotonic() < deadline:
            response = self.call('list', ListControllers.Request())
            if response is None:
                self.pump(0.5)
                continue
            states = {c.name: c.state for c in response.controller}
            if all(states.get(name) == 'active' for name in names):
                break
            self.get_logger().info(f'Preparing controllers: {states}')
            for name in names:
                state = states.get(name)
                if state is None:
                    self.call('load', LoadController.Request(name=name))
                elif state == 'unconfigured':
                    self.call('configure', ConfigureController.Request(name=name))
                elif state == 'inactive':
                    request = SwitchController.Request(
                        activate_controllers=[name], strictness=2, activate_asap=True)
                    request.timeout.sec = 10
                    self.call('switch', request)
            # Re-query after every operation: a timed-out response does not
            # imply that loading/configuration failed on the server.
            self.pump(0.5)
        else:
            raise RuntimeError('Controller preparation timed out')
        self.reason = 'CHECKING_SIMULATION_CONFIG'
        while rclpy.ok() and time.monotonic() < deadline:
            response = self.call('config', GetParameters.Request(names=['safety_override']))
            if response is not None and response.values:
                if response.values[0].string_value != 'backup_only':
                    raise RuntimeError('motion_control did not load config/simulation.yaml')
                self.get_logger().info('Verified launch configuration: safety_override=backup_only')
                break
            self.pump(0.5)
        else:
            raise RuntimeError('Cannot verify motion_control launch configuration')
        self.reason = 'WAITING_FOR_DOCK_AND_ODOM'
        while rclpy.ok() and time.monotonic() < deadline:
            if self.docked is not None and time.monotonic() - self.odom_at < 1.0:
                break
            self.pump(0.2)
        for _ in range(2):
            if self.docked is False:
                self.initialized = True
                self.reason = 'READY'
                self.get_logger().info('ROBOT_READY: controllers active, undocked, odometry fresh')
                self.publish()
                return
            self.reason = 'UNDOCKING'
            if not self.undock.wait_for_server(timeout_sec=5):
                self.pump(0.5)
                continue
            goal = self.await_future(self.undock.send_goal_async(Undock.Goal()))
            if goal is not None and goal.accepted:
                result = self.await_future(goal.get_result_async(), timeout=65)
                self.get_logger().info(f'Undock result: {result}')
                if result is None:
                    self.await_future(goal.cancel_goal_async(), timeout=5)
            self.pump(0.5)
        if self.docked is False:
            self.initialized = True
            self.reason = 'READY'
            return
        raise RuntimeError('Undock failed; gesture motion stays blocked')


def main():
    rclpy.init()
    node = SimulationReadyNode()
    try:
        node.prepare()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        node.reason = f'PREPARATION_FAILED: {exc}'
        node.get_logger().error(node.reason)
        if rclpy.ok():
            rclpy.spin(node)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
