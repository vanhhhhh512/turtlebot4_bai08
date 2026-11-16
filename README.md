# TurtleBot 4 — Bài thực hành 8

Nhận diện biểu cảm khuôn mặt bằng DeepFace kết hợp OpenCV, điều khiển TurtleBot 4 qua `/cmd_vel`.

## Môi trường

Ubuntu 22.04, ROS 2 Humble, TurtleBot 4 Standard, Gazebo Fortress, Python 3.10. Nhận diện dùng YuNet và DeepFace Emotion chạy ONNX trên CPU. Cần webcam và desktop X11 để mở giao diện, Gazebo và RViz.

Cài ROS Humble và simulator theo [TurtleBot 4 Simulation](https://turtlebot.github.io/turtlebot4-user-manual/software/simulation.html), sau đó:

```bash
sudo apt install ros-humble-turtlebot4-simulator ros-humble-rmw-cyclonedds-cpp \
  python3-colcon-common-extensions python3-venv python3-pil.imagetk \
  python3-tk python3-matplotlib xdotool ffmpeg
```

## Clone, build và mở demo

```bash
git clone https://github.com/vanhhhhh512/turtlebot4_bai08.git
cd turtlebot4_bai08
python3 -m venv .venv_emotion
env -u PYTHONPATH -u LD_LIBRARY_PATH .venv_emotion/bin/pip install \
  -r ros2_ws/src/bai08_turtlebot4/requirements-emotion.lock
env -u PYTHONPATH -u LD_LIBRARY_PATH .venv_emotion/bin/python tools/prepare_model.py
env -i HOME="$HOME" USER="$USER" PATH=/usr/local/bin:/usr/bin:/bin bash tools/build_underlay.sh
BAI08_UNDERLAY="$PWD/underlay" bash tools/build.sh
bash start_demo.sh
```

## Nhận diện và quan sát

Chờ robot và model sẵn sàng rồi đưa một khuôn mặt hoặc ảnh vào webcam, giữ ổn định và chờ robot hoàn thành trước khi đổi biểu cảm.

| Biểu cảm | Chuyển động |
| --- | --- |
| Happy | Đi cong sang trái |
| Sad | Đi cong sang phải |
| Neutral | Dừng tại chỗ |
| Angry | Lùi nhẹ |
| Surprise | Xoay một vòng tại chỗ |
| Fear | Tiến nhẹ |

Chương trình lấy trung bình điểm trong khoảng ngắn, yêu cầu nhãn đứng đầu ổn định và cách nhãn thứ hai đủ rõ mới chốt lệnh.

Nút **STOP** dừng robot, **START** cho nhận lệnh trở lại.
