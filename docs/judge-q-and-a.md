# Rightly — Q&A cho người đánh giá

> Tài liệu này mô tả bản pilot hiện tại. Các mục “định hướng” không được hiểu là tính năng đã hoàn thiện.

## Rightly khác chatbot hoặc công cụ tìm kiếm ở đâu?

Rightly tập trung vào câu hỏi thông tin công, thủ tục hành chính và pháp luật phổ thông bằng tiếng Việt. Pipeline tìm văn bản trong kho nguồn đã cấu hình, chuyển các câu không dấu về thuật ngữ chuẩn trước khi truy xuất, rồi yêu cầu mô hình trả lời dựa trên phần bằng chứng tìm được. Đây là khác biệt về phạm vi, truy xuất nguồn và cách trình bày; Rightly không tuyên bố thay thế công cụ tìm kiếm, luật sư hay cơ quan nhà nước.

## Rightly có “đúng pháp luật” tuyệt đối không?

Không. Nguồn có thể thiếu, thay đổi hoặc chưa cập nhật. Hệ thống có kiểm tra citation/đầu ra và cảnh báo khi không có bằng chứng phù hợp, nhưng người dùng vẫn phải đối chiếu văn bản chính thức hoặc hỏi cơ quan có thẩm quyền. Pilot đo trải nghiệm người dùng, không phải chứng nhận độ đúng pháp lý độc lập.

## Khi luật thay đổi thì cập nhật thế nào?

Nguồn được quản lý trong kho dữ liệu và có metadata/trạng thái nguồn; tài liệu hết hiệu lực được đánh dấu để tránh trình bày như luật hiện hành. Việc cập nhật vẫn cần người quản trị kiểm tra và triển khai lại kho nguồn. Không nên hiểu rằng Rightly tự động biết mọi thay đổi pháp luật theo thời gian thực.

## Vì sao có chế độ local/offline?

Bản local được thiết kế để giữ dữ liệu và khả năng hỏi đáp trên máy người dùng sau khi đã cài đủ runtime, model và kho nguồn. Bộ cài tự kiểm tra cấu hình và chỉ mở ứng dụng sau các bước preflight. Lần cài đầu vẫn cần Internet để tải thành phần; khả năng offline thực tế còn phụ thuộc máy đã cài đủ model/thư viện và cần được kiểm thử trên chính máy đó.

## Người cao tuổi có thể dùng không?

Voice input/output và giao diện chữ lớn là các hướng phục vụ người ít quen công nghệ. Tuy nhiên microphone còn phụ thuộc quyền của Chrome/Edge và chất lượng nhận dạng phụ thuộc thiết bị, môi trường nói và backend đã cài. Public pilot có người ở nhiều nhóm tuổi, nhưng mẫu chưa đủ để kết luận hiệu quả đại diện cho toàn bộ người cao tuổi.

## Dữ liệu người dùng được bảo vệ ra sao?

Local history được tách khỏi cloud. Cloud sync không tự bật; người dùng phải chủ động xác nhận. Khi gửi nội dung tới provider cloud đã cấu hình, Rightly scrub một số định danh có độ tin cậy cao như email, số điện thoại, CCCD/CMND, hộ chiếu và địa chỉ có mốc đường/phố. Đây là biện pháp giảm rủi ro, không phải cam kết ẩn danh tuyệt đối. Không đưa consent, video private pilot hay hội thoại thô vào repository công khai.

## Pilot chứng minh điều gì?

Snapshot public pilot ngày 26/08/2026 có 56 phản hồi và cho thấy tín hiệu tích cực về trải nghiệm: thân thiện/phù hợp 4,41/5; ý tưởng cốt lõi 4,36/5; dễ dùng 4,23/5; rõ ràng 4,18/5; chính xác/tin cậy 4,18/5. Đây là số liệu phản hồi tự báo cáo do chủ biểu mẫu quản lý, không phải benchmark độc lập hay bằng chứng đại diện dân số. Feedback về voice, câu trả lời bị ngắt, mobile, tốc độ và nguồn rỗng đã được chuyển thành các thay đổi trong code; chi tiết và giới hạn nằm ở `docs/pilot-results-2026-08.md`.

## Sản phẩm có thể nhân rộng không?

Kiến trúc tách giao diện, pipeline, kho nguồn và backend model; bộ cài có phát hiện cấu hình và chọn model theo ngưỡng phần cứng. Vì vậy có cơ sở kỹ thuật để mở rộng sang kho nguồn hoặc nhóm người dùng khác. Tuy nhiên cần kiểm thử từng cấu hình Windows, kiểm tra chất lượng nguồn địa phương, chi phí vận hành cloud và chất lượng voice trước khi tuyên bố triển khai diện rộng.

## Hotline/viễn thông đã là tính năng hiện tại chưa?

Không nên trình bày hotline hoặc tích hợp viễn thông như tính năng đã hoàn thiện nếu chưa có bằng chứng triển khai tương ứng. Đây là hướng mở rộng; bản hiện tại được đánh giá qua web và bản local.

## Chi phí hiện tại là bao nhiêu?

Repository chưa cung cấp một benchmark chi phí độc lập theo mỗi người dùng. Chi phí cloud phụ thuộc provider, model, số token, audio và lưu lượng; local chuyển phần tính toán sang thiết bị người dùng nhưng yêu cầu tải model và phần cứng phù hợp. Vì vậy không đưa ra con số tiết kiệm cố định khi chưa đo đủ.

## Checklist demo ngắn cho giám khảo

1. Mở web production, thử câu hỏi pháp luật có dấu và câu không dấu; kiểm tra phần nguồn.
2. Thử phép tính ngắn để xác nhận các yêu cầu tất định không bị gửi nhầm sang LLM.
3. Nếu có máy Windows sạch, chạy bộ cài; xác nhận preflight, health check và log lỗi dễ hiểu.
4. Sau khi cài đủ model, ngắt mạng rồi thử gõ, microphone và TTS; ghi rõ model/backend thực tế.
5. Khi thử voice trên Chrome/Edge, cấp quyền microphone một lần; kiểm tra câu dài, dừng giữa chừng và không phát chồng audio.
6. Khi báo cáo kết quả, phân biệt rõ bản hiện tại, cải tiến sau submission và định hướng tương lai.
