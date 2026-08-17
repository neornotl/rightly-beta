"""P6: Citation validator.

Checks that every source cited by the LLM answer is:
  - registered (known source_id in the curated law-status registry),
  - current (not expired at "today"; expired docs are flagged with the
    replacement document),
  - supported (the source was actually retrieved for this query).

A failing citation downgrades the answer in the pipeline (ORANGE/REFUSE).
The registry is curated human-verified data: data/law_status.json.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from app.schemas import GroundedAnswer

_EXPIRY_PARSE = "%d-%m-%Y"
_EXPIRY_ISO = "%Y-%m-%d"


@dataclass(frozen=True)
class CitationIssue:
    source_id: str
    kind: str  # unknown | outdated | unsupported
    message: str
    replacement: str = ""


@dataclass(frozen=True)
class CitationVerdict:
    ok: bool
    issues: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "issues": [vars(i) for i in self.issues],
        }


class CitationValidator:
    """Validates cited source_ids against the curated registry."""

    def __init__(
        self,
        status_path: Optional[Path] = None,
        today: Optional[date] = None,
    ) -> None:
        self.status_path = Path(status_path or Path("data") / "law_status.json")
        self.today = today or date.today()
        self.sources: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not self.status_path.exists():
            raise FileNotFoundError(f"law status registry not found: {self.status_path}")
        data = json.loads(self.status_path.read_text(encoding="utf-8"))
        self.sources = data.get("sources", {})

    @staticmethod
    def _parse(value: str) -> Optional[date]:
        for fmt in (_EXPIRY_ISO, _EXPIRY_PARSE):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        return None

    def describe(self, source_id: str) -> str:
        info = self.sources.get(source_id)
        if not info:
            return source_id
        return f"{info.get('ky_hieu', '')} ({info.get('trich_yeu', source_id)})".strip()

    def validate(
        self,
        answer: GroundedAnswer,
        retrieved_sources: Optional[set[str]] = None,
    ):
        retrieved_sources = retrieved_sources or set()
        issues: list = []
        valid_citations = 0
        total_citations = 0
        for sid in dict.fromkeys(answer.source_ids):
            total_citations += 1
            info = self.sources.get(sid)
            if info is None:
                issues.append(
                    CitationIssue(
                        source_id=sid,
                        kind="unknown",
                        message=f"Nguồn '{sid}' không có trong danh mục văn bản pháp luật.",
                    )
                )
                continue
            expired_on = self._parse(info.get("expired_on") or "")
            if expired_on is not None and expired_on <= self.today:
                replacement = ""
                repl = self.sources.get(info.get("replaced_by") or "")
                if repl:
                    replacement = self.describe(info["replaced_by"])
                issues.append(
                    CitationIssue(
                        source_id=sid,
                        kind="outdated",
                        message=(
                            f"{self.describe(sid)} đã hết hiệu lực từ "
                            f"{info['expired_on']} và không được dùng để trả lời."
                        ),
                        replacement=replacement,
                    )
                )
                continue
            elif sid not in retrieved_sources:
                issues.append(
                    CitationIssue(
                        source_id=sid,
                        kind="unsupported",
                        message=(
                            f"Trích dẫn {self.describe(sid)} không nằm trong "
                            "nguồn đã truy xuất cho câu hỏi này."
                        ),
                    )
                )
                continue
            # Valid current citation
            valid_citations += 1
        # If no citations at all, pass (no citations to validate).
        # If citations exist, require at least one valid current citation.
        ok = (total_citations == 0) or (valid_citations > 0)
        return CitationVerdict(ok=ok, issues=issues)
