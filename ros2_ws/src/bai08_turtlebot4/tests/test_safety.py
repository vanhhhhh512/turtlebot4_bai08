import math, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bai08_turtlebot4.core import Controller, LABELS, wrap


class Safety(unittest.TestCase):
    def setUp(self):
        self.c = Controller("test")
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
            dict(session="other", seq=999, capture_mono=self.t),
            dict(session="test", seq=self.seq, capture_mono=self.t),
            dict(session="test", seq=999, capture_mono=self.t - 3),
        ]:
            self.assertFalse(self.c.prediction(p, self.t))
            self.assertEqual(last, self.c.capture_at)
        self.assertEqual(self.c.tick(self.t + 1.0), (0.0, 0.0))
        self.assertIsNone(self.c.action)
        self.stable("surprise", 30)
        self.assertIsNone(self.c.action)

    def test_odom_clock_stop_and_hazard(self):
        for fault in ["odom_at", "clock_at", "hazard", "enabled", "external_publisher"]:
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
                        if fault in ("hazard", "external_publisher")
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
