# Demo webcam Bài08

1. Chạy `bash start_demo.sh`, chờ robot/model/GUI và ĐANG QUAY. Giữ terminal mở.
2. Đưa một mặt hoặc ảnh vào camera, giữ biểu cảm rõ khoảng một giây. Mặc định trung bình7scores trong0.5s, nhãn đứng đầu có mean≥55%, margin≥15điểm phần trăm và ổn định0.2s mới chốt; không cần Neutral trước lượt đầu. Không còn một frame>57% hoặc11/57.
3. Các tham số là tạm thời, chưa tối ưu trên video có nhãn. Xem TEMPORAL_EVALUATION.md. Không dùng hai đoạn Angry/Neutral cũ để hiệu chỉnh. Model nhận sai ổn định vẫn có thể chốt sai.
4. Sau khi chạy xong, giữ ảnh không chạy lại. Đổi biểu cảm và giữ rõ để xác nhận lại từ dữ liệu mới; không chen/xếp hàng lệnh trong action.
5. Muốn lặp cùng biểu cảm: Neutral đã xác nhận hoặc đưa ảnh ra≥1s rồi đưa lại. Mất mặt ngắn khi chờ không bắt Neutral; khi đang chạy sẽ dừng/hủy và không tự tiếp tục action cũ.
6. Neutral dừng sau cùng bộ chốt thời gian. STOP, Disgust, mất mặt và lỗi dừng độc lập; lỗi robot/model/camera/watchdog cần xử lý rồi START. START yêu cầu frame mới và cửa sổ mới.
7. Phím1 hiện điểm trung bình thật `TB xx%`, phím2 ẩn; mặc định ẩn, GUI có focus. Chỉ đổi hiển thị; không có nút/hint phím trên UI. Scores chính vẫn là raw model.
8. Surprise xoay đủ2π odom rồi dừng. Trajectory màu theo nhãn/action_id, không dựng XY giả.
9. Ctrl+C một lần để STOP/finalize WebM; chờ báo đóng. Video ở results/latest_session.json và terminal. Không kill-9.

Log temporal_mean giữ raw/mean/margin/cửa sổ/thời gian ổn định và action/odom. Báo cáo chỉ dùng demo thật người dùng chọn và hình đã xác thực. Scores không phải accuracy.
