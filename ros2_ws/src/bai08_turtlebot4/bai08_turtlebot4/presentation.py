"""Stable FSM presentation and retained Canvas odometry objects; no raw labels."""
import math
from .trajectory import COLORS

ERRORS = {
    "NO_FACE": "ĐƯA TRỌN KHUÔN MẶT VÀO CAMERA",
    "FACE_COUNT_MISMATCH": "CHỈ ĐỂ MỘT KHUÔN MẶT TRONG CAMERA",
    "MULTIPLE_FACES": "CHỈ ĐỂ MỘT KHUÔN MẶT TRONG CAMERA",
    "FACE_CHANGED": "KHUÔN MẶT THAY ĐỔI — GIỮ NEUTRAL ĐỂ SẴN SÀNG",
    "CAMERA_ERROR": "MẤT CAMERA — KIỂM TRA KẾT NỐI WEBCAM",
    "INFERENCE_ERROR": "LỖI NHẬN DIỆN — ROBOT ĐÃ DỪNG",
    "MALFORMED_PREDICTION": "DỮ LIỆU NHẬN DIỆN LỖI — ROBOT ĐÃ DỪNG",
    "OUTSIDE_SET": "DISGUST — ROBOT DỪNG; GIỮ NEUTRAL ĐỂ TIẾP TỤC",
    "ODOM_STALE": "MẤT PHẢN HỒI ROBOT — ĐÃ DỪNG ĐIỀU KHIỂN",
    "CLOCK_STALE": "MÔ PHỎNG ĐANG TẠM DỪNG — CHỜ KẾT NỐI",
    "PREDICTION_STALE": "ĐANG CHỜ HÌNH CAMERA MỚI — ROBOT DỪNG",
    "OTHER_CMD_PUBLISHER": "TRÙNG BỘ ĐIỀU KHIỂN — CẦN ĐÓNG PHIÊN CŨ",
    "OTHER_CLOCK_PUBLISHER": "TRÙNG MÔ PHỎNG — CẦN ĐÓNG PHIÊN CŨ",
    "ROBOT_NOT_PREPARED": "ĐANG CHUẨN BỊ ROBOT — CHỜ SẴN SÀNG",
    "HAZARD": "ROBOT GẶP VẬT CẢN — ĐÃ DỪNG",
    "ACTION_TIMEOUT": "HẾT THỜI GIAN HÀNH ĐỘNG — ROBOT ĐÃ DỪNG",
    "ODOM_JUMP": "PHẢN HỒI VỊ TRÍ THAY ĐỔI — ROBOT ĐÃ DỪNG",
    "BAD_ODOM": "PHẢN HỒI VỊ TRÍ LỖI — ROBOT ĐÃ DỪNG",
    "REARM_WINDOW_EXPIRED": "HẾT LƯỢT CHỜ — GIỮ NEUTRAL ĐỂ SẴN SÀNG",
}
WAIT = "GIỮ NEUTRAL ĐỂ CHUẨN BỊ LƯỢT MỚI"


class StatusPresenter:
    def __init__(self):
        self.stopped = None

    def message(self, status, now):
        if now - status.get("monotonic", 0) >= 1:
            return "ĐANG CHỜ KẾT NỐI ROBOT"
        if not status.get("enabled"):
            self.stopped = None
            return "ĐÃ DỪNG — NHẤN START ĐỂ TIẾP TỤC"
        reason = status.get("reason")
        if reason in ERRORS:
            self.stopped = ERRORS[reason]
            return self.stopped
        action = status.get("action")
        if action and status.get("state") == "EXECUTING":
            self.stopped = None
            return f"ĐÃ XÁC NHẬN: {action['label'].upper()} — ROBOT ĐANG CHẠY  #{action['id']}"
        if status.get("armed"):
            self.stopped = None
            return "SẴN SÀNG — TẠO BIỂU CẢM ĐỂ ĐIỀU KHIỂN"
        if reason == "COMPLETED":
            self.stopped = "HOÀN THÀNH — " + WAIT
        elif reason == "NEUTRAL":
            self.stopped = "ĐÃ XÁC NHẬN: NEUTRAL — ROBOT DỪNG"
        elif reason == "LOW_CONFIDENCE" and self.stopped is None:
            self.stopped = "BIỂU CẢM CHƯA RÕ — " + WAIT
        return self.stopped or WAIT


