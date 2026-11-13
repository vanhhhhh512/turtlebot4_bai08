"""Pure decision logic. Monotonic seconds, metres, radians; no ML/ROS imports."""

import math

LABELS = ("angry", "disgust", "fear", "happy", "sad", "surprise", "neutral")
DEFAULT = dict(
    confidence=0.55,
    margin=0.18,
    hold=0.40,
    neutral_hold=0.6,
    prediction_timeout=0.9,
    rearm_window=8.0,
    odom_timeout=0.5,
    clock_timeout=0.6,
    linear=0.10,
    angular=0.35,
    distance=0.23,
    backup=0.17,
    arc=math.pi / 3,
    turn=2 * math.pi,
    action_timeout=35.0,
    ema=0.55,
    release_confidence=0.40,
    release_margin=0.06,
    interruption_hold=0.30,
)


def wrap(a):
    return math.atan2(math.sin(a), math.cos(a))


class Controller:
    def __init__(self, session, config=None, allow_test=False):
        self.cfg = dict(DEFAULT, **(config or {}))
        self.session, self.allow_test = session, allow_test
        self.last_seq, self.capture_at, self.last_pred = -1, -1e9, -1e9
        self.odom_at = self.clock_at = -1e9
        self.pose = None
        self.speed = (0.0, 0.0)
        self.raw = self.stable = None
        self.scores = None
        self.candidate, self.candidate_at = None, 0.0
        self.armed, self.enabled = False, True
        self.armed_until = -1e9
        self.action = None
        self.uncertain_since = None
        self.events = []
        self.state, self.reason = "LOADING", "WAIT_MODEL_ROBOT"
        self.counter = 0
        self.prepared = False
        self.hazard = False
        self.external_publisher = False

    def emit(self, event, now, **kw):
        self.events.append(dict(event=event, monotonic=now, **kw))

    def cancel(self, reason, now):
        if self.action:
            self.emit("ACTION_END", now, **self.action, reason=reason, pose=self.pose)
        self.action = None
        self.uncertain_since = None
        self.speed = (0.0, 0.0)
        self.armed = False
        self.candidate = None
        self.stable = None
        self.scores = None
        self.reason = reason
        self.state = "STOPPED"

    def odom(self, x, y, yaw, v, w, now):
        if not all(math.isfinite(a) for a in (x, y, yaw, v, w)):
            return self.cancel("BAD_ODOM", now)
        if self.pose and self.action:
            a = self.action
            d = math.hypot(x - self.pose[0], y - self.pose[1])
            dy = wrap(yaw - self.pose[2])
            if d > 0.3 or abs(dy) > 0.6:
                self.cancel("ODOM_JUMP", now)
            else:
                a["distance"] += d
                a["yaw"] += dy
                a["max_center_drift"] = max(
                    a["max_center_drift"],
                    math.hypot(x - a["origin"][0], y - a["origin"][1]),
                )
        self.pose = (x, y, yaw)
        self.measured = (v, w)
        self.odom_at = now

    def prediction(self, p, now):
        # Replayed/mismatched packets cannot refresh watchdog or change state.
        try:
            seq = p["seq"]
            stamp = p["capture_mono"]
            if (
                p["session"] != self.session
                or not isinstance(seq, int)
                or seq <= self.last_seq
            ):
                return False
            if (
                not math.isfinite(stamp)
                or stamp <= self.capture_at
                or stamp > now + 0.05
                or now - stamp > self.cfg["prediction_timeout"]
            ):
                return False
            if p.get("source") != "webcam" and not self.allow_test:
                return False
            self.last_seq, self.capture_at, self.last_pred = seq, stamp, now
            if (
                p.get("status") != "OK"
                or p.get("faces") != 1
                or p.get("identity_changed")
            ):
                self.raw = None
                self.cancel(
                    (
                        p.get("status", "FACE_INVALID")
                        if p.get("status") != "OK"
                        else (
                            "FACE_COUNT_MISMATCH"
                            if p.get("faces") != 1
                            else "FACE_CHANGED"
                        )
                    ),
                    now,
                )
                return True
            s = p["scores"]
            if (
                set(s) != set(LABELS)
                or not all(math.isfinite(v) and 0 <= v <= 1 for v in s.values())
                or not 0.98 <= sum(s.values()) <= 1.02
            ):
                raise ValueError("scores invalid")
            raw = sorted(s, key=s.get, reverse=True)
            self.raw = raw[0]
            confident = (
                s[raw[0]] >= self.cfg["confidence"]
                and s[raw[0]] - s[raw[1]] >= self.cfg["margin"]
            )
            if self.raw == "disgust":
                self.cancel("OUTSIDE_SET", now)
                return True
            if self.action and self.raw == "neutral" and confident:
                self.cancel("NEUTRAL", now)
                return True
            if self.scores is None:
                self.scores = dict(s)
            else:
                alpha = self.cfg["ema"]
                self.scores = {
                    k: alpha * s[k] + (1 - alpha) * self.scores[k] for k in s
                }
            order = sorted(self.scores, key=self.scores.get, reverse=True)
            label = order[0]
            if self.action:
                # A single noisy raw frame must not bypass the temporal filter.
                # Use a lower release threshold than the starting threshold;
                # persistent uncertainty still cancels, with no automatic resume.
                supported = (
                    label == self.action["label"]
                    and self.scores[label] >= self.cfg["release_confidence"]
                    and self.scores[label] - self.scores[order[1]]
                    >= self.cfg["release_margin"]
                )
                if supported:
                    self.uncertain_since = None
                elif self.uncertain_since is None:
                    self.uncertain_since = now
                elif now - self.uncertain_since >= self.cfg["interruption_hold"]:
                    self.cancel(
                        "LABEL_CHANGED" if label != self.action["label"]
                        and self.scores[label] >= self.cfg["confidence"]
                        else "LOW_CONFIDENCE", now,
                    )
                return True
            filtered_confident = (
                self.scores[label] >= self.cfg["confidence"]
                and self.scores[label] - self.scores[order[1]] >= self.cfg["margin"]
            )
            # A clear Neutral frame must never launch a lagging EMA action.
            if self.raw == "neutral" and confident and label != "neutral":
                self.candidate = None
                return True
            if not filtered_confident:
                # A human passes through uncertain scores while changing face.
                # Only an unused Neutral permit may survive this short idle gap;
                # an interrupted action has already been canceled and disarmed.
                if self.armed and not self.action and now <= self.armed_until:
                    self.speed = (0.0, 0.0)
                    self.state, self.reason = "STOPPED", "LOW_CONFIDENCE_WAIT_STABLE"
                    self.candidate = None
                    self.stable = None
                else:
                    self.cancel("LOW_CONFIDENCE", now)
                return True
            if (
                self.scores[label] < self.cfg["confidence"]
                or self.scores[label] - self.scores[order[1]] < self.cfg["margin"]
            ):
                self.candidate = None
                return True
            if label != self.candidate:
                self.candidate, self.candidate_at = label, now
            hold = self.cfg["neutral_hold"] if label == "neutral" else self.cfg["hold"]
            if now - self.candidate_at >= hold:
                self.stable = label
                if label == "neutral" and self.enabled and self.healthy(now):
                    self.armed = True
                    self.armed_until = now + self.cfg["rearm_window"]
                    self.state, self.reason = "READY", "NEUTRAL_REARMED"
                elif (
                    self.armed
                    and now <= self.armed_until
                    and not self.action
                    and self.enabled
                    and self.healthy(now)
                ):
                    self.start(label, now)
                elif not self.armed and self.enabled and self.healthy(now):
                    self.state, self.reason = "WAIT_NEUTRAL", "REQUIRE_NEUTRAL"
            return True
        except (KeyError, TypeError, ValueError, OverflowError):
            self.cancel("MALFORMED_PREDICTION", now)
            return False

    def healthy(self, now):
        return (
            self.prepared
            and self.pose is not None
            and now - self.odom_at < self.cfg["odom_timeout"]
            and now - self.clock_at < self.cfg["clock_timeout"]
            and not self.hazard
            and not self.external_publisher
        )

    def start(self, label, now):
        if label not in ("happy", "sad", "angry", "fear", "surprise"):
            return
        self.counter += 1
        self.uncertain_since = None
        self.action = dict(
            id=self.counter,
            label=label,
            start=now,
            origin=self.pose,
            distance=0.0,
            yaw=0.0,
            max_center_drift=0.0,
        )
        self.armed = False
        self.state, self.reason = "EXECUTING", label
        self.emit("ACTION_START", now, **self.action)

    def tick(self, now):
        issue = (
            "GUI_STOP"
            if not self.enabled
            else (
                "OTHER_CMD_PUBLISHER"
                if self.external_publisher
                else (
                    "HAZARD"
                    if self.hazard
                    else (
                        "ROBOT_NOT_PREPARED"
                        if not self.prepared
                        else (
                            "ODOM_STALE"
                            if now - self.odom_at >= self.cfg["odom_timeout"]
                            else (
                                "CLOCK_STALE"
                                if now - self.clock_at >= self.cfg["clock_timeout"]
                                else (
                                    "PREDICTION_STALE"
                                    if now - self.capture_at
                                    >= self.cfg["prediction_timeout"]
                                    else None
                                )
                            )
                        )
                    )
                )
            )
        )
        if issue:
            self.cancel(issue, now)
            return (0.0, 0.0)
        if self.armed and now > self.armed_until:
            self.cancel("REARM_WINDOW_EXPIRED", now)
        if self.action:
            a = self.action
            l = a["label"]
            cfg = self.cfg
            target = (
                cfg["arc"]
                if l in ("happy", "sad")
                else (
                    cfg["turn"]
                    if l == "surprise"
                    else cfg["backup"] if l == "angry" else cfg["distance"]
                )
            )
            amount = (
                (-a["yaw"] if l == "sad" else a["yaw"])
                if l in ("happy", "sad", "surprise")
                else a["distance"]
            )
            a["progress"] = max(0.0, min(1.0, amount / target))
            if amount >= target:
                self.emit("ACTION_END", now, **a, reason="completed", pose=self.pose)
                self.action = None
                self.state, self.reason = "WAIT_NEUTRAL", "COMPLETED"
            elif now - a["start"] > cfg["action_timeout"]:
                self.cancel("ACTION_TIMEOUT", now)
            else:
                v = (
                    0.0
                    if l == "surprise"
                    else -cfg["linear"] if l == "angry" else cfg["linear"]
                )
                w = (
                    cfg["angular"]
                    if l in ("happy", "surprise")
                    else -cfg["angular"] if l == "sad" else 0.0
                )
                self.speed = (v, w)
                return self.speed
        self.speed = (0.0, 0.0)
        if self.state == "LOADING":
            self.state, self.reason = "WAIT_NEUTRAL", "MODEL_ROBOT_READY"
        return self.speed
