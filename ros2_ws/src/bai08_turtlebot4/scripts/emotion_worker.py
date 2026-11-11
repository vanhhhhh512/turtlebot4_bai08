#!/usr/bin/env python3
"""Real webcam + DeepFace. Latest-frame thread; ML never enters ROS executor."""
import argparse, hashlib, json, os, signal, sys, threading, time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bai08_turtlebot4.ipc import atomic
os.environ.setdefault('DEEPFACE_BACKEND_ENGINE','onnx')
os.environ.setdefault('OMP_NUM_THREADS','2')
import cv2
import numpy as np
from deepface import DeepFace


def main():
    ap=argparse.ArgumentParser();ap.add_argument('run');ap.add_argument('--camera',type=int,default=0);ap.add_argument('--seconds',type=float,default=0);args=ap.parse_args()
    run=Path(args.run);run.mkdir(parents=True,exist_ok=True)
    stop=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    cap=cv2.VideoCapture(args.camera,cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,640);cap.set(cv2.CAP_PROP_FRAME_HEIGHT,480);cap.set(cv2.CAP_PROP_BUFFERSIZE,1)
    if not cap.isOpened():raise RuntimeError('Cannot open real webcam '+str(args.camera))
    latest=[None];lock=threading.Lock();counts=[0];started=time.monotonic()
    def capture():
        failures=0
        while not stop.is_set():
            ok,frame=cap.read();stamp=time.monotonic();counts[0]+=1
            with lock:latest[0]=(frame if ok else None,stamp,counts[0])
            if ok:
                failures=0
                # Live camera refresh is independent of inference.
                cv2.imwrite(str(run/'camera.tmp.jpg'),frame)
                os.replace(run/'camera.tmp.jpg',run/'camera.jpg')
            else:
                failures+=1;time.sleep(.05)
                if failures>30:stop.set()
    thread=threading.Thread(target=capture,daemon=True);thread.start()
    log=(run/'predictions.jsonl').open('a',buffering=1)
    seq=0;prev_box=None;prev_stamp=0
    try:
        # Downloads should be completed by prepare_model.py before demo.
        required=('facial_expression_model_weights.onnx','haarcascade_frontalface_default.xml','haarcascade_eye.xml')
        cache=Path(os.environ['DEEPFACE_HOME'])/'.deepface/weights'
        if any(not (cache/n).is_file() for n in required):raise RuntimeError('Missing model assets; run tools/prepare_model.py before demo')
        model=DeepFace.build_model(model_name='Emotion',task='facial_attribute')
        DeepFace.analyze(np.zeros((48,48,3),dtype=np.uint8),actions=['emotion'],detector_backend='skip',enforce_detection=False,silent=True)
        atomic(run/'model_ready.json',dict(ready=True,model='DeepFace Emotion ONNX',wall=time.time(),pid=os.getpid()))
        used_frame=-1
        while not stop.is_set() and (not args.seconds or time.monotonic()-started<args.seconds):
            with lock:data=latest[0]
            if data is None or data[2]==used_frame:time.sleep(.01);continue
            frame,stamp,frame_id=data;used_frame=frame_id;seq+=1;begin=time.monotonic()
            p=dict(session=run.name,source='webcam',seq=seq,frame_id=frame_id,capture_mono=stamp,wall=time.time(),camera=args.camera,faces=0,status='CAMERA_ERROR',scores={},raw_scores={},bbox=None)
            if frame is not None:
                try:
                    faces=DeepFace.extract_faces(frame,detector_backend='opencv',enforce_detection=True,align=True)
                    p['faces']=len(faces)
                    if len(faces)!=1:p['status']='MULTIPLE_FACES'
                    else:
                        f=faces[0];box=f['facial_area'];p['bbox']=box
                        result=DeepFace.analyze(frame,actions=['emotion'],detector_backend='opencv',enforce_detection=True,align=True,silent=True)[0]
                        raw={k:float(v) for k,v in result['emotion'].items()}
                        # DeepFace demography API reports percentages (verified source).
                        scores={k:v/100. for k,v in raw.items()}
                        if not .98<=sum(scores.values())<=1.02:raise ValueError('Unexpected DeepFace emotion percentage scale')
                        p.update(status='OK',raw_scores=raw,scores=scores,raw_label=max(scores,key=scores.get))
                        b=(box['x'],box['y'],box['w'],box['h'])
                        if prev_box and stamp-prev_stamp<1:
                            x,y,w,h=b;a,c,u,v=prev_box
                            intersection=max(0,min(x+w,a+u)-max(x,a))*max(0,min(y+h,c+v)-max(y,c))
                            iou=intersection/max(1,w*h+u*v-intersection)
                            p['identity_changed']=iou<.15
                        prev_box,prev_stamp=b,stamp
                except ValueError as e:
                    p['status']='NO_FACE' if 'Face could not be detected' in str(e) else 'INFERENCE_ERROR'
                    p['error']=str(e)
                except Exception as e:p.update(status='INFERENCE_ERROR',error=repr(e))
            end=time.monotonic()
            p.update(prediction_mono=end,inference_ms=1000*(end-begin),capture_to_prediction_ms=1000*(end-stamp),capture_fps=counts[0]/max(.01,end-started))
            log.write(json.dumps(p,ensure_ascii=False,allow_nan=False)+'\n');atomic(run/'prediction.json',p)
            if frame is not None and seq%30==1:
                cv2.imwrite(str(run/f'webcam_{seq:06d}.jpg'),frame)
            time.sleep(max(0.,.12-(end-begin)))
    finally:
        stop.set();thread.join(timeout=2);cap.release();log.close()
        atomic(run/'worker_exit.json',dict(wall=time.time(),pid=os.getpid(),seq=seq))

if __name__=='__main__':main()
