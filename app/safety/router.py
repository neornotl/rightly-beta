"""Hybrid safety router.

Order of checks (rule-based FIRST, LLM classification OPTIONAL last):

1. Emergency / violence signals (RED) — run BEFORE any LLM call.
2. Legal-judgment requests (ORANGE/GUIDE).
3. Out-of-scope topics (ORANGE/GUIDE).
4. Retrieval sufficiency (no answer if below MIN_RETRIEVAL_SCORE or empty).
5. Ambiguity check.
6. Optional structured LLM classification (cloud mode only).
7. Conservative fallback: anything unresolved becomes CLARIFY/REFUSE, never a
   confident answer without evidence.

The LLM never decides routing alone: rule hits always take precedence.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Optional

from app.config import Settings
from app.safety.policy import Policy
from app.safety.rules import (
    RuleHits,
    check_rules,
    has_danger_context,
    has_legal_info_intent,
    has_procedural_intent,
    is_soft_topic_emergency,
    normalize_query,
)
from app.schemas import RetrievedChunk, SafetyDecision, Zone

_CITED_DECREE_RE = re.compile(
    r"(?:nghị\s+định|nđ|thông\s+tư|tt|quyết\s+định|luật)\s*(?:số|so)?\s*(\d{1,4})/(20\d\d)",
    re.IGNORECASE,
)


class SafetyRouter:
    def __init__(
        self,
        settings: Optional[Settings] = None,
        policy: Optional[Policy] = None,
        min_score: Optional[float] = None,
    ):
        self.settings = settings or Settings()
        self.policy = policy or Policy()
        self.min_score = min_score if min_score is not None else self.settings.min_retrieval_score
        self._registry: frozenset[str] | None = None

    def _load_registry(self) -> frozenset[str]:
        """Verified legal citations from data/law_status.json, e.g. {"158/2025"}."""
        if self._registry is not None:
            return self._registry
        symbols: set[str] = set()
        status_path = Path(self.settings.data_dir) / "law_status.json"
        if status_path.exists():
            try:
                payload = json.loads(status_path.read_text(encoding="utf-8"))
                for info in payload.get("sources", {}).values():
                    ky_hieu = info.get("ky_hieu", "")
                    m = re.match(r"(\d+)/(20\d\d)", ky_hieu)
                    if m:
                        symbols.add(f"{int(m.group(1))}/{m.group(2)}")
            except (OSError, ValueError):
                pass
        self._registry = frozenset(symbols)
        return self._registry

    def _has_unverifiable_citation(self, query: str) -> bool:
        """True when the query cites at least one law not in the verified registry.

        Citations in canonical National-Assembly form (X/YYYY/QH##) with a
        plausible year are treated as legitimate cross-references; anything
        else outside the registry is flagged as unverifiable.
        """
        registry = self._load_registry()
        citations = _CITED_DECREE_RE.findall(query)
        if not citations:
            return False
        for num, year in citations:
            key = f"{int(num)}/{year}"
            if key in registry:
                continue
            if int(year) <= 2026 and re.search(
                rf"{re.escape(key)}/(?:QH\d+|NĐ-CP|TT\b)", query, re.IGNORECASE
            ):
                continue
            return True
        return False

    def _has_verified_citation(self, query: str) -> bool:
        """True when the query cites at least one law present in the registry.

        Recognizes both canonical ("NĐ số 51/2010", "luật 64/2025") and the
        compact no-diacritic dataset forms ("luat51_2010", "nd64_2025").
        """
        registry = self._load_registry()
        if any(
            f"{int(num)}/{year}" in registry
            for num, year in _CITED_DECREE_RE.findall(query)
        ):
            return True
        return any(
            f"{entries[0]}/{entries[1]}" in registry
            for entries in re.findall(r"(?:luat|nd|nđ|tt)(\d+)_(20\d\d)", query, re.IGNORECASE)
        )

    def route(
        self,
        raw_query: str,
        chunks: list[RetrievedChunk],
        llm_classifier: Optional[Callable[[str, list[RetrievedChunk]], bool]] = None,
    ) -> tuple[SafetyDecision, str]:
        """Return (decision, normalized_query)."""
        query = normalize_query(raw_query)
        if not query:
            return self.policy.ambiguous_decision(), query

        hits: RuleHits = check_rules(query)

        # Intent guard: a query whose ONLY red signals are soft law-topic
        # keywords (bạo lực / xâm hại / cấp cứu / hỏa hoạn ...) AND that is
        # framed as a legal-information request AND has no victim/danger
        # context is a law-information question, NOT an active emergency.
        # It falls through to ordinary routing below. Hard signals (tự tử,
        # đốt nhà, hack tài khoản, đe dọa...) are never downgraded.
        legal_info_intent = has_legal_info_intent(query) and not has_danger_context(query)
        emergency_is_law_info = (
            is_soft_topic_emergency(hits)
            and legal_info_intent
        )

        # 1. RED rules have highest priority, before any LLM.
        if hits.emergency and not emergency_is_law_info:
            return self.policy.emergency_decision(), query
        if hits.violence and not emergency_is_law_info:
            return self.policy.violence_decision(), query

        # 2. Criminal-matter requests (careful, refer out before any conclusion).
        # Same intent guard: asking ABOUT hình sự/tội phạm as a law topic is a
        # legal-information question, not necessarily a criminal-matter plea.
        if hits.criminal and not legal_info_intent:
            return self.policy.criminal_decision(), query

        # 2.5 Fake / rumored / future-law references — refuse to confirm.
        # Exception: a legal-information question whose citations are ALL in
        # the verified registry is a legitimate cross-reference, not a rumor.
        # A citation mix (real + fake) or any unverifiable citation still
        # refuses (test_fake_law_mixed_real_and_fake_refused).
        unverifiable = self._has_unverifiable_citation(query)
        if (hits.fake_law or unverifiable) and not (
            legal_info_intent
            and not unverifiable
            and self._has_verified_citation(query)
        ):
            return self.policy.fake_law_decision(), query

        # 3. Legal judgment requests. A question that merely asks ABOUT a
        # legal topic/procedure/citation (legal_info_intent) is a normal
        # legal-information request and flows to grounded answering below;
        # a dispute/judgment plea (tranh chấp..., phán quyết...) is guided out.
        if hits.legal and not legal_info_intent:
            return self.policy.legal_decision(), query

        # 4. Out-of-scope. A legal/procedural information question ("Thủ tục
        # quay phim?") should not be rejected merely because it mentions a
        # hobby/entertainment keyword in passing — that is why only STRONG
        # procedural framing ("thủ tục", "quy định", "hồ sơ"...) overrides an
        # out-of-scope topic rule; a bare "là gì/thế nào" does not.
        if hits.out_of_scope and not has_procedural_intent(query):
            return self.policy.out_of_scope_decision(), query

        # 5. Retrieval sufficiency.
        sufficient = [c for c in chunks if c.score >= self.min_score]
        if not sufficient:
            return self.policy.insufficient_decision(), query

        # 6. Ambiguity heuristics.
        if hits.ambiguous and not chunks:
            return self.policy.ambiguous_decision(), query
        if len(hits.ambiguous) >= 2:
            return self.policy.ambiguous_decision(), query

        # 7. Optional structured LLM classification (only when provided).
        if llm_classifier is not None:
            try:
                safe = llm_classifier(query, sufficient)
            except Exception:
                safe = False  # conservative: on failure, do not auto-answer
            if not safe:
                return self.policy.ambiguous_decision(), query
            return self.policy.safe_decision(llm_reasoned=True), query

        # 8. Conservative fallback: grounded safe answer.
        return self.policy.safe_decision(llm_reasoned=False), query

    def would_answer(self, decision: SafetyDecision) -> bool:
        """True when the pipeline may produce a grounded spoken answer."""
        return decision.zone == Zone.YELLOW and decision.action.value == "ANSWER"
