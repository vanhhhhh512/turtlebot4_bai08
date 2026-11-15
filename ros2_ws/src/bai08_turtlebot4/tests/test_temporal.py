"""Synthetic filter/controller regressions, not recognition accuracy evidence."""
import math
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bai08_turtlebot4.temporal import TemporalScores
from bai08_turtlebot4.core import Controller, LABELS, wrap


def scores(label, value=.95):
    return {k: value if k == label else (1-value)/6 for k in LABELS}


class Averaging(unittest.TestCase):
    def test_time_weighting_and_clipped_boundary(self):
        f = TemporalScores(window=1, max_gap=2, min_samples=2, hold=0)
        f.add(0, scores('happy', .2))
        f.add(.1, scores('happy', .3))
        s = f.add(1, scores('happy', .8))
        self.assertAlmostEqual(s['scores']['happy'], .52)
        s = f.add(1.1, scores('happy', .8))
        self.assertAlmostEqual(s['scores']['happy'], .575)
        self.assertAlmostEqual(sum(s['scores'].values()), 1)

    def test_only_past_capture_time_counts(self):
        f = TemporalScores(window=.5, hold=.2)
        for t in (0, .1, .2, .3, .4, .5, .6):
            self.assertFalse(f.add(t, scores('fear'))['confirmed'])
        self.assertTrue(f.add(.7, scores('fear'))['confirmed'])
        with self.assertRaises(ValueError):
            f.add(.7, scores('fear'))

    def test_gap_restarts_coverage_and_stability(self):
        f = TemporalScores()
        for n in range(9):
            f.add(n/10, scores('fear'))
        s = f.add(1.2, scores('fear'))
        self.assertFalse(s['ready'])
        self.assertEqual(s['sample_count'], 1)
        self.assertFalse(s['confirmed'])

    def test_margin_is_required_even_with_sufficient_confidence(self):
        f = TemporalScores(confidence=.5, margin=.15)
        s = dict.fromkeys(LABELS, 0.); s.update(happy=.55, sad=.45)
        for n in range(20):
            result = f.add(n/10, s)
        self.assertFalse(result['confirmed'])

    def test_current_raw_must_agree_with_filtered_winner(self):
        f = TemporalScores()
        for n in range(9):
            f.add(n/10, scores('fear'))
        result = f.add(.9, scores('sad'))
        self.assertEqual(result['label'], 'fear')
        self.assertFalse(result['confirmed'])

    def test_no_frame_rate_requirement_for_constant_scores(self):
        for dt in (.05, .1, .2):
            f = TemporalScores()
            t = 0
            while t < 1.01:
                s = f.add(t, scores('fear')); t += dt
            self.assertTrue(s['confirmed'])
            self.assertAlmostEqual(s['scores']['fear'], .95)

    def test_invalid_configuration_rejected(self):
        for cfg in ({'window':0}, {'hold':-1}, {'max_gap':float('nan')},
                    {'confidence':2}, {'margin':-1}, {'min_samples':1}):
            with self.assertRaises(ValueError): TemporalScores(**cfg)


