#!/usr/bin/env python3
"""Explicit synthetic event inputs through the real node and simulation odom."""
import argparse
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bai08_turtlebot4.ipc import read, atomic
from bai08_turtlebot4.core import LABELS

ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('run',type=Path)
run=ap.parse_args().run
assert read(run/'session.json')['source']=='component_test'
assert read(run/'effective_config.json')['decision_mode']=='events'
seq=read(run/'prediction.json').get('seq',0)
results=[]


def send(label='fear',score=.95,**extra):
    global seq
    seq+=1
    packet=dict(session=run.name,source='component_test',seq=seq,frame_id=seq,
                capture_mono=time.monotonic(),status='OK',faces=1,
                scores={k:score if k==label else (1-score)/6 for k in LABELS})
    packet.update(extra)
    atomic(run/'prediction.json',packet)
    time.sleep(.20)
    return read(run/'status.json')


def start():
    atomic(run/'ui_command.json',dict(session=run.name,seq=time.monotonic_ns(),
           command='START',monotonic=time.monotonic()))
    time.sleep(.2)


def check(name,condition,**evidence):
    results.append(dict(scenario=name,pass_=bool(condition),**evidence))
    atomic(run/'event_policy_tests.json',dict(
        source='synthetic component scores + actual ROS node/simulator odom',results=results))
    assert condition,(name,read(run/'status.json'))
    print(name,'PASS',flush=True)


try:
    start()
    s=send('fear',.6001)
    check('first_high_frame_without_neutral',bool(s['action']) and s['action']['seq']==seq)
    first=s['action']['id']
    deadline=time.monotonic()+8
    while s['action'] and time.monotonic()<deadline:s=send('fear')
    check('finite_action_completes',not s['action'] and s['locked_label']=='fear')
    for _ in range(6):s=send('fear')
    check('held_image_does_not_repeat',not s['action'])
    s=send('sad')
    check('new_expression_first_frame_waits',not s['action'] and s['state']=='WAIT_CHANGE')
    s=send('sad')
    check('new_expression_second_frame_starts',bool(s['action']) and s['action']['label']=='sad')
    second=s['action']['id']
    s=send('happy')
    check('other_label_cannot_interrupt_or_queue',s['action']['id']==second)
    s=send(status='NO_FACE',faces=0)
    check('no_face_cancels_now',not s['action'])
    for _ in range(4):s=send('sad')
    check('short_gap_does_not_resume_consumed_action',not s['action'])
    for _ in range(8):s=send(status='NO_FACE',faces=0)
    s=send('sad')
    check('fresh_absence_reopens_same_expression',bool(s['action']) and s['action']['id']>second)
    (run/'STOP').touch();time.sleep(.2)
    for _ in range(3):s=send('fear')
    check('stop_cannot_be_bypassed_by_high_score',not s['action'] and not s['enabled'])
    start()
    for i in range(10):
        s=send('fear',.6000)
        assert not s['action'],s
    s=send('fear',.6000)
    check('sixty_percent_uses_eleven_vote_fallback',bool(s['action']) and
          s['action']['branch']=='vote_threshold' and s['vote_counts']['fear']==11)
    s=send('neutral',.6001)
    check('neutral_stops_and_opens_new_round',not s['action'] and s['locked_label'] is None)
finally:
    (run/'STOP').touch()
