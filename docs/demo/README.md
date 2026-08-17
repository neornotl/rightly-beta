# Demo transcript — Tiếng Làng v4.0 (SYNTHETIC DEMO)

> **THẬN TRỌNG**: đây là **DEMO dữ liệu mẫu hư cấu**, KHÔNG phải kết quả pilot
> và không thay thế hướng dẫn chính thức. Chạy hoàn toàn cục bộ (Mock LLM +
> corpus 11 văn bản thật), không gọi API, không thu âm thật.
>
> Tạo lúc: 08/08/2026 (giờ Việt Nam).
> Chạy lại bằng (định kỳ xác định, không cần key):
> ```
> APP_MODE=local LLM_BACKEND=mock python scripts/run_mock_demo.py --query "..."
> ```
> Lưu ý: câu trả lời là đoạn trích OCR từ văn bản luật gốc — lỗi dấu/đánh máy
> là của văn bản OCR, không phải hệ thống.

---

## VÀNG - quy định luật thật 1 (trích dẫn Luật Hộ tịch)

**Câu hỏi:** Đăng ký khai sinh mới cần những giấy tờ gì?

**Kết luận:** zone=YELLOW action=ANSWER reasons=SAFE_GROUNDED_QUERY

**Trả lời:**

> Điều 26. Thủ tục đẳng ký lại khai sinb 1 Hồ sơ đăng ký lại khai sinh gồm các giấy tờ sau đây: Tờ khai theo mẫu quy định, trong đó có cam đoan của người yêu cầu về việc đã đăng ký khai sinh nhung nguời đó không luu giữ được bản chính Giấy khai sinh; b) Bản sao toàn bộ hồ sơ, giấy tờ của người yêu cầu hoặc hồ s0, giấy tờ; tài liệu khác trong đó có các thông tin liên quan đến nội dung khai sinh của người đó; c) Truờng hợp người yêu cầu đẳng ký lại khai sinh là cán bộ, công chức, viên chức, người đang công tác trong lực lượng vũ trang thì ngoài các giấy tờ theo quy định tại Điểm a và Điểm b Khoản này phải có văn bàn xác nhận của Thủ truởng cơ quan; đơn vị về việc những nội dung khai sinh của người đó gồm họ, chữ đệm, tên; giới tính; ngày, tháng; năm sinh; dân tộc; quốc tịch; quê quán; quan hệ cha con, mẹ con phù hợp với hồ sơ do co quan; đơn vị dang quản lý. 2 Trong thời hạn 05 ngày làm việc

**Trích dẫn:** Thông tin lấy từ Nghị định 123/2015/NĐ-CP Quy định chi tiết một số điều và biện pháp thi hành Luật Hộ tịch (nd123_2015, luat60_2014).

**Nguồn:** nd123_2015, luat60_2014

**Độ trễ (ms):** {'normalize_ms': 0.0, 'retrieval_ms': 1334.8, 'safety_ms': 5.1, 'llm_ms': 0.3, 'tts_ms': 1.5}

---

## VÀNG - quy định luật thật 2 (lệ phí hộ tịch, Luật Hộ tịch)

**Câu hỏi:** Lệ phí cấp bản sao trích lục hộ tịch là bao nhiêu?

**Kết luận:** zone=YELLOW action=ANSWER reasons=SAFE_GROUNDED_QUERY

**Trả lời:**

> uả qua hệ thống buu chính thì phải gửi nộp lệ phí đẵng ký hộ tịch, lệ phí cấp bản sao trích lục hộ tịch nếu không thuộc diện được miễn lệ phí và chi phí trả kết quà qua hệ thống buu chính. Nguời tiếp nhận hồ sơ ghi rõ phương thức trả kết quả trong giấy tiếp nhận. Được trả kết quả qua hệ thống buu chính đối với yêu cầu ghi vào Sổ hộ tịch các việc hộ tịch do cơ quan có thẩm quyền của nước ngoài giải quyết, bao gồm khai sinh; kết hôn; giám hộ; nhận cha, mẹ, con; xác định cha, mẹ, con; nuôi con nuôi; thay đổi hộ tịch; khai tử; ly hôn; hủy hôn nhân trái pháp luật và yêu cầu cấp bàn sao trích lục hộ tịch theo quy định tại Điều 63 của Luật Hộ tịch.

**Trích dẫn:** Thông tin lấy từ Nghị định 123/2015/NĐ-CP Quy định chi tiết một số điều và biện pháp thi hành Luật Hộ tịch (nd123_2015, luat60_2014).

**Nguồn:** nd123_2015, luat60_2014

**Độ trễ (ms):** {'normalize_ms': 0.0, 'retrieval_ms': 651.1, 'safety_ms': 0.1, 'llm_ms': 0.1, 'tts_ms': 0.8}

---

## ĐỎ - khẩn cấp (chuyển kênh, không trả lời nội dung)

**Câu hỏi:** Tôi bị đau tim dữ dội, làm sao bây giờ?

**Kết luận:** zone=RED action=ESCALATE reasons=EMERGENCY_SIGNAL

**Hướng dẫn:**
> Tôi không phải cơ quan khẩn cấp. Nếu bạn đang gặp tình huống nguy hiểm, hãy gọi ngay số khẩn cấp địa phương hoặc nhờ người thân giúp đỡ. Tôi không thể thay thế hỗ trợ của con người.

**Độ trễ (ms):** {'normalize_ms': 0.0, 'retrieval_ms': 393.6, 'safety_ms': 0.1}

---

## TỪ CHỐI - ngoài phạm vi (không có nguồn đủ tin cậy)

**Câu hỏi:** Tổng thống Mỹ tên là gì?

**Kết luận:** zone=ORANGE action=REFUSE reasons=INSUFFICIENT_SOURCE

**Hướng dẫn:**
> Tôi không tìm thấy nguồn thông tin đủ tin cậy cho câu hỏi này. Tôi sẽ không trả lời khi chưa chắc chắn. Bạn có thể hỏi lại bằng cách khác, hoặc liên hệ bộ phận một cửa của xã để được hướng dẫn.

**Độ trễ (ms):** {'normalize_ms': 0.0, 'retrieval_ms': 186.8, 'safety_ms': 0.1}

---

## TỪ CHỐI - đúng chủ đề nhưng chỉ có văn bản đã hết hiệu lực

**Câu hỏi:** Quy định tạm trú theo Nghị định 62/2021 còn áp dụng không?

**Kết luận:** zone=ORANGE action=REFUSE reasons=CITATION_OUTDATED

**Hướng dẫn:**
> Tôi chỉ tìm thấy văn bản đã hết hiệu lực cho câu hỏi này, nên tôi sẽ không đưa ra câu trả lời để tránh thông tin sai. Bạn nên liên hệ bộ phận một cửa của xã để được hướng dẫn theo quy định hiện hành.

**Độ trễ (ms):** {'normalize_ms': 0.0, 'retrieval_ms': 1160.6, 'safety_ms': 0.2, 'llm_ms': 0.0}
