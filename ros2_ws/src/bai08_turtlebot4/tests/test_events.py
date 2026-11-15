"""Historical event policy: synthetic component packets, never webcam accuracy."""
import math
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bai08_turtlebot4.core import Controller, LABELS, wrap
from bai08_turtlebot4.presentation import StatusPresenter


class Events(unittest.TestCase):
    def setUp(self):
        self.c = Controller('event-test', {"decision_mode": "events"}, allow_test=True)
        self.t, self.seq = 10., 0
        self.pose = (0., 0., 0.)

    def packet(self, label='happy', score=.95, dt=.1, **changes):
        self.t += dt; self.seq += 1
        self.c.prepared = True
        self.c.clock_at = self.t
        self.c.odom(*self.pose, 0., 0., self.t)
        p = dict(session='event-test', source='component_test', seq=self.seq,
                 frame_id=self.seq, capture_mono=self.t, status='OK', faces=1,
                 scores={k: score if k == label else (1-score)/6 for k in LABELS})
        p.update(changes)
        return p

    def frame(self, label='happy', score=.95, **changes):
        p = self.packet(label, score, **changes)
        self.c.prediction(p, self.t)
        return self.c.tick(self.t)

    def finish(self):
        label = self.c.action['label']
        for _ in range(500):
            v,w = self.c.speed
            x,y,yaw = self.pose
            self.pose = (x + v*.1*math.cos(yaw), y + v*.1*math.sin(yaw), wrap(yaw+w*.1))
            self.frame(label)
            if self.c.action is None:break
        self.assertIsNone(self.c.action)
        self.assertEqual([e for e in self.c.events if e['event']=='ACTION_END'][-1]['reason'],'completed')

    def test_default_first_prediction_starts_without_neutral(self):
        self.assertEqual(self.c.cfg['decision_mode'],'events')
        self.assertEqual(self.c.cfg['score_fast_threshold'],.57)
        for label,cmd in [('happy',(.1,.35)),('sad',(.1,-.35)),('angry',(-.1,0)),
                          ('fear',(.1,0)),('surprise',(0,.35))]:
            self.setUp()
            self.assertEqual(self.frame(label,.5701),cmd)
            self.assertEqual(self.c.counter,1)
            self.assertEqual(self.c.action['frame_id'],1)
            self.assertEqual(self.c.confirmation['branch'],'score_fast_path')

    def test_exact_fifty_seven_requires_eleven_real_votes(self):
        for _ in range(10):
            self.frame('fear',.57);self.assertIsNone(self.c.action)
        self.frame('fear',.57)
        self.assertEqual(self.c.action['branch'],'vote_threshold')
        self.assertEqual(len(self.c.votes),11)

    def test_completed_same_image_never_repeats(self):
        self.frame('fear');self.finish()
        for _ in range(100):self.frame('fear')
        self.assertEqual(self.c.counter,1)
        self.assertEqual(self.c.state,'WAIT_RELEASE')

    def test_different_expression_requires_two_new_predictions(self):
        self.frame('angry');self.finish()
        self.frame('sad');self.assertIsNone(self.c.action)
        self.assertEqual(self.c.state,'WAIT_CHANGE')
        self.frame('sad');self.assertEqual(self.c.action['label'],'sad')
        self.assertEqual(self.c.confirmation['previous_label'],'angry')
        self.assertEqual(self.c.confirmation['change_count'],2)

    def test_noise_and_weak_frame_reset_change_evidence(self):
        self.frame('fear');self.finish()
        for label in ('happy','sad','happy','sad','happy'):
            self.frame(label);self.assertIsNone(self.c.action)
        self.frame('happy',1/7);self.frame('happy')
        self.assertIsNone(self.c.action)
        self.frame('happy');self.assertEqual(self.c.counter,2)

    def test_running_predictions_are_not_queued_for_later(self):
        self.frame('fear')
        for _ in range(10):self.frame('sad')
        self.assertEqual(self.c.action['label'],'fear')
        self.finish()
        self.frame('sad');self.assertIsNone(self.c.action)
        self.frame('sad');self.assertEqual(self.c.action['label'],'sad')

    def test_short_face_gap_idle_does_not_require_neutral(self):
        self.frame(status='NO_FACE',faces=0)
        self.assertEqual(self.frame('sad',.99),(.1,-.35))

    def test_short_face_gap_cancels_without_resuming_same_action(self):
        self.frame('fear');self.frame(status='NO_FACE',faces=0)
        for _ in range(10):self.frame('fear')
        self.assertIsNone(self.c.action)
        self.assertEqual(self.c.counter,1)
        self.frame('sad');self.frame('sad')
        self.assertEqual(self.c.counter,2)

    def test_one_second_fresh_absence_unlocks_same_expression(self):
        self.frame('fear');self.finish()
        for _ in range(7):self.frame(status='NO_FACE',faces=0)
        self.assertEqual(self.c.locked_label,'fear')
        for _ in range(6):self.frame(status='NO_FACE',faces=0)
        self.assertIsNone(self.c.locked_label)
        self.frame('fear');self.assertEqual(self.c.counter,2)
        releases=[e for e in self.c.events if e['event']=='EXPRESSION_RELEASED']
        self.assertEqual(releases[-1]['cause'],'face_absence')

    def test_camera_error_and_multiple_faces_do_not_count_as_release(self):
        for changes in (dict(status='CAMERA_ERROR',faces=0),dict(status='OK',faces=2)):
            self.setUp();self.frame('fear');self.finish()
            for _ in range(15):self.frame(**changes)
            self.assertEqual(self.c.locked_label,'fear')
            self.frame('fear');self.assertIsNone(self.c.action)

    def test_stale_or_replayed_no_face_cannot_unlock(self):
        self.frame('fear');self.finish()
        p=self.packet(status='NO_FACE',faces=0)
        self.c.prediction(p,self.t)
        for _ in range(15):
            self.t+=.1
            self.c.clock_at=self.t
            self.c.odom(*self.pose,0.,0.,self.t)
            self.assertFalse(self.c.prediction(p,self.t))
            self.c.tick(self.t)
        self.assertEqual(self.c.locked_label,'fear')
        self.assertEqual(self.c.fault_latched,'PREDICTION_STALE')

    def test_neutral_stops_and_releases_the_round(self):
        self.frame('fear')
        self.assertEqual(self.frame('neutral'),(0.,0.))
        self.assertIsNone(self.c.locked_label)
        self.frame('fear');self.assertEqual(self.c.counter,2)

    def test_neutral_low_score_releases_only_at_vote_threshold(self):
        self.frame('fear');self.finish()
        for _ in range(10):
            self.frame('neutral',.57);self.assertEqual(self.c.locked_label,'fear')
        self.frame('neutral',.57);self.assertIsNone(self.c.locked_label)
        self.frame('fear');self.assertEqual(self.c.counter,2)

    def test_hard_faults_need_start_even_after_health_recovers(self):
        for attr,value in [('hazard',True),('external_publisher',True),
                           ('external_clock',True),('prepared',False),('odom_at',0.),('clock_at',0.)]:
            self.setUp();self.frame('fear')
            p=self.packet('sad');setattr(self.c,attr,value)
            self.c.prediction(p,self.t);self.c.tick(self.t)
            self.assertIsNotNone(self.c.fault_latched,attr)
            if attr in ('hazard','external_publisher','external_clock'):setattr(self.c,attr,False)
            self.frame('sad');self.frame('sad');self.assertIsNone(self.c.action)
            self.c.request_start(self.t)
            self.frame('sad');self.assertEqual(self.c.counter,2)

    def test_stop_neutral_and_absence_cannot_bypass_latch(self):
        self.frame('fear');self.c.enabled=False;self.frame()
        for _ in range(15):self.frame(status='NO_FACE',faces=0)
        self.frame('neutral');self.frame('sad')
        self.assertIsNone(self.c.action)
        self.assertEqual(self.c.locked_label,'fear')
        self.c.request_start(self.t);self.frame('sad')
        self.assertEqual(self.c.counter,2)

    def test_start_refuses_pre_start_packet_and_has_watchdog_grace(self):
        p=self.packet('fear');self.c.request_start(self.t+.01)
        self.assertFalse(self.c.prediction(p,self.t+.02))
        self.c.tick(self.t+.02)
        self.assertIsNone(self.c.fault_latched)
        self.frame('fear');self.assertEqual(self.c.counter,1)

    def test_expired_old_neutral_permit_does_not_block_events(self):
        self.frame('neutral');self.c.armed_until=0.
        self.frame('fear');self.assertEqual(self.c.counter,1)

    def test_disgust_stops_and_same_expression_stays_consumed(self):
        self.frame('fear');self.frame('disgust',.99)
        self.assertIsNone(self.c.action)
        self.frame('fear');self.assertIsNone(self.c.action)

    def test_invalid_packet_never_starts_first_action(self):
        for changes in (dict(session='other'),dict(source='other'),dict(frame_id=-1),
                        dict(capture_mono=0.),dict(capture_mono=999.),dict(faces=2),
                        dict(identity_changed=True)):
            self.setUp();self.c.allow_test=False
            p=self.packet('fear',source='webcam');p.update(changes)
            self.c.prediction(p,self.t);self.c.tick(self.t)
            self.assertEqual(self.c.counter,0,changes)

    def test_ui_clears_old_face_message_and_explains_repeat_lock(self):
        view=StatusPresenter();s=dict(monotonic=10,enabled=True,decision_mode='events')
        self.assertEqual(view.message(dict(s,reason='NO_FACE'),10),'CHỜ KHUÔN MẶT')
        msg=view.message(dict(s,state='READY',reason='WAIT_EXPRESSION',armed=True),10)
        self.assertIn('SẴN SÀNG',msg)
        msg=view.message(dict(s,state='WAIT_RELEASE',locked_label='happy',reason='EXPRESSION_HELD'),10)
        self.assertIn('HAPPY',msg);self.assertNotIn('NEUTRAL',msg)
        for state in ('WAIT_CHANGE','WAIT_INPUT','WAIT_RELEASE'):
            self.assertEqual(view.message(dict(s,state=state,locked_label='happy',reason='WAIT_VOTES'),10),msg)
        msg=view.message(dict(s,reason='ODOM_STALE',fault_latched='ODOM_STALE'),10)
        self.assertIn('START',msg)


if __name__=='__main__':unittest.main(verbosity=2)
