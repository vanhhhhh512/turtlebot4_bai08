"""Component inputs only: these checks do not validate webcam recognition."""
import math
import sys
import unittest
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bai08_turtlebot4.core import Controller, LABELS, wrap
from bai08_turtlebot4.presentation import StatusPresenter
from bai08_turtlebot4.trajectory import Trajectory


def scores(label, score):
    return {k: score if k == label else (1-score)/6 for k in LABELS}


class FastPath(unittest.TestCase):
    def setUp(self):
        self.c = Controller("component", allow_test=True)
        self.now, self.seq = 10., 0
        self.pose = (0., 0., 0.)

    def packet(self, label, score=.9, **changes):
        self.now += .05
        self.seq += 1
        self.c.prepared = True
        self.c.clock_at = self.now
        self.c.odom(*self.pose, 0., 0., self.now)
        p = dict(session="component", source="component_test", status="OK", faces=1,
                 seq=self.seq, frame_id=self.seq, capture_mono=self.now,
                 scores=scores(label, score))
        p.update(changes)
        return p

    def frame(self, label, score=.9, **changes):
        self.c.prediction(self.packet(label, score, **changes), self.now)
        return self.c.tick(self.now)

    def ready(self):
        self.frame("neutral")
        self.assertTrue(self.c.armed)

    def test_all_motion_labels_start_on_first_high_prediction_and_audit(self):
        for label, command in [("happy",(.1,.35)), ("sad",(.1,-.35)),
                               ("angry",(-.1,0)), ("fear",(.1,0)), ("surprise",(0,.35))]:
            self.setUp(); self.ready()
            self.assertEqual(self.frame(label,.6001), command)
            self.assertEqual(self.c.counter, 1)
            self.assertEqual(Counter(k for _, k in self.c.votes)[label], 1)
            event = next(e for e in self.c.events if e["event"] == "ACTION_START")
            self.assertEqual((event["branch"],event["score"],event["seq"],event["frame_id"]),
                             ("score_fast_path",.6001,2,2))

    def test_exact_boundary_and_eleven_vote_fallback(self):
        for value in (.5999, .6000):
            self.setUp(); self.ready()
            for _ in range(10):
                self.frame("angry",value)
                self.assertIsNone(self.c.action)
            self.frame("angry",value)
            self.assertEqual(self.c.action["branch"], "vote_threshold")
            self.assertEqual(self.c.action["score"], value)

    def test_fallback_neutral_requires_eleven_fresh_votes(self):
        for _ in range(10):
            self.frame("neutral",.6)
            self.assertFalse(self.c.armed)
        self.frame("neutral",.6)
        self.assertTrue(self.c.armed)
        self.assertEqual(self.c.confirmation["branch"],"vote_threshold")

    def test_high_neutral_stops_now_and_new_neutral_rearms(self):
        self.ready(); self.frame("fear")
        self.assertEqual(self.frame("neutral",.6001),(0.,0.))
        self.assertIsNone(self.c.action)
        self.assertFalse(self.c.armed)
        for _ in range(80): self.frame("fear")
        self.assertEqual(self.c.counter,1)
        self.frame("neutral"); self.frame("fear")
        self.assertEqual(self.c.counter,2)

    def test_action_locks_label_and_completes_only_once(self):
        self.ready(); self.frame("surprise")
        self.frame("happy")
        self.assertEqual(self.c.action["label"],"surprise")
        for _ in range(380):
            self.pose = (0.,0.,wrap(self.pose[2]+.035))
            self.frame("surprise")
        self.assertIsNone(self.c.action)
        self.assertEqual(self.c.counter,1)
        self.assertEqual([e for e in self.c.events if e["event"]=="ACTION_END"][-1]["reason"],"completed")

    def test_neutral_at_sixty_percent_keeps_existing_stop_hold(self):
        self.ready(); self.frame("fear")
        self.frame("neutral", .6)
        self.assertIsNotNone(self.c.action)
        for _ in range(18):
            self.frame("neutral", .6)
            if self.c.action is None:
                break
        self.assertIsNone(self.c.action)
        self.assertFalse(self.c.armed)
        self.assertEqual(self.c.confirmation["branch"], "neutral_stop_hold")

    def test_fast_path_never_bypasses_health_or_stop(self):
        for field, value in [("enabled",False),("prepared",False),("hazard",True),
                             ("external_publisher",True),("external_clock",True),
                             ("odom_at",0.),("clock_at",0.)]:
            self.setUp(); self.ready()
            p=self.packet("happy")
            setattr(self.c,field,value)
            self.c.prediction(p,self.now);self.c.tick(self.now)
            self.assertIsNone(self.c.action,field)
            self.assertEqual(self.c.counter,0,field)

    def test_high_invalid_packets_do_not_start_or_refresh(self):
        for changes in [dict(session="other"),dict(seq=1),dict(frame_id=1),
                        dict(capture_mono=1.),dict(capture_mono=100.),
                        dict(source="other"),dict(faces=2),dict(status="NO_FACE",faces=0),
                        dict(identity_changed=True),dict(scores=scores("disgust",.99))]:
            self.setUp();self.ready()
            # Enforce the production source check for this test.
            self.c.allow_test=False
            self.frame("happy",source="webcam",**changes) if "source" not in changes else self.frame("happy",**changes)
            self.assertIsNone(self.c.action,changes)
        self.assertEqual(self.c.reason,"OUTSIDE_SET")

    def test_freshness_and_neutral_permit_are_required(self):
        self.frame("happy",.99)
        self.assertIsNone(self.c.action)
        self.ready()
        self.c.armed_until=self.now+.01
        self.frame("happy",.99)
        self.assertIsNone(self.c.action)
        self.assertFalse(self.c.armed)
        self.c.enabled=False
        self.frame("neutral",.99)
        self.assertFalse(self.c.armed)


