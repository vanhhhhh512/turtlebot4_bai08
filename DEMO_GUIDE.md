# Demo webcam Bài08

1. Chạy `bash start_demo.sh`, chờ robot/model/GUI và ĐANG QUAY. Giữ terminal mở.
2. Đưa một mặt hoặc ảnh vào camera. Lượt đầu top-1>57% được nhận ngay, không phải đưa Neutral trước. Score≤57% dùng11phiếu/57prediction dự phòng.
3. Sau khi chạy xong, giữ ảnh không làm chạy lại. Đổi biểu cảm khác và giữ qua2prediction mới liên tiếp để có action tiếp; không chen lệnh trong lúc action đang chạy.
4. Muốn chạy lại cùng biểu cảm: đưa Neutral, hoặc đưa ảnh ra khỏi camera≥1s rồi đưa lại. Mất mặt ngắn khi đang chờ không bắt Neutral; mất mặt khi đang chạy dừng/hủy và không tự tiếp tục action cũ.
5. Neutral>57% hoặc STOP dừng ngay; Neutral rõ≤57% giữ0.8s cũng dừng. Lỗi robot/model/camera/watchdog giữ khóa: xử lý lỗi rồi START. Disgust và nhiều mặt vẫn dừng.
6. Phím1 hiện số phiếu thật x/57 cạnh từng nhãn, phím2 ẩn; mặc định ẩn, dùng khi GUI có focus. Hai phím không điều khiển robot. Không có nút/hint phím trên UI.
7. Surprise xoay tới đủ2π odom rồi dừng; quan sát tiến độ yaw, không tính bằng đồng hồ. Trajectory giữ màu lịch sử theo nhãn/action_id, không dựng đường XY giả.
8. Ctrl+C một lần để STOP/finalize WebM; chờ báo đóng. Video ở results/latest_session.json và terminal. Không kill-9.

Log source, scores, score_fast_path/vote_threshold, mở lượt, action và odom theo từng run. Báo cáo chỉ dùng demo thật người dùng chọn và hình đã xác thực, không đưa lịch sử thử vào báo cáo. Score/phiếu không phải accuracy.
