"""Shared fixtures for the pilot-readiness gate suite (tests/gates).

All gates run OFFLINE: real legal corpus + BM25 retriever + MockLLM +
MockTTS + real CitationValidator + real FAQMatcher. Deterministic, no
network, no API keys. The same batteries must be re-run against the real
LLM (Pateway) before the pilot opens — see gates/README.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.faq import FAQMatcher
from app.llm.mock_llm import MockLLM
from app.pipeline import Pipeline
from app.retrieval.bm25_retriever import BM25Retriever
from app.safety.policy import Policy
from app.safety.router import SafetyRouter
from app.tts.mock_tts import MockTTS
from app.validation.citation_validator import CitationValidator

REAL_CHUNKS = Path("data/chunks/real_chunks.jsonl")
REGISTRY = Path("data/law_status.json")


def make_settings(tmp_path, **overrides) -> Settings:
    settings = Settings(
        data_dir=tmp_path / "data",
        results_dir=tmp_path / "results",
        log_dir=tmp_path / "logs",
        app_mode="local",
        retrieval_backend="bm25",
        llm_backend="mock",
        tts_backend="mock",
        **overrides,
    )
    settings.resolved_log_dir().mkdir(parents=True, exist_ok=True)
    return settings


@pytest.fixture(scope="session")
def bm25_retriever() -> BM25Retriever:
    return BM25Retriever.from_jsonl(REAL_CHUNKS)


@pytest.fixture
def citation_validator() -> CitationValidator:
    return CitationValidator(REGISTRY)


@pytest.fixture
def faq_matcher() -> FAQMatcher:
    return FAQMatcher()


@pytest.fixture
def offline_pipeline(tmp_path, bm25_retriever) -> Pipeline:
    """Full offline pipeline: real corpus, mock LLM/TTS, real validator+FAQ."""
    settings = make_settings(tmp_path)
    return Pipeline(
        settings=settings,
        retriever=bm25_retriever,
        llm=MockLLM(),
        tts=MockTTS(),
        router=SafetyRouter(settings=settings, policy=Policy()),
        validator=CitationValidator(REGISTRY),
        faq=FAQMatcher(),
    )