class PresentationAndOdom(unittest.TestCase):
    def test_header_ignores_raw_votes_and_uncertain_ready_reasons(self):
        view=StatusPresenter()
        texts=set()
        for label in LABELS:
            for reason in ("WAIT_VOTES","LOW_CONFIDENCE_WAIT_STABLE","NEUTRAL_REARMED"):
                texts.add(view.message(dict(monotonic=10,enabled=True,armed=True,
                                            raw=label,reason=reason,state="READY"),10))
        self.assertEqual(len(texts),1)
        running=dict(monotonic=10,enabled=True,state="EXECUTING",action=dict(label="fear",id=7))
        self.assertIn("FEAR",view.message(running,10))
        self.assertIn("START",view.message(dict(running,enabled=False),10))
        self.assertIn("KẾT NỐI",view.message(running,12))

    def test_stop_remains_until_rearm_but_new_action_is_immediate(self):
        view=StatusPresenter()
        s=dict(monotonic=10,enabled=True,state="WAIT_NEUTRAL",armed=False,reason="COMPLETED")
        complete=view.message(s,10)
        self.assertEqual(view.message(dict(s,reason="REQUIRE_NEUTRAL",raw="happy"),10),complete)
        fault=view.message(dict(s,reason="ODOM_STALE"),10)
        self.assertEqual(view.message(dict(s,reason="REQUIRE_NEUTRAL"),10),fault)
        view.message(dict(s,armed=True,reason="WAIT_VOTES"),10)
        self.assertIn("ĐANG CHẠY",view.message(dict(s,state="EXECUTING",reason="happy",
                                                    action=dict(label="happy",id=8)),10))

    def test_history_boundaries_labels_jumps_and_stationary_yaw(self):
        t=Trajectory();pose=(0.,0.,0.)
        t.observe(pose,1,None)
        a=dict(id=1,label="happy",origin=pose,yaw=0.)
        t.event(dict(event="ACTION_START",monotonic=2,**a),pose)
        self.assertEqual(t.segments[-1]["points"],[[0.,0.,2]])
        t.observe((.1,0.,.1),3,a)
        t.event(dict(event="ACTION_END",monotonic=4,reason="completed",**a),(.1,0.,.1))
        b=dict(id=2,label="surprise",origin=(.1,0.,.1),yaw=0.)
        t.event(dict(event="ACTION_START",monotonic=5,**b),b["origin"])
        for i in range(1,30):
            b["yaw"]=i*.1
            t.observe((.1,0.,.1+b["yaw"]),5+i*.1,b)
        self.assertEqual(len(t.segments[-1]["points"]),1)
        self.assertAlmostEqual(t.segments[-1]["yaw"],2.9)
        self.assertEqual(t.segments[-2]["label"],"happy")
        self.assertEqual(t.segments[-2]["action_id"],1)
        t.event(dict(event="DECISION_ACCEPTED",monotonic=9,label="neutral",action_id=2),(.1,0.,3.))
        self.assertEqual(t.markers[-1]["pose"],[.1,0.,3.])
        self.assertFalse(any(s["label"]=="neutral" for s in t.segments))
        t.observe((10.,10.,0.),10,None)
        self.assertEqual(len(t.segments[-1]["points"]),1)
        self.assertIsNone(t.segments[-1]["label"])


if __name__ == "__main__": unittest.main(verbosity=2)
