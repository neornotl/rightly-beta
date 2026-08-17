"""Routing policy: mapping from rule hits / retrieval state to decisions.

The policy deliberately keeps wording generic and safe. Official channel
strings come from config placeholders that MUST be verified before deployment.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas import Action, ReasonCode, SafetyDecision, Zone


@dataclass
class Policy:
    hold_message: str = "Xin chờ chút, tôi đang tìm thông tin chính thức cho câu hỏi của bạn."
    red_message: str = (
        "Tôi không phải cơ quan khẩn cấp. Nếu bạn đang gặp tình huống nguy "
        "hiểm, hãy gọi ngay số khẩn cấp địa phương hoặc nhờ người thân giúp "
        "đỡ. Tôi không thể thay thế hỗ trợ của con người."
    )
    criminal_message: str = (
        "Câu hỏi của bạn liên quan đến vụ việc hình sự, rất hệ trọng và tôi "
        "không tự ý đưa ra kết luận về các tình huống này. Bạn nên liên hệ "
        "công an hoặc đường dây nóng để được tư vấn trực tiếp (số điện thoại "
        "chưa xác minh, cần cập nhật trước khi triển khai)."
    )
    legal_message: str = (
        "Câu hỏi của bạn liên quan đến tranh chấp hoặc phán quyết pháp lý, "
        "ngoài phạm vi thông tin thủ tục hành chính của tôi. Bạn nên liên hệ "
        "trợ giúp pháp lý hoặc cơ quan có thẩm quyền (số điện thoại chưa xác "
        "minh, cần cập nhật trước khi triển khai)."
    )
    fake_law_message: str = (
        "Tôi không tìm thấy văn bản pháp luật với số và năm bạn vừa nêu trong "
        "kho nguồn chính thức đã kiểm chứng. Tôi không tự ý xác nhận hoặc "
        "bình luận về thông tin chưa được kiểm chứng (tin đồn, mạng xã hội, "
        "văn bản không rõ nguồn). Bạn nên tra cứu tại Cổng Dịch vụ công quốc "
        "gia hoặc liên hệ bộ phận một cửa để được hướng dẫn chính thức."
    )
    out_of_scope_message: str = (
        "Câu hỏi này nằm ngoài phạm vi thủ tục hành chính mà tôi hỗ trợ. "
        "Tôi chỉ giúp về thủ tục hành chính và quyền lợi công tại các xã, "
        "phường, thị trấn."
    )
    insufficient_message: str = (
        "Tôi không tìm thấy nguồn thông tin đủ tin cậy cho câu hỏi này. "
        "Tôi sẽ không trả lời khi chưa chắc chắn. Bạn có thể hỏi lại bằng "
        "cách khác, hoặc liên hệ bộ phận một cửa của xã để được hướng dẫn."
    )
    ambiguous_message: str = (
        "Tôi chưa hiểu rõ câu hỏi của bạn. Bạn có thể nói lại hoặc hỏi chi "
        "tiết hơn, ví dụ: 'Thủ tục cấp giấy xác nhận hộ khẩu?'"
    )
    citation_outdated_message: str = (
        "Tôi chỉ tìm thấy văn bản đã hết hiệu lực cho câu hỏi này, nên tôi "
        "sẽ không đưa ra câu trả lời để tránh thông tin sai. Bạn nên liên hệ "
        "bộ phận một cửa của xã để được hướng dẫn theo quy định hiện hành."
    )
    citation_unsupported_message: str = (
        "Câu trả lời dự kiến không khớp với nguồn chính thức đã truy xuất, "
        "nên tôi sẽ không đọc câu trả lời này. Bạn có thể hỏi lại bằng cách "
        "khác hoặc liên hệ bộ phận một cửa của xã để được hỗ trợ."
    )

    def emergency_decision(self) -> SafetyDecision:
        return SafetyDecision(
            zone=Zone.RED,
            action=Action.ESCALATE,
            reason_codes=[ReasonCode.EMERGENCY_SIGNAL.value],
            user_message=self.red_message,
            requires_human=True,
        )

    def violence_decision(self) -> SafetyDecision:
        return SafetyDecision(
            zone=Zone.RED,
            action=Action.ESCALATE,
            reason_codes=[ReasonCode.VIOLENCE_OR_THREAT.value],
            user_message=self.red_message,
            requires_human=True,
        )

    def criminal_decision(self) -> SafetyDecision:
        return SafetyDecision(
            zone=Zone.ORANGE,
            action=Action.GUIDE,
            reason_codes=[ReasonCode.CRIMINAL_MATTER.value],
            user_message=self.criminal_message,
            requires_human=True,
        )

    def legal_decision(self) -> SafetyDecision:
        return SafetyDecision(
            zone=Zone.ORANGE,
            action=Action.GUIDE,
            reason_codes=[ReasonCode.LEGAL_JUDGMENT_REQUEST.value],
            user_message=self.legal_message,
            requires_human=True,
        )

    def out_of_scope_decision(self) -> SafetyDecision:
        return SafetyDecision(
            zone=Zone.ORANGE,
            action=Action.GUIDE,
            reason_codes=[ReasonCode.OUT_OF_SCOPE.value],
            user_message=self.out_of_scope_message,
            requires_human=False,
        )

    def fake_law_decision(self) -> SafetyDecision:
        return SafetyDecision(
            zone=Zone.ORANGE,
            action=Action.REFUSE,
            reason_codes=[ReasonCode.FAKE_LAW_REFERENCE.value],
            user_message=self.fake_law_message,
            requires_human=False,
        )

    def insufficient_decision(self) -> SafetyDecision:
        return SafetyDecision(
            zone=Zone.ORANGE,
            action=Action.REFUSE,
            reason_codes=[ReasonCode.INSUFFICIENT_SOURCE.value],
            user_message=self.insufficient_message,
            requires_human=False,
        )

    def ambiguous_decision(self) -> SafetyDecision:
        return SafetyDecision(
            zone=Zone.YELLOW,
            action=Action.CLARIFY,
            reason_codes=[ReasonCode.AMBIGUOUS_QUERY.value],
            user_message=self.ambiguous_message,
            requires_human=False,
        )

    def safe_decision(self, llm_reasoned: bool = False) -> SafetyDecision:
        codes = [ReasonCode.SAFE_GROUNDED_QUERY.value]
        if llm_reasoned:
            codes.append(ReasonCode.LLM_CLASSIFICATION.value)
        return SafetyDecision(
            zone=Zone.YELLOW,
            action=Action.ANSWER,
            reason_codes=codes,
            user_message="",
            requires_human=False,
        )

    def citation_decision(self, outdated: bool = False) -> SafetyDecision:
        """Answer was rejected because citations failed grounding checks."""
        code = ReasonCode.CITATION_OUTDATED if outdated else ReasonCode.CITATION_UNSUPPORTED
        message = self.citation_outdated_message if outdated else self.citation_unsupported_message
        return SafetyDecision(
            zone=Zone.ORANGE,
            action=Action.REFUSE,
            reason_codes=[code.value],
            user_message=message,
            requires_human=False,
        )
