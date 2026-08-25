# Xác thực asset của bộ cài

## Trạng thái hiện tại

`scripts/asset_manifest.json` đang để trống có chủ đích. Vì vậy bộ cài chỉ có
thể tải tiếp khi mạng chập chờn và kiểm tra runtime sau cài đặt; **không được
diễn giải đây là kiểm tra SHA-256 thành công**.

## TODO trước phát hành production

1. Tải từng binary trực tiếp từ nguồn phát hành chính thức trên một môi trường
   kiểm soát được.
2. Đối chiếu SHA-256 với checksum do nhà phát hành công bố, hoặc lưu bằng
   chứng nội bộ có người chịu trách nhiệm phê duyệt.
3. Ghi URL/tên file và hash 64 ký tự vào `scripts/asset_manifest.json`.
4. Chạy test verifier với file đúng và file đã sửa một byte; chỉ khi đó mới đổi
   trạng thái phát hành thành “asset integrity verified”.

Không đoán hash từ tên file, không sao chép hash không có nguồn và không bỏ qua
cảnh báo này trong tài liệu demo/production.
