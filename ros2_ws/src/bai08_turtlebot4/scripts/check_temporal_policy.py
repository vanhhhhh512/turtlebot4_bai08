#!/usr/bin/env python3
"""Synthetic scores through real ROS/controller/odom; not webcam accuracy."""
import argparse
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bai08_turtlebot4.ipc import read,atomic
from bai08_turtlebot4.core import LABELS

ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('run',type=Path)
run=ap.parse_args().run
assert read(run/'session.json')['source']=='component_test'
cfg=read(run/'effective_config.json')
assert cfg['decision_mode']=='temporal'
seq=read(run/'prediction.json').get('seq',0)
results=[]


def send(label='fear',score=.95,**extra):
    global seq
    seq+=1
    atomic(run/'prediction.json',dict(session=run.name,source='component_test',seq=seq,
           frame_id=seq,capture_mono=time.monotonic(),status='OK',faces=1,
           scores={k:score if k==label else (1-score)/6 for k in LABELS},**extra))
    time.sleep(.16)
    return read(run/'status.json')


def hold(label='fear',seconds=1.,**extra):
    until=time.monotonic()+seconds
    while time.monotonic()<until:s=send(label,**extra)
    return s


def until_action(label):
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        s=send(label)
        if s.get('action'):return s
    raise AssertionError(('no action',label,s))


def start():
    atomic(run/'ui_command.json',dict(session=run.name,seq=time.monotonic_ns(),
           command='START',monotonic=time.monotonic()))
    time.sleep(.2)


def check(name,condition,**evidence):
    results.append(dict(scenario=name,pass_=bool(condition),**evidence))
    atomic(run/'temporal_policy_tests.json',dict(source=__doc__,config=cfg,results=results))
    print(name,'PASS' if condition else 'FAIL',flush=True)
    assert condition,(name,read(run/'status.json'))


try:
    start()
    s=send(score=.999)
    check('one_high_frame_cannot_bypass_filter',not s['action'])
    s=hold(score=1/7)
    check('high_spike_followed_by_uncertainty_does_not_start',not s['action'])
    # Explicit small-margin input, even when the leading score is 55%.
    weak=dict.fromkeys(LABELS,0.);weak.update(happy=.55,sad=.45)
    until=time.monotonic()+1.2
    while time.monotonic()<until:
        seq+=1
        atomic(run/'prediction.json',dict(session=run.name,source='component_test',seq=seq,
               frame_id=seq,capture_mono=time.monotonic(),status='OK',faces=1,scores=weak))
        time.sleep(.16)
    s=read(run/'status.json')
    check('insufficient_margin_does_not_start',not s['action'])
    s=until_action('fear');first=s['action']['id'];confirmation=s['confirmation']
    check('stable_mean_starts_without_neutral',s['action']['label']=='fear' and
          s['action']['branch']=='temporal_mean',confirmation=confirmation)
    check('acceptance_audits_real_window_and_mean',confirmation['temporal']['ready'] and
          confirmation['temporal']['stable_seconds']>=cfg['temporal_hold']-1e-8 and
          confirmation['score']==confirmation['temporal']['scores']['fear'])
    deadline=time.monotonic()+5
    while s['action'] and time.monotonic()<deadline:s=send()
    check('finite_action_completes',not s['action'] and s['locked_label']=='fear')
    s=hold()
    check('held_expression_does_not_repeat',not s['action'])
    s=send('sad')
    check('new_label_must_rebuild_post_action_window',not s['action'])
    s=until_action('sad');second=s['action']['id']
    check('stable_different_label_starts',s['action']['label']=='sad' and second>first)
    s=hold('happy',seconds=.9)
    check('different_label_cannot_interrupt_or_queue',s['action']['id']==second)
    # Construct separately to override packet status/faces.
    seq+=1
    atomic(run/'prediction.json',dict(session=run.name,source='component_test',seq=seq,
           frame_id=seq,capture_mono=time.monotonic(),status='NO_FACE',faces=0))
    time.sleep(.2);s=read(run/'status.json')
    check('no_face_immediately_stops_and_erases_history',not s['action'] and not s['temporal'])
    s=hold('sad')
    check('short_absence_does_not_resume_consumed_label',not s['action'])
    until=time.monotonic()+1.4
    while time.monotonic()<until:
        seq+=1
        atomic(run/'prediction.json',dict(session=run.name,source='component_test',seq=seq,
               frame_id=seq,capture_mono=time.monotonic(),status='NO_FACE',faces=0))
        time.sleep(.16)
    s=until_action('sad')
    check('fresh_absence_releases_same_label_with_new_filter',s['action']['id']>second)
    s=send('neutral')
    check('one_neutral_spike_does_not_confirm_stop',bool(s['action']))
    s=hold('neutral',seconds=1.4)
    check('stable_neutral_stops_and_releases',not s['action'] and s['locked_label'] is None and
          s['confirmation']['label']=='neutral' and s['confirmation']['branch']=='temporal_mean')
    s=until_action('fear')
    (run/'STOP').touch();time.sleep(.2)
    s=hold('happy')
    check('stop_cannot_be_bypassed_by_stable_high_mean',not s['action'] and not s['enabled'])
    start();s=send('happy')
    check('start_requires_new_temporal_history',not s['action'])
    s=until_action('happy')
    check('start_then_stable_new_frames_recovers',s['action']['label']=='happy')
finally:
    (run/'STOP').touch()
