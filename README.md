# Rightly

Rightly là trợ lý hỏi–đáp tiếng Việt về thông tin công và pháp luật. Người dùng có thể nhập câu hỏi bằng chữ hoặc giọng nói; hệ thống tìm nguồn trong kho dữ liệu đã cấu hình rồi tạo câu trả lời dễ đọc, kèm nguồn khi có bằng chứng phù hợp.

> **Trạng thái hiện tại:** MVP/bản thử nghiệm. Rightly không phải cơ quan nhà nước, không thay thế luật sư và không phải kênh tư vấn khẩn cấp. Nội dung có thể thiếu hoặc chậm cập nhật; hãy kiểm tra lại với cơ quan có thẩm quyền.

## Sản phẩm

- **Bản web:** [intel-demo-topaz.vercel.app](https://intel-demo-topaz.vercel.app/)
- **Bản release nguồn:** nhánh [`release`](https://github.com/neornotl/rightly-beta/tree/release) của repo beta.
- **Repo release công khai:** [`neornotl/rightly`](https://github.com/neornotl/rightly/tree/release), được đồng bộ từ nhánh release nguồn.
- **Bản phát triển:** nhánh [`dev`](https://github.com/neornotl/rightly-beta/tree/dev). Bản web hiện theo dõi nhánh này để nhóm kiểm thử liên tục.

## Những gì bản này có

- Chat tiếng Việt trên web và giao diện local tùy cấu hình máy.
- Nhận câu hỏi bằng chữ; nhận giọng nói phụ thuộc quyền Microphone của trình duyệt và backend ASR đã cài.
- Truy xuất văn bản nguồn (BM25/hybrid tùy cấu hình), safety routing và câu trả lời có trích nguồn khi tìm được evidence.
- TTS có thể dùng backend cloud hoặc local theo cấu hình; không mặc định có nghĩa là offline hoàn toàn.
- Chế độ local/offline cần cài đủ Python, thư viện và model theo hướng dẫn; chế độ web cần các biến môi trường cloud tương ứng.

## Chạy và phát triển

Xem [`docs/`](docs/) và các file `requirements*.txt` để biết đúng cấu hình của bản checkout. Không commit API key, service-account JSON hoặc dữ liệu người dùng vào repo.

## Pilot

- **Public pilot:** [mở biểu mẫu](https://docs.google.com/forms/d/11cJjCN9qlkSYzMzSYPoCE0EzQwBddtvS4uRwzwTsTFE/edit?usp=sharing_eil_se_dm&ts=6a8dd201) (liên kết biểu mẫu do nhóm cung cấp).
- **Private pilot:** Chưa công bố — sẽ bổ sung sau.
- Chưa công bố kết quả pilot định lượng; các số liệu trong tài liệu thử nghiệm chỉ được coi là kết quả nội bộ cho đến khi có báo cáo được nhóm xác nhận.

Chi tiết biểu mẫu, phạm vi thu thập phản hồi và cách xử lý dữ liệu: [`docs/product-and-pilot.md`](docs/product-and-pilot.md).

Sơ đồ quan hệ hai repo: [`docs/repository-layout.md`](docs/repository-layout.md).

## Credit

| Thành viên | Vai trò | Email |
| --- | --- | --- |
| Trần Hoàng Sơn | Phát triển sản phẩm | [hoangson24092009vn@gmail.com](mailto:hoangson24092009vn@gmail.com) |
| Lê Xuân Bách | Pháp lý | [bachlxbach@gmail.com](mailto:bachlxbach@gmail.com) |
| Trương Quang Minh | Quảng bá và điều phối pilot | [truongquangminh7@gmail.com](mailto:truongquangminh7@gmail.com) |

## An toàn và giới hạn

Rightly ưu tiên trả lời có căn cứ và có thể hỏi lại, từ chối hoặc hướng người dùng tới kênh chính thức khi thiếu nguồn hoặc gặp tình huống rủi ro. Không gửi thông tin nhạy cảm vào issue/pull request; hãy đọc chính sách riêng tư trước khi chạy pilot.
