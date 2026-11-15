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

Bộ chốt mặc định dùng `decision_mode=temporal`, lấy trung bình **toàn bộ 7 scores theo thời gian capture**, không còn nhánh một frame>57% hoặc11/57:

- Cửa sổ **0.5s**, trung bình có trọng số thời gian bằng tích phân hình thang trên các mẫu đã nhận. Cần phủ đủ cửa sổ, ít nhất3mẫu; gap>0.35s bắt đầu lại. Không dùng frame tương lai.
- Nhãn đứng đầu có **mean≥0.55**, cách nhãn thứ hai **≥0.15** (15điểm phần trăm), đồng ý với top1 hiện tại, liên tục **0.2s** mới xác nhận. Đầu vào ổn định từ đầu cần khoảng0.7s cộng inference/lịch xử lý. Không bắt Neutral trước lượt đầu.
- **Các giá trị trên là cấu hình tạm, chưa tối ưu trên video webcam có nhãn.** Hai đoạn Angry/Neutral calibration cũ không dùng chọn tham số theo yêu cầu người dùng. Công cụ đánh giá, cách gán nhãn, chia selection/holdout và đo sai/độ trễ ở [TEMPORAL_EVALUATION.md](TEMPORAL_EVALUATION.md).
- Mỗi action hữu hạn khóa nhãn đã nhận. Giữ ảnh sau khi xong không chạy lặp. Biểu cảm khác chỉ được xác nhận từ cửa sổ mới sau action; đang chạy không chen lệnh hoặc xếp hàng.
- Lặp cùng biểu cảm bằng Neutral đã xác nhận hoặc NO_FACE mới liên tục≥1s rồi đưa mặt/ảnh lại. Camera lỗi, silence, replay hoặc nhiều mặt không mở lượt. Mất mặt khi đang chạy hủy ngay, cùng biểu cảm trở lại không tự tiếp tục.
- Neutral dùng cùng mean/margin/hold, không dừng bằng một frame cao. **STOP, Disgust, mất mặt/nhiều mặt và lỗi vẫn dừng độc lập.** Điểm raw yếu (top1<0.40 hoặc margin<0.06) liên tục0.5s hủy action. START, lỗi, bắt đầu/kết thúc/hủy action và mở lượt đều xóa lịch sử bộ lọc.

STOP, lỗi camera/model, hazard, odom/clock quá hạn, trùng publisher, timeout action hoặc prediction quá hạn được giữ khóa sau khi đã hoạt động: sửa lỗi rồi bấm START. Chỉ frame capture sau START được nhận; watchdog prediction0.9s, odom0.5s, clock0.6s giữ nguyên. Không có permitNeutral8s. Các mode `events`/`votes`/`ema` còn để tái tạo run cũ, không phải mặc định. Mean/score không phải accuracy và không sửa được nhận sai liên tục của model.

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

Webcam mặc định `/dev/video0`; đổi bằng `--camera 2`. Khi robot undock/controller/clock/odom và model warm đều sẵn sàng, recorder chờ đúng cửa sổ cùng session rồi tự quay. Launcher giữ STOP lúc khởi động; chỉ bật nhận biểu cảm sau khi FFmpeg thực sự tạo file. Truy vấn khóa màn hình lỗi tạm thời được thử lại; ba lỗi liên tiếp dừng có kiểm soát. Cleanup vẫn tiếp tục nếu terminal đóng hoặc một tiến trình kết thúc lỗi. GNOME idle được inhibit trong phiên demo (không đổi setting lâu dài); khóa màn hình bằng tay vẫn làm STOP và finalize. Không có âm thanh mặc định. Bật micro bằng `--microphone TEN_SOURCE`.

Đưa một khuôn mặt/ảnh vào khung và giữ biểu cảm rõ khoảng một giây khi hệ thống sẵn sàng. Chương trình chốt bằng mean/margin/thời gian ổn định; giữ ảnh không chạy lặp. Đổi biểu cảm sau action, hoặc Neutral/đưa ảnh ra≥1s để lặp cùng biểu cảm. Surprise cần khoảng18s ở0.35rad/s. STOP và lỗi robot giữ khóa đến START. **Ctrl+C một lần**: STOP, chờ robot dừng, FFmpeg nhận `q` để finalize rồi đóng đúng nhóm process. Không kill rộng hoặc kill-9 recorder.

Cấu hình đã đánh giá có thể truyền bằng `bash start_demo.sh --control-config verification/selected_control.json`; launcher lưu lại trong run. Xem hướng dẫn đánh giá trước khi gọi một cấu hình là đã hiệu chỉnh.

## Log và kiểm chứng

`runs/<id>/`: session.json (PID/domain/partition), predictions.jsonl (source webcam, frame/seq/timestamps/raw percentages/normalized scores/bbox), control.jsonl (Twist/FSM/events), odom.jsonl, effective_config.json, status.json, recording.json. Hình camera và log chỉ local. `results/demo_<id>.webm`: hình cửa sổ thật 12 FPS, VP8. Recorder kiểm decode toàn bộ, xuất first/last PNG; cần xem hình để xác nhận nội dung.

