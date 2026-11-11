#!/usr/bin/env python3
"""COMPONENT TEST: explicit synthetic scores, physical simulator odometry."""
import argparse,json,math,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bai08_turtlebot4.ipc import atomic,read
from bai08_turtlebot4.core import LABELS
ap=argparse.ArgumentParser();ap.add_argument('run');ap.add_argument('--labels',nargs='+',default=['happy','sad','angry','fear','surprise']);a=ap.parse_args();run=Path(a.run)
seq=0

def frame(label,**extra):
    global seq
    seq+=1;now=time.monotonic()
    p=dict(session=run.name,source='component_test',seq=seq,frame_id=seq,capture_mono=now,prediction_mono=now,wall=time.time(),status='OK',faces=1,scores={k:float(k==label) for k in LABELS})
    p.update(extra);atomic(run/'prediction.json',p);time.sleep(.08)

def hold(label,seconds):
    until=time.monotonic()+seconds
    while time.monotonic()<until:frame(label)

results=[]
for label in a.labels:
    hold('neutral',1.4)
    before=read(run/'status.json');print('BEGIN',label,before.get('state'),before.get('reason'),flush=True)
    started=time.monotonic();observed=False;last_action=None
    while time.monotonic()-started<39:
        frame(label);s=read(run/'status.json')
        if s.get('action'):observed=True;last_action=s['action']
        if observed and not s.get('action'):break
    hold('neutral',1.)
    events=[json.loads(l) for l in (run/'control.jsonl').read_text().splitlines() if 'ACTION_END' in l]
    end=events[-1] if events and events[-1]['label']==label else None
    after=read(run/'status.json')
    target=math.pi/3 if label in ('happy','sad') else 2*math.pi if label=='surprise' else .17 if label=='angry' else .23
    measured=abs(end['yaw']) if end and label in ('happy','sad','surprise') else end['distance'] if end else None
    tol=.13 if label in ('happy','sad','surprise') else .035
    passed=bool(end and end['reason']=='completed' and abs(measured-target)<=tol and max(abs(v) for v in after.get('measured',[99,99]))<.025)
    results.append(dict(source='component_test synthetic scores + actual simulation odom',label=label,observed=observed,target=target,tolerance=tol,measured=measured,pass_=passed,end=end,after=after))
    atomic(run/'motion_tests.json',results);print(label,'PASS' if passed else 'FAIL',measured,end and end['reason'],flush=True)
print('All component tests complete; not webcam recognition evidence.',flush=True)
