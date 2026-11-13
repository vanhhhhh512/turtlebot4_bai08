# Demo webcam Bài08

1. Chạy `bash start_demo.sh`; chờ robot/model/GUI và ĐANG QUAY. Giữ terminal mở.
2. Giữ Neutral tới READY. Sau đó tạo Happy, Sad, Angry, Fear, Surprise; Neutral giữa các lượt.
3. Chỉ cần model có11 phiếu trong57 prediction gần nhất, không cần liên tiếp. GUI hiển thị số phiếu. Khi action đã chốt, giữ biểu cảm hoặc theo dõi robot; nhãn khác không đổi action giữa chừng.
4. Neutral rõ giữ0.8s hoặc nút STOP để dừng. Mất mặt/camera/lỗi/hazard/watchdog vẫn dừng. Sau dừng hoặc hoàn thành, Neutral mới chuẩn bị lượt tiếp; giữ một mặt không tạo lệnh lặp.
5. Surprise xoay tới đủ2π odom rồi dừng, khoảng18–23s khi mô phỏng gần realtime; quan sát tiến độ thay vì tính bằng đồng hồ.
6. Ctrl+C một lần ở terminal phiên để STOP/finalize WebM. Chờ báo đóng, không kill-9. Đường dẫn video trong results/latest_session.json và terminal.

Log raw predictions, vote decision, action, odom và video lưu theo run riêng. Báo cáo dùng demo được chọn; không đưa nhật ký thử nghiệm vào báo cáo. Không gọi số phiếu hoặc score là accuracy.
