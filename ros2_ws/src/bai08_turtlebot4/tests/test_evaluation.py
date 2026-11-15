"""Synthetic evaluation fixtures; never evidence of webcam accuracy."""
import sys
import json
import runpy
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bai08_turtlebot4.core import LABELS
from bai08_turtlebot4.evaluation import evaluate

CFG=dict(window=.5,hold=.2,confidence=.55,margin=.15,max_gap=.35,min_samples=3)


def recording(truth='fear',pred='fear',onset=True):
    return dict(id='synthetic-fixture',intervals=[dict(label=truth,start_capture_mono=0.,
                 end_capture_mono=2.,onset_verified=onset)],samples=[
        dict(source='webcam',seq=n,frame_id=n,capture_mono=n/10,status='OK',faces=1,
             scores={k:.95 if k==pred else .05/6 for k in LABELS}) for n in range(20)])


class Evaluation(unittest.TestCase):
    def test_correct_event_and_onset_latency(self):
        r=evaluate([recording()],CFG)
        self.assertEqual(r['wrong_confirmation_events'],0)
        self.assertEqual(r['missed_intervals'],0)
        self.assertEqual(r['latency_count'],1)
        self.assertAlmostEqual(r['latency_p50_seconds'],.7)
        self.assertEqual(len(r['events']),1)
        self.assertGreater(r['abstention_rate'],0)

    def test_model_prediction_cannot_replace_human_ground_truth(self):
        r=evaluate([recording('angry','fear')],CFG)
        self.assertEqual(r['false_motion_confirmations'],1)
        self.assertEqual(r['missed_intervals'],1)
        self.assertEqual(r['accuracy_with_abstentions'],0)

    def test_unverified_onset_never_produces_latency(self):
        r=evaluate([recording(onset=False)],CFG)
        self.assertIsNone(r['latency_p50_seconds'])
        self.assertEqual(r['latency_count'],0)

    def test_background_false_event_rate(self):
        r=evaluate([recording('none','fear')],CFG)
        self.assertEqual(r['false_motion_confirmations'],1)
        self.assertEqual(r['false_motion_confirmations_per_minute'],30)
        self.assertEqual(r['missed_intervals'],1)
        r=evaluate([recording('none','neutral')],CFG)
        self.assertEqual(r['false_motion_confirmations'],0)
        self.assertEqual(r['accuracy_with_abstentions'],1)

    def test_replay_does_not_accumulate_samples(self):
        rec=recording();rec['samples']=[rec['samples'][0]]*40
        r=evaluate([rec],CFG)
        self.assertEqual(r['labelled_samples'],1)
        self.assertEqual(r['events'],[])

    def test_recordings_do_not_share_filter_state(self):
        a=recording();b=recording();a['samples']=a['samples'][:5];b['samples']=b['samples'][:5]
        self.assertEqual(evaluate([a,b],CFG)['events'],[])


class EvaluationCLI(unittest.TestCase):
    def setUp(self):
        self.cli=runpy.run_path(str(Path(__file__).resolve().parents[4]/'tools/evaluate_temporal.py'))
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        samples=recording()['samples']
        (self.root/'predictions.jsonl').write_text(''.join(json.dumps(p)+'\n' for p in samples))
        self.r=dict(id='fixture',group='person-a',split='selection',
                    annotation_kind='synthetic_unit_fixture',predictions='predictions.jsonl',
                    intervals=recording()['intervals'])

    def manifest(self,rows):
        path=self.root/'annotations.json'
        path.write_text(json.dumps(dict(recordings=rows)))
        return path

    def test_tuning_missing_holdout_cannot_recommend_parameters(self):
        path=self.manifest([self.r]);out=self.root/'result.json'
        with patch.object(sys,'argv',['evaluate',str(path),'--out',str(out),'--tune']),redirect_stdout(StringIO()):
            self.cli['main']()
        result=json.loads(out.read_text())
        self.assertEqual(result['candidate_count'],54)
        self.assertEqual(result['selection_status'],'insufficient_labels_or_independent_holdout')
        self.assertIsNone(result['suggested_control_config'])
        self.assertFalse(result['configuration_written'])

    def test_same_recording_and_group_cannot_leak_into_holdout(self):
        for group in ('person-a','person-b'):
            path=self.manifest([self.r,dict(self.r,id='second',split='holdout',group=group)])
            with self.assertRaises(ValueError): self.cli['load_manifest'](path)

    def test_overlapping_human_intervals_rejected(self):
        path=self.manifest([dict(self.r,intervals=recording()['intervals']*2)])
        with self.assertRaises(ValueError): self.cli['load_manifest'](path)

    def test_actual_actions_are_separate_from_replay_candidates(self):
        (self.root/'control.jsonl').write_text(json.dumps(dict(event='ACTION_START',source='webcam',
           id=4,label='angry',capture_mono=.8,monotonic=.9))+'\n')
        path=self.manifest([dict(self.r,control='control.jsonl')]);out=self.root/'result.json'
        with patch.object(sys,'argv',['evaluate',str(path),'--out',str(out)]),redirect_stdout(StringIO()):
            self.cli['main']()
        result=json.loads(out.read_text())
        self.assertEqual(result['actual_recorded_activations'][0]['wrong_activations'],1)
        self.assertEqual(result['current']['selection']['false_motion_confirmations'],0)


if __name__=='__main__': unittest.main()
