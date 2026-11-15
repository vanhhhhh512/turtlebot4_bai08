"""Pure decision logic. Monotonic seconds, metres, radians; no ML/ROS imports."""

import math
from collections import Counter, deque
from .temporal import TemporalScores

LABELS = ("angry", "disgust", "fear", "happy", "sad", "surprise", "neutral")
DEFAULT = dict(
    decision_mode="temporal",
    temporal_window=0.50,
    temporal_hold=0.20,
    temporal_confidence=0.55,
    temporal_margin=0.15,
    temporal_max_gap=0.35,
    temporal_min_samples=3,
    temporal_low_hold=0.50,
    change_predictions=2,
    face_release_seconds=1.0,
    vote_window=57,
    vote_min=11,
    vote_confidence=0.40,
    vote_margin=0.06,
    score_fast_threshold=0.57,
    neutral_stop_hold=0.80,
    vote_low_hold=0.50,
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
        if self.cfg["decision_mode"] not in ("temporal", "events", "votes", "ema"):
            raise ValueError("Unknown decision_mode")
        self.event_mode = self.cfg["decision_mode"] in ("events", "temporal")
        self.temporal = TemporalScores(**{
            k: self.cfg["temporal_" + k] for k in
            ("window", "hold", "confidence", "margin", "max_gap", "min_samples")})
        self.session, self.allow_test = session, allow_test
        self.last_seq, self.capture_at, self.last_pred = -1, -1e9, -1e9
        self.last_frame = -1
        self.odom_at = self.clock_at = -1e9
        self.pose = None
        self.speed = (0.0, 0.0)
        self.raw = self.stable = None
        self.scores = None
        self.candidate, self.candidate_at = None, 0.0
        self.armed, self.enabled = False, True
        self.armed_until = -1e9
        self.action = None
        self.confirmation = None
        self.locked_label = None
        self.change_label, self.change_count = None, 0
        self.absence_since = self.absence_last = None
        self.fault_latched = None
        self.ever_ready = False
        self.accept_after = -1e9
        self.uncertain_since = None
        self.votes = deque(maxlen=int(self.cfg["vote_window"]))
        self.neutral_since = None
        self.events = []
        self.state, self.reason = "LOADING", "WAIT_MODEL_ROBOT"
        self.counter = 0
        self.prepared = False
        self.hazard = False
        self.external_publisher = False
        self.external_clock = False

    def emit(self, event, now, **kw):
        self.events.append(dict(event=event, monotonic=now, **kw))

    def cancel(self, reason, now):
        self.temporal.reset()
        if self.event_mode:
            hard = reason in {
                "GUI_STOP", "OTHER_CMD_PUBLISHER", "OTHER_CLOCK_PUBLISHER", "HAZARD",
                "ROBOT_NOT_PREPARED", "ODOM_STALE", "CLOCK_STALE", "BAD_ODOM",
                "ODOM_JUMP", "ACTION_TIMEOUT", "CAMERA_ERROR", "INFERENCE_ERROR",
                "MALFORMED_PREDICTION", "PREDICTION_STALE",
            }
            if hard and (self.ever_ready or self.action or reason == "GUI_STOP"):
                self.fault_latched = self.fault_latched or reason
            self.change_label, self.change_count = None, 0
            if reason != "NO_FACE":
                self.absence_since = self.absence_last = None
        if self.action:
            self.emit("ACTION_END", now, **self.action, reason=reason, pose=self.pose)
        self.action = None
        self.uncertain_since = None
        self.votes.clear()
        self.neutral_since = None
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
                # Forward displacement in the robot frame, with its sign.
                heading = self.pose[2] + dy / 2
                a["signed_distance"] += ((x - self.pose[0]) * math.cos(heading)
                                         + (y - self.pose[1]) * math.sin(heading))
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
        if not isinstance(p, dict):
            self.cancel("MALFORMED_PREDICTION", now)
            return False
        if p.get("session") != self.session:
            return False
        if p.get("source") != "webcam" and not self.allow_test:
            return False
        try:
            seq = p["seq"]
            frame_id = p["frame_id"]
            stamp = p["capture_mono"]
            if (
                type(seq) is not int
                or seq <= self.last_seq
                or type(frame_id) is not int
                or frame_id <= self.last_frame
            ):
                return False
            if (
                not math.isfinite(stamp)
                or stamp <= self.capture_at
                or (self.event_mode and stamp <= self.accept_after)
                or stamp > now + 0.05
                or now - stamp > self.cfg["prediction_timeout"]
            ):
                return False
            self.last_seq, self.capture_at, self.last_pred = seq, stamp, now
            self.last_frame = frame_id
            if (
                p.get("status") != "OK"
                or p.get("faces") != 1
                or p.get("identity_changed")
            ):
                self.raw = None
                reason = (p.get("status", "FACE_INVALID") if p.get("status") != "OK"
                          else "FACE_COUNT_MISMATCH" if p.get("faces") != 1
                          else "FACE_CHANGED")
                self.cancel(reason, now)
                if self.event_mode and reason == "NO_FACE" and p.get("faces") == 0:
                    self.observe_absence(now)
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
            if self.event_mode:
                self.absence_since = self.absence_last = None
                if self.cfg["decision_mode"] == "temporal":
                    self.temporal_prediction(s, raw, now)
                else:
                    self.event_prediction(s, raw, confident, now)
                return True
            # Expiry must be checked before the new frame can launch an action.
            if self.armed and now > self.armed_until:
                self.cancel("REARM_WINDOW_EXPIRED", now)
            if self.cfg["decision_mode"] == "votes":
                self.vote_prediction(s, raw, confident, now)
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

    def request_start(self, now):
        """An explicit START acknowledges faults and opens a fresh input round."""
        self.enabled = True
        self.cancel("START_WAIT_PREDICTION" if self.event_mode
                    else "START_REQUIRE_NEUTRAL", now)
        if self.event_mode:
            self.fault_latched = None
            self.locked_label = None
            self.accept_after = now
            self.ever_ready = True
            self.state, self.reason = "WAIT_INPUT", "WAIT_PREDICTION"

    def release_expression(self, cause, now):
        self.temporal.reset()
        if self.locked_label is not None:
            self.emit("EXPRESSION_RELEASED", now, label=self.locked_label,
                      cause=cause, seq=self.last_seq, frame_id=self.last_frame)
            self.locked_label = None
            self.votes.clear()
        self.change_label, self.change_count = None, 0

    def observe_absence(self, now):
        # Only consecutive, fresh NO_FACE packets count as a release gesture.
        # Camera failure, silence, multiple faces and replay cannot unlock.
        if not self.enabled or self.fault_latched:
            return
        if (self.absence_last is None or
                self.capture_at - self.absence_last >= self.cfg["prediction_timeout"]):
            self.absence_since = self.capture_at
        self.absence_last = self.capture_at
        if self.capture_at - self.absence_since >= self.cfg["face_release_seconds"]:
            self.release_expression("face_absence", now)

    def temporal_prediction(self, scores, order, now):
        """The event lifecycle with one causal score filter for every new label."""
        if not self.enabled or not self.healthy(now) or self.fault_latched:
            self.temporal.reset()
            return
        self.ever_ready = True
        result = self.temporal.add(self.capture_at, scores)
        label, mean = result["label"], result["scores"]
        if self.action:
            self.stable = self.action["label"]
            if result["confirmed"] and label == "neutral":
                ident = self.action["id"]
                # Keep the actual confirming window in the audit before reset.
                self.decision(label, mean, "temporal_mean", now, ident)
                self.cancel("NEUTRAL", now)
                self.release_expression("neutral", now)
                self.stable = "neutral"
                self.armed = True
                self.state, self.reason = "READY", "NEUTRAL_STOPPED"
                return
            supported = (scores[order[0]] >= self.cfg["release_confidence"] and
                         scores[order[0]] - scores[order[1]] >= self.cfg["release_margin"])
            if supported:
                self.uncertain_since = None
            elif self.uncertain_since is None:
                self.uncertain_since = self.capture_at
            elif self.capture_at - self.uncertain_since >= self.cfg["temporal_low_hold"]:
                self.cancel("LOW_CONFIDENCE", now)
            return  # Other expressions cannot interrupt or queue another action.
        self.armed = self.locked_label is None
        self.state, self.reason = ("WAIT_RELEASE", "EXPRESSION_HELD") if self.locked_label else (
            "WAIT_INPUT", "WAIT_STABLE_EXPRESSION")
        if not result["confirmed"]:
            return
        if label == "neutral":
            if self.locked_label is not None or self.stable != "neutral":
                self.decision(label, mean, "temporal_mean", now)
                self.release_expression("neutral", now)
            self.stable, self.armed = "neutral", True
            self.state, self.reason = "READY", "WAIT_EXPRESSION"
        elif label != self.locked_label:
            self.accept_action(label, mean, "temporal_mean", now)

    def event_prediction(self, scores, order, neutral_confident, now):
        """Initial input is immediate; only a consumed expression needs release."""
        label = order[0]
        if not self.enabled or not self.healthy(now) or self.fault_latched:
            self.change_label, self.change_count = None, 0
            return
        self.ever_ready = True
        fast = scores[label] > self.cfg["score_fast_threshold"]
        accepted = (scores[label] >= self.cfg["vote_confidence"] and
                    scores[label] - scores[order[1]] >= self.cfg["vote_margin"])
        self.votes.append((self.capture_at, label if accepted else None))
        if self.action:
            self.running_prediction(scores, order, neutral_confident, now)
            self.change_label, self.change_count = None, 0
            if self.action is None and self.reason == "NEUTRAL":
                self.release_expression("neutral", now)
                self.armed = True
                self.state, self.reason = "READY", "NEUTRAL_STOPPED"
            return
        counts = Counter(k for _, k in self.votes if k is not None)
        if label == "neutral":
            self.change_label, self.change_count = None, 0
            if fast or (accepted and counts[label] >= self.cfg["vote_min"]):
                if self.locked_label is not None or self.stable != "neutral":
                    self.decision(label, scores, "score_fast_path" if fast else "vote_threshold", now)
                self.release_expression("neutral", now)
                self.stable = "neutral"
            self.armed = self.locked_label is None
            self.state, self.reason = ("READY", "WAIT_EXPRESSION") if self.armed else (
                "WAIT_RELEASE", "EXPRESSION_HELD")
            return
        if not accepted:
            self.change_label, self.change_count = None, 0
            self.armed = self.locked_label is None
            self.state, self.reason = "WAIT_INPUT", "LOW_CONFIDENCE_WAIT_INPUT"
            return
        if label == self.locked_label:
            self.change_label, self.change_count = None, 0
            self.armed = False
            self.state, self.reason = "WAIT_RELEASE", "EXPRESSION_HELD"
            return
        if self.locked_label is not None:
            if self.change_label != label:
                self.change_label, self.change_count = label, 1
            else:
                self.change_count += 1
            if self.change_count < self.cfg["change_predictions"]:
                self.armed = False
                self.state, self.reason = "WAIT_CHANGE", "CONFIRM_NEW_EXPRESSION"
                return
        self.armed = True
        self.state, self.reason = "READY", "WAIT_VOTES"
        if fast or counts[label] >= self.cfg["vote_min"]:
            if not fast:
                self.emit("VOTE_ACCEPTED", now, label=label, count=counts[label],
                          window=len(self.votes), threshold=self.cfg["vote_min"])
            self.accept_action(label, scores, "score_fast_path" if fast else "vote_threshold", now)

    def decision(self, label, scores, branch, now, action_id=None):
        """Audit the actual fresh prediction that confirmed a task."""
        self.confirmation = dict(
            label=label, score=scores[label], branch=branch,
            seq=self.last_seq, frame_id=self.last_frame, capture_mono=self.capture_at,
            action_id=action_id, monotonic=now, pose=self.pose,
        )
        if self.event_mode:
            if branch == "temporal_mean":
                self.confirmation.update(temporal=dict(self.temporal.snapshot),
                                         raw_score=self.temporal.samples[-1][1][label])
            self.confirmation.update(previous_label=self.locked_label,
                                     change_count=self.change_count)
        self.emit("DECISION_ACCEPTED", now,
                  **{k: v for k, v in self.confirmation.items() if k != "monotonic"})

    def vote_prediction(self, scores, order, neutral_confident, now):
        """One fresh score above the configured threshold has priority; 11/57 remains the fallback."""
        label = order[0]
        fast = scores[label] > self.cfg["score_fast_threshold"]
        accepted = (
            scores[label] >= self.cfg["vote_confidence"]
            and scores[label] - scores[order[1]] >= self.cfg["vote_margin"]
        )
        self.votes.append((self.capture_at, label if accepted else None))
        counts = Counter(k for _, k in self.votes if k is not None)
        if self.action:
            self.running_prediction(scores, order, neutral_confident, now)
            return
        if not self.enabled or not self.healthy(now):
            return
        # No hold, EMA, rounded percentage or vote minimum gates this branch.
        if fast:
            if label == "neutral":
                if not self.armed:
                    self.decision(label, scores, "score_fast_path", now)
                self.armed = True
                self.armed_until = now + self.cfg["rearm_window"]
                self.stable = "neutral"
                self.state, self.reason = "READY", "NEUTRAL_REARMED"
                self.speed = (0.0, 0.0)
            elif self.armed:
                self.stable = label
                self.accept_action(label, scores, "score_fast_path", now)
            else:
                self.state, self.reason = "WAIT_NEUTRAL", "REQUIRE_NEUTRAL"
            return
        if not accepted:
            self.stable = None
            self.state = "READY" if self.armed else "STOPPED"
            self.reason = "LOW_CONFIDENCE_WAIT_STABLE" if self.armed else "LOW_CONFIDENCE"
            return
        if not self.armed:
            if label == "neutral" and counts["neutral"] >= self.cfg["vote_min"]:
                self.armed = True
                self.armed_until = now + self.cfg["rearm_window"]
                self.stable = "neutral"
                self.state, self.reason = "READY", "NEUTRAL_REARMED"
                self.decision(label, scores, "vote_threshold", now)
            else:
                self.state, self.reason = "WAIT_NEUTRAL", "REQUIRE_NEUTRAL"
            return
        if accepted and label == "neutral":
            self.armed_until = now + self.cfg["rearm_window"]
        self.state, self.reason = "READY", "WAIT_VOTES"
        if accepted and label not in ("neutral", "disgust"):
            if counts[label] >= self.cfg["vote_min"]:
                self.emit("VOTE_ACCEPTED", now, label=label, count=counts[label],
                          window=len(self.votes), threshold=self.cfg["vote_min"])
                self.stable = label
                self.accept_action(label, scores, "vote_threshold", now)

    def running_prediction(self, scores, order, neutral_confident, now):
        label = order[0]
        fast = scores[label] > self.cfg["score_fast_threshold"]
        accepted = (scores[label] >= self.cfg["vote_confidence"] and
                    scores[label] - scores[order[1]] >= self.cfg["vote_margin"])
        self.stable = self.action["label"]
        if label == "neutral" and fast:
            action_id = self.action["id"]
            self.cancel("NEUTRAL", now)
            self.decision(label, scores, "score_fast_path", now, action_id)
            return
        if label == "neutral" and neutral_confident:
            if self.neutral_since is None:
                self.neutral_since = now
            elif now - self.neutral_since >= self.cfg["neutral_stop_hold"]:
                action_id = self.action["id"]
                self.cancel("NEUTRAL", now)
                self.decision(label, scores, "neutral_stop_hold", now, action_id)
                return
        else:
            self.neutral_since = None
        if accepted:
            self.uncertain_since = None
        elif self.uncertain_since is None:
            self.uncertain_since = now
        elif now - self.uncertain_since >= self.cfg["vote_low_hold"]:
            self.cancel("LOW_CONFIDENCE", now)
        return

    def accept_action(self, label, scores, branch, now):
        self.stable = label
        self.decision(label, scores, branch, now, self.counter + 1)
        self.start(label, now, {k: self.confirmation[k] for k in
                              ("branch", "score", "seq", "frame_id", "capture_mono",
                               "raw_score", "temporal") if k in self.confirmation})

    def healthy(self, now):
        return (
            self.prepared
            and self.pose is not None
            and now - self.odom_at < self.cfg["odom_timeout"]
            and now - self.clock_at < self.cfg["clock_timeout"]
            and not self.hazard
            and not self.external_publisher
            and not self.external_clock
        )

    def start(self, label, now, decision=None):
        if label not in ("happy", "sad", "angry", "fear", "surprise"):
            return
        self.temporal.reset()
        self.counter += 1
        self.uncertain_since = None
        self.neutral_since = None
        self.action = dict(
            id=self.counter,
            label=label,
            start=now,
            origin=self.pose,
            distance=0.0,
            signed_distance=0.0,
            yaw=0.0,
            max_center_drift=0.0,
            **(decision or {}),
        )
        self.armed = False
        if self.event_mode:
            self.locked_label = label
            self.change_label, self.change_count = None, 0
        self.state, self.reason = "EXECUTING", label
        self.emit("ACTION_START", now, **self.action)

    def tick(self, now):
        issues = (
            ("GUI_STOP", not self.enabled),
            ("OTHER_CMD_PUBLISHER", self.external_publisher),
            ("OTHER_CLOCK_PUBLISHER", self.external_clock),
            ("HAZARD", self.hazard),
            ("ROBOT_NOT_PREPARED", not self.prepared),
            ("ODOM_STALE", now - self.odom_at >= self.cfg["odom_timeout"]),
            ("CLOCK_STALE", now - self.clock_at >= self.cfg["clock_timeout"]),
            ("PREDICTION_STALE", now - (max(self.capture_at, self.accept_after)
              if self.event_mode else self.capture_at)
              >= self.cfg["prediction_timeout"]),
        )
        issue = next((reason for reason, active in issues if active), None)
        if issue:
            self.cancel(issue, now)
            return (0.0, 0.0)
        if self.event_mode and self.fault_latched:
            self.state, self.reason = "FAULT", self.fault_latched
            self.speed = (0.0, 0.0)
            return self.speed
        if not self.event_mode and self.armed and now > self.armed_until:
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
                else -a["signed_distance"] if l == "angry" else a["signed_distance"]
            )
            a["progress"] = max(0.0, min(1.0, amount / target))
            if amount >= target:
                self.emit("ACTION_END", now, **a, reason="completed", pose=self.pose)
                self.action = None
                self.temporal.reset()
                self.votes.clear()
                self.neutral_since = None
                self.change_label, self.change_count = None, 0
                self.state, self.reason = (
                    "WAIT_RELEASE" if self.event_mode else "WAIT_NEUTRAL",
                    "COMPLETED")
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
