"""Naturalness tests (Round 11 council): tone, templates, spoken citation.

Council consensus: answers must stay grounded/safe but sound like a real
hotline agent — short sentences, polite fillers, spoken citation <=15 words.

Round 24 council: raw source codes must never reach speech, action slot is
dropped from answer_full, and the topic must not echo the raw query.
"""

from __future__ import annotations

from app.llm.mock_llm import MockLLM
from app.llm.prompts import (
    SYSTEM_PROMPT,
    TEMPLATES,
    clean_spoken_title,
    shorten_spoken_citation,
)
from app.schemas import RetrievedChunk, SourceMetadata
from app.validation.response_validator import detect_issues, sanitize_answer


class TestSystemPromptTone:
    def test_has_polite_pronouns(self):
        assert "anh/chị" in SYSTEM_PROMPT
        assert "ạ" in SYSTEM_PROMPT and "dạ" in SYSTEM_PROMPT

    def test_forbids_repeating_document_title(self):
        assert "KHÔNG lặp lại nguyên văn tiêu đề văn bản" in SYSTEM_PROMPT

    def test_short_sentence_rule(self):
        assert "18 từ" in SYSTEM_PROMPT
        assert "Một ý một câu" in SYSTEM_PROMPT

    def test_grounding_still_enforced(self):
        assert "CHÍNH XÁC" in SYSTEM_PROMPT
        assert "source_id" in SYSTEM_PROMPT
        assert "không bịa thông tin" in SYSTEM_PROMPT

    def test_safety_rules_present(self):
        assert "113" in SYSTEM_PROMPT and "115" in SYSTEM_PROMPT
        assert "hết hiệu lực" in SYSTEM_PROMPT
        assert "Ngoài phạm vi" in SYSTEM_PROMPT

    def test_default_length_rule(self):
        assert "NGẮN" in SYSTEM_PROMPT
        assert "80 từ" in SYSTEM_PROMPT


class TestTemplates:
    def test_all_six_situations_covered(self):
        assert set(TEMPLATES) == {
            "answer_full",
            "insufficient",
            "off_scope",
            "criminal",
            "expired",
            "clarify",
        }

    def test_insufficient_offers_guidance_not_bare_rejection(self):
        text = TEMPLATES["insufficient"]
        assert "chưa có dữ liệu" in text
        assert "1022" in text
        assert "được hướng dẫn" in text

    def test_criminal_routes_to_emergency(self):
        text = TEMPLATES["criminal"]
        assert "113" in text and "115" in text

    def test_clarify_asks_for_limited_info(self):
        assert "{needed}" in TEMPLATES["clarify"]

    def test_expired_points_to_replacement(self):
        assert "{replacement}" in TEMPLATES["expired"]


class TestSpokenCitation:
    def test_empty_input(self):
        assert shorten_spoken_citation("") == ""

    def test_strips_leading_opener(self):
        out = shorten_spoken_citation("Căn cứ Điều 14 Luật Hôn nhân và Gia đình 2014")
        assert out.startswith("Điều 14")
        assert "Căn cứ" not in out

    def test_drops_article_clause_details(self):
        out = shorten_spoken_citation("Luật Hôn nhân và Gia đình 2014, Điều 14, Khoản 1, Điểm a")
        assert out == "Luật Hôn nhân và Gia đình 2014, Điều 14"
        assert "Khoản" not in out and "Điểm" not in out

    def test_trims_after_sentence_boundary(self):
        out = shorten_spoken_citation(
            "Theo quy định của Nghị định 134/2015/NĐ-CP. Người lao động được..."
        )
        assert "Người lao động" not in out

    def test_caps_word_count(self):
        long = "Luật Hôn nhân và Gia đình năm 2014 " + " ".join(f"từ{a}" for a in range(25))
        out = shorten_spoken_citation(long)
        assert len(out.split()) <= 16

    def test_short_citation_untouched(self):
        out = shorten_spoken_citation("Điều 4, Nghị định 134/2015")
        assert out == "Điều 4, Nghị định 134/2015"

    def test_strips_raw_source_code_suffix(self):
        out = shorten_spoken_citation("theo Bộ luật Lao động 18_VBHN-VPQH")
        assert out == "Bộ luật Lao động"
        assert "VBHN" not in out

    def test_clean_spoken_title_drops_source_codes(self):
        assert clean_spoken_title("Bộ luật Lao động 18_VBHN-VPQH") == "Bộ luật Lao động"
        assert clean_spoken_title("Luật Bảo hiểm xã hội 19_VBHN-VPQH") == "Luật Bảo hiểm xã hội"
        assert clean_spoken_title("Bộ luật Lao động") == "Bộ luật Lao động"


