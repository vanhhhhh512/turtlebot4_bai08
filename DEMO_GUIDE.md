# Demo webcam Bài08

1. Chạy `bash start_demo.sh`; chờ robot/model/GUI và ĐANG QUAY. Giữ terminal mở.
2. Giữ Neutral tới READY. Sau đó tạo Happy, Sad, Angry, Fear, Surprise; Neutral giữa các lượt.
3. Khi READY và an toàn, top-1>60% trên một prediction mới sẽ xác nhận ngay; score≤60% dùng11 phiếu trong57 prediction. GUI giữ nhãn/action_id đã chốt; nhãn khác không chen lệnh. Bộ đếm mặc định ẩn: phím1 hiện số phiếu thật x/57 cạnh từng nhãn, phím2 ẩn khi cửa sổ có focus; hai phím không điều khiển robot.
4. Neutral>60% hoặc nút STOP dừng ngay; Neutral rõ≤60% giữ0.8s cũng dừng. Mất mặt/camera/lỗi/hazard/watchdog vẫn dừng. Sau dừng hoặc hoàn thành, Neutral mới chuẩn bị lượt tiếp; giữ một mặt không tạo lệnh lặp.
5. Surprise xoay tới đủ2π odom rồi dừng, khoảng18–23s khi mô phỏng gần realtime; quan sát tiến độ thay vì tính bằng đồng hồ.
6. Ctrl+C một lần ở terminal phiên để STOP/finalize WebM. Chờ báo đóng, không kill-9. Đường dẫn video trong results/latest_session.json và terminal.

Trajectory có màu cố định theo biểu cảm và legend, giữ màu lịch sử theo action_id. Neutral chỉ đánh dấu pose dừng, Surprise hiển thị yaw xoay thật, không có đường XY giả. Footer chỉ báo quay WebM.

Log raw predictions, score_fast_path/vote_threshold, action, odom và video lưu theo run riêng. Báo cáo dùng demo được chọn; không đưa nhật ký thử nghiệm vào báo cáo. Không gọi số phiếu hoặc score là accuracy.