class TrajectoryPlot:
    def __init__(self, canvas):
        self.canvas, self.items = canvas, {}
        canvas.create_text(175, 12, text="Quỹ đạo odom thực • x/y (m)", fill="#222")
        for i, (label, color) in enumerate(COLORS.items()):
            x, y = 12 + (i % 3) * 115, 253 + (i // 3) * 19
            canvas.create_line(x, y, x + 14, y, fill=color, width=3)
            canvas.create_text(x + 19, y, text=label.capitalize(), anchor="w",
                               font=("DejaVu Sans", 8), fill="#222")
        canvas.create_text(175, 293, text="Chấm xám: Neutral • Tím: yaw xoay tại pose",
                           font=("DejaVu Sans", 8), fill="#555")

    def item(self, key, kind, coords, **options):
        old = self.items.get(key)
        values = (tuple(coords), options)
        if old is None:
            ident = getattr(self.canvas, "create_" + kind)(*coords, **options)
            self.items[key] = (ident, values)
        elif old[1] != values:
            self.canvas.coords(old[0], *coords)
            self.canvas.itemconfigure(old[0], **options)
            self.items[key] = (old[0], values)
        self.used.add(key)

    def update(self, status):
        segments = status.get("trajectory", [])
        markers = status.get("trajectory_markers", [])
        pose = status.get("pose")
        points = [p[:2] for s in segments for p in s["points"]]
        points += [m["pose"][:2] for m in markers]
        if pose:
            points.append(pose[:2])
        self.used = set()
        xs, ys = zip(*points) if points else ([0.0], [0.0])
        cx, cy = (max(xs)+min(xs))/2, (max(ys)+min(ys))/2
        span = max(.8, max(xs)-min(xs), max(ys)-min(ys))*1.3
        scale = 170/span
        def xy(x, y):
            return (175+(x-cx)*scale, 128-(y-cy)*scale)
        for i in range(-2, 3):
            q = i*span/4
            x, y = 175+q*scale, 128-q*scale
            self.item(f"gx{i}", "line", (x, 43, x, 213), fill="#ddd")
            self.item(f"gy{i}", "line", (90, y, 260, y), fill="#ddd")
            self.item(f"tx{i}", "text", (x, 226), text=f"{cx+q:.2f}", font=("DejaVu Sans", 8))
            self.item(f"ty{i}", "text", (37, y), text=f"{cy+q:.2f}", font=("DejaVu Sans", 8))
        for s in segments:
            key = f"s{s['segment_id']}"
            color = COLORS.get(s["label"], "#999999")
            pts = s["points"]
            if len(pts) > 1 and s["label"] != "neutral":
                self.item(key, "line", [v for p in pts for v in xy(*p[:2])],
                          fill=color, width=2, dash=() if s["label"] else (3, 3))
            if s["label"] == "surprise" and pts:
                x, y = xy(*pts[0][:2])
                self.item(key+"spin", "oval", (x-6, y-6, x+6, y+6), outline=color, width=2)
                self.item(key+"yaw", "text", (x+9, y-13), anchor="w", fill=color,
                          font=("DejaVu Sans", 8), text=f"#{s['action_id']}  {s.get('yaw',0):.2f} rad")
        for i, m in enumerate(markers):
            x, y = xy(*m["pose"][:2])
            self.item(f"neutral{i}", "oval", (x-4, y-4, x+4, y+4),
                      fill=COLORS["neutral"], outline="white")
        if segments and segments[0]["points"]:
            x, y = xy(*segments[0]["points"][0][:2])
            self.item("origin", "oval", (x-4, y-4, x+4, y+4), outline="#222", width=2)
        if pose:
            x, y = xy(*pose[:2])
            color = COLORS.get((status.get("action") or {}).get("label"), COLORS["neutral"])
            self.item("heading", "line", (x, y, x+18*math.cos(pose[2]), y-18*math.sin(pose[2])),
                      arrow="last", fill=color, width=3)
        for key in set(self.items) - self.used:
            self.canvas.delete(self.items.pop(key)[0])
