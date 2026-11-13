#!/usr/bin/env python3
"""Synthetic prediction faults + real robot odometry; never model accuracy."""
import argparse, json, math, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bai08_turtlebot4.ipc import read, atomic
from bai08_turtlebot4.core import LABELS

ap = argparse.ArgumentParser()
ap.add_argument("run")
a = ap.parse_args()
run = Path(a.run)
seq = read(run / "prediction.json").get("seq", 0)
results = []


def send(label="neutral", **kw):
    global seq
    seq += 1
    now = time.monotonic()
    p = dict(
        session=run.name,
        source="component_test",
        seq=seq,
        capture_mono=now,
        status="OK",
        faces=1,
        scores={k: float(k == label) for k in LABELS},
    )
    p.update(kw)
    atomic(run / "prediction.json", p)
    time.sleep(0.08)


def hold(label, seconds):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        send(label)


def begin():
    hold("neutral", 1.4)
    hold("fear", 1.5)
    s = read(run / "status.json")
    assert s.get("action"), s
    return s


fault_names = [
    "neutral",
    "no_face",
    "multiple_faces",
    "low_confidence",
    "disgust",
    "stale_prediction",
    "replayed_prediction",
    "gui_stop",
    "change_label",
]
vote_mode = read(run / "effective_config.json").get("decision_mode") == "votes"
if vote_mode:
    # A new expression is deliberately ignored during a locked action.
    fault_names.remove("change_label")
for fault in fault_names:
    begin()
    start = time.monotonic()
    if fault == "neutral":
        send("neutral")
    elif fault == "no_face":
        send("fear", status="NO_FACE", faces=0)
    elif fault == "multiple_faces":
        send("fear", faces=2)
    elif fault == "low_confidence":
        send("fear", scores={k: 1 / 7 for k in LABELS})
    elif fault == "disgust":
        send("disgust")
    elif fault == "gui_stop":
        (run / "STOP").touch()
    elif fault == "change_label":
        send("angry")
    elif fault == "replayed_prediction":
        p = read(run / "prediction.json")
        p["seq"] = max(0, p["seq"] - 20)
        atomic(run / "prediction.json", p)
    # Stale/replay: leave packet unchanged; wall watchdog must stop.
    first_zero = stopped = None
    deadline = start + 2.5
    while time.monotonic() < deadline:
        # Persistent evidence is distinct from a one-frame spike or stale packet.
        if fault == "neutral" and vote_mode:
            send("neutral")
        elif fault == "low_confidence":
            send("fear", scores={k: 1 / 7 for k in LABELS})
        elif fault == "change_label":
            send("angry")
        s = read(run / "status.json")
        if not s.get("action") and s.get("v") == s.get("w") == 0 and first_zero is None:
            first_zero = time.monotonic()
        if first_zero and max(abs(v) for v in s.get("measured", [99, 99])) < 0.025:
            stopped = time.monotonic()
            break
        time.sleep(0.02)
    results.append(
        dict(
            source="component_test + actual simulation odom",
            fault=fault,
            zero_delay_s=first_zero - start if first_zero else None,
            actual_stop_s=stopped - start if stopped else None,
            reason=s.get("reason"),
            pass_=bool(
                stopped and stopped - start < 1.4
                and (fault != "low_confidence" or s.get("reason") == "LOW_CONFIDENCE")
                and (fault != "change_label" or s.get("reason") == "LABEL_CHANGED")
            ),
        )
    )
    print(results[-1], flush=True)
    atomic(run / "fault_tests.json", results)
    if fault == "gui_stop":
        atomic(
            run / "ui_command.json",
            dict(
                session=run.name,
                seq=time.monotonic_ns(),
                command="START",
                monotonic=time.monotonic(),
            ),
        )
        time.sleep(0.2)
    # Holding the old expression must not restart after fault.
    hold("fear", 1.2)
    assert not read(run / "status.json").get("action"), "Resumed stale action"
print("FAULT COMPONENT TESTS DONE", flush=True)
sys.exit(0 if all(r["pass_"] for r in results) else 1)
