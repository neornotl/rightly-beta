# Rightly — Responsible AI và giới hạn sử dụng

## Nguyên tắc

- Nói rõ đây là MVP/pilot, không phải dịch vụ pháp lý chính thức.
- Ưu tiên câu trả lời dựa trên nguồn; không bịa điều luật, mức phạt, điều kiện hoặc trích dẫn.
- Khi thiếu bằng chứng hoặc nguồn có vấn đề, phải nói giới hạn và hướng người dùng tới cơ quan/văn bản chính thức.
- Tách dữ liệu local khỏi cloud; đồng bộ cloud là hành động có chủ ý của người dùng.
- Không công khai dữ liệu định danh, consent chưa hoàn chỉnh, video hoặc transcript private pilot.

## Rủi ro và kiểm soát hiện có

| Rủi ro | Kiểm soát đang có | Giới hạn còn lại |
| --- | --- | --- |
| Nguồn thiếu hoặc lỗi thời | Kho nguồn có metadata/trạng thái; citation validation; cảnh báo giới hạn | Không thay thế việc kiểm tra văn bản hiện hành |
| Model trả lời quá tự tin | Prompt yêu cầu không bịa; pipeline có response/citation validation | Không bảo đảm mọi lỗi ngữ nghĩa được phát hiện |
| Lộ thông tin cá nhân qua cloud | Scrub định danh trước khi gửi provider; cloud sync opt-in | Scrub không phải ẩn danh tuyệt đối |
| Voice nhận sai | Cho phép ASR backend cấu hình và hiển thị lỗi; microphone cần quyền trình duyệt | Phụ thuộc microphone, tiếng ồn, ngôn ngữ và model |
| Offline không đủ thành phần | Installer preflight LLM/ASR/TTS/health; tải tiếp sau lỗi mạng | Chưa thay thế kiểm thử clean-install trên mọi máy |
| Dữ liệu pilot bị sử dụng sai mục đích | Repo chỉ công bố tổng hợp; private evidence giữ riêng | Consent hiện có chưa phải căn cứ công bố hình ảnh hoàn chỉnh |

## Cách diễn giải bằng chứng

Kết quả public pilot là tín hiệu về trải nghiệm và mức độ phù hợp cảm nhận. Không dùng các điểm đánh giá đó để khẳng định độ chính xác pháp lý, tác động xã hội nhân quả hoặc khả năng phục vụ toàn bộ dân số. Khi trình bày private pilot, chỉ nêu quy mô và phương pháp ở mức tổng hợp; mọi file gốc phải ở kênh riêng có kiểm soát.

## Báo cáo sự cố

Nếu câu trả lời sai, thiếu, bị ngắt hoặc voice phát chồng: lưu request/response ở mức tối thiểu cần thiết, loại bỏ PII trước khi chia sẻ, ghi lại phiên bản code/model/backend và tạo regression test không chứa dữ liệu thật. Không đăng transcript người dùng hoặc ảnh màn hình có thông tin nhận diện lên issue công khai.
