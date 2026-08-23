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
import re
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
        # User-supplied documents are registered separately; accept them as
        # valid citation targets without polluting the curated law registry.
        user_registry = self.status_path.parent / "user_registry.json"
        if user_registry.exists():
            try:
                udata = json.loads(user_registry.read_text(encoding="utf-8"))
                for sid, info in (udata.get("sources") or {}).items():
                    self.sources.setdefault(sid, info)
            except (ValueError, OSError):
                pass

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
        # If citations exist, require ALL citations to be valid current citations.
        ok = (total_citations == 0) or (valid_citations == total_citations)
        return CitationVerdict(ok=ok, issues=issues)

    def validate_claims(
        self,
        answer: GroundedAnswer,
        retrieved_sources: Optional[set[str]] = None,
    ) -> CitationVerdict:
        """Validate that critical claims in answer are supported by evidence.
        
        Extracts claims with numbers, dates, ages, percentages, agencies, articles
        and verifies they appear in the cited source chunks.
        """
        retrieved_sources = retrieved_sources or set()
        issues: list = []
        
        # Extract critical claims from answer_text
        claims = self._extract_critical_claims(answer.answer_text)
        
        # Get full text of retrieved chunks for claim verification
        # This would need access to chunk texts - for now check source-level
        for claim in claims:
            claim_supported = False
            for sid in retrieved_sources:
                info = self.sources.get(sid)
                if info and "text" in info:
                    if self._claim_in_source(claim, info["text"]):
                        claim_supported = True
                        break
            if not claim_supported and claim.get("required", True):
                issues.append(
                    CitationIssue(
                        source_id="claim_verification",
                        kind="unsupported_claim",
                        message=f"Claim not supported by retrieved evidence: {claim['text']}",
                    )
                )
        
        ok = len([i for i in issues if i.kind == "unsupported_claim"]) == 0
        return CitationVerdict(ok=ok, issues=issues)
    
    def _extract_critical_claims(self, text: str) -> list[dict]:
        """Extract critical claims that need evidence support."""
        claims = []
        text_lower = text.casefold()
        
        # Money amounts
        for match in re.finditer(r"(\d+(?:[.,]\d+)?)\s*(triệu|nghìn|đồng|vnd)", text_lower):
            claims.append({
                "type": "amount",
                "text": match.group(0),
                "value": match.group(1),
                "unit": match.group(2),
                "required": True,
            })
        
        # Ages
        for match in re.finditer(r"(\d+)\s*tuổi", text_lower):
            claims.append({
                "type": "age",
                "text": match.group(0),
                "value": match.group(1),
                "required": True,
            })
        
        # Percentages
        for match in re.finditer(r"(\d+(?:[.,]\d+)?)\s*%", text_lower):
            claims.append({
                "type": "percentage",
                "text": match.group(0),
                "value": match.group(1),
                "required": True,
            })
        
        # Deadlines (days/months/years)
        for match in re.finditer(r"(\d+)\s*(ngày|tháng|năm)", text_lower):
            if any(kw in text_lower for kw in ["thời hạn", "giải quyết", "bảo lưu", "chờ"]):
                claims.append({
                    "type": "deadline",
                    "text": match.group(0),
                    "value": match.group(1),
                    "unit": match.group(2),
                    "required": True,
                })
        
        # Legal articles
        for match in re.finditer(r"điều\s+(\d+[a-z]?)", text_lower):
            claims.append({
                "type": "article",
                "text": f"Điều {match.group(1)}",
                "value": match.group(1),
                "required": True,
            })
        
        return claims
    
    def _claim_in_source(self, claim: dict, source_text: str) -> bool:
        """Check if claim appears in source text (simplified)."""
        source_lower = source_text.casefold()
        claim_text = claim["text"].casefold()
        
        # For amounts, check if the number appears with same unit
        if claim["type"] == "amount":
            return claim["value"] in source_lower and claim["unit"] in source_lower
        if claim["type"] == "age":
            return claim["value"] in source_lower and "tuổi" in source_lower
        if claim["type"] == "percentage":
            return claim["value"] in source_lower and "%" in source_lower
        if claim["type"] == "deadline":
            return claim["value"] in source_lower and claim["unit"] in source_lower
        if claim["type"] == "article":
            return claim["text"].lower() in source_lower
        
        return claim_text in source_lower
