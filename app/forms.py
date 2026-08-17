"""Phiếu chuẩn bị hồ sơ (registration slip) — hỗ trợ khai sẵn, không thu thập.

Nguyên tắc (khớp phán quyết R16 + Ethical AI):
- AI chỉ điền sẵn các trường QUY TRÌNH (thủ tục, nơi nộp, giấy tờ, thời hạn).
- Trường cá nhân (họ tên, CCCD, địa chỉ) LUÔN để trống — người dân tự khai và
  tự mang tới cơ quan; phiếu KHÔNG gửi đi đâu, không lưu nội dung người dùng.
- Kèm lời nhắc trung thực: phiếu không phải giấy tờ chính thức.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.contacts import Contact


@dataclass(frozen=True)
class RegistrationSlip:
    query: str
    summary: str
    next_step: str = ""
    contact: Optional[Contact] = None
    documents: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines: list[str] = [
            "# MẪU MINH HỌA — KHÔNG CÓ GIÁ TRỊ PHÁP LÝ",
            "",
            "> ⚠️ Phiếu này do Rightly (bản DEMO) tạo để hỗ trợ BẠN khai sẵn.",
            "> Thông tin cá nhân bên dưới do CHÍNH BẠN điền và tự mang đến cơ",
            "> quan. Rightly KHÔNG thu thập, lưu trữ hay gửi thông tin của bạn",
            "> đến bất kỳ đâu. Phiếu KHÔNG thay thế giấy tờ chính thức.",
            "",
            "## Câu hỏi của bạn",
            self.query,
            "",
            "## Tóm tắt hướng dẫn",
            self.summary,
            "",
        ]
        if self.next_step:
            lines += ["## Bước tiếp theo", self.next_step, ""]
        if self.contact is not None:
            lines += ["## Nơi liên hệ"]
            lines += [f"- **{self.contact.label}**"]
            if self.contact.callable:
                lines += [f"- Điện thoại: {self.contact.phone}"]
            if self.contact.note:
                lines += [f"- Ghi chú: {self.contact.note}"]
            lines.append("")
        lines += ["## Thông tin cá nhân (BẠN tự điền)", ""]
        for item in ("Họ và tên:", "Ngày sinh:", "Số CCCD:", "Địa chỉ thường trú:"):
            lines += [f"- {item} ________________", ""]
        lines += ["## Giấy tờ cần chuẩn bị (tham khảo)", ""]
        for doc in self.documents or ["(Chưa xác định — hỏi thêm cơ quan khi đến nộp)"]:
            lines += [f"- [ ] {doc}", ""]
        lines += ["## Lưu ý", ""]
        for note in self.notes:
            lines += [f"- {note}", ""]
        lines += [
            "",
            "—",
            "MẪU MINH HỌA — KHÔNG CÓ GIÁ TRỊ PHÁP LÝ. Tạo bởi Rightly (bản DEMO).",
        ]
        return "\n".join(lines)


def build_registration_slip(
    query: str,
    summary: str,
    next_step: str = "",
    contact: Optional[Contact] = None,
    documents: Optional[list[str]] = None,
) -> RegistrationSlip:
    """Build a slip; never includes personal data (none is collected here)."""
    return RegistrationSlip(
        query=query,
        summary=summary,
        next_step=next_step,
        contact=contact,
        documents=list(documents or []),
        notes=[
            "Thời gian xử lý, lệ phí và biểu mẫu có thể thay đổi — kiểm tra lại "
            "với cơ quan tiếp nhận trước khi nộp.",
            "Rightly không thay thế cán bộ hoặc cơ quan nhà nước.",
        ],
    )
