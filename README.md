# Nhận diện biểu cảm webcam và TurtleBot 4 — Bài 08 (tên làm việc)

Đỗ Việt Anh — 23020719 — K68E-RE. Ubuntu 22.04, ROS 2 Humble, Gazebo Fortress, TurtleBot 4 Standard.

Webcam thật → YuNet detector + DeepFace 0.0.104 Emotion ONNX CPU → lọc theo thời gian → sự kiện hữu hạn → `/cmd_vel` → odom. Worker ML dùng venv riêng; controller ROS dùng Python hệ thống, timer 20 Hz theo wall time. Không cần Nav2. Bài 08 là tên nối tiếp Bài 07, đề chưa quy định số chính thức.

| Nhãn | v (m/s) | ω (rad/s) | Đích odom |
|---|---:|---:|---|
| happy | +0.10 | +0.35 | cung trái 60° |
| sad | +0.10 | −0.35 | cung phải 60° |
| neutral | 0 | 0 | dừng sau xác nhận Neutral rõ |
| angry | −0.10 | 0 | lùi 0.17 m |
| surprise | 0 | +0.35 | tích lũy 2π rad |
| fear | +0.10 | 0 | tiến 0.23 m |

Bộ chốt mặc định dùng `decision_mode=events`, tách nhận lệnh mới khỏi khóa chống chạy lặp:

- Khi đã START, robot khỏe và có một prediction mới hợp lệ **top-1>0.60**, lượt đầu chạy ngay, không cần Neutral, không hold/EMA/11 phiếu. So giá trị thật:0.6000 chưa đủ nhánh nhanh,0.6001 đủ dù UI làm tròn thành60.0%.
- Một action hữu hạn khóa biểu cảm đã nhận. Giữ nguyên biểu cảm sau khi xong không phát lại. Trong lúc chạy, biểu cảm khác không chen lệnh, không được xếp hàng cho lượt sau.
- Sau khi action hết hoặc bị hủy, biểu cảm khác cần **2 prediction hợp lệ liên tiếp** của chính biểu cảm đó. Chỉ đếm từ sau khi action kết thúc; prediction cũ, yếu hoặc mất mặt ngắt chuỗi. Khi đủ điều kiện, score>0.60 chạy ngay ở prediction thứ hai.
- Muốn lặp cùng biểu cảm: Neutral được xác nhận, hoặc đưa mặt/ảnh ra khỏi camera **ít nhất1s**, rồi đưa lại. Chỉ các packet NO_FACE mới liên tục được tính; camera lỗi, mất prediction, replay hoặc nhiều mặt không mở khóa.
- Mất mặt khi đang chờ chỉ chuyển sang chờ khuôn mặt. Khi đang chạy, mất mặt vẫn dừng/hủy ngay; biểu cảm đã tiêu thụ vẫn khóa, không tự tiếp tục action cũ khi mặt trở lại.
- Score≤0.60 dùng **11 phiếu trong57 prediction** dự phòng; mỗi phiếu top-1≥0.40, margin≥0.06. Số phiếu trên UI luôn là dữ liệu thật, không nâng thành11 khi nhánh nhanh đã chấp thuận.

Neutral>0.60 vẫn dừng ngay và mở lượt mới; Neutral≤0.60 dùng11 phiếu để mở lại cùng biểu cảm. Khi đang chạy, Neutral rõ (score≥0.55, margin≥0.18) liên tục0.8s vẫn có quyền dừng; điểm yếu kéo dài0.5s hủy. Disgust/mất mặt/nhiều mặt vẫn STOP, không gán thành một chuyển động khác.

STOP, lỗi camera/model, hazard, odom/clock quá hạn, trùng publisher, timeout action hoặc prediction quá hạn được giữ khóa sau khi đã hoạt động: sửa lỗi rồi bấm START để xác nhận mở lại. START yêu cầu frame được capture sau lệnh; không chạy prediction tồn từ trước START. Watchdog prediction0.9s, odom0.5s, clock0.6s vẫn giữ. Không còn permitNeutral8s trong chế độ mới. Cấu hình `votes`/`ema` cũ còn để tái tạo các run trước; không phải mặc định hiện hành. Các ngưỡng là thiết kế, không phải accuracy.

## Cài đặt

Cài ROS Humble Desktop, TurtleBot 4 simulator Fortress theo tài liệu chính thức:

- https://docs.ros.org/en/humble/Installation/Ubuntu-Install-Debs.html
- https://turtlebot.github.io/turtlebot4-user-manual/software/simulation.html
- https://github.com/serengil/deepface

