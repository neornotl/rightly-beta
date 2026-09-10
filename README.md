# Rightly — development repository

Repo phát triển của Rightly, trợ lý hỏi–đáp tiếng Việt về thông tin công và pháp luật. Nhánh `dev` chứa thay đổi đang được kiểm thử; bản nguồn ổn định để người dùng tham khảo nằm tại [`neornotl/rightly`](https://github.com/neornotl/rightly).

> **Phạm vi:** Rightly là MVP/bản thử nghiệm, không phải cơ quan nhà nước và không thay thế tư vấn pháp lý. Nguồn có thể thiếu hoặc chậm cập nhật.

## Liên kết chính

- [Bản web](https://intel-demo-topaz.vercel.app/)
- [Repo release công khai](https://github.com/neornotl/rightly)
- [Các bản phát hành](https://github.com/neornotl/rightly/releases)
- Hướng dẫn người dùng Windows: [`README-NGUOI-DUNG.txt`](README-NGUOI-DUNG.txt)

## Pilot công khai

- [Góp ý trải nghiệm qua biểu mẫu](https://docs.google.com/forms/d/11cJjCN9qlkSYzMzSYPoCE0EzQwBddtvS4uRwzwTsTFE/viewform)
- Snapshot đã ghi nhận: 56 phản hồi tại ngày 26/08/2026. Đây không phải tổng cuối cùng; không dùng snapshot này để suy ra số hiện tại.
- Phạm vi và giới hạn: [`docs/product-and-pilot.md`](docs/product-and-pilot.md) và [`docs/pilot-results-2026-08.md`](docs/pilot-results-2026-08.md).

## Phạm vi mã nguồn

| Đường dẫn | Vai trò |
| --- | --- |
| `web/` | Giao diện web |
| `api/` | API/serverless entry point |
| `app/` | Pipeline, retrieval, safety, provider và validation |
| `legal-sources/` | Kho nguồn pháp luật được giữ lại làm nguồn chuẩn |
| `data/` | Dữ liệu và chỉ mục runtime |
| `tests/` | Kiểm thử tự động và gate |
| `scripts/` | Build, preflight, audit, smoke test và đóng gói |
| `docs/evidence/` | Tài liệu nguồn công khai có thể kiểm tra |

Các output đánh giá sinh ra, script debug/patch một lần, tài liệu demo cũ và cây nguồn pháp luật trùng lặp không được giữ trong nhánh chính.

## Thiết lập phát triển

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m pip install -r requirements.txt
python -m pytest -m "not slow"
```

Kiểm tra trước khi đưa thay đổi sang release:

```powershell
python scripts/verify_database.py --skip-embeddings
python scripts/predeploy_check.py
python scripts/smoke_public_release.py
```

Các kiểm tra cần model, API key, thiết bị hoặc mạng phải được báo riêng; không suy diễn PASS cấu trúc thành xác nhận chất lượng pháp lý hay hiệu năng trên thiết bị thật.

## Quy ước đóng góp

- Tạo branch ngắn gọn từ `dev`; không đưa thẳng thử nghiệm chưa xác minh vào `release`.
- Không commit secret, dữ liệu nhận dạng người dùng, bản ghi pilot riêng tư hoặc file môi trường.
- Gắn claim về pilot, benchmark hoặc phần cứng với artifact có thể kiểm tra và ghi rõ phạm vi.
- Ưu tiên thay đổi nhỏ, có test; giữ cloud/ASR/TTS tùy chọn và có fallback rõ ràng.

## Nhóm thực hiện

- Trần Hoàng Sơn — phát triển sản phẩm
- Lê Xuân Bách — nội dung pháp lý
- Trương Quang Minh — truyền thông và điều phối pilot

## Giấy phép

[MIT](LICENSE)
