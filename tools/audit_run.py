"""Audit measurements without inventing intended expression or success."""

import argparse, collections, hashlib, json, statistics
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("run", type=Path)
a = ap.parse_args()
r = a.run


def rows(name):
    p = r / name
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


pred = rows("predictions.jsonl")
ctrl = rows("control.jsonl")
odom = rows("odom.jsonl")
valid = [p for p in pred if p.get("status") == "OK"]
actions = [e for e in ctrl if e.get("event") == "ACTION_END"]
starts = [e for e in ctrl if e.get("event") == "ACTION_START"]
controls = [e for e in ctrl if e.get("event") == "CONTROL"]
out = dict(
    run=str(r.resolve()),
    prediction_count=len(pred),
    valid_face_predictions=len(valid),
    statuses=dict(collections.Counter(p.get("status") for p in pred)),
    raw_labels=dict(collections.Counter(p.get("raw_label") for p in valid)),
    actions=actions,
    action_starts=starts,
    intended_labels="not provided; no model accuracy claimed",
    odom_samples=len(odom),
)
if pred:
    out["median_inference_ms"] = statistics.median(p["inference_ms"] for p in pred)
    out["p95_capture_to_prediction_ms"] = sorted(
        p["capture_to_prediction_ms"] for p in pred
    )[int(0.95 * (len(pred) - 1))]
if controls:
    out["last_actual_velocity"] = controls[-1].get("measured")
    out["cmd_publisher_counts"] = dict(
        collections.Counter(e.get("cmd_publishers") for e in controls)
    )
    out["last_state"] = controls[-1]["state"]
if (r / "session.json").exists():
    m = json.loads((r / "session.json").read_text())
    v = Path(m["video"])
    if v.exists():
        out["video"] = str(v)
        out["video_sha256"] = hashlib.sha256(v.read_bytes()).hexdigest()
    if (r / "recording.json").exists():
        out["recording"] = json.loads((r / "recording.json").read_text())
(r / "audit.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
print(
    json.dumps(
        {
            k: v
            for k, v in out.items()
            if k not in ("actions", "action_starts", "recording")
        },
        ensure_ascii=False,
        indent=2,
    )
)
