# Rightly — dev

Rightly là trợ lý hỏi–đáp tiếng Việt về thông tin công và pháp luật. Người dùng có thể nhập câu hỏi bằng chữ hoặc giọng nói; hệ thống tìm nguồn trong kho dữ liệu đã cấu hình rồi tạo câu trả lời dễ đọc, kèm nguồn khi có bằng chứng phù hợp.

> **Trạng thái:** nhánh `dev` dùng cho phát triển và kiểm thử liên tục. Đây vẫn là MVP/bản thử nghiệm, không phải dịch vụ pháp lý chính thức.

## Sản phẩm đang chạy

- **Bản web giữ nguyên địa chỉ:** [intel-demo-topaz.vercel.app](https://intel-demo-topaz.vercel.app/)
- **Nhánh dev:** [rightly-beta/dev](https://github.com/neornotl/rightly-beta/tree/dev)
- **Nhánh release:** [rightly-beta/release](https://github.com/neornotl/rightly-beta/tree/release)
- **Repo nền/nghiên cứu:** [neornotl/rightly](https://github.com/neornotl/rightly)

## Tính năng và giới hạn thực tế

- Chat tiếng Việt trên web và giao diện local tùy cấu hình máy.
- Nhận câu hỏi bằng chữ; giọng nói phụ thuộc quyền Microphone của trình duyệt và backend ASR đã cài.
- Truy xuất văn bản nguồn, safety routing và câu trả lời có trích nguồn khi tìm được evidence.
- TTS dùng backend cloud hoặc local theo cấu hình. Chế độ local/offline cần cài đủ model và thư viện; không mặc định có nghĩa là offline hoàn toàn.
- Nguồn có thể thiếu hoặc chậm cập nhật. Không dùng kết quả như tư vấn pháp lý cuối cùng; hãy kiểm tra với cơ quan có thẩm quyền.

## Chạy và phát triển

Đọc các file `requirements*.txt`, hướng dẫn trong [`docs/`](docs/) và các script setup trước khi chạy. Không commit API key, service-account JSON hoặc dữ liệu người dùng.

## Pilot

- **Public pilot:** [mở biểu mẫu](https://docs.google.com/forms/d/11cJjCN9qlkSYzMzSYPoCE0EzQwBddtvS4uRwzwTsTFE/edit?usp=sharing_eil_se_dm&ts=6a8dd201) (liên kết do nhóm cung cấp).
- **Private pilot:** Chưa công bố — sẽ bổ sung sau.
- Chưa có báo cáo pilot định lượng được công bố; số liệu thử nghiệm nội bộ không được trình bày như kết quả người dùng thật.

Chi tiết: [`docs/product-and-pilot.md`](docs/product-and-pilot.md).

## Credit

| Thành viên | Vai trò | Email |
| --- | --- | --- |
| Trần Hoàng Sơn | Phát triển sản phẩm | [hoangson24092009vn@gmail.com](mailto:hoangson24092009vn@gmail.com) |
| Lê Xuân Bách | Pháp lý | [bachlxbach@gmail.com](mailto:bachlxbach@gmail.com) |
| Trương Quang Minh | Quảng bá và điều phối pilot | [truongquangminh7@gmail.com](mailto:truongquangminh7@gmail.com) |

