# Rightly — release v0.18.0-pilot

Rightly là trợ lý hỏi–đáp tiếng Việt về thông tin công và pháp luật. Người dùng có thể nhập câu hỏi bằng chữ hoặc giọng nói; hệ thống tìm nguồn trong kho dữ liệu đã cấu hình rồi tạo câu trả lời dễ đọc, kèm nguồn khi có bằng chứng phù hợp.

> **Trạng thái:** bản pilot phát hành để đánh giá. Đây vẫn là MVP/bản thử nghiệm, không phải dịch vụ pháp lý chính thức.

## Sản phẩm đang chạy

- **Bản web giữ nguyên địa chỉ:** [intel-demo-topaz.vercel.app](https://intel-demo-topaz.vercel.app/)
- **Bộ cài Windows một file (pilot):** [Rightly Setup v0.18.0](https://github.com/neornotl/rightly/releases/tag/v0.18.0-pilot)
- **Nhánh dev:** [rightly-beta/dev](https://github.com/neornotl/rightly-beta/tree/dev)
- **Nhánh release nguồn:** [rightly-beta/release](https://github.com/neornotl/rightly-beta/tree/release)
- **Repo đã nộp cho AI Global Impact Festival:** [neornotl/rightly](https://github.com/neornotl/rightly)

## Judge path — 3 phút

1. Mở [bản web](https://intel-demo-topaz.vercel.app/) và chọn **Chat**.
2. Thử: `quy dinh khi vuot den do` (câu không dấu + nguồn), `1+4-3+7=?` (tính tất định), `Tôi cần làm gì khi chưa rõ thủ tục?` (hướng dẫn dễ đọc), và `alo` (hội thoại thông thường).
3. Mở phần **Nguồn** để kiểm tra evidence; xem [báo cáo pilot](docs/pilot-results-2026-08.md) để đối chiếu phản hồi và thay đổi.
4. Nếu muốn kiểm tra local, tải [Rightly Setup v0.18.0](https://github.com/neornotl/rightly/releases/tag/v0.18.0-pilot). Bản cài cần Windows 10/11 x64, tối thiểu 8 GB RAM, 25 GB trống và internet ở lần cài đầu.

Đây là đường kiểm tra nhanh, không phải cam kết mọi câu hỏi pháp lý đều được trả lời đúng. Khi nguồn không đủ, người dùng cần kiểm tra lại với cơ quan có thẩm quyền.

### Feedback pilot → fix → evidence

| Feedback public pilot | Thay đổi sản phẩm | Evidence có thể kiểm tra |
| --- | --- | --- |
| Câu trả lời hiển thị chậm | Hiển thị delta qua SSE khi model đang sinh | `api/index.py`, `web/index.html` |
| Voice bị ngắt hoặc chồng tiếng | Hàng đợi tuần tự và hủy audio/request cũ | `web/index.html` |
| Nguồn hiển thị `null` | Chuẩn hóa envelope và lọc nguồn rỗng | `api/index.py`, `web/index.html` |
| Câu hỏi không dấu khó tìm | Mở rộng truy vấn có giới hạn | `app/retrieval/query_expansion.py` |
| Phép tính ngắn có thể sai | Bộ tính toán tất định cho biểu thức an toàn | `app/arithmetic.py` |
| Khó theo dõi quá trình cài local | Log tiến trình, retry/resume, hardware check và preflight | `setup_installer.py`, `scripts/preflight_offline.py` |

### Feature status

| Trạng thái | Phạm vi |
| --- | --- |
| **Available** | Chat web, truy xuất nguồn, semantic routing giới hạn, xử lý câu không dấu, stream SSE, bộ tính toán an toàn, local installer/preflight theo cấu hình máy |
| **Pilot / cần xác minh thiết bị** | Microphone và TTS trên từng Chrome/Edge; offline đầy đủ sau khi cài đủ model; hiệu năng trên nhiều cấu hình Windows |
| **Future** | Đánh giá độ đúng pháp lý độc lập quy mô lớn, mở rộng dữ liệu địa phương, hotline/telecom và đồng bộ cloud tự nguyện |

Các cải tiến sau ngày nộp hồ sơ được ghi nhận minh bạch là **post-submission improvements**; không dùng chúng để thay đổi nội dung clip hoặc số liệu pilot đã nộp.

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

Để kiểm tra nhanh bản public và metadata bộ cài mà không cần API key, model hay tải asset, chạy [`scripts/smoke_public_release.py`](scripts/smoke_public_release.py). Hướng dẫn và các hợp đồng được kiểm tra: [`docs/public-smoke-test.md`](docs/public-smoke-test.md).

## Pilot

- **Public pilot đang diễn ra:** [biểu mẫu trải nghiệm](https://docs.google.com/forms/d/11cJjCN9qlkSYzMzSYPoCE0EzQwBddtvS4uRwzwTsTFE/viewform) được mở trực tiếp từ giao diện Rightly; số phản hồi có thể tiếp tục tăng.
- **Snapshot đã kiểm tra:** 56 phản hồi tại ngày 26/08/2026. Đây không phải tổng cuối cùng; không dùng các mốc cũ (ví dụ 51) để suy ra số hiện tại.
- Điểm trung bình: thân thiện/phù hợp 4,41/5; ý tưởng cốt lõi 4,36/5; dễ dùng 4,23/5; rõ ràng 4,18/5; chính xác/tin cậy 4,18/5.
- **Private pilot:** 5 hồ sơ người tham gia và 3 bản ghi phiên thử nghiệm ngày 22/08/2026 được lưu riêng. Không đưa dữ liệu định danh, chữ ký hoặc video gốc lên GitHub.
- Feedback về giọng đọc, câu trả lời bị ngắt, tốc độ hiển thị, mobile và nguồn `null` đã được chuyển thành các thay đổi có thể kiểm tra trong pipeline/web.

Kết quả, giới hạn mẫu và cách bảo vệ dữ liệu: [`docs/pilot-results-2026-08.md`](docs/pilot-results-2026-08.md). Chi tiết sản phẩm: [`docs/product-and-pilot.md`](docs/product-and-pilot.md).

Sơ đồ quan hệ hai repo: [`docs/repository-layout.md`](docs/repository-layout.md).

### Post-submission evidence

The [isolated OpenVINO E5-small benchmark](benchmarks/openvino-e5-results-2026-08.md)
measured approximately **1.62–1.76×** lower query-encoding latency across three
series on one Intel Core i7-10510U test machine, with equivalent embeddings and
100% top-10 overlap on five probes. This is experimental post-submission CPU
evidence, not a claim of production integration, legal-accuracy improvement, or
GPU/NPU acceleration.

## Credit

| Thành viên | Vai trò | Email |
| --- | --- | --- |
| Trần Hoàng Sơn | Phát triển sản phẩm | [hoangson24092009vn@gmail.com](mailto:hoangson24092009vn@gmail.com) |
| Lê Xuân Bách | Pháp lý | [bachlxbach@gmail.com](mailto:bachlxbach@gmail.com) |
| Trương Quang Minh | Quảng bá và điều phối pilot | [truongquangminh7@gmail.com](mailto:truongquangminh7@gmail.com) |
