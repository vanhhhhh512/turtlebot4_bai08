#!/usr/bin/env python3
import json, math, os, sys, time
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bai08_turtlebot4.ipc import atomic, read

run = Path(sys.argv[1])
session = run.name
root = tk.Tk()
root.title("Bai08 - Webcam Emotion - " + session)
root.geometry("1100x780")
root.configure(bg="#F2F2F2")
style = ttk.Style()
style.theme_use("clam")
style.configure("TFrame", background="#F2F2F2")
style.configure("TLabel", background="#F2F2F2", font=("DejaVu Sans", 11))
style.configure("TButton", font=("DejaVu Sans", 11))
style.configure("TProgressbar", background="#0072BD")
header = ttk.Label(
    root,
    text="NHẬN DIỆN BIỂU CẢM • TURTLEBOT 4",
    font=("DejaVu Sans", 18, "bold"),
    foreground="#0072BD",
)
header.pack(pady=12)
info = ttk.Label(root, text="LOADING — chờ model và robot", font=("DejaVu Sans", 13))
info.pack()
body = ttk.Frame(root)
body.pack(fill="both", expand=True, padx=16, pady=12)
left = ttk.Frame(body)
left.pack(side="left", fill="both", expand=True)
cam = tk.Label(left, bg="white")
cam.pack(fill="both", expand=True)
caption = ttk.Label(left, text="Camera / bbox / prediction timestamp", wraplength=660)
caption.pack(pady=6)
right = ttk.Frame(body)
right.pack(side="right", fill="y", padx=14)
bars = {}
for label in ("happy", "sad", "neutral", "angry", "surprise", "fear", "disgust"):
    row = ttk.Frame(right)
    row.pack(fill="x", pady=2)
    lab = ttk.Label(row, text=label, width=9)
    lab.pack(side="left")
    bar = ttk.Progressbar(row, length=130, maximum=100)
    bar.pack(side="left")
    val = ttk.Label(row, text="0.0%", width=7)
    val.pack(side="left")
    bars[label] = (bar, val)
plot = tk.Canvas(right, width=310, height=270, bg="white", highlightthickness=0)
plot.pack(pady=12)
detail = ttk.Label(right, text="", wraplength=310)
detail.pack()
progress = ttk.Progressbar(right, length=300, maximum=1)
progress.pack(pady=8)
footer = ttk.Frame(root)
footer.pack(fill="x", padx=18, pady=12)
sequence = 0


def stop():
    (run / "STOP").touch()


def start():
    global sequence
    sequence += 1
    atomic(
        run / "ui_command.json",
        dict(
            session=session,
            seq=time.monotonic_ns(),
            monotonic=time.monotonic(),
            command="START",
        ),
    )


def close():
    stop()
    root.destroy()


ttk.Button(footer, text="START / chờ Neutral", command=start).pack(side="left")
tk.Button(
    footer,
    text="STOP",
    command=stop,
    bg="#C43B32",
    fg="white",
    font=("DejaVu Sans", 14, "bold"),
    width=12,
).pack(side="left", padx=16)
record = ttk.Label(footer, text="Chưa quay • không thu micro")
record.pack(side="right")


