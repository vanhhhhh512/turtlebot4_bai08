#!/usr/bin/env python3
import argparse,fcntl,json,os,signal,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bai08_turtlebot4.ipc import atomic,read

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--component-test',action='store_true');ap.add_argument('--no-record',action='store_true');ap.add_argument('--headless',action='store_true');ap.add_argument('--camera',type=int,default=0);ap.add_argument('--microphone');a=ap.parse_args()
    package=Path(__file__).resolve().parents[1];root=package.parents[2]
    domain=os.environ.get('BAI08_DOMAIN','108')
    lock=open('/tmp/bai08_domain_'+domain+'.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    session=time.strftime('%Y%m%d_%H%M%S')+'_'+str(os.getpid());run=root/'runs'/session;run.mkdir(parents=True)
    video=root/'results'/('demo_'+session+'.webm');(root/'results').mkdir(exist_ok=True)
    # Whitelist environment: no inherited ROS/Jazzy, Python or Ignition overlay.
    env={k:v for k,v in os.environ.items() if k in ('HOME','USER','DISPLAY','XAUTHORITY','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS','LANG','LC_ALL','PATH')}
    env.update(PATH=str(Path.home()/'.local/bin')+':/usr/local/bin:/usr/bin:/bin',BAI08_DOMAIN=domain,BAI08_PACKAGE=str(package),BAI08_SESSION=session,BAI08_RUN=str(run),IGN_PARTITION='bai08_'+session)
    local_underlay=root/'underlay'
    previous_underlay=root.parent/'week7/verification/underlay'
    underlay=os.environ.get('BAI08_UNDERLAY',str(local_underlay if (local_underlay/'install/setup.bash').exists() else previous_underlay))
    if not Path(underlay+'/install/setup.bash').is_file():raise RuntimeError('Missing Create3 underlay: set BAI08_UNDERLAY')
    env['BAI08_UNDERLAY']=underlay
    tool=__import__('shutil').which('xdotool') or str(root.parent/'week5/tools/local/usr/bin/xdotool')
    if Path(tool).is_file():
        env['BAI08_XDOTOOL']=tool
        local_lib=Path(tool).parents[1]/'lib/x86_64-linux-gnu'
        if local_lib.is_dir():env['LD_LIBRARY_PATH']=str(local_lib)
    meta=dict(run=str(run),video=str(video),session=session,domain=int(domain),partition=env['IGN_PARTITION'],source='component_test' if a.component_test else 'webcam',started_at=time.time(),pids={})
    atomic(run/'session.json',meta);atomic(root/'results/latest_session.json',meta)
    stopped=False
    def stop(*_):
        nonlocal stopped
        (run/'STOP').touch();stopped=True
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(sig,stop)
    procs={};logs=[]
    def spawn(name,cmd,child_env=env):
        log=(run/(name+'.log')).open('w');logs.append(log)
        p=subprocess.Popen(cmd,env=child_env,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,start_new_session=True)
        procs[name]=p;meta['pids'][name]=p.pid;atomic(run/'session.json',meta);atomic(root/'results/latest_session.json',meta);return p
    def finish(name,sig=signal.SIGINT,timeout=30):
        p=procs.get(name)
        if p is None:return
        if p.poll() is None:
            try:os.killpg(p.pid,sig)
            except ProcessLookupError:pass
        try:p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid,signal.SIGTERM);p.wait(timeout=15)
    result=0
    try:
        print('Run: '+str(run)+'\nDomain '+domain+' | '+env['IGN_PARTITION'],flush=True)
        command='source "$BAI08_PACKAGE/scripts/ros_env.sh"; source "'+str(root)+'/ros2_ws/install/setup.bash"; exec ros2 launch bai08_turtlebot4 demo.launch.py run_dir:="$BAI08_RUN" gui:='+str(not a.headless).lower()+' allow_test:='+str(a.component_test).lower()
        sim=spawn('simulation',['bash','--noprofile','--norc','-c',command])
        if not a.component_test:
            ml_env={k:v for k,v in env.items() if k not in ('LD_LIBRARY_PATH',)}
            ml_env.update(DEEPFACE_HOME=str(root/'.model_cache'),DEEPFACE_BACKEND_ENGINE='onnx',OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2')
            spawn('worker',[str(root/'.venv_emotion/bin/python'),str(package/'scripts/emotion_worker.py'),str(run),'--camera',str(a.camera)],ml_env)
        panel=None
        if not a.headless:panel=spawn('panel',['/usr/bin/python3',str(package/'scripts/panel.py'),str(run)])
        deadline=time.monotonic()+240
        while not stopped:
            if any(p.poll() is not None for p in procs.values()):raise RuntimeError('A process exited before ready; inspect logs')
            status=read(run/'status.json')
            robot=status.get('prepared') and status.get('odom_age',99)<.5 and status.get('clock_age',99)<.6
            model=a.component_test or read(run/'model_ready.json').get('ready')
            if robot and model:
                print('ROBOT + MODEL READY. '+('COMPONENT TEST INPUT ONLY' if a.component_test else 'Giữ Neutral trước webcam để rearm.'),flush=True)
                atomic(run/'READY.json',dict(monotonic=time.monotonic(),robot=True,model=bool(model),source=meta['source']))
                if not a.no_record and not a.headless:
                    cmd=['/usr/bin/python3',str(package/'scripts/record_demo.py'),str(run),str(video),'--launch-sid',str(sim.pid),'--panel-sid',str(panel.pid)]
                    if a.microphone:cmd+=['--microphone',a.microphone]
                    spawn('recorder',cmd)
                break
            if time.monotonic()>deadline:raise TimeoutError('READY timeout 240s')
            time.sleep(.2)
        while not stopped:
            for name,p in procs.items():
                if p.poll() is not None:raise RuntimeError(name+' exited; see '+str(run/(name+'.log')))
            time.sleep(.1)
    except (Exception,KeyboardInterrupt) as e:
        print('Session: '+repr(e),flush=True);result=1
    finally:
        (run/'STOP').touch()
        # Controller keeps publishing zero; preserve windows until WebM finalized.
        time.sleep(1.)
        finish('recorder',timeout=220)
        finish('worker');finish('panel',signal.SIGTERM);finish('simulation',timeout=45)
        for p in procs.values():
            try:os.killpg(p.pid,signal.SIGTERM)
            except ProcessLookupError:pass
        meta.update(ended_at=time.time(),exit_code=result,returncodes={k:p.returncode for k,p in procs.items()})
        atomic(run/'session.json',meta)
        for log in logs:log.close()
        print('Session closed. '+str(run)+'\nVideo: '+str(video) if video.exists() else 'Session closed. '+str(run),flush=True)
    return result
if __name__=='__main__':sys.exit(main())
