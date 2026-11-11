#!/usr/bin/env python3
"""Capture live windows of this session; graceful FFmpeg q then full decode."""
import argparse,json,os,shutil,signal,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bai08_turtlebot4.ipc import atomic

def main():
    ap=argparse.ArgumentParser();ap.add_argument('run');ap.add_argument('output');ap.add_argument('--launch-sid',type=int,required=True);ap.add_argument('--panel-sid',type=int,required=True);ap.add_argument('--microphone');a=ap.parse_args()
    run=Path(a.run);out=Path(a.output)
    if out.exists():raise RuntimeError('Refusing overwrite')
    tool=shutil.which('xdotool') or os.environ.get('BAI08_XDOTOOL')
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg:
        import imageio_ffmpeg
        ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
    stopped=False
    def stop(*_):
        nonlocal stopped
        stopped=True
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,stop)
    deadline=time.monotonic()+120
    windows=[]
    while not stopped:
        windows=[]
        for title,sid in [('Bai08 - Webcam Emotion - '+run.name,a.panel_sid),('^Gazebo$',a.launch_sid),('emotion.rviz|RViz',a.launch_sid)]:
            result=subprocess.run([tool,'search','--onlyvisible','--name',title],capture_output=True,text=True)
            valid=[]
            for wid in result.stdout.split():
                try:
                    pid=int(subprocess.check_output([tool,'getwindowpid',wid],text=True).strip())
                    if os.getsid(pid)==sid:valid.append(dict(id=int(wid),title=title,pid=pid,sid=sid))
                except (ValueError,OSError,subprocess.CalledProcessError):pass
            if len(valid)>1:raise RuntimeError('Multiple windows in own session: '+title)
            if valid:windows.append(valid[0])
        if len(windows)==3:break
        if time.monotonic()>deadline:raise RuntimeError('Own-session windows missing: '+repr(windows))
        time.sleep(.5)
    if stopped:return 130
    # Arrange real windows without covering one another before x11grab.
    for win,(x,y,w,h) in zip(windows,[(75,45,1060,970),(1140,45,775,480),(1140,560,775,460)]):
        subprocess.run([tool,'windowsize',str(win['id']),str(w),str(h)],check=True)
        time.sleep(.2)
        subprocess.run([tool,'windowmove',str(win['id']),str(x),str(y)],check=True)
        subprocess.run([tool,'windowraise',str(win['id'])],check=True)
    time.sleep(1.)
    display=os.environ.get('DISPLAY',':0')
    if '.' not in display.rsplit(':',1)[-1]:display+='.0'
    cmd=[ffmpeg,'-hide_banner','-n','-stdin']
    for win in windows:cmd+=['-thread_queue_size','64','-f','x11grab','-framerate','12','-window_id',str(win['id']),'-draw_mouse','0','-i',display]
    audio=None
    if a.microphone:
        if a.microphone.endswith('.monitor'):raise RuntimeError('Microphone must not be monitor')
        audio=subprocess.Popen(['parec','--device='+a.microphone,'--raw','--format=s16le','--rate=16000','--channels=1'],stdout=subprocess.PIPE,start_new_session=True)
        fd=audio.stdout.fileno();cmd+=['-thread_queue_size','128','-f','s16le','-ar','16000','-ac','1','-i',f'pipe:{fd}']
    cmd+=['-filter_complex','[0:v]setpts=PTS-STARTPTS,scale=1000:900:force_original_aspect_ratio=decrease,pad=1000:900:(ow-iw)/2:(oh-ih)/2:color=0xF2F2F2[p];[1:v]setpts=PTS-STARTPTS,scale=600:450[g];[2:v]setpts=PTS-STARTPTS,scale=600:450[r];[g][r]vstack=inputs=2[s];[p][s]hstack=inputs=2,fps=12[v]','-map','[v]']
    if audio:cmd+=['-map','3:a:0','-c:a','libopus','-b:a','64k','-shortest']
    cmd+=['-c:v','libvpx','-deadline','realtime','-cpu-used','8','-threads','2','-b:v','1600k','-crf','12','-g','120','-lag-in-frames','0','-auto-alt-ref','0','-pix_fmt','yuv420p','-cluster_time_limit','1000','-f','webm',str(out)]
    meta=dict(source='live session X11 app windows',windows=windows,video=str(out),audio=bool(audio),started_at=time.time(),recording=True)
    with open(str(out)+'.log','w') as log:
        proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=log,stderr=log,pass_fds=(fd,) if audio else (),start_new_session=True)
        if audio:audio.stdout.close()
        warm_deadline=time.monotonic()+15
        while proc.poll() is None and not stopped and (not out.exists() or out.stat().st_size==0) and time.monotonic()<warm_deadline:time.sleep(.1)
        if proc.poll() is not None or not out.exists() or out.stat().st_size==0:
            stopped=True;meta['recording']=False
        atomic(run/'recording.json',meta)
        print(('ĐANG QUAY WEBM: ' if meta['recording'] else 'LỖI KHỞI ĐỘNG WEBM: ')+str(out)+(' + micro' if audio else ' (không âm thanh)'),flush=True)
        while proc.poll() is None and not stopped:time.sleep(.2)
        if audio and audio.poll() is None:audio.terminate()
        if proc.poll() is None:
            try:proc.stdin.write(b'q\n');proc.stdin.flush();proc.stdin.close()
            except (BrokenPipeError,OSError):pass
        try:proc.wait(timeout=25)
        except subprocess.TimeoutExpired:
            proc.terminate();proc.wait(timeout=10)
        if audio:audio.wait(timeout=5)
    verify=subprocess.run([ffmpeg,'-v','error','-i',str(out),'-f','null','-'],capture_output=True,text=True,timeout=180)
    meta.update(ended_at=time.time(),returncode=proc.returncode,recording=False,decode_verified=verify.returncode==0,decode_errors=verify.stderr,bytes=out.stat().st_size)
    atomic(run/'recording.json',meta);atomic(str(out)+'.json',meta)
    for name,options in [('first',['-frames:v','1']),('last',['-sseof','-1'])]:
        command=[ffmpeg,'-v','error','-y']
        if name=='last':command+=options
        command+=['-i',str(out),'-frames:v','1',str(out.with_suffix('.'+name+'.png'))]
        subprocess.run(command,timeout=25,check=True)
    return 0 if verify.returncode==0 and proc.returncode==0 else 1
if __name__=='__main__':sys.exit(main())