class TestAnswerFullNoActionSlot:
    def test_template_has_no_action_slot(self):
        assert "{action}" not in TEMPLATES["answer_full"]

    def test_template_sounds_like_hotline_agent(self):
        text = TEMPLATES["answer_full"]
        assert text.startswith("Dạ vâng ạ")
        assert "{topic}" in text and "{core}" in text and "{citation}" in text

    def test_mock_llm_never_emits_anh_chi_di(self):
        meta = SourceMetadata(
            source_id="boluat45_2019",
            title="Bộ luật Lao động 18_VBHN-VPQH",
            source_type="law",
            publisher="VPQH",
        )
        chunk = RetrievedChunk(
            chunk_id="boluat45_2019::c000",
            source_id="boluat45_2019",
            text=(
                "Điều kiện hưởng: Kể từ năm 2021, tuổi nghỉ hưu là "
                "đủ 60 tuổi 03 tháng đối với nam và 55 tuổi 04 tháng đối với nữ. "
                "Lộ trình tăng dần đến 62 tuổi nam vào 2028, 60 tuổi nữ vào 2035."
            ),
            score=1.0,
            metadata=meta,
        )
        out = MockLLM().generate_answer(
            "theo quy định của pháp luật thì tuổi nghỉ hưu là bao nhiêu tuổi",
            [chunk],
        )
        answer = out["answer_text"]
        assert "Anh/chị Đi." not in answer
        assert "Anh/chị đi" not in answer
        assert "18_VBHN" not in answer
        assert "18_VBHN" not in out["spoken_citation"]
        assert "..." not in answer
        raw_query = "theo quy định của pháp luật thì tuổi nghỉ hưu là bao nhiêu tuổi"
        assert raw_query not in answer


class TestSpokenResponseValidator:
    def test_detects_raw_source_code(self):
        from app.schemas import GroundedAnswer

        ans = GroundedAnswer(
            answer_text="Theo Bộ luật Lao động 18_VBHN-VPQH",
            spoken_citation="Bộ luật Lao động 18_VBHN-VPQH",
            source_ids=["boluat45_2019"],
        )
        assert "RAW_SOURCE_ID_IN_ANSWER" in detect_issues(ans, "q")

    def test_detects_query_echo(self):
        from app.schemas import GroundedAnswer

        q = "theo quy định thì tuổi nghỉ hưu là bao nhiêu"
        ans = GroundedAnswer(answer_text=f"Dạ vâng ạ, {q} thì ...", source_ids=[])
        assert "QUERY_ECHO" in detect_issues(ans, q)
        assert "TRUNCATED_TEXT" in detect_issues(ans, q)

    def test_sanitize_strips_codes_and_suffix(self):
        from app.schemas import GroundedAnswer

        ans = GroundedAnswer(
            answer_text="Dạ vâng ạ, về tuổi nghỉ hưu thì ... 18_VBHN-VPQH",
            spoken_citation="theo Bộ luật Lao động 18_VBHN-VPQH",
            source_ids=["boluat45_2019"],
        )
        clean = sanitize_answer(ans, "tuổi nghỉ hưu")
        assert "18_VBHN" not in clean.answer_text
        assert "18_VBHN" not in clean.spoken_citation
        assert not clean.answer_text.endswith("...")
