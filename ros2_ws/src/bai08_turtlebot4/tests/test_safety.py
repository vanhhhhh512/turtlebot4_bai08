import math, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bai08_turtlebot4.core import Controller, LABELS, wrap


class Safety(unittest.TestCase):
    def setUp(self):
        self.c = Controller("test", {"decision_mode": "ema"})
        self.t = 10.0
        self.seq = 0
        self.pose = (0.0, 0.0, 3.0)

    def frame(self, label="neutral", dt=0.1, **kw):
        self.t += dt
        self.seq += 1
        c = self.c
        c.prepared = True
        c.clock_at = self.t
        c.odom(*self.pose, 0.0, 0.0, self.t)
        p = dict(
            session="test",
            seq=self.seq,
            frame_id=self.seq,
            capture_mono=self.t,
            source="webcam",
            status="OK",
            faces=1,
            scores={k: float(k == label) for k in LABELS},
        )
        p.update(kw)
        c.prediction(p, self.t)
        return c.tick(self.t)

    def stable(self, label, n=17):
        result = None
        for _ in range(n):
            result = self.frame(label)
        return result

    def begin(self, label):
        self.stable("neutral")
        self.assertTrue(self.c.armed)
        cmd = self.stable(label)
        self.assertIsNotNone(self.c.action)
        return cmd

    def test_mapping_and_finite(self):
        for label, sign in [
            ("happy", (1, 1)),
            ("sad", (1, -1)),
            ("angry", (-1, 0)),
            ("fear", (1, 0)),
            ("surprise", (0, 1)),
        ]:
            self.setUp()
            cmd = self.begin(label)
            self.assertEqual(tuple((v > 0) - (v < 0) for v in cmd), sign)
            # Synthetic odometry traverses yaw wrap; expressly component test.
            for _ in range(400):
                v, w = self.c.speed
                x, y, yaw = self.pose
                self.pose = (
                    x + v * 0.1 * math.cos(yaw),
                    y + v * 0.1 * math.sin(yaw),
                    wrap(yaw + w * 0.1),
                )
                self.frame(label)
                if not self.c.action:
                    break
            ends = [e for e in self.c.events if e["event"] == "ACTION_END"]
            self.assertEqual(ends[-1]["reason"], "completed")
            if label == "surprise":
                self.assertGreaterEqual(ends[-1]["yaw"], 2 * math.pi)
            self.stable(label, 30)
            self.assertIsNone(self.c.action)
            self.assertEqual(self.c.counter, 1)

    def test_neutral_immediate(self):
        self.begin("happy")
        self.assertEqual(self.frame("neutral"), (0.0, 0.0))
        self.assertFalse(self.c.armed)

    def test_no_face_multi_disgust_immediate(self):
        for bad in [
            dict(status="NO_FACE", faces=0),
            dict(faces=2),
            dict(scores={k: float(k == "disgust") for k in LABELS}),
        ]:
            self.setUp()
            self.begin("fear")
            self.assertEqual(self.frame(**bad), (0.0, 0.0))
            self.assertIsNone(self.c.action)

    def test_replay_session_and_stale(self):
        self.begin("surprise")
        last = self.c.capture_at
        for p in [
            dict(session="other"),
            dict(session="other", seq=999, frame_id=999, capture_mono=self.t),
            dict(session="test", seq=self.seq, frame_id=999, capture_mono=self.t),
            dict(session="test", seq=999, frame_id=999, capture_mono=self.t - 3),
        ]:
            self.assertFalse(self.c.prediction(p, self.t))
            self.assertEqual(last, self.c.capture_at)
            self.assertIsNotNone(self.c.action)
        self.assertEqual(self.c.tick(self.t + 1.0), (0.0, 0.0))
        self.assertIsNone(self.c.action)
        self.stable("surprise", 30)
        self.assertIsNone(self.c.action)

    def test_odom_clock_stop_and_hazard(self):
        for fault in ["odom_at", "clock_at", "hazard", "enabled", "external_publisher", "external_clock"]:
            self.setUp()
            self.begin("happy")
            setattr(
                self.c,
                fault,
                (
                    False
                    if fault == "enabled"
                    else (
                        True
                        if fault in ("hazard", "external_publisher", "external_clock")
                        else self.t - 1.0
                    )
                ),
            )
            self.assertEqual(self.c.tick(self.t), (0.0, 0.0))
            self.assertIsNone(self.c.action)

    def test_label_change_and_rearm(self):
        self.begin("fear")
        self.stable("angry", 7)
        self.assertIsNone(self.c.action)
        self.stable("angry")
        self.assertIsNone(self.c.action)
        self.stable("neutral")
        self.stable("angry")
        self.assertEqual(self.c.counter, 2)

    def test_natural_uncertain_transition_after_neutral(self):
        self.stable("neutral")
        weak = {k: 0.0 for k in LABELS}
        weak.update(neutral=0.4, happy=0.45, sad=0.15)
        for _ in range(4):
            self.assertEqual(self.frame("happy", scores=weak), (0.0, 0.0))
            self.assertTrue(self.c.armed)
        self.stable("happy", 10)
        self.assertIsNotNone(self.c.action)
        self.assertEqual(self.c.action["label"], "happy")
        self.frame("happy", scores=weak)
        self.assertIsNotNone(self.c.action)
        for _ in range(12):
            self.frame("happy", scores={k: 1 / 7 for k in LABELS})
        self.assertIsNone(self.c.action)
        self.assertFalse(self.c.armed)
        self.stable("happy", 20)
        self.assertIsNone(self.c.action)

    def test_running_hysteresis_and_single_frame_label_noise(self):
        self.begin("fear")
        self.frame("angry")
        self.assertIsNotNone(self.c.action)
        self.frame("fear")
        self.assertIsNotNone(self.c.action)
        weak = {k: 0.0 for k in LABELS}
        weak.update(fear=0.48, neutral=0.30, sad=0.22)
        for _ in range(20):
            self.frame("fear", scores=weak)
            self.assertIsNotNone(self.c.action)
        self.assertEqual(self.c.counter, 1)

    def test_start_filter_survives_isolated_weak_frames(self):
        self.stable("neutral")
        for i in range(10):
            scores = {k: 0.0 for k in LABELS}
            scores.update(happy=0.50 if i % 3 == 2 else 0.90,
                          neutral=0.30 if i % 3 == 2 else 0.05,
                          sad=0.20 if i % 3 == 2 else 0.05)
            self.frame("happy", scores=scores)
        self.assertIsNotNone(self.c.action)
        self.assertEqual(self.c.action["label"], "happy")

    def test_clear_neutral_cannot_launch_lagging_ema_action(self):
        self.stable("neutral")
        self.frame("happy")
        self.frame("happy")
        self.assertIsNone(self.c.action)
        self.frame("neutral")
        self.assertIsNone(self.c.action)

    def test_persistent_uncertainty_cancels_and_never_resumes(self):
        self.begin("fear")
        start = self.t
        for _ in range(9):
            self.frame("fear", scores={k: 1 / 7 for k in LABELS})
            if self.c.action is None:
                break
        self.assertIsNone(self.c.action)
        self.assertLessEqual(self.t - start, 0.8)
        self.stable("fear", 30)
        self.assertIsNone(self.c.action)

    def test_uncertain_idle_permit_expires(self):
        self.stable("neutral")
        weak = {k: 1 / 7 for k in LABELS}
        for _ in range(100):
            self.frame("happy", scores=weak)
        self.assertFalse(self.c.armed)
        self.stable("happy")
        self.assertIsNone(self.c.action)

    def test_fixture_refused_in_real_mode(self):
        self.stable("neutral")
        self.frame("happy", source="component_test")
        self.assertEqual(self.c.raw, "neutral")

    def test_malformed_prediction_stops_without_crashing(self):
        for packet in ([1, 2], "invalid", 17, {"session": "test", "source": "webcam"}):
            self.setUp()
            self.begin("fear")
            self.assertFalse(self.c.prediction(packet, self.t))
            self.assertIsNone(self.c.action)
            self.assertEqual(self.c.reason, "MALFORMED_PREDICTION")


