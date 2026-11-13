"""Bounded odometry history, labelled only by confirmed controller actions."""
import math

COLORS = dict(happy="#0072BD", sad="#D95319", angry="#A2142F",
              fear="#77AC30", surprise="#7E2F8E", neutral="#6B7280")


class Trajectory:
    def __init__(self):
        self.segments = []
        self.markers = []
        self.current = None
        self.last_pose = None
        self.serial = 0
        self.revision = 0

    def boundary(self, pose, now, action=None):
        self.serial += 1
        self.current = dict(segment_id=self.serial,
                            action_id=action["id"] if action else None,
                            label=action["label"] if action else None,
                            start=now, end=None, reason=None, points=[], yaw=0.0)
        self.segments.append(self.current)
        self._point(pose, now)

    def _point(self, pose, now):
        self.current["points"].append([pose[0], pose[1], now])
        self.current["pose"] = list(pose)
        self.revision += 1
        # Bound both stationary actions and samples in long sessions.
        self.segments = self.segments[-300:]
        while sum(len(s["points"]) for s in self.segments) > 3000:
            if len(self.segments[0]["points"]) > 1:
                self.segments[0]["points"].pop(0)
            else:
                self.segments.pop(0)

    def event(self, event, pose):
        kind, now = event["event"], event["monotonic"]
        if pose is None:
            return
        if kind == "ACTION_START":
            if self.current and self.current["end"] is None:
                self.current.update(end=now, reason="action_boundary")
            self.boundary(event.get("origin") or pose, now, event)
        elif kind == "ACTION_END":
            for s in reversed(self.segments):
                if s["action_id"] == event["id"]:
                    s.update(end=now, reason=event["reason"], yaw=event["yaw"])
                    break
            if self.current and self.current["action_id"] == event["id"]:
                self.current = None
            self.revision += 1
        elif kind == "DECISION_ACCEPTED" and event["label"] == "neutral":
            self.markers.append(dict(label="neutral", action_id=event["action_id"],
                                     monotonic=now, pose=list(pose)))
            self.markers = self.markers[-100:]
            self.revision += 1

    def observe(self, pose, now, action):
        if pose is None or not all(math.isfinite(v) for v in pose):
            return
        jump = self.last_pose and (math.hypot(pose[0] - self.last_pose[0],
                                              pose[1] - self.last_pose[1]) > .3 or
                                  abs(math.atan2(math.sin(pose[2]-self.last_pose[2]),
                                                 math.cos(pose[2]-self.last_pose[2]))) > .6)
        key = (action["id"], action["label"]) if action else (None, None)
        if jump or self.current is None or key != (self.current["action_id"], self.current["label"]):
            if self.current and self.current["end"] is None:
                self.current.update(end=now, reason="odom_jump" if jump else "action_boundary")
            self.boundary(pose, now, action)
        else:
            p = self.current["points"][-1]
            if math.hypot(pose[0] - p[0], pose[1] - p[1]) > .008:
                self._point(pose, now)
            self.current["pose"] = list(pose)
            self.current["yaw"] = action.get("yaw", 0.0) if action else 0.0
        self.last_pose = tuple(pose)
