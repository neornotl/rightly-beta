# Rightly - bằng chứng pilot tháng 08/2026

**Ngày chốt snapshot:** 26/08/2026 (không phải ngày kết thúc pilot)

**Phạm vi:** public pilot đang diễn ra bằng Google Forms, có liên kết từ giao diện app, và private pilot có quan sát trực tiếp

**Mục đích:** ghi nhận bằng chứng sử dụng thật, phản hồi và thay đổi sản phẩm; không thay thế đánh giá độc lập về độ đúng pháp lý.

## 1. Public pilot đang diễn ra

Biểu mẫu public vẫn mở để tiếp tục thu thập phản hồi qua [Rightly - khảo sát trải nghiệm](https://docs.google.com/forms/d/11cJjCN9qlkSYzMzSYPoCE0EzQwBddtvS4uRwzwTsTFE/viewform). Snapshot do chủ biểu mẫu kiểm tra tại ngày **26/08/2026** có **56 phản hồi**. Đây là số liệu tại một thời điểm, không phải tổng cuối cùng; các mốc cũ như 51 không được dùng để suy ra số hiện tại.

### Cơ cấu mẫu

| Nhóm | Số lượng |
| --- | ---: |
| Học sinh/sinh viên | 48 |
| Người cao tuổi | 7 |
| Khác | 1 |

| Độ tuổi | Số lượng |
| --- | ---: |
| Dưới 18 | 37 |
| 18-24 | 11 |
| 45-59 | 1 |
| Từ 60 trở lên | 7 |

| Giới tính | Số lượng |
| --- | ---: |
| Nam | 26 |
| Nữ | 28 |
| Khác/không thuộc hai lựa chọn trên | 2 |

### Điểm trải nghiệm

| Tiêu chí | Điểm trung bình / 5 | Số đánh giá 4-5 |
| --- | ---: | ---: |
| Thân thiện và phù hợp | 4,41 | 46/56 |
| Ý tưởng cốt lõi | 4,36 | 47/56 |
| Giao diện dễ sử dụng | 4,23 | 43/56 |
| Câu trả lời rõ ràng | 4,18 | 43/56 |
| Chính xác và đáng tin cậy | 4,18 | 41/56 |

Có 9 phản hồi tự do. Các chủ đề chính gồm tốc độ, giao diện/mobile, mức độ cá nhân hóa, giọng đọc tự nhiên hơn và trường hợp câu trả lời bị ngắt/chưa đầy đủ. Biểu mẫu public: [Rightly - khảo sát trải nghiệm](https://docs.google.com/forms/d/11cJjCN9qlkSYzMzSYPoCE0EzQwBddtvS4uRwzwTsTFE/viewform).

## 2. Feedback chuyển thành thay đổi sản phẩm

| Phản hồi quan sát được | Thay đổi đã đưa vào mã nguồn | Cách kiểm tra |
| --- | --- | --- |
| Chờ lâu mới thấy câu trả lời | SSE và hiển thị delta ngay khi model sinh nội dung | `api/index.py`, `web/index.html` |
| Voice bị ngắt hoặc hai giọng chồng nhau | Hàng đợi TTS tuần tự, hủy request/audio cũ và đọc theo các đoạn đầy đủ | `web/index.html` |
| Nguồn hiển thị `null` | Chuẩn hóa câu trả lời và lọc nguồn rỗng ở cả API lẫn giao diện | `api/index.py`, `web/index.html` |
| Câu hỏi không dấu/ASR khó truy xuất | Mở rộng truy vấn có giới hạn sang thuật ngữ pháp lý chuẩn | `app/retrieval/query_expansion.py` |
| Phép tính ngắn có thể bị LLM trả sai | Bộ tính toán tất định, giới hạn biểu thức an toàn | `app/arithmetic.py` |
| Người dùng khó theo dõi cài local | Installer có giao diện, log tiến trình, retry/resume, nhận diện phần cứng và preflight | `setup_installer.py`, `scripts/detect_hardware.py`, `scripts/preflight_offline.py` |

Những thay đổi trên là phản hồi-to-fix ở mức mã nguồn. Việc voice trên từng trình duyệt vẫn cần cấp quyền Microphone và được kiểm tra trên thiết bị thật; bộ cài pilot vẫn cần thêm các lần clean-install độc lập trên nhiều cấu hình máy.

## 3. Private pilot

Ngày 22/08/2026, nhóm lưu:

- 5 hồ sơ người tham gia;
- 3 bản ghi phiên thử nghiệm MP4;
- tổng dung lượng video khoảng 24,2 GB.

Các vật liệu gốc được lưu riêng để bảo vệ người tham gia. GitHub không chứa tên, thông tin liên hệ, chữ ký, nội dung hội thoại thô hoặc video gốc. Khi ban giám khảo cần đối chiếu, nhóm có thể trình bày bằng kênh kiểm soát và chỉ trong phạm vi consent hợp lệ.

### Tình trạng consent và giới hạn sử dụng

Các file consent hiện tại còn placeholder và phần chữ ký/ngày chưa hoàn chỉnh. Một hồ sơ yêu cầu không để lộ mặt và phải blur. Vì vậy:

- không công bố raw video hay consent form trong repo;
- không dùng các file hiện tại để khẳng định có quyền quảng bá hình ảnh;
- trước khi chia sẻ trích đoạn, phải hoàn thiện consent hoặc ẩn danh/blur theo yêu cầu;
- số liệu private pilot chỉ được báo cáo ở dạng tổng hợp.

## 4. Diễn giải đúng phạm vi

Pilot cho thấy Rightly có mức chấp nhận ban đầu tốt và tạo được vòng lặp phản hồi - sửa lỗi. Tuy nhiên mẫu public tập trung nhiều vào người trẻ; nhóm người cao tuổi mới có 7/56 phản hồi. Điểm tự báo cáo không chứng minh mọi câu trả lời pháp lý đều đúng. Bước đánh giá tiếp theo cần có bộ câu hỏi pháp lý gán nhãn, người chấm độc lập, clean-install trên nhiều máy và usability test có nhiệm vụ cụ thể cho nhóm người cao tuổi/khó tiếp cận số.

## 5. Tính riêng tư và Responsible AI

- Không commit khóa API, service-account, dữ liệu người dùng hoặc tài liệu consent.
- Chỉ công bố số liệu tổng hợp cần thiết cho việc đánh giá dự án.
- Câu trả lời của Rightly không phải quyết định hành chính hay tư vấn pháp lý chính thức.
- Người dùng được khuyến nghị kiểm tra lại nguồn và liên hệ cơ quan có thẩm quyền khi tình huống có rủi ro cao.
