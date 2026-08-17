# Dữ liệu nguồn Tiếng Làng

Quy tắc dữ liệu trong repository này:

- Mọi tài liệu trong `sources/` phải ghi nhãn `DEMO` / `SYNTHETIC` nếu không
  phải nguồn chính thức.
- Không đưa hướng dẫn hành chính thật dưới dạng giả thật.
- `chunks/` là output của `scripts/ingest_documents.py` (được gitignore ngoại
  trừ `demo_chunks.jsonl`).
- `metadata.csv` được sinh tự động bởi cùng script.

## Cách tạo dữ liệu

```
python scripts/ingest_documents.py
```

Script đọc mọi `*.md` trong `sources/`, cắt chunk (900 ký tự, overlap 120),
ghi `chunks/demo_chunks.jsonl` và `metadata.csv`.

## Lưu ý triển khai

- Dữ liệu chính thức của một xã thật phải được import từ nguồn có kiểm duyệt
  của con người, kèm ngày cập nhật và publisher rõ ràng (xem
  `docs/data_card.md`).
- Tuyệt đối không dùng dữ liệu này cho trả lời thật ở giai đoạn pilot.