def refresh():
    p = read(run / "prediction.json")
    s = read(run / "status.json")
    now = time.monotonic()
    fresh = now - s.get("monotonic", 0) < 1
    votes = s.get("vote_counts", {})
    candidate_votes = sorted(
        ((k, n) for k, n in votes.items() if k != "neutral"),
        key=lambda pair: pair[1], reverse=True,
    )
    vote_text = (
        f" | {candidate_votes[0][0]}: {candidate_votes[0][1]}/{s.get('vote_min',11)} phiếu"
        if candidate_votes and not s.get("action") else ""
    )
    info.configure(
        text=(
            (s.get("state", "LOADING") + " — " + s.get("reason", "WAIT_MODEL_ROBOT") + vote_text)
            if fresh
            else "ERROR — ROS status stale / chờ khởi động"
        )
    )
    try:
        im = Image.open(run / "camera.jpg").convert("RGB")
        draw = ImageDraw.Draw(im)
        b = p.get("bbox")
        if b and now - p.get("capture_mono", 0) < 1:
            draw.rectangle(
                (b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]),
                outline="#0072BD",
                width=3,
            )
        im.thumbnail((660, 495))
        photo = ImageTk.PhotoImage(im)
        cam.configure(image=photo)
        cam.image = photo
    except (OSError, ValueError):
        pass
    caption.configure(
        text=f"Webcam {p.get('camera','?')} | frame {p.get('frame_id','?')} | {p.get('status','LOADING')}\nNhãn thô: {p.get('raw_label','—')} | ổn định: {s.get('stable') or '—'} | score ≠ accuracy\nDetector {p.get('detector','?')} | capture {p.get('capture_fps',0):.1f} FPS | inference {p.get('inference_ms',0):.0f} ms | tuổi frame {now-p.get('capture_mono',now):.2f} s"
    )
    for k, (bar, val) in bars.items():
        score = p.get("scores", {}).get(k, 0) * 100
        bar["value"] = score
        val.configure(text=f"{score:.1f}%")
    a = s.get("action") or {}
    guide = (
        "Đang thực hiện; giữ Neutral 0.8 s hoặc STOP để dừng"
        if a else f"Sẵn sàng: mỗi biểu cảm cần {s.get('vote_min',11)}/{s.get('vote_window',57)} frame"
        if s.get("armed") else "Giữ Neutral để chuẩn bị lượt mới"
    )
    progress["value"] = a.get("progress", 0)
    detail.configure(
        text=f"v = {s.get('v',0):.2f} m/s   ω = {s.get('w',0):.2f} rad/s\nAction: {a.get('label','—')}   #{a.get('id','—')}\nΔs = {a.get('distance',0):.3f} m   Δyaw = {a.get('yaw',0):.3f} rad\n{guide}\nModel: DeepFace Emotion ONNX CPU"
    )
    plot.delete("all")
    plot.create_text(155, 12, text="Quỹ đạo odom thực • x/y (m)", fill="#222")
    points = s.get("path", [])
    pose = s.get("pose")
    if points:
        xs = [x for x, y in points]
        ys = [y for x, y in points]
        cx = (max(xs) + min(xs)) / 2
        cy = (max(ys) + min(ys)) / 2
        span = max(0.8, max(xs) - min(xs), max(ys) - min(ys)) * 1.3
        scale = 210 / span

        def xy(x, y):
            return (155 + (x - cx) * scale, 140 - (y - cy) * scale)

        for i in range(-2, 3):
            q = i * span / 4
            x = 155 + q * scale
            y = 140 - q * scale
            plot.create_line(x, 35, x, 245, fill="#ddd")
            plot.create_text(x, 256, text=f"{cx+q:.1f}", font=("DejaVu Sans", 8))
            plot.create_line(50, y, 260, y, fill="#ddd")
            plot.create_text(25, y, text=f"{cy+q:.1f}", font=("DejaVu Sans", 8))
        if len(points) > 1:
            plot.create_line(
                *[v for x, y in points for v in xy(x, y)], fill="#0072BD", width=2
            )
        x, y = xy(*points[0])
        plot.create_oval(x - 4, y - 4, x + 4, y + 4, fill="#77AC30")
        if pose:
            x, y = xy(*pose[:2])
            plot.create_line(
                x,
                y,
                x + 18 * math.cos(pose[2]),
                y - 18 * math.sin(pose[2]),
                arrow="last",
                fill="#D95319",
                width=3,
            )
    rec = read(run / "recording.json")
    record.configure(
        text=("● ĐANG QUAY WEBM" if rec.get("recording") else "Chưa quay / đã dừng")
        + " • "
        + ("có micro" if rec.get("audio") else "không thu micro")
    )
    root.after(100, refresh)


root.update()
# Tk does not set _NET_WM_PID itself; attach PID to its outer X11 window.
import subprocess, re

window_tree = subprocess.check_output(
    ["xwininfo", "-id", str(root.winfo_id()), "-tree"], text=True
)
client_id = re.search(r"Parent window id: (0x[0-9a-fA-F]+)", window_tree).group(1)
subprocess.run(
    [
        "xprop",
        "-id",
        client_id,
        "-f",
        "_NET_WM_PID",
        "32c",
        "-set",
        "_NET_WM_PID",
        str(os.getpid()),
    ],
    check=True,
)
root.protocol("WM_DELETE_WINDOW", close)
root.after(100, refresh)
root.mainloop()
