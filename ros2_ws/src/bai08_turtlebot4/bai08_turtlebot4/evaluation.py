"""Labelled-recording replay of the recognizer, without claiming robot motion."""
import math
from collections import Counter
from .core import LABELS
from .temporal import TemporalScores

MOTION_LABELS = set(LABELS) - {'neutral', 'disgust'}


def evaluate(recordings, parameters):
    confusion = Counter()
    events, intervals, latencies = [], [], []
    duration = 0.
    for recording in recordings:
        filt = TemporalScores(**parameters)
        labels = recording['intervals']
        duration += sum(i['end_capture_mono']-i['start_capture_mono'] for i in labels)
        accepted_label, absence_start, absence_last = None, None, None
        seq = frame = -1
        last_stamp = -math.inf
        clip_events = []
        for p in recording['samples']:
            stamp = p.get('capture_mono')
            if (p.get('source') != 'webcam' or type(p.get('seq')) is not int
                    or type(p.get('frame_id')) is not int
                    or p['seq'] <= seq or p['frame_id'] <= frame
                    or not isinstance(stamp, (int, float)) or not math.isfinite(stamp)
                    or stamp <= last_stamp):
                continue
            seq, frame, last_stamp = p['seq'], p['frame_id'], stamp
            interval = next((i for i in labels if i['start_capture_mono'] <= stamp < i['end_capture_mono']), None)
            truth = interval['label'] if interval else None
            valid = (p.get('status') == 'OK' and p.get('faces') == 1
                     and not p.get('identity_changed'))
            s = p.get('scores', {})
            valid = (valid and set(s) == set(LABELS)
                     and all(isinstance(v,(int,float)) and math.isfinite(v) and 0 <= v <= 1 for v in s.values())
                     and .98 <= sum(s.values()) <= 1.02)
            predicted = '__abstain__'
            if not valid or max(s, key=s.get) == 'disgust':
                filt.reset()
                if p.get('status') == 'NO_FACE' and p.get('faces') == 0:
                    if absence_last is None or stamp-absence_last >= .9:
                        absence_start = stamp
                    absence_last = stamp
                    if stamp-absence_start >= 1: accepted_label = None
                else:
                    absence_start = absence_last = None
            else:
                absence_start = absence_last = None
                result = filt.add(stamp,s)
                if result['confirmed']:
                    predicted = result['label']
                    if predicted != accepted_label:
                        e = dict(recording=recording['id'], capture_mono=stamp,
                                 label=predicted, truth=truth, seq=p['seq'],
                                 wrong=truth is not None and predicted != truth,
                                 false_motion_confirmation=truth is not None and
                                 predicted in MOTION_LABELS and predicted != truth)
                        events.append(e);clip_events.append(e)
                        accepted_label = predicted
            if truth == 'none' and predicted not in MOTION_LABELS:
                predicted = 'none'
            if truth is not None: confusion[truth,predicted] += 1
        for interval in labels:
            correct = [e for e in clip_events if e['label']==interval['label'] and
                       interval['start_capture_mono'] <= e['capture_mono'] < interval['end_capture_mono']]
            if interval['label'] == 'none':
                detected = not any(e['false_motion_confirmation'] for e in clip_events if
                                   interval['start_capture_mono'] <= e['capture_mono'] < interval['end_capture_mono'])
            else:
                detected = bool(correct)
            delay = (correct[0]['capture_mono']-interval['start_capture_mono']
                     if correct and interval.get('onset_verified') else None)
            if delay is not None: latencies.append(delay)
            intervals.append(dict(recording=recording['id'], label=interval['label'],
                                  detected=detected, latency_seconds=delay,
                                  onset_verified=bool(interval.get('onset_verified'))))
    classes = sorted({a for a,b in confusion})
    f1 = {}
    for label in classes:
        tp = confusion[label,label]
        fp = sum(n for (a,b),n in confusion.items() if a != label and b == label)
        fn = sum(n for (a,b),n in confusion.items() if a == label and b != label)
        f1[label] = 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.
    total = sum(confusion.values())
    wrong = sum(e['wrong'] for e in events)
    false_motion = sum(e['false_motion_confirmation'] for e in events)
    ordered = sorted(latencies)
    return dict(
        scope='offline recognizer confirmations; no busy-action/odom simulation; not actual robot activations',
        labelled_seconds=duration, labelled_samples=total,
        accuracy_with_abstentions=sum(n for (a,b),n in confusion.items() if a==b)/total if total else None,
        abstention_rate=sum(n for (a,b),n in confusion.items() if b=='__abstain__')/total if total else None,
        macro_f1=sum(f1.values())/len(f1) if f1 else None, per_class_f1=f1,
        confusion=[dict(truth=a,predicted=b,count=n) for (a,b),n in sorted(confusion.items())],
        wrong_confirmation_events=wrong, false_motion_confirmations=false_motion,
        false_motion_confirmations_per_minute=false_motion*60/duration if duration else None,
        missed_intervals=sum(not i['detected'] for i in intervals), intervals=intervals,
        latency_count=len(ordered), latency_p50_seconds=ordered[len(ordered)//2] if ordered else None,
        latency_p95_seconds=ordered[min(len(ordered)-1,math.ceil(.95*len(ordered))-1)] if ordered else None,
        events=events)
