"""Core data schemas (standard library dataclasses).

All pipeline data flows through these types. Keeping them dependency-free
means the mock vertical slice has zero third-party requirements.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional


class Zone(str, Enum):
    YELLOW = "YELLOW"
    ORANGE = "ORANGE"
    RED = "RED"


class Action(str, Enum):
    ANSWER = "ANSWER"
    CLARIFY = "CLARIFY"
    GUIDE = "GUIDE"
    REFUSE = "REFUSE"
    ESCALATE = "ESCALATE"


class ReasonCode(str, Enum):
    EMERGENCY_SIGNAL = "EMERGENCY_SIGNAL"
    VIOLENCE_OR_THREAT = "VIOLENCE_OR_THREAT"
    CRIMINAL_MATTER = "CRIMINAL_MATTER"
    LEGAL_JUDGMENT_REQUEST = "LEGAL_JUDGMENT_REQUEST"
    FAKE_LAW_REFERENCE = "FAKE_LAW_REFERENCE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    INSUFFICIENT_SOURCE = "INSUFFICIENT_SOURCE"
    AMBIGUOUS_QUERY = "AMBIGUOUS_QUERY"
    SAFE_GROUNDED_QUERY = "SAFE_GROUNDED_QUERY"
    LLM_CLASSIFICATION = "LLM_CLASSIFICATION"
    SYSTEM_ERROR = "SYSTEM_ERROR"
    CITATION_UNSUPPORTED = "CITATION_UNSUPPORTED"
    CITATION_OUTDATED = "CITATION_OUTDATED"


@dataclass(frozen=True)
class SourceMetadata:
    source_id: str
    title: str
    source_type: str  # e.g. "gov_procedure", "gov_faq", "demo"
    publisher: str
    published_date: str = ""
    language: str = "vi"
    license: str = ""
    is_demo: bool = False
    url: str = ""
    notes: str = ""


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    source_id: str
    text: str
    score: float
    metadata: Optional[SourceMetadata] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "source_id": self.source_id,
            "text": self.text,
            "score": round(self.score, 4),
            "metadata": asdict(self.metadata) if self.metadata else None,
        }


@dataclass(frozen=True)
class UserQuery:
    text: str
    normalized_text: str = ""
    session_id: str = ""
    timestamp: str = ""
    audio_path: Optional[str] = None


@dataclass(frozen=True)
class SafetyDecision:
    zone: Zone
    action: Action
    reason_codes: list[str] = field(default_factory=list)
    user_message: str = ""
    requires_human: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "zone": self.zone.value,
            "action": self.action.value,
            "reason_codes": list(self.reason_codes),
            "user_message": self.user_message,
            "requires_human": self.requires_human,
        }


@dataclass(frozen=True)
class GroundedAnswer:
    answer_text: str
    spoken_citation: str = ""
    source_ids: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    next_step: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer_text": self.answer_text,
            "spoken_citation": self.spoken_citation,
            "source_ids": list(self.source_ids),
            "limitations": list(self.limitations),
            "next_step": self.next_step,
        }


@dataclass(frozen=True)
class PipelineResult:
    session_id: str
    query: str
    normalized_query: str = ""
    decision: SafetyDecision = field(
        default_factory=lambda: SafetyDecision(zone=Zone.YELLOW, action=Action.CLARIFY)
    )
    answer: Optional[GroundedAnswer] = None
    chunks: list[RetrievedChunk] = field(default_factory=list)
    latencies_ms: dict[str, float] = field(default_factory=dict)
    app_mode: str = "mock"
    tts_output: str = ""
    faq_answered: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "query": self.query,
            "normalized_query": self.normalized_query,
            "decision": self.decision.to_dict(),
            "answer": self.answer.to_dict() if self.answer else None,
            "chunks": [c.to_dict() for c in self.chunks],
            "latencies_ms": {k: round(v, 1) for k, v in self.latencies_ms.items()},
            "app_mode": self.app_mode,
            "tts_output": self.tts_output,
            "faq_answered": self.faq_answered,
        }


@dataclass(frozen=True)
class EvaluationRecord:
    session_id: str
    query: str
    zone: str
    action: str
    latency_ms: float = 0.0
    score: float = 0.0
    notes: str = ""