```bash
sudo apt install ros-humble-turtlebot4-simulator ros-humble-rmw-cyclonedds-cpp \
  python3-colcon-common-extensions python3-venv python3-pil.imagetk \
  python3-tk python3-matplotlib xdotool ffmpeg
python3 -m venv .venv_emotion
env -u PYTHONPATH -u LD_LIBRARY_PATH .venv_emotion/bin/pip install \
  -r ros2_ws/src/bai08_turtlebot4/requirements-emotion.lock
env -u PYTHONPATH -u LD_LIBRARY_PATH .venv_emotion/bin/python tools/prepare_model.py
```

Weights Emotion/YuNet và Haar XML được tải từ nguồn chính thức, kiểm SHA256 trước dùng, không có weights trong Git. Không cần TensorFlow/PyTorch. Không đổi Python dependency toàn cục. GUI dùng Pillow hệ thống, không import venv ML. Micro tùy chọn cần `pulseaudio-utils` và tên thiết bị `pactl list short sources`.

Create 3 underlay cần bản cấu hình mô phỏng đã kiểm tra. Script dưới clone source công khai đã pin rồi chỉ build hai package Create3; không dùng artefact private:

```bash
env -i HOME="$HOME" USER="$USER" PATH=/usr/local/bin:/usr/bin:/bin bash tools/build_underlay.sh
BAI08_UNDERLAY="$PWD/underlay" bash tools/build.sh
```

Launcher ưu tiên `BAI08_UNDERLAY`, sau đó `underlay/install`, cuối cùng underlay Bài 07 nếu checkout cùng thư mục bài thực hành. Chỉ dùng file của bài cũ làm underlay đọc, không sửa. Safety riêng `/motion_control: safety_override: backup_only` cho phép lùi trong mô phỏng, còn guard bump/cliff/stall/wheel-drop/proximity. Source upstream ghi reflex simulation không đầy đủ; không coi đây là bảo vệ robot vật lý.

## Chạy

```bash
bash start_demo.sh
```

Đóng phiên cũ trước khi mở lại. Mỗi lần tạo run ID, ROS domain 108, IGN partition riêng và file WebM mới. Lock domain chống chạy hai phiên. Có thể đặt `BAI08_DOMAIN=109`. Chỉ chạy môi trường Humble sạch; launcher loại bỏ overlay Python/ROS kế thừa. Model assets phải được chuẩn bị trước, nếu thiếu thì worker báo lỗi, không READY giả.

Webcam mặc định `/dev/video0`; đổi bằng `--camera 2`. Khi robot undock/controller/clock/odom và model warm đều sẵn sàng, recorder chờ đúng cửa sổ cùng session rồi tự quay. Launcher giữ STOP lúc khởi động; chỉ bật chờ Neutral sau khi FFmpeg thực sự tạo file. Truy vấn khóa màn hình lỗi tạm thời được thử lại; ba lỗi liên tiếp dừng có kiểm soát. Cleanup vẫn tiếp tục nếu terminal đóng hoặc một tiến trình kết thúc lỗi. GNOME idle được inhibit trong phiên demo (không đổi setting lâu dài); khóa màn hình bằng tay vẫn làm STOP và finalize. Không có âm thanh mặc định. Bật micro bằng `--microphone TEN_SOURCE`.

Đưa một khuôn mặt/ảnh vào khung khi hệ thống sẵn sàng. Lượt đầu>60% chạy ngay. Giữ nguyên ảnh không chạy lặp; đổi sang biểu cảm khác cần2prediction mới liên tiếp sau khi action hết. Dùng Neutral hoặc đưa ảnh ra≥1s để lặp cùng biểu cảm. Surprise cần khoảng18s ở0.35rad/s. STOP và lỗi robot giữ khóa đến START. **Ctrl+C một lần**: latch STOP ngay, chờ robot dừng, FFmpeg nhận `q` để finalize rồi đóng đúng nhóm process. Không kill rộng hoặc kill-9 recorder.

## Log và kiểm chứng

`runs/<id>/`: session.json (PID/domain/partition), predictions.jsonl (source webcam, frame/seq/timestamps/raw percentages/normalized scores/bbox), control.jsonl (Twist/FSM/events), odom.jsonl, effective_config.json, status.json, recording.json. Hình camera và log chỉ local. `results/demo_<id>.webm`: hình cửa sổ thật 12 FPS, VP8. Recorder kiểm decode toàn bộ, xuất first/last PNG; cần xem hình để xác nhận nội dung.

