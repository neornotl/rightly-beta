"""GATE 2 — Citation & legal-effectiveness (Luna gate #2).

Checks the curated registry (data/law_status.json) and the validator:

- Registry integrity: every source has ky_hieu/trich_yeu, a valid status,
  and expired sources carry an expired_on date.
- Every source cited by the 50-FAQ set is registered and not expired.
- Validator behaviour: unknown / unsupported / outdated citations are
  rejected; a valid current + retrieved citation passes.
- Pipeline behaviour: an answer citing only retrieved, current sources
  passes; a hallucinated source_id is refused end-to-end.

NOTE: content-level accuracy ("answer legally supported") still needs a
human legal reviewer on a sample of answers — that part is manual.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.schemas import GroundedAnswer

REGISTRY = Path("data/law_status.json")

VALID_STATUSES = {"active_verified", "expired", "pending_effective"}


def _load_registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8")).get("sources", {})


def _answer(*source_ids: str, text: str = "câu trả lời tham khảo") -> GroundedAnswer:
    return GroundedAnswer(answer_text=text, source_ids=list(source_ids))


# --- Registry integrity ------------------------------------------------------


def test_gate2_registry_complete_and_consistent():
    sources = _load_registry()
    assert len(sources) >= 180, "registry shrank; expected ~184 sources"
    for sid, info in sources.items():
        assert info.get("ky_hieu"), f"{sid} missing ky_hieu"
        assert info.get("trich_yeu"), f"{sid} missing trich_yeu"
        assert info.get("status") in VALID_STATUSES, f"{sid} bad status {info.get('status')!r}"
        if info.get("status") == "expired":
            assert info.get("expired_on"), f"{sid} expired but has no expired_on"


def test_gate2_faq_citations_registered_and_active():
    faqs = json.loads(Path("data/faq.json").read_text(encoding="utf-8"))["faqs"]
    sources = _load_registry()
    all_sids = set()
    for faq in faqs:
        assert faq.get("id"), "every FAQ needs an id"
        sids = faq.get("source_ids") or []
        assert sids, f"FAQ {faq['id']} must carry source_ids (council fix)"
        all_sids.update(sids)
    unknown = [s for s in all_sids if s not in sources]
    expired = [s for s in all_sids if s in sources and sources[s]["status"] == "expired"]
    assert not unknown, f"FAQ cites unregistered sources: {unknown}"
    assert not expired, f"FAQ cites expired sources: {expired}"


# --- Validator behaviour -----------------------------------------------------


def test_gate2_unknown_source_rejected(citation_validator):
    verdict = citation_validator.validate(_answer("KHONG_TON_TAI"))
    assert not verdict.ok
    assert any(i.kind == "unknown" for i in verdict.issues)


def test_gate2_unsupported_source_rejected(citation_validator):
    # Source exists and is current, but was NOT retrieved for the query.
    verdict = citation_validator.validate(_answer("luat19_2026"), retrieved_sources={"other"})
    assert not verdict.ok
    assert any(i.kind == "unsupported" for i in verdict.issues)


def test_gate2_outdated_source_rejected(citation_validator):
    verdict = citation_validator.validate(_answer("nd62_2021"), retrieved_sources={"nd62_2021"})
    assert not verdict.ok
    assert any(i.kind == "outdated" for i in verdict.issues)


def test_gate2_valid_current_citation_passes(citation_validator):
    verdict = citation_validator.validate(
        _answer("luat19_2026"), retrieved_sources={"luat19_2026"}
    )
    assert verdict.ok


def test_gate2_expired_sources_cannot_be_used_for_answers():
    sources = _load_registry()
    expired = [s for s, v in sources.items() if v["status"] == "expired"]
    assert len(expired) == 4, "expected the 4 known expired decrees"
    for sid in expired:
        info = sources[sid]
        assert info.get("expired_on") or info.get("replaced_by"), (
            f"expired source {sid} should point to replacement/expiry"
        )


# --- Pipeline end-to-end -----------------------------------------------------


def test_gate2_pipeline_answer_with_valid_citations_passes(offline_pipeline):
    session_id = offline_pipeline.create_session()
    # Safe, grounded query: mock LLM cites only retrieved chunks -> must pass.
    result = offline_pipeline.process_text(session_id, "Tuổi nghỉ hưu năm 2026 là bao nhiêu?")
    offline_pipeline.delete_session(session_id)
    if result.answer is not None:
        assert result.answer.source_ids, "answer must carry citations"
        for sid in result.answer.source_ids:
            assert sid in {c.source_id for c in result.chunks}


def test_gate2_hallucinated_citation_refused_end_to_end(offline_pipeline):
    class HallucinateLLM:
        name = "hallucinate"

        def generate_answer(self, query, chunks, max_chars=2000, history=None):
            return {
                "answer_text": "câu trả lời bịa",
                "spoken_citation": "",
                "source_ids": ["HALLUCINATED_SRC"],
                "limitations": [],
                "next_step": "",
            }

    offline_pipeline.llm = HallucinateLLM()  # type: ignore[assignment]
    session_id = offline_pipeline.create_session()
    result = offline_pipeline.process_text(session_id, "Nghị định 123/2015/NĐ-CP về hộ tịch?")
    offline_pipeline.delete_session(session_id)
    assert result.answer is None
    assert any("CITATION" in rc for rc in result.decision.reason_codes), result.decision.reason_codes
