# Rightly — giới thiệu sản phẩm và pilot

## Giới thiệu

Rightly là một MVP trợ lý hỏi–đáp tiếng Việt, tập trung vào thông tin công, thủ tục hành chính và các câu hỏi pháp luật phổ thông. Nhánh `dev` là nơi nhóm thử nghiệm pipeline, giao diện và trải nghiệm giọng nói trước khi đưa thay đổi vào `release`.

Bản web đang chạy tại [https://intel-demo-topaz.vercel.app/](https://intel-demo-topaz.vercel.app/). Đây là bản thử nghiệm, không phải cổng thông tin nhà nước và không thay thế luật sư hoặc tư vấn chuyên môn.

## Lối kiểm tra nhanh cho ban giám khảo

Trong khoảng 3 phút, có thể mở [bản web](https://intel-demo-topaz.vercel.app/) và thử: `quy dinh khi vuot den do` (câu không dấu + nguồn), `1+4-3+7=?` (tính tất định), `Tôi cần làm gì khi chưa rõ thủ tục?` (hướng dẫn dễ đọc), và `alo` (hội thoại thông thường). Sau đó xem [báo cáo pilot](pilot-results-2026-08.md), rồi xem [bản cài Windows v0.18.0](https://github.com/neornotl/rightly/releases/tag/v0.18.0-pilot).

Đây là lối kiểm tra minh họa, không phải benchmark pháp lý độc lập. Những tính năng mới sau ngày nộp hồ sơ được đánh dấu là **post-submission improvements**.

## Pilot

Pilot dùng để quan sát khả năng sử dụng, độ rõ của câu trả lời, trải nghiệm giọng nói và lỗi thực tế. Snapshot ngày 26/08/2026 gồm 56 phản hồi public và 5 hồ sơ private pilot. Đây là bằng chứng trải nghiệm người dùng, không phải benchmark độc lập về độ đúng pháp lý; người dùng vẫn cần kiểm tra nguồn chính thức.

### Public pilot

[Mở biểu mẫu public](https://docs.google.com/forms/d/11cJjCN9qlkSYzMzSYPoCE0EzQwBddtvS4uRwzwTsTFE/viewform)

Kết quả tổng hợp, cơ cấu mẫu và feedback-to-fix được ghi tại [`pilot-results-2026-08.md`](pilot-results-2026-08.md). Dữ liệu phản hồi thô do chủ biểu mẫu quản lý và có thể cung cấp cho ban giám khảo theo kênh kiểm soát phù hợp.

### Feedback-to-fix và trạng thái tính năng

| Phản hồi | Fix đã triển khai | Trạng thái/evidence |
| --- | --- | --- |
| Chờ lâu mới thấy câu trả lời | SSE hiển thị delta trong lúc sinh | Available; `api/index.py`, `web/index.html` |
| Voice ngắt hoặc chồng nhau | Queue tuần tự, hủy audio cũ | Pilot; cần kiểm tra Chrome/Edge thật |
| Nguồn `null` | Unwrap envelope và lọc source rỗng | Available; `api/index.py`, `web/index.html` |
| Câu không dấu khó truy xuất | Query expansion có giới hạn | Available; `app/retrieval/query_expansion.py` |
| Cài local khó theo dõi | Hardware check, retry/resume và preflight | Pilot; cần clean-install độc lập |

Các mục như benchmark pháp lý độc lập quy mô lớn, hotline/telecom và mở rộng dữ liệu địa phương vẫn là **future**; không mô tả chúng như tính năng đã hoàn thiện.

## Bằng chứng về vấn đề thực tế

Tài liệu nền về các rào cản tiếp cận dịch vụ công số nằm tại [`docs/evidence/tong-hop-nguon-dich-vu-cong-so.txt`](evidence/tong-hop-nguon-dich-vu-cong-so.txt). Đây là evidence bối cảnh cho proposal/pilot, không phải căn cứ pháp lý và không phải kết quả pilot của Rightly. Xem thêm quy tắc sử dụng tại [`docs/evidence/README.md`](evidence/README.md).

### Private pilot

Ngày 22/08/2026, nhóm lưu 5 hồ sơ người tham gia và 3 bản ghi phiên thử nghiệm (khoảng 24,2 GB) trong thư mục Drive riêng. Repo không chứa form, chữ ký, thông tin liên hệ, hội thoại thô hoặc video nhận diện người tham gia.

Các file consent hiện có còn trường mẫu chưa điền và chưa có chữ ký/ngày xác nhận hoàn chỉnh. Vì vậy nhóm **không coi chúng là quyền công bố hình ảnh**. Mọi trích đoạn có thể nhận diện chỉ được sử dụng sau khi có consent hoàn chỉnh; trường hợp đã yêu cầu che mặt phải được blur trước khi chia sẻ.

## Credit

- **Trần Hoàng Sơn** — phát triển sản phẩm — [hoangson24092009vn@gmail.com](mailto:hoangson24092009vn@gmail.com)
- **Lê Xuân Bách** — pháp lý — [bachlxbach@gmail.com](mailto:bachlxbach@gmail.com)
- **Trương Quang Minh** — quảng bá và điều phối pilot — [truongquangminh7@gmail.com](mailto:truongquangminh7@gmail.com)