class VoteSafety(unittest.TestCase):
    def frame(self, label="neutral", **kw):
        # Exercise the <=60% fallback, independently of the immediate branch.
        kw.setdefault("scores", {k: .60 if k == label else .40/6 for k in LABELS})
        return Safety.frame(self, label, **kw)
    stable = Safety.stable

    def setUp(self):
        self.c = Controller("test", {"vote_min": 4})
        self.t, self.seq = 10.0, 0
        self.pose = (0.0, 0.0, 3.0)

    def begin(self, label):
        self.stable("neutral", 4)
        self.stable(label, 4)
        self.assertIsNotNone(self.c.action)

    def test_four_nonconsecutive_votes_start_once(self):
        self.stable("neutral", 4)
        for _ in range(3):
            self.frame("angry")
            self.stable("neutral", 5)
            self.assertIsNone(self.c.action)
        scores = {k: 0.0 for k in LABELS}
        scores.update(angry=0.544, neutral=0.456)
        self.assertLess(self.frame("angry", scores=scores)[0], 0)
        self.assertEqual(self.c.counter, 1)

    def test_default_requires_more_than_ten_votes(self):
        self.c = Controller("test")
        self.stable("neutral", 11)
        self.stable("happy", 10)
        self.assertIsNone(self.c.action)
        self.frame("happy")
        self.assertEqual(self.c.action["label"], "happy")

    def test_expired_neutral_permit_cannot_start_on_final_vote(self):
        self.c.cfg["rearm_window"] = 0.5
        self.stable("neutral", 4)
        self.stable("happy", 3)
        self.frame("happy", dt=0.3)
        self.assertIsNone(self.c.action)
        self.assertFalse(self.c.armed)
        self.stable("happy", 20)
        self.assertIsNone(self.c.action)

    def test_repeated_camera_frame_cannot_refresh_watchdog(self):
        self.begin("surprise")
        stamp = self.c.capture_at
        frame = self.seq
        for _ in range(12):
            self.frame("surprise", frame_id=frame)
        self.assertEqual(self.c.capture_at, stamp)
        self.assertIsNone(self.c.action)
        self.assertEqual(self.c.reason, "PREDICTION_STALE")

    def test_wrong_direction_cannot_complete_straight_motion(self):
        for label, wrong_sign in [("angry", 1), ("fear", -1)]:
            self.setUp()
            self.begin(label)
            for _ in range(35):
                x, y, yaw = self.pose
                self.pose = (x + wrong_sign * 0.01 * math.cos(yaw),
                             y + wrong_sign * 0.01 * math.sin(yaw), yaw)
                self.frame(label)
            self.assertIsNotNone(self.c.action)
            self.assertEqual(self.c.action["progress"], 0)

    def test_votes_expire_outside_57_frames(self):
        self.stable("neutral", 4)
        self.stable("angry", 3)
        self.stable("neutral", 57)
        self.frame("angry")
        self.assertIsNone(self.c.action)

    def test_locked_action_neutral_stop_and_no_resume(self):
        self.begin("fear")
        self.stable("sad", 5)
        self.assertEqual(self.c.action["label"], "fear")
        self.stable("neutral", 11)
        self.assertIsNone(self.c.action)
        self.assertEqual(
            [e for e in self.c.events if e["event"] == "ACTION_END"][-1]["reason"],
            "NEUTRAL",
        )
        self.stable("fear", 30)
        self.assertIsNone(self.c.action)
        self.stable("neutral", 4)
        self.stable("fear", 4)
        self.assertEqual(self.c.counter, 2)
        self.assertEqual(self.frame("fear", status="NO_FACE", faces=0), (0, 0))

    def test_surprise_completes_one_turn_without_repeat(self):
        self.begin("surprise")
        for _ in range(220):
            x, y, yaw = self.pose
            self.pose = (x, y, wrap(yaw + self.c.speed[1] * 0.1))
            self.frame("surprise")
        self.assertIsNone(self.c.action)
        self.assertEqual(self.c.counter, 1)
        self.assertEqual(self.c.events[-1]["reason"], "completed")
        self.assertGreaterEqual(self.c.events[-1]["yaw"], 2 * math.pi)


if __name__ == "__main__":
    unittest.main(verbosity=2)
