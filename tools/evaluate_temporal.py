#!/usr/bin/env python3
"""Evaluate/tune causal score averaging from HUMAN labels, never model labels.

Paths in the annotation manifest are relative to that manifest. Time bounds are
capture_mono from predictions.jsonl; mark onset_verified only after reviewing
the expression onset in video. Entire recordings/people stay in one split.
"""
import argparse
import itertools
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'ros2_ws/src/bai08_turtlebot4'))
from bai08_turtlebot4.core import DEFAULT, LABELS
from bai08_turtlebot4.evaluation import evaluate


def load_manifest(path):
    doc=json.loads(path.read_text())
    recordings=doc['recordings']; groups={};seen_ids=set(); sources={};sessions={}
    for r in recordings:
        if r['id'] in seen_ids: raise ValueError('Duplicate recording id')
        seen_ids.add(r['id'])
        if r['split'] not in ('selection','holdout'): raise ValueError('Invalid split')
        if not r.get('group'): raise ValueError('Provide person/session group to prevent leakage')
        if groups.setdefault(r['group'],r['split']) != r['split']:
            raise ValueError('Same person/session group occurs in selection and holdout')
        pred=(path.parent/r['predictions']).resolve()
        if r.get('annotation_kind') == 'human_video':
            if not r.get('video') or not (path.parent/r['video']).is_file():
                raise ValueError('human_video requires the referenced local video')
        if sources.setdefault(str(pred),r['split']) != r['split']:
            raise ValueError('Same prediction recording appears in both splits')
        r['samples']=[json.loads(line) for line in pred.read_text().splitlines() if line.strip()]
        if any(p.get('source')!='webcam' for p in r['samples']):
            raise ValueError('Dataset contains non-webcam input; use unit tests for synthetic input')
        for session in {p.get('session') for p in r['samples']}:
            if session and sessions.setdefault(session,r['split']) != r['split']:
                raise ValueError('Same webcam session appears in both splits')
        previous=-float('inf')
        if not r['intervals']: raise ValueError('Recording has no human-labelled intervals')
        for i in sorted(r['intervals'],key=lambda i:i['start_capture_mono']):
            start,end=i['start_capture_mono'],i['end_capture_mono']
            if not all(math.isfinite(t) for t in (start,end)) or not start < end or start < previous:
                raise ValueError('Invalid/overlapping intervals')
            if i['label'] not in (*LABELS,'none'): raise ValueError('Unknown human label')
            if 'onset_verified' in i and type(i['onset_verified']) is not bool:
                raise ValueError('onset_verified must be a JSON boolean')
            if not any(start <= p.get('capture_mono',-float('inf')) < end for p in r['samples']):
                raise ValueError('Labelled interval contains no prediction samples')
            previous=end
    return recordings


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('annotations',type=Path)
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--tune',action='store_true')
    args=ap.parse_args()
    recordings=load_manifest(args.annotations.resolve())
    base={k:DEFAULT['temporal_'+k] for k in ('window','hold','confidence','margin','max_gap','min_samples')}
    splits={s:[r for r in recordings if r['split']==s] for s in ('selection','holdout')}
    result=dict(parameters=base,parameter_status='provisional_not_webcam_validated',
                annotations=str(args.annotations.resolve()),
                current={s:evaluate(rs,base) if rs else None for s,rs in splits.items()})
    # Actual robot activations are measured separately from offline candidates.
    # Their control log belongs to its recorded algorithm, not this replay.
    actual=[]
    for r in recordings:
        if not r.get('control'): continue
        decisions=[]
        with (args.annotations.resolve().parent/r['control']).open() as stream:
            for line in stream:
                e=json.loads(line)
                if e.get('event')!='ACTION_START' or e.get('source')!='webcam': continue
                stamp=e.get('capture_mono',e['monotonic'])
                i=next((i for i in r['intervals'] if i['start_capture_mono']<=stamp<i['end_capture_mono']),None)
                if i:
                    decisions.append(dict(action_id=e['id'],label=e['label'],truth=i['label'],
                         wrong=e['label']!=i['label'],capture_mono=stamp,
                         latency_seconds=e['monotonic']-i['start_capture_mono'] if i.get('onset_verified') else None))
        seconds=sum(i['end_capture_mono']-i['start_capture_mono'] for i in r['intervals'])
        actual.append(dict(recording=r['id'],scope='actual ACTION_START in original recorded control log',
                           labelled_seconds=seconds,activations=len(decisions),
                           wrong_activations=sum(d['wrong'] for d in decisions),
                           wrong_activations_per_minute=sum(d['wrong'] for d in decisions)*60/seconds if seconds else None,
                           decisions=decisions))
    result['actual_recorded_activations']=actual
    if args.tune:
        if not splits['selection']: raise ValueError('Tuning requires selection data')
        candidates=[]
        for window,hold,confidence,margin in itertools.product((.3,.5,.7),(.1,.2),(.5,.55,.65),(.1,.15,.2)):
            cfg=dict(base,window=window,hold=hold,confidence=confidence,margin=margin)
            report=evaluate(splits['selection'],cfg)
            # Rank ONLY selection data; holdout is evaluated once afterwards.
            rank=(report['false_motion_confirmations'],report['wrong_confirmation_events'],
                  report['missed_intervals'],-(report['macro_f1'] or 0),
                  report['latency_p95_seconds'] if report['latency_p95_seconds'] is not None else float('inf'))
            candidates.append((rank,cfg,report))
        _,best,report=min(candidates,key=lambda x:x[0])
        required=set(LABELS)-{'disgust'}|{'none'}
        adequate=all(rs and required <= {i['label'] for r in rs for i in r['intervals']}
                     and all(r.get('annotation_kind')=='human_video' and
                             all(i.get('onset_verified') for i in r['intervals'] if i['label']!='none')
                             for r in rs) for rs in splits.values())
        result.update(candidate_count=len(candidates),best_on_selection=best,
                      best_selection_metrics=report,
                      best_holdout_metrics=evaluate(splits['holdout'],best) if splits['holdout'] else None,
                      selection_status='review_holdout_metrics' if adequate else 'insufficient_labels_or_independent_holdout',
                      suggested_control_config=dict(decision_mode='temporal',**{'temporal_'+k:v for k,v in best.items()}) if adequate else None,
                      configuration_written=False)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('current','best_selection_metrics','best_holdout_metrics')},ensure_ascii=False,indent=2))


if __name__=='__main__': main()
