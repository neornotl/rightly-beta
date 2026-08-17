"""Spoken-answer quality guard (council R24 consensus).

Runs after LLM + CitationValidator, right before TTS. Catches the three
communication bugs voted by the council:
  - RAW_SOURCE_ID_IN_ANSWER / _IN_CITATION: technical ids like '18_VBHN-VPQH'
    leaking into speech,
  - QUERY_ECHO: the raw user query repeated verbatim as topic/answer,
  - TRUNCATED_TEXT: answers ending with a dangling '...' mid-sentence.

Fixes in place (sanitize) and reports issues so the pipeline can log them;
never raises — TTS must not break because of cosmetic text issues.
"""

from __future__ import annotations

import re

from app.llm.prompts import clean_spoken_title, shorten_spoken_citation
from app.schemas import GroundedAnswer

#: Raw source-code identifiers, e.g. '18_VBHN-VPQH', 'ND-161/2026-CP'.
_RAW_SOURCE_CODE = re.compile(r"\b\d+_[A-Z0-9]+(?:-[A-Z0-9]+)*\b", re.IGNORECASE)
#: Dangling truncation markers at end of text.
_TRUNCATED_TAIL = re.compile(r"\s*\.{3,}\s*$|…$")


def detect_issues(answer: GroundedAnswer, query: str) -> list[str]:
    """Return a list of detected spoken-quality issue codes (empty = clean)."""
    issues: list[str] = []
    if _RAW_SOURCE_CODE.search(answer.answer_text or ""):
        issues.append("RAW_SOURCE_ID_IN_ANSWER")
    if _RAW_SOURCE_CODE.search(answer.spoken_citation or ""):
        issues.append("RAW_SOURCE_ID_IN_CITATION")
    if _TRUNCATED_TAIL.search(answer.answer_text or ""):
        issues.append("TRUNCATED_TEXT")
    a = re.sub(r"\s+", " ", (answer.answer_text or "").lower()).strip()
    q = re.sub(r"\s+", " ", (query or "").lower()).strip("?")
    if len(q) >= 12 and q in a:
        issues.append("QUERY_ECHO")
    return issues


def sanitize_answer(answer: GroundedAnswer, query: str) -> GroundedAnswer:
    """Return a copy of the answer with spoken-unsafe text cleaned in place.

    Preserves single newlines (per-article answer structure) but collapses
    horizontal whitespace and blank lines.
    """
    text = _RAW_SOURCE_CODE.sub("", answer.answer_text or "")
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]*\n+[ \t]*", "\n", text)
    text = text.strip(" ,;:.")
    if _TRUNCATED_TAIL.search(text):
        text = _TRUNCATED_TAIL.sub("", text).rstrip(" ,;") + "."
    text = re.sub(r"\.{2,}", ".", text)
    spoken = _RAW_SOURCE_CODE.sub("", answer.spoken_citation or "")
    spoken = shorten_spoken_citation(clean_spoken_title(spoken))
    return GroundedAnswer(
        answer_text=text,
        spoken_citation=spoken,
        source_ids=answer.source_ids,
        limitations=answer.limitations,
        next_step=answer.next_step,
    )