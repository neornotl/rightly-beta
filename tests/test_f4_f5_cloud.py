"""F4/F5 tests: key rotation, fallback LLM, rate limiter, voice FAQ."""

from __future__ import annotations

import json

import pytest

from app.faq import FAQMatcher, _strip_diacritics
from app.llm.base import LLMError
from app.llm.fallback import FallbackLLM
from app.llm.groq_llm import GroqLLM
from app.ratelimit import RateLimiter
from app.schemas import RetrievedChunk

CHUNKS = [RetrievedChunk(source_id="ho_tich", chunk_id="ht-1", text="nội dung", score=0.9)]


class _FakeChoices:
    def __init__(self, content: str):
        self.message = type("M", (), {"content": content})


class _FakeUsage:
    prompt_tokens = 10
    completion_tokens = 5
    total_tokens = 15


class _FakeCompletion:
    def __init__(self, content: str):
        self.choices = [_FakeChoices(content)]
        self.usage = _FakeUsage()


def _fake_client(create_fn, completions_attr="create"):
    comp = type("Comp", (), {completions_attr: create_fn})()
    return type("C", (), {"chat": type("Chat", (), {"completions": comp})()})()


# ---------- F4: Groq key rotation ----------


def test_groq_rotates_key_on_429(monkeypatch):
    llm = GroqLLM(api_key="a", api_keys=("a", "b", "c"), backoff_seconds=0)
    used: list[str] = []

    def fake_create(self, **kwargs):
        current = llm.api_keys[llm._key_index]
        used.append(current)
        if current == "a":
            raise RuntimeError("429 Too Many Requests")
        return _FakeCompletion(
            json.dumps(
                {
                    "answer_text": "ok",
                    "spoken_citation": "c",
                    "source_ids": ["ht-1"],
                    "limitations": [],
                    "next_step": "",
                }
            )
        )

    monkeypatch.setattr(llm, "_get_client", lambda: _fake_client(fake_create))
    out = llm.generate_answer("hỏi?", CHUNKS)
    assert out["answer_text"] == "ok"
    assert used[0] == "a"
    assert used[-1] == "b"
    assert llm._key_index == 1


def test_groq_all_keys_exhausted_raises(monkeypatch):
    llm = GroqLLM(api_key="a", api_keys=("a", "b"), backoff_seconds=0)

    def fake_create(self, **kwargs):
        raise RuntimeError("429 Too Many Requests")

    monkeypatch.setattr(llm, "_get_client", lambda: _fake_client(fake_create))
    with pytest.raises(LLMError):
        llm.generate_answer("hỏi?", CHUNKS)
    assert llm._key_index == 1


def test_groq_no_rotation_on_non_json(monkeypatch):
    llm = GroqLLM(api_key="a", api_keys=("a", "b"), backoff_seconds=0)

    def fake_get_client():
        return _fake_client(lambda self, **kwargs: _FakeCompletion("không phải json"))

    monkeypatch.setattr(llm, "_get_client", fake_get_client)
    with pytest.raises(LLMError, match="non-JSON"):
        llm.generate_answer("hỏi?", CHUNKS)
    assert llm._key_index == 0


# ---------- F4: FallbackLLM ----------


class _FailingLLM:
    name = "failing"

    @property
    def available(self):
        return True

    def generate_answer(self, query, chunks, max_chars=2000, history=None):
        raise LLMError("primary down")

    def classify_safe(self, query, chunks):
        # Simulates a backend that propagates an outage (adapter contract:
        # "failure means NOT safe" applies to the FallbackLLM's total result).
        raise LLMError("primary down")


class _SucceedingLLM:
    name = "succeeding"

    @property
    def available(self):
        return True

    def generate_answer(self, query, chunks, max_chars=2000, history=None):
        return {
            "answer_text": "fallback ok",
            "spoken_citation": "c",
            "source_ids": [],
            "limitations": [],
            "next_step": "",
        }

    def classify_safe(self, query, chunks):
        return True


def test_fallback_uses_primary_on_success():
    fallback = FallbackLLM(primary=_SucceedingLLM(), fallback=_FailingLLM())
    assert fallback.generate_answer("q", CHUNKS)["answer_text"] == "fallback ok"


def test_fallback_uses_fallback_after_primary_failure():
    fallback = FallbackLLM(primary=_FailingLLM(), fallback=_SucceedingLLM())
    assert fallback.generate_answer("q", CHUNKS)["answer_text"] == "fallback ok"


def test_fallback_raises_when_both_fail():
    fallback = FallbackLLM(primary=_FailingLLM(), fallback=_FailingLLM())
    with pytest.raises(LLMError, match="fallback"):
        fallback.generate_answer("q", CHUNKS)


def test_fallback_classify_safe_falls_through():
    fallback = FallbackLLM(primary=_FailingLLM(), fallback=_SucceedingLLM())
    assert fallback.classify_safe("q", CHUNKS) is True


# ---------- F4: RateLimiter ----------


def test_ratelimit_allows_up_to_limit_and_blocks():
    rl = RateLimiter(limit=3, window_seconds=60)
    assert rl.allow("ip1", now=0.0)
    assert rl.allow("ip1", now=1.0)
    assert rl.allow("ip1", now=2.0)
    assert not rl.allow("ip1", now=3.0)
    assert rl.allow("ip2", now=4.0)


def test_ratelimit_window_expires():
    rl = RateLimiter(limit=1, window_seconds=10)
    assert rl.allow("ip1", now=0.0)
    assert not rl.allow("ip1", now=5.0)
    assert rl.allow("ip1", now=11.0)


def test_ratelimit_remaining_and_sweep():
    rl = RateLimiter(limit=2, window_seconds=10)
    rl.allow("ip1", now=0.0)
    rl.allow("ip1", now=1.0)
    rl.allow("ip2", now=1.0)
    assert rl.remaining("ip1", now=2.0) == 0
    assert rl.sweep(now=20.0) == 2


def test_ratelimit_zero_limit_blocks_everything():
    rl = RateLimiter(limit=0, window_seconds=60)
    assert not rl.allow("ip1", now=0.0)


# ---------- F5: Voice FAQ ----------


def test_strip_diacritics_handles_tones_and_d():
    assert _strip_diacritics("Sổ đỏ cần gì?") == "so do can gi?"
    assert _strip_diacritics("Đăng Ký Khai Sinh") == "dang ky khai sinh"


def test_faq_matches_diacritic_insensitively():
    faq = FAQMatcher()
    hit = faq.answer("so do cua toi chua co, lam so do lan dau can gi?")
    assert hit is not None
    assert hit.faq_id == "so-do"
    assert hit.score >= FAQMatcher.MIN_SCORE


def test_faq_no_match_falls_through():
    faq = FAQMatcher()
    assert faq.answer("thời tiết hôm nay thế nào") is None
    assert faq.answer("") is None


def test_faq_short_words_do_not_trigger():
    faq = FAQMatcher()
    # "khai" alone is 4 chars < MIN_SCORE -> no hit.
    assert faq.answer("khai") is None


def test_faq_to_grounded_answer_shape():
    faq = FAQMatcher()
    hit = faq.answer("Đăng ký khai sinh cho cháu cần những gì?")
    assert hit is not None
    ans = hit.to_grounded_answer()
    assert ans.answer_text
    # FAQ entries now carry verified source citations (gate 2): source_ids is a
    # list of source identifiers (may be empty for self-contained entries).
    assert isinstance(ans.source_ids, list)
    assert all(isinstance(s, str) and s for s in ans.source_ids)
    assert any("FAQ" in lim for lim in ans.limitations)


def test_faq_loaded_from_disk():
    faq = FAQMatcher()
    assert faq.count >= 5
