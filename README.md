# Rightly — release v0.18.0-pilot

Rightly là trợ lý hỏi–đáp tiếng Việt về thông tin công và pháp luật. Người dùng có thể nhập câu hỏi bằng chữ hoặc giọng nói; hệ thống tìm nguồn trong kho dữ liệu đã cấu hình rồi tạo câu trả lời dễ đọc, kèm nguồn khi có bằng chứng phù hợp.

> **Trạng thái:** bản pilot phát hành để đánh giá. Đây vẫn là MVP/bản thử nghiệm, không phải dịch vụ pháp lý chính thức.

## Sản phẩm đang chạy

- **Bản web giữ nguyên địa chỉ:** [intel-demo-topaz.vercel.app](https://intel-demo-topaz.vercel.app/)
- **Bộ cài Windows một file (pilot):** [Rightly Setup v0.18.0](https://github.com/neornotl/rightly/releases/tag/v0.18.0-pilot)
- **Nhánh dev:** [rightly-beta/dev](https://github.com/neornotl/rightly-beta/tree/dev)
- **Nhánh release nguồn:** [rightly-beta/release](https://github.com/neornotl/rightly-beta/tree/release)
- **Repo đã nộp cho AI Global Impact Festival:** [neornotl/rightly](https://github.com/neornotl/rightly)

## Tính năng và giới hạn thực tế

- Chat tiếng Việt trên web và giao diện local tùy cấu hình máy.
- Nhận câu hỏi bằng chữ; giọng nói phụ thuộc quyền Microphone của trình duyệt và backend ASR đã cài.
- Truy xuất văn bản nguồn, safety routing và câu trả lời có trích nguồn khi tìm được evidence.
- TTS dùng backend cloud hoặc local theo cấu hình. Chế độ local/offline cần cài đủ model và thư viện; không mặc định có nghĩa là offline hoàn toàn.
- Bản cài pilot tự nhận diện RAM/CPU/GPU, chọn model 3B hoặc 7B theo ngưỡng phần cứng, tải tiếp sau lỗi mạng và chỉ mở ứng dụng sau preflight LLM/ASR/TTS/health. Yêu cầu hiện tại: Windows 10/11 x64, tối thiểu 8 GB RAM, 25 GB trống và internet trong lần cài đầu.
- Bộ cài chỉ nói “đã kiểm tra SHA-256” khi release publisher đã ghi hash chính thức trong [`scripts/asset_manifest.json`](scripts/asset_manifest.json). Hiện manifest chưa có hash, nên preflight hiện cảnh báo rõ: runtime có thể sẵn sàng nhưng asset tải xuống chưa được chứng thực mật mã. Xem TODO phát hành tại [`docs/installer-integrity.md`](docs/installer-integrity.md).
- Câu hỏi tiếng Việt không dấu được mở rộng sang thuật ngữ pháp lý chuẩn trước khi truy xuất; phép tính ngắn được xử lý tất định thay vì giao cho LLM.
- Đăng nhập web **không** tự đọc hoặc ghi lịch sử cloud. Người dùng phải bấm “Đồng bộ: Tắt” và xác nhận rõ ràng trước khi đồng bộ; có nút “Xóa cloud” để xóa toàn bộ lịch sử của tài khoản. Mẫu RLS và retention 90 ngày nằm tại [`docs/supabase_context.sql`](docs/supabase_context.sql).
- Trước khi một câu hỏi hoặc lịch sử đi tới Gemini, Groq hoặc Pateway, Rightly thay các định danh có độ tin cậy cao (email, số điện thoại, CCCD/CMND, hộ chiếu, địa chỉ có mốc đường/phố) bằng nhãn ẩn danh. Bản hiển thị và truy xuất cục bộ không bị sửa.
- Nguồn có thể thiếu hoặc chậm cập nhật. Không dùng kết quả như tư vấn pháp lý cuối cùng; hãy kiểm tra với cơ quan có thẩm quyền.

## Chạy và phát triển

Đọc các file `requirements*.txt`, hướng dẫn trong [`docs/`](docs/) và các script setup trước khi chạy. Không commit API key, service-account JSON hoặc dữ liệu người dùng.

## Pilot

- **Public pilot:** [biểu mẫu trải nghiệm](https://docs.google.com/forms/d/11cJjCN9qlkSYzMzSYPoCE0EzQwBddtvS4uRwzwTsTFE/viewform), 56 phản hồi tại snapshot ngày 26/08/2026.
- Điểm trung bình: thân thiện/phù hợp 4,41/5; ý tưởng cốt lõi 4,36/5; dễ dùng 4,23/5; rõ ràng 4,18/5; chính xác/tin cậy 4,18/5.
- **Private pilot:** 5 hồ sơ người tham gia và 3 bản ghi phiên thử nghiệm ngày 22/08/2026 được lưu riêng. Không đưa dữ liệu định danh, chữ ký hoặc video gốc lên GitHub.
- Feedback về giọng đọc, câu trả lời bị ngắt, tốc độ hiển thị, mobile và nguồn `null` đã được chuyển thành các thay đổi có thể kiểm tra trong pipeline/web.

Kết quả, giới hạn mẫu và cách bảo vệ dữ liệu: [`docs/pilot-results-2026-08.md`](docs/pilot-results-2026-08.md). Chi tiết sản phẩm: [`docs/product-and-pilot.md`](docs/product-and-pilot.md).

Sơ đồ quan hệ hai repo: [`docs/repository-layout.md`](docs/repository-layout.md).

## Credit

| Thành viên | Vai trò | Email |
| --- | --- | --- |
| Trần Hoàng Sơn | Phát triển sản phẩm | [hoangson24092009vn@gmail.com](mailto:hoangson24092009vn@gmail.com) |
| Lê Xuân Bách | Pháp lý | [bachlxbach@gmail.com](mailto:bachlxbach@gmail.com) |
| Trương Quang Minh | Quảng bá và điều phối pilot | [truongquangminh7@gmail.com](mailto:truongquangminh7@gmail.com) |
