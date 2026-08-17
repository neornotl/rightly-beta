"""P6: Citation validator tests, including the NĐ 62/2021 expiry case.

NĐ 62/2021 (quy định chi tiết Luật Cư trú) hết hiệu lực từ 10/01/2025,
thay thế bởi NĐ 154/2024 — a validator must reject it for "today".
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.schemas import GroundedAnswer
from app.validation.citation_validator import CitationValidator

STATUS = Path("data") / "law_status.json"


@pytest.fixture()
def validator():
    return CitationValidator(status_path=STATUS, today=date(2026, 8, 7))


def test_valid_citation_passes(validator):
    answer = GroundedAnswer(answer_text="x", source_ids=["nd154_2024", "luat68_2020"])
    verdict = validator.validate(answer, {"nd154_2024", "luat68_2020"})
    assert verdict.ok
    assert verdict.issues == []


def test_empty_citations_pass(validator):
    verdict = validator.validate(GroundedAnswer(answer_text="x"), set())
    assert verdict.ok


def test_nd62_2021_is_outdated_after_expiry(validator):
    answer = GroundedAnswer(answer_text="x", source_ids=["nd62_2021"])
    verdict = validator.validate(answer, {"nd62_2021"})
    assert not verdict.ok
    issue = verdict.issues[0]
    assert issue.kind == "outdated"
    assert "62/2021/NĐ-CP" in issue.message
    assert "154/2024/NĐ-CP" in issue.replacement
    assert issue.source_id == "nd62_2021"


def test_nd62_2021_was_valid_before_expiry():
    validator = CitationValidator(status_path=STATUS, today=date(2024, 6, 1))
    answer = GroundedAnswer(answer_text="x", source_ids=["nd62_2021"])
    verdict = validator.validate(answer, {"nd62_2021"})
    assert verdict.ok


def test_unsupported_citation_is_rejected(validator):
    answer = GroundedAnswer(answer_text="x", source_ids=["luat60_2014"])
    verdict = validator.validate(answer, {"nd123_2015"})
    assert not verdict.ok
    issue = verdict.issues[0]
    assert issue.kind == "unsupported"
    assert "60/2014/QH13" in issue.message


def test_unknown_source_is_rejected(validator):
    answer = GroundedAnswer(answer_text="x", source_ids=["luat99_9999"])
    verdict = validator.validate(answer, {"nd123_2015"})
    assert not verdict.ok
    assert verdict.issues[0].kind == "unknown"


def test_outdated_takes_precedence_over_unsupported(validator):
    answer = GroundedAnswer(answer_text="x", source_ids=["nd62_2021"])
    verdict = validator.validate(answer, set())
    assert verdict.issues[0].kind == "outdated"
    assert len(verdict.issues) == 1


def test_duplicate_citations_flagged_once(validator):
    answer = GroundedAnswer(answer_text="x", source_ids=["nd62_2021", "nd62_2021"])
    verdict = validator.validate(answer, {"nd62_2021"})
    assert len(verdict.issues) == 1
