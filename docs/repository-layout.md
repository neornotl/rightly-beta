# Quan hệ giữa các repository

Rightly dùng hai repo với vai trò khác nhau:

| Repo/nhánh | Vai trò |
| --- | --- |
| [`rightly-beta/dev`](https://github.com/neornotl/rightly-beta/tree/dev) | Phát triển và kiểm thử liên tục. |
| [`rightly-beta/release`](https://github.com/neornotl/rightly-beta/tree/release) | Nhánh nguồn dùng để chuẩn bị bản phát hành. |
| [`rightly/release`](https://github.com/neornotl/rightly/tree/release) | Repo release công khai, đồng bộ từ `rightly-beta/release`. |

Địa chỉ web giữ nguyên: [https://intel-demo-topaz.vercel.app/](https://intel-demo-topaz.vercel.app/). Bản web hiện theo dõi nhánh `dev` của `rightly-beta` để nhóm kiểm thử; việc đó không thay đổi địa chỉ người dùng truy cập.

Khi chuẩn bị bản phát hành mới, cập nhật và kiểm tra `rightly-beta/release` trước, sau đó đồng bộ snapshot đã kiểm tra sang `rightly/release`. Không đưa private pilot URL hoặc secret vào bất kỳ repo nào.