Frame camera phải tăng cùng sequence và timestamp; frame lặp không làm mới watchdog hoặc thêm phiếu. Chỉ dữ liệu mới sau action được dùng để xác nhận đổi biểu cảm; không phát lại lệnh đã tiêu thụ. Quãng tiến/lùi được tích phân có dấu trong frame robot; chuyển động ngược hướng không được tính hoàn thành.

Log `EXPRESSION_RELEASED` ghi cách mở lượt bằng Neutral hoặc mất mặt đủ1s. Status có locked_label, change_count và fault_latched để audit; không đưa các trường kỹ thuật lên GUI. Log `DECISION_ACCEPTED` và `ACTION_START` phân biệt `score_fast_path`/`vote_threshold`, giữ score, seq, frame_id, capture_mono và action_id thật. `effective_config.json` lưu ngưỡng chấp thuận nhanh.

Yaw hoàn thành từ tổng sai phân atan2(sin Δ,cos Δ), không so hướng đầu/cuối. Cung theo frame robot (+x tiến,+z quay trái), không đảo dấu theo camera. Đường XY là odom thực; UI không vẽ đường mục tiêu thay kết quả.

Bridge upstream có cổng Ignition→ROS `/cmd_vel`; remap riêng `cmd_vel_bridge:cmd_vel` sang `/bai08/unused_ign_cmd` để chỉ controller Bài08 publish `/cmd_vel`. Nếu có nhiều publisher kể cả trùng tên controller, hoặc nhiều nguồn /clock, guard dừng và không READY. Giao diện ghi rõ nguyên nhân chặn thay vì luôn yêu cầu Neutral. Không mở teleop/Nav2 trong cùng domain.

## Test thành phần, tách khỏi webcam

```bash
python3 -m unittest discover -s ros2_ws/src/bai08_turtlebot4/tests -v
bash start_demo.sh --component-test --headless --no-record
# terminal khác, dùng đúng run path vừa in:
python3 ros2_ws/src/bai08_turtlebot4/scripts/check_motion.py runs/RUN_ID
python3 ros2_ws/src/bai08_turtlebot4/scripts/check_faults.py runs/RUN_ID
python3 ros2_ws/src/bai08_turtlebot4/scripts/check_event_policy.py runs/RUN_ID
```

Chỉ chế độ `--component-test` mới nhận scores tổng hợp. Mặc định chỉ nhận source webcam của worker. Test logic/mapping và odom mô phỏng không đo accuracy nhận diện. Không có nút chọn nhãn trong GUI.

## Giới hạn

Default YuNet ONNX thay Haar sau kiểm tra 19 ảnh webcam thật lưu lại: YuNet tìm một mặt ở 18 ảnh, Haar ở 7 ảnh; phép thử này không đo accuracy emotion. YuNet cũng đã thử ảnh nền không mặt và ảnh ghép hai mặt. Có thể dùng `--detector opencv` để tái tạo backend trước. Detector vẫn có thể mất mặt khi che hoặc nghiêng nhiều. Tracker bbox phát hiện bước nhảy lớn, không xác thực danh tính hay phát hiện mọi lần đổi người cùng vị trí. Fear/Sad có thể nhầm; cần người thật tạo biểu cảm và ghi nhãn định tạo riêng trước khi đánh giá. Không suy luận trạng thái tâm lý thật. Repository source không chứa báo cáo, camera, video, model, log hoặc dữ liệu bài cũ.

Worker giới hạn mỗi ONNX session ở 2 intra-op/1 inter-op threads và tắt busy spinning, OpenCV 1 thread, để không tranh CPU với Gazebo. Đây là cùng model/weights, không thay nhãn hoặc scores bằng tay.

GUI giữ trạng thái theo FSM/action_id đã chốt, không đổi status theo top-1 từng frame. Scores vẫn cập nhật realtime. Mặc định ẩn bộ đếm; khi cửa sổ có focus, phím **1** hiện số phiếu thật `x/57` cạnh từng nhãn, phím **2** ẩn. Hai phím chỉ đổi hiển thị, không reset phiếu hoặc phát lệnh. GUI không có nút/hint phím, caption chẩn đoán hay chữ audio; footer chỉ báo quay WebM.

Trajectory dùng odom thực, phân đoạn theo action_id/nhãn chốt/thời gian; không nối qua action hoặc odom jump. Màu cố định: Happy xanh dương, Sad cam, Angry đỏ, Fear xanh lá, Surprise tím, Neutral xám; có legend. Đoạn odom ngoài action hiển thị xám đứt nét, không gán biểu cảm. Neutral là marker tại pose dừng; Surprise dùng marker/hướng và góc yaw tích lũy thật, không dựng vòng tròn XY. Grid và các đối tượng Canvas được giữ lại qua refresh.
