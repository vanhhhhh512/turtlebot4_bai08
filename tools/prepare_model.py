"""Download exact tested assets with bounded time, verify hash, smoke inference."""

import hashlib, json, os, subprocess, sys, time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
(root / "results").mkdir(exist_ok=True)
assets = [
    (
        "facial_expression_model_weights.onnx",
        "https://github.com/serengil/deepface_models/releases/download/v1.0/facial_expression_model_weights.onnx",
    ),
    (
        "haarcascade_frontalface_default.xml",
        "https://github.com/opencv/opencv/raw/4.9.0/data/haarcascades/haarcascade_frontalface_default.xml",
    ),
    (
        "haarcascade_eye.xml",
        "https://github.com/opencv/opencv/raw/4.9.0/data/haarcascades/haarcascade_eye.xml",
    ),
    (
        "face_detection_yunet_2023mar.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    ),
]
cache = root / ".model_cache/.deepface/weights"
cache.mkdir(parents=True, exist_ok=True)
expected = {
    "face_detection_yunet_2023mar.onnx": "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    "facial_expression_model_weights.onnx": "2131942f16003c515f6b1fb09827f9eef111048f033bcc477fbb71f0d446f2a9",
    "haarcascade_frontalface_default.xml": "0f7d4527844eb514d4a4948e822da90fbb16a34a0bbbbc6adc6498747a5aafb0",
    "haarcascade_eye.xml": "71cc64fc305a355dc60067880f6fbbd43dd155bd63ee3844661a1bda34b2fd8c",
}
rows = []
for name, url in assets:
    path = cache / name
    if not path.exists():
        temp = path.with_suffix(".download")
        subprocess.run(
            [
                "curl",
                "-fL",
                "--connect-timeout",
                "15",
                "--max-time",
                "300",
                url,
                "-o",
                str(temp),
            ],
            check=True,
            timeout=310,
        )
        temp.rename(path)
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected[name]:
        raise RuntimeError("Hash mismatch: " + str(path))
    rows.append(
        dict(
            name=name,
            url=url,
            bytes=path.stat().st_size,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    )
(root / "results/model_manifest.json").write_text(json.dumps(rows, indent=2))
os.environ["DEEPFACE_HOME"] = str(root / ".model_cache")
os.environ["DEEPFACE_BACKEND_ENGINE"] = "onnx"
from deepface import DeepFace
import numpy as np

m = DeepFace.build_model("Emotion", task="facial_attribute")
start = time.monotonic()
r = DeepFace.analyze(
    np.zeros((48, 48, 3), dtype=np.uint8),
    actions=["emotion"],
    detector_backend="skip",
    enforce_detection=False,
    silent=True,
)
print(
    "Synthetic warm-up only; not face evidence.",
    m.model.get_providers(),
    time.monotonic() - start,
)
