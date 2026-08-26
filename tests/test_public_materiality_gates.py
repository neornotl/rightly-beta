"""Public-handler regression coverage for deterministic legal safety gates."""

from __future__ import annotations

import json
from io import BytesIO

import pytest

from api import index


def _post(path: str, payload: dict):
    request = object.__new__(index.handler)
    request.path = path
    raw = json.dumps(payload).encode("utf-8")
    request.headers = {"Content-Length": str(len(raw))}
    request.rfile = BytesIO(raw)
    sent = {}
    request._send = lambda status, content_type, body, **kwargs: sent.update(
        status=status, content_type=content_type, body=body, **kwargs
    )
    return request, sent


def _body(sent: dict) -> dict:
    return json.loads(sent["body"])


@pytest.mark.parametrize(
    ("question", "decision", "required_phrase"),
    [
        ("Lương hưu của tôi chưa nhận 2 tháng thì sao?", "clarify", "tài khoản"),
        ("Người cao tuổi khám BHYT được hưởng quyền lợi gì?", "clarify", "nhóm quyền lợi"),
        ("Uống bia rồi lái xe bị phạt bao nhiêu?", "clarify", "nồng độ cồn"),
    ],
)
def test_public_materiality_clarifications_do_not_retrieve_or_call_provider(
    monkeypatch, question, decision, required_phrase
):
    monkeypatch.setattr(index, "RATE_LIMIT_PER_IP", 99)
    monkeypatch.setattr(index, "RATE_LIMIT_WARN_AT", 2)
    monkeypatch.setattr(index, "_grounded_search", lambda *_args, **_kwargs: pytest.fail("no retrieval"))
    monkeypatch.setattr(index.handler, "_ask_api", lambda *_args, **_kwargs: pytest.fail("no provider"))
    request, sent = _post("/api/chat", {"text": question, "lang": "vi"})

    request.do_POST()

    body = _body(sent)
    assert sent["status"] == 200
    assert body["decision"] == decision
    assert required_phrase in body["reply"]
    assert body["sources"] == []
    assert body["metadata"]["provider"] == "deterministic"


def test_public_abstention_suppresses_lexically_related_citations(monkeypatch):
    monkeypatch.setattr(index, "RATE_LIMIT_PER_IP", 99)
    monkeypatch.setattr(index, "RATE_LIMIT_WARN_AT", 2)
    monkeypatch.setattr(
        index,
        "_grounded_search",
        lambda *_args, **_kwargs: [
            {
                "cid": "land::c001",
                "sid": "land",
                "title": "Nguồn về đất đai",
                "text": "Điều kiện chuyển nhượng quyền sử dụng đất.",
                "score": 1.0,
            }
        ],
    )
    monkeypatch.setattr(index.handler, "_ask_api", lambda *_args, **_kwargs: pytest.fail("no provider"))
    request, sent = _post(
        "/api/chat",
        {"text": "Xác nhận hộ nghèo để con được miễn giảm học phí cần gì?", "lang": "vi"},
    )

    request.do_POST()

    body = _body(sent)
    assert body["decision"] == "abstain"
    assert body["sources"] == []
    assert "không thể kết luận" in body["reply"]
    assert body["metadata"]["corpus_version"] != "not_queried"


def test_public_direct_evidence_dict_is_not_mistaken_for_missing_evidence(monkeypatch):
    monkeypatch.setattr(index, "RATE_LIMIT_PER_IP", 99)
    monkeypatch.setattr(index, "RATE_LIMIT_WARN_AT", 2)
    monkeypatch.setattr(
        index,
        "_grounded_search",
        lambda *_args, **_kwargs: [
            {
                "cid": "edu::c001",
                "sid": "edu",
                "title": "Nguồn học phí",
                "text": "Hộ nghèo được miễn giảm học phí theo quy định.",
                "score": 2.0,
            }
        ],
    )
    monkeypatch.setattr(index.handler, "_ask_api", lambda *_args, **_kwargs: "Dạ, theo nguồn edu.")
    request, sent = _post(
        "/api/chat",
        {"text": "Hộ nghèo được miễn giảm học phí không?", "lang": "vi"},
    )

    request.do_POST()

    body = _body(sent)
    assert body["sources"] == ["edu"]


def test_public_unverifiable_reference_abstains_without_substituting_a_law(monkeypatch):
    monkeypatch.setattr(index, "RATE_LIMIT_PER_IP", 99)
    monkeypatch.setattr(index, "RATE_LIMIT_WARN_AT", 2)
    monkeypatch.setattr(index, "_verified_law_references", lambda: frozenset({"168/2024"}))
    monkeypatch.setattr(index, "_grounded_search", lambda *_args, **_kwargs: pytest.fail("no retrieval"))
    monkeypatch.setattr(index.handler, "_ask_api", lambda *_args, **_kwargs: pytest.fail("no provider"))
    request, sent = _post("/api/chat", {"text": "Luật 997/2026 quy định gì về giao thông?", "lang": "vi"})

    request.do_POST()

    body = _body(sent)
    assert body["decision"] == "abstain"
    assert body["sources"] == []
    assert "chưa xác minh được" in body["reply"]


def test_public_registry_allows_a_reference_present_in_the_checked_source_set(monkeypatch):
    monkeypatch.setattr(index, "_verified_law_references", lambda: frozenset({"168/2024"}))

    assert not index._unverifiable_legal_reference("Nghị định 168/2024/NĐ-CP quy định gì?")


def test_public_emergency_bypasses_retrieval_and_stream_has_no_sources(monkeypatch):
    monkeypatch.setattr(index, "RATE_LIMIT_PER_IP", 99)
    monkeypatch.setattr(index, "RATE_LIMIT_WARN_AT", 2)
    monkeypatch.setattr(index, "_grounded_search", lambda *_args, **_kwargs: pytest.fail("no retrieval"))
    monkeypatch.setattr(index.handler, "_ask_api", lambda *_args, **_kwargs: pytest.fail("no provider"))
    request, sent = _post("/api/chat/stream", {"text": "Tôi đang đau tim dữ dội, phải làm sao?", "lang": "vi"})

    request.do_POST()

    events = [
        json.loads(line.removeprefix("data: "))
        for line in sent["body"].splitlines()
        if line.startswith("data: ")
    ]
    answer = next(event for event in events if event["type"] == "answer")
    assert answer["decision"] == "emergency"
    assert answer["sources"] == []
    assert "115" in answer["reply"]