class TemporalControl(unittest.TestCase):
    def setUp(self):
        self.c = Controller('temporal-test', allow_test=True)
        self.t, self.seq, self.pose = 10., 0, (0., 0., 0.)

    def frame(self, label='fear', value=.95, dt=.1, **changes):
        self.t += dt; self.seq += 1
        self.c.prepared = True; self.c.clock_at = self.t
        self.c.odom(*self.pose, 0., 0., self.t)
        p = dict(session=self.c.session, source='component_test', seq=self.seq,
                 frame_id=self.seq, capture_mono=self.t, status='OK', faces=1,
                 scores=scores(label, value))
        p.update(changes)
        self.c.prediction(p, self.t)
        self.c.tick(self.t)
        return p

    def hold(self, label='fear', n=12, **kw):
        for _ in range(n): self.frame(label, **kw)

    def finish(self):
        for _ in range(500):
            if not self.c.action: break
            label = self.c.action['label']
            v,w = self.c.speed; x,y,yaw = self.pose
            self.pose = (x+v*.1*math.cos(yaw), y+v*.1*math.sin(yaw), wrap(yaw+w*.1))
            self.frame(label)
        self.assertIsNone(self.c.action)
        self.assertEqual([e for e in self.c.events if e['event']=='ACTION_END'][-1]['reason'],'completed')

    def test_default_has_no_single_high_frame_bypass_or_votes(self):
        self.assertEqual(self.c.cfg['decision_mode'], 'temporal')
        self.frame(value=.999)
        self.assertIsNone(self.c.action)
        self.hold()
        self.assertEqual(self.c.action['branch'],'temporal_mean')
        self.assertEqual(len(self.c.votes),0)
        self.assertGreaterEqual(self.c.confirmation['temporal']['stable_seconds'], .2-1e-8)
        self.assertEqual(self.c.action['temporal'], self.c.confirmation['temporal'])

    def test_single_spike_and_ambiguous_scores_do_not_start(self):
        self.hold(value=1/7)
        self.frame(value=.999)
        self.hold(value=1/7)
        self.assertIsNone(self.c.action)
        s = dict.fromkeys(LABELS,0.);s.update(happy=.55,sad=.45)
        self.hold(scores=s)
        self.assertIsNone(self.c.action)

    def test_five_mapping_and_held_expression_do_not_repeat(self):
        for label in ('happy','sad','fear','angry','surprise'):
            self.setUp();self.hold(label)
            self.assertEqual(self.c.action['label'], label)
            self.finish();self.hold(label,n=20)
            self.assertEqual(self.c.counter,1)

    def test_running_label_is_not_queued_after_completion(self):
        self.hold();self.hold('sad',n=8)
        self.assertEqual(self.c.action['label'],'fear')
        self.finish()
        self.frame('sad');self.assertIsNone(self.c.action)
        self.hold('sad');self.assertEqual(self.c.action['label'],'sad')

    def test_neutral_uses_filter_then_stops_and_releases(self):
        self.hold();self.frame('neutral')
        self.assertIsNotNone(self.c.action)
        self.hold('neutral')
        self.assertIsNone(self.c.action)
        self.assertIsNone(self.c.locked_label)
        self.assertEqual(self.c.confirmation['branch'],'temporal_mean')
        self.hold();self.assertEqual(self.c.counter,2)

    def test_no_face_stops_immediately_and_clears_history(self):
        self.hold();self.frame(status='NO_FACE',faces=0)
        self.assertIsNone(self.c.action)
        self.assertFalse(self.c.temporal.snapshot)
        self.hold();self.assertIsNone(self.c.action)
        self.hold(n=13,status='NO_FACE',faces=0)
        self.assertIsNone(self.c.locked_label)
        self.frame();self.assertIsNone(self.c.action)
        self.hold();self.assertEqual(self.c.counter,2)

    def test_stop_and_health_fault_require_start_and_new_history(self):
        for fault in ('hazard','external_publisher','external_clock'):
            self.setUp();self.hold();setattr(self.c,fault,True)
            self.frame();self.assertIsNone(self.c.action)
            setattr(self.c,fault,False);self.hold('sad')
            self.assertIsNone(self.c.action)
            self.c.request_start(self.t);self.frame('sad')
            self.assertIsNone(self.c.action)
            self.hold('sad');self.assertEqual(self.c.counter,2)
        self.c.enabled=False;self.frame();self.hold('happy')
        self.assertIsNone(self.c.action)

    def test_replay_and_pre_start_packet_cannot_warm_filter(self):
        p=self.frame();self.c.request_start(self.t)
        for _ in range(20):
            self.assertFalse(self.c.prediction(p,self.t+.01))
        self.assertFalse(self.c.temporal.snapshot)
        self.frame();self.assertIsNone(self.c.action)

    def test_face_fault_and_disgust_cannot_launch_lagging_mean(self):
        for kw in ({'faces':2},{'identity_changed':True},{'label':'disgust'}):
            self.setUp();self.hold(n=6)
            self.frame(**kw)
            self.assertIsNone(self.c.action)
            self.frame();self.assertIsNone(self.c.action)


if __name__ == '__main__': unittest.main()
