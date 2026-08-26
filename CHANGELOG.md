# Changelog

## v0.18.0-pilot — 26/08/2026

Bản cập nhật sau mốc nộp bài, tập trung vào độ tin cậy và Responsible AI:

- routing ngữ nghĩa, xử lý câu không dấu và phép tính ngắn có kiểm soát;
- privacy opt-in cho đồng bộ cloud và lọc PII trước khi gọi provider;
- readiness/preflight local, retry-resume, hủy TTS/request và installer marker v18;
- framework kiểm tra SHA-256 khi publisher cung cấp checksum;
- giới hạn body API 512 KiB cho chat và 20 MB cho audio, log structured không chứa nội dung người dùng;
- cải thiện mobile composer và accessibility.

Giới hạn còn lại: checksum publisher cho toàn bộ Python/Piper/Ollama/model chưa đầy đủ; clean install trên máy mới và kiểm thử microphone thật trên nhiều trình duyệt chưa được xác minh trong bản này.
