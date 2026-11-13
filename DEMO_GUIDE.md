# Demo webcam Bài 08

1. Chạy `bash /home/admin1/xla/wk4/week8/start_demo.sh` trong terminal. Chỉ chạy một phiên.
2. Chờ Gazebo, RViz, GUI camera và trạng thái **ĐANG QUAY WEBM**. Robot tự ra khỏi dock; không phát teleop.
3. Ngồi cách camera khoảng 0,5–0,8 m, mặt thẳng, đủ sáng, chỉ một người. Đưa trọn đầu vào khung. Giữ Neutral để GUI báo READY.
4. Lần lượt tạo Happy (cười), Sad (buồn), Angry (cau mày), Fear (sợ), Surprise (ngạc nhiên). Giữa mỗi lượt giữ Neutral để rearm. Nhìn nhãn model thực; không coi biểu cảm định tạo là kết quả nhận diện. Giữ biểu cảm đến khi action hoàn thành; Surprise khoảng 18 giây. Neutral dừng ngay nên làm sau khi quỹ đạo xong, hoặc dùng để kiểm dừng giữa chừng.
5. Tạo thêm một lượt Happy rồi trở về Neutral sớm để kiểm dừng; ra khỏi khung để kiểm mất mặt. Giữ một biểu cảm sau khi action xong để kiểm không chạy lặp. Nếu nhận sai giữ nguyên log, thử lại sau Neutral.
6. STOP đỏ dừng; START đưa về chờ Neutral. Kết thúc bằng **Ctrl+C một lần ở terminal chính**, chờ thông báo đã đóng phiên. Đừng đóng cửa sổ trước recorder.
7. Lấy đường dẫn WebM chính xác từ terminal hoặc `results/latest_session.json`, xem `recording.json` trong run xác nhận decode. Chỉ sau khi xem nội dung mới chọn video gửi. Không âm thanh mặc định; muốn thuyết minh chạy thêm `--microphone TEN_SOURCE`.
8. Up file WebM lên Google Drive rồi cấp URL mới; chưa có URL thì báo cáo ghi file local/chưa có link. Không dùng video Bài 07.

Log nhãn đối chiếu (người thực hiện định tạo) phải do người dùng xác nhận. Chỉ log dự đoán model không đủ tính accuracy hoặc confusion matrix. Tất cả lượt sai được giữ.

Bộ lọc khi đang chạy có hysteresis: ngưỡng bắt đầu 0.55/margin 0.18, duy trì trên EMA 0.40/margin 0.06; mất hỗ trợ liên tục 0.30 s thì hủy. Một frame nhiễu không hủy ngay. Neutral rõ/mất mặt/STOP vẫn dừng ngay; sau khi hủy cần Neutral mới.

Nhãn thô đúng chưa chắc robot đã được phép chạy: nếu WAIT_NEUTRAL, giữ Neutral tới READY rồi đổi biểu cảm trong 8 s. Bộ lọc xét EMA, giữ nhãn 0.40 s để khởi động. Giữ terminal của phiên mở trong lúc demo; đóng terminal sẽ STOP và finalize.
