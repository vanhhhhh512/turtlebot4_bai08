#!/usr/bin/env python3
"""Isolated component faults: real odom, injected predictions/hazard, paused sim."""
import argparse,json,math,os,signal,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bai08_turtlebot4.ipc import atomic,read
from bai08_turtlebot4.core import LABELS
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from nav_msgs.msg import Odometry
from irobot_create_msgs.msg import HazardDetectionVector,HazardDetection
ap=argparse.ArgumentParser();ap.add_argument('run');a=ap.parse_args();run=Path(a.run);session=read(run/'session.json');seq=read(run/'prediction.json').get('seq',0)
rclpy.init();node=Node('bai08_fault_observer');velocity=[None,None];samples=[];results=[]
def odom(m):
 velocity[:]=[m.twist.twist.linear.x,m.twist.twist.angular.z];samples.append(dict(monotonic=time.monotonic(),v=velocity[0],w=velocity[1]))
node.create_subscription(Odometry,'/odom',odom,qos_profile_sensor_data)
hazpub=node.create_publisher(HazardDetectionVector,'/hazard_detection',10)
def pump(seconds):
 until=time.monotonic()+seconds
 while time.monotonic()<until:rclpy.spin_once(node,timeout_sec=.01)
def send(label):
 global seq
 seq+=1;now=time.monotonic();atomic(run/'prediction.json',dict(session=run.name,seq=seq,capture_mono=now,source='component_test',faces=1,status='OK',scores={k:float(k==label) for k in LABELS}))
def hold(label,seconds):
 until=time.monotonic()+seconds
 while time.monotonic()<until:send(label);pump(.08)
def begin():
 hold('neutral',1.4);hold('fear',1.4)
 assert read(run/'status.json').get('action'),read(run/'status.json')
def record(fault,**kw):
 result=dict(fault=fault,source='injected component input + actual simulation odom',**kw);results.append(result);atomic(run/'runtime_faults.json',results);print(result,flush=True)
def service(pause):
 env=os.environ.copy();env['IGN_PARTITION']=session['partition']
 return subprocess.run(['ign','service','-s','/world/emotion_arena/control','--reqtype','ignition.msgs.WorldControl','--reptype','ignition.msgs.Boolean','--timeout','3000','--req','pause: '+str(pause).lower()],env=env,capture_output=True,text=True,timeout=5)
try:
 # Keep the same expression for several seconds after a finite action.
 hold('neutral',1.4);hold('fear',6.)
 ends=[json.loads(l) for l in (run/'control.jsonl').read_text().splitlines() if 'ACTION_END' in l]
 s=read(run/'status.json');record('hold_same_expression',pass_=not s.get('action') and len(ends)==1,end_count=len(ends),state=s['state'])
 begin();start=time.monotonic();resp=service(True);hold('fear',1.2);s=read(run/'status.json')
 events=[json.loads(l) for l in (run/'control.jsonl').read_text().splitlines() if 'ACTION_END' in l]
 paused_stopped=s.get('v')==s.get('w')==0 and not s.get('action') and events[-1]['reason'] in ('ODOM_STALE','CLOCK_STALE','ROBOT_NOT_PREPARED');service(False);hold('fear',1.5)
 record('sim_pause_resume',pass_=paused_stopped and not read(run/'status.json').get('action'),pause_response=resp.stdout,reason=s['reason'],cmd_zero=s.get('v')==s.get('w')==0)
 begin();start=time.monotonic();msg=HazardDetectionVector();d=HazardDetection();d.type=HazardDetection.BUMP;msg.detections=[d]
 for _ in range(10):hazpub.publish(msg);send('fear');pump(.05)
 hold('fear',1.0);s=read(run/'status.json');events=[json.loads(l) for l in (run/'control.jsonl').read_text().splitlines() if 'ACTION_END' in l]
 record('injected_bump_hazard',pass_=events[-1]['reason']=='HAZARD' and not s.get('action') and max(abs(v) for v in velocity)<.025,reason=events[-1]['reason'],measured=velocity[:],note='Synthetic HazardDetection BUMP, not collision test')
 begin()
 # Find exactly the controller in the known launch session, never any old node.
 sid=session['pids']['simulation'];matches=[]
 for path in Path('/proc').iterdir():
  if path.name.isdigit():
   try:
    cmd=(path/'cmdline').read_bytes().replace(b'\0',b' ').decode()
    if '/lib/bai08_turtlebot4/controller ' in cmd and os.getsid(int(path.name))==sid:matches.append(int(path.name))
   except (OSError,ProcessLookupError):pass
 assert len(matches)==1,matches
 pid=matches[0];start=time.monotonic();os.kill(pid,signal.SIGSTOP);stop_at=None
 try:
  while time.monotonic()-start<2.5:
   pump(.02)
   if velocity[0] is not None and max(abs(v) for v in velocity)<.025:stop_at=time.monotonic();break
 finally:os.kill(pid,signal.SIGCONT)
 pump(.4);hold('fear',1.4);s=read(run/'status.json')
 record('controller_frozen',pass_=bool(stop_at and stop_at-start<2.5 and not s.get('action')),actual_stop_s=stop_at-start if stop_at else None,pid=pid,note='SIGSTOP/CONT simulates a hung publisher; independent observer measures odom')
finally:
 service(False);send('neutral');pump(.5);(run/'STOP').touch();atomic(run/'observer_odom.json',samples);node.destroy_node();rclpy.shutdown()
