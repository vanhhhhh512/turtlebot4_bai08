# Đo bộ chốt theo thời gian

Mặc định mới là `decision_mode=temporal`. Tham số 0.5s / 0.2s / 0.55 / 0.15 là **tạm thời, chưa tối ưu trên webcam có nhãn**. Theo yêu cầu mới, không dùng hai đoạn Angry/Neutral calibration cũ để chọn tham số. Không lấy nhãn model hoặc tên action làm ground truth.

## Thuật toán đang dùng

Với mỗi prediction mới hợp lệ, lấy toàn bộ 7 scores thật trong 0.5 giây theo **capture_mono**. Tích phân hình thang theo timestamp, chia cho độ dài cửa sổ: đây là trung bình có trọng số thời gian, tránh việc một đoạn FPS cao có nhiều phiếu hơn. Chỉ nội suy giữa hai mẫu đã nhận; không dùng frame tương lai, không ngoại suy qua khoảng mất dữ liệu. Giữ một mẫu ngay trước biên để cắt chính xác cửa sổ.

Cần đủ 0.5s dữ liệu liên tục và ít nhất 3 mẫu. Khoảng cách hai mẫu trên 0.35s làm bắt đầu lại cửa sổ. Nhãn đứng đầu phải có mean≥0.55, mean top1−top2≥0.15 và đồng ý với top1 của frame hiện tại; các điều kiện này phải liên tục ít nhất 0.2s theo capture time. Sai một điều kiện thì thời gian ổn định bắt đầu lại. Với đầu vào ổn định từ đầu, độ trễ tối thiểu khoảng 0.7s, cộng thời gian inference/lịch xử lý; FPS thấp hoặc nhãn dao động có thể chậm hơn. Không có nhánh score cao một frame hoặc đếm11/57 trong mode này.

Neutral dùng cùng bộ chốt, nên không còn quyền dừng bằng một frame score cao. Nút STOP, Disgust, mất mặt và lỗi vẫn dừng độc lập ngay khi được controller xử lý. Khi đang chạy, frame yếu (top1<0.40 hoặc margin<0.06) liên tục 0.5s hủy action. Biểu cảm khác không chen lệnh hoặc xếp hàng. START, lỗi, bắt đầu/kết thúc/hủy action và mở lượt đều xóa lịch sử; biểu cảm sau action phải được xác nhận từ dữ liệu mới. Khóa cùng nhãn, mở lại bằng Neutral hoặc NO_FACE mới liên tục≥1s và mọi guard robot vẫn áp dụng.

Log `temporal_mean` lưu cả mean 7 lớp, raw score, margin, thời gian phủ cửa sổ, thời gian ổn định, timestamps và số mẫu. Scores raw trên GUI giữ nguyên; phím1 hiện `TB xx%` từ mean thật, phím2 ẩn. Không còn số x/57 trong mode mới. Các mode events/votes/ema chỉ để tái tạo các phiên cũ.

## Gán nhãn video

Tạo JSON local theo ví dụ dưới. Mỗi recording phải có group người/phiên; cùng người hoặc cùng session chỉ thuộc một split. Dùng `selection` để chọn tham số và `holdout` độc lập để đánh giá sau khi chọn. Các đường dẫn là tương đối với file JSON. `predictions.jsonl`, `control.jsonl`, video và nhãn đều giữ local, không đẩy GitHub.

```json
{
  "recordings": [
    {
      "id": "session-A",
      "group": "person-A",
      "split": "selection",
      "annotation_kind": "human_video",
      "video": "../results/demo_SESSION.webm",
      "predictions": "../runs/SESSION/predictions.jsonl",
      "control": "../runs/SESSION/control.jsonl",
      "intervals": [
        {
          "start_capture_mono": 100.0,
          "end_capture_mono": 103.0,
          "label": "happy",
          "onset_verified": true
        }
      ]
    }
  ]
}
```

Số thời gian trong ví dụ chỉ minh họa schema. Thay bằng mốc thật sau khi xem video và đối chiếu timestamp trong predictions/recording metadata. Video quay GUI có thể hiển thị frame camera trễ hơn timestamp bắt đầu quay; không lấy giây video cộng thẳng vào capture_mono mà bỏ qua căn chỉnh. Chỉ đánh `onset_verified=true` khi đã xác định thời điểm bắt đầu biểu cảm; đoạn đã giữ biểu cảm từ trước khi ghi nhãn không dùng để đo latency.

Nhãn: happy/sad/neutral/angry/surprise/fear/disgust; `none` là đoạn không chủ ý phát lệnh, dùng đo kích hoạt nhầm. Không chồng các interval; phần chưa gán nhãn không được tính là đúng hay sai. Cần cả chuyển tiếp, biểu cảm khó, đưa ảnh điện thoại, giữ ảnh, mất mặt và đoạn nền. Nhãn ý định người dùng và nhãn biểu cảm quan sát được cần được quy định nhất quán; ghi chú trường hợp không rõ thay vì suy nhãn từ model.

## Đánh giá và chọn tham số

```bash
python3 tools/evaluate_temporal.py verification/annotations.json \
  --out results/temporal_evaluation.json
python3 tools/evaluate_temporal.py verification/annotations.json \
  --tune --out results/temporal_selection.json
```

Báo cáo có confusion matrix (tính cả từ chối xác nhận), macro F1, tỷ lệ chưa chốt, số interval bỏ lỡ, xác nhận sai/phút và latency p50/p95 ở những onset đã xác thực. Đếm theo prediction, không theo refresh UI. Bộ chọn thử 54 cấu hình window∈{0.3,0.5,0.7}s, hold∈{0.1,0.2}s, confidence∈{0.5,0.55,0.65}, margin∈{0.1,0.15,0.2}; chỉ xếp hạng bằng selection, sau đó đánh giá holdout một lần. Ưu tiên ít xác nhận chuyển động sai, ít xác nhận sai, ít bỏ lỡ, F1 rồi độ trễ. Bộ chọn không sửa source hoặc tự khởi động robot.

Offline replay đo **cơ hội xác nhận từ bộ nhận dạng**, không mô phỏng quãng đường/robot đang bận; không gọi số này là action robot thực. Nếu cung cấp `control`, báo cáo thêm `actual_recorded_activations` từ ACTION_START thật của chính phiên đã quay, gồm kích hoạt sai/phút và latency có nhãn. Đây là hành vi thuật toán lúc quay, không phải kết quả giả định của cấu hình replay mới. STOP/watchdog/one-action phải kiểm riêng qua controller và odom.

Nếu thiếu holdout độc lập, nhãn video đã xem, onset xác thực, đủ sáu lớp và đoạn nền ở mỗi split, kết quả chỉ là thử nghiệm: `selection_status=insufficient_labels_or_independent_holdout`, không xuất cấu hình khuyến nghị. Ngay cả khi đủ schema, vẫn cần xem số mẫu/thời lượng và metric holdout; đủ trường dữ liệu không có nghĩa đã đạt chất lượng.

Khi có cấu hình đã đánh giá, lưu object `suggested_control_config` thành file JSON rồi chạy:

```bash
bash start_demo.sh --control-config verification/selected_control.json
```

Launcher lưu cấu hình yêu cầu và effective_config trong run để audit. Trung bình không sửa được model nhận sai ổn định với điểm cao; trường hợp đó cần đánh giá crop/model/dữ liệu riêng.
