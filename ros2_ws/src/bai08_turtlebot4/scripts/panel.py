#!/usr/bin/env python3
import os, sys, time
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bai08_turtlebot4.ipc import atomic, read
from bai08_turtlebot4.presentation import StatusPresenter, TrajectoryPlot

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
info_area = ttk.Frame(root, height=50)
info_area.pack(fill="x")
info_area.pack_propagate(False)
info = ttk.Label(info_area, text="ĐANG CHUẨN BỊ CAMERA VÀ ROBOT", font=("DejaVu Sans", 15, "bold"))
info.configure(anchor="center", width=75, wraplength=1060, justify="center",
               font=("DejaVu Sans", 14, "bold"))
info.pack(fill="both", expand=True)
presenter = StatusPresenter()
footer = ttk.Frame(root)
footer.pack(side="bottom", fill="x", padx=18, pady=12)
body = ttk.Frame(root)
body.pack(fill="both", expand=True, padx=16, pady=12)
left = ttk.Frame(body)
left.pack(side="left", fill="both", expand=True)
cam = tk.Label(left, bg="white")
cam.pack(fill="both", expand=True)
right = ttk.Frame(body)
right.pack(side="right", fill="y", padx=14)
bars = {}
vote_labels = {}
show_votes = False


def set_votes(visible):
    global show_votes
    show_votes = visible
    update_votes(read(run / "status.json"))


def update_votes(status):
    for label, widget in vote_labels.items():
        text = f"{status.get('vote_counts', {}).get(label, 0)}/57" if show_votes else ""
        if widget.cget("text") != text:
            widget.configure(text=text)


root.bind("<KeyPress-1>", lambda event: set_votes(True))
root.bind("<KeyPress-2>", lambda event: set_votes(False))
for label in ("happy", "sad", "neutral", "angry", "surprise", "fear", "disgust"):
    row = ttk.Frame(right)
    row.pack(fill="x", pady=1)
    lab = ttk.Label(row, text=label, width=9)
    lab.pack(side="left")
    bar = ttk.Progressbar(row, length=130, maximum=100)
    bar.pack(side="left")
    val = ttk.Label(row, text="0.0%", width=7)
    val.pack(side="left")
    bars[label] = (bar, val)
    count = ttk.Label(row, text="", width=5, anchor="e")
    count.pack(side="left")
    vote_labels[label] = count
plot = tk.Canvas(right, width=350, height=306, bg="white", highlightthickness=0)
plot.pack(pady=8)
trajectory_plot = TrajectoryPlot(plot)
detail = ttk.Label(right, text="", wraplength=310)
detail.pack()
progress = ttk.Progressbar(right, length=300, maximum=1)
progress.pack(pady=5)
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
record = ttk.Label(footer, text="Chưa quay / đã dừng")
record.pack(side="right")


def refresh():
    p = read(run / "prediction.json")
    s = read(run / "status.json")
    now = time.monotonic()
    message = presenter.message(s, now)
    if info.cget("text") != message:
        info.configure(text=message)
    update_votes(s)
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
    for k, (bar, val) in bars.items():
        score = p.get("scores", {}).get(k, 0) * 100
        bar["value"] = score
        val.configure(text=f"{score:.1f}%")
    a = s.get("action") or {}
    progress["value"] = a.get("progress", 0)
    text = (f"v = {s.get('v',0):.2f} m/s   ω = {s.get('w',0):.2f} rad/s\n"
            f"Action: {a.get('label','—')}   #{a.get('id','—')}\n"
            f"Δs = {a.get('distance',0):.3f} m   Δyaw = {a.get('yaw',0):.3f} rad")
    if detail.cget("text") != text:
        detail.configure(text=text)
    trajectory_plot.update(s)
    rec = read(run / "recording.json")
    text = "● ĐANG QUAY WEBM" if rec.get("recording") else "Chưa quay / đã dừng"
    if record.cget("text") != text:
        record.configure(text=text)
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