Frame camera phải tăng cùng sequence và timestamp; frame lặp không làm mới watchdog hoặc thêm mẫu vào bộ lọc. Chỉ dữ liệu mới sau action được dùng để xác nhận đổi biểu cảm; không phát lại lệnh đã tiêu thụ. Quãng tiến/lùi được tích phân có dấu trong frame robot; chuyển động ngược hướng không được tính hoàn thành.

Log `EXPRESSION_RELEASED` ghi Neutral/mất mặt đủ1s. `DECISION_ACCEPTED` và `ACTION_START` ghi branch=`temporal_mean`, mean score, raw score, toàn bộ scores trung bình, margin, thời gian phủ/ổn định, timestamps, số mẫu và action_id. Status lưu `temporal` để audit/UI. `effective_config.json` giữ tham số thực của phiên; các log score_fast_path/vote_threshold trong run cũ thuộc thuật toán lịch sử.

Yaw hoàn thành từ tổng sai phân atan2(sin Δ,cos Δ), không so hướng đầu/cuối. Cung theo frame robot (+x tiến,+z quay trái), không đảo dấu theo camera. Đường XY là odom thực; UI không vẽ đường mục tiêu thay kết quả.

Bridge upstream có cổng Ignition→ROS `/cmd_vel`; remap riêng `cmd_vel_bridge:cmd_vel` sang `/bai08/unused_ign_cmd` để chỉ controller Bài08 publish `/cmd_vel`. Nếu có nhiều publisher kể cả trùng tên controller, hoặc nhiều nguồn /clock, guard dừng và không READY. Giao diện ghi rõ nguyên nhân chặn thay vì luôn yêu cầu Neutral. Không mở teleop/Nav2 trong cùng domain.

## Test thành phần, tách khỏi webcam

```bash
python3 -m unittest discover -s ros2_ws/src/bai08_turtlebot4/tests -v
bash start_demo.sh --component-test --headless --no-record
# terminal khác, dùng đúng run path vừa in:
python3 ros2_ws/src/bai08_turtlebot4/scripts/check_motion.py runs/RUN_ID
python3 ros2_ws/src/bai08_turtlebot4/scripts/check_faults.py runs/RUN_ID
python3 ros2_ws/src/bai08_turtlebot4/scripts/check_temporal_policy.py runs/RUN_ID
```

Chỉ chế độ `--component-test` mới nhận scores tổng hợp. Mặc định chỉ nhận source webcam của worker. Test logic/mapping và odom mô phỏng không đo accuracy nhận diện. Không có nút chọn nhãn trong GUI.

## Giới hạn

Default YuNet ONNX thay Haar sau kiểm tra 19 ảnh webcam thật lưu lại: YuNet tìm một mặt ở 18 ảnh, Haar ở 7 ảnh; phép thử này không đo accuracy emotion. YuNet cũng đã thử ảnh nền không mặt và ảnh ghép hai mặt. Có thể dùng `--detector opencv` để tái tạo backend trước. Detector vẫn có thể mất mặt khi che hoặc nghiêng nhiều. Tracker bbox phát hiện bước nhảy lớn, không xác thực danh tính hay phát hiện mọi lần đổi người cùng vị trí. Fear/Sad có thể nhầm; cần người thật tạo biểu cảm và ghi nhãn định tạo riêng trước khi đánh giá. Không suy luận trạng thái tâm lý thật. Repository source không chứa báo cáo, camera, video, model, log hoặc dữ liệu bài cũ.

Worker giới hạn mỗi ONNX session ở 2 intra-op/1 inter-op threads và tắt busy spinning, OpenCV 1 thread, để không tranh CPU với Gazebo. Đây là cùng model/weights, không thay nhãn hoặc scores bằng tay.

GUI giữ trạng thái theo FSM/action_id đã chốt, không đổi status theo top-1 từng frame. Scores vẫn cập nhật realtime. Mặc định ẩn cột điểm trung bình; khi cửa sổ có focus, phím **1** hiện `TB xx%` từ mean thật cạnh từng nhãn, phím **2** ẩn. Hai phím chỉ đổi hiển thị, không reset bộ lọc hoặc phát lệnh. Mode lịch sử vẫn hiển thị phiếu x/57 khi được chọn tường minh. GUI không có nút/hint phím, caption chẩn đoán hay chữ audio; footer chỉ báo quay WebM.

Trajectory dùng odom thực, phân đoạn theo action_id/nhãn chốt/thời gian; không nối qua action hoặc odom jump. Màu cố định: Happy xanh dương, Sad cam, Angry đỏ, Fear xanh lá, Surprise tím, Neutral xám; có legend. Đoạn odom ngoài action hiển thị xám đứt nét, không gán biểu cảm. Neutral là marker tại pose dừng; Surprise dùng marker/hướng và góc yaw tích lũy thật, không dựng vòng tròn XY. Grid và các đối tượng Canvas được giữ lại qua refresh.
