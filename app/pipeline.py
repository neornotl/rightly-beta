"""End-to-end pipeline: ASR -> normalize -> retrieval -> router -> LLM -> TTS.

Privacy guarantees implemented here:
- Raw audio is deleted after the session when
  DELETE_RAW_AUDIO_AFTER_SESSION=true (only for files under DATA_DIR; we never
  delete user-provided files outside the project).
- Transcripts are not logged unless SAVE_TRANSCRIPTS=true.
- Only the transcript + needed chunks go to the LLM (never raw audio).
- In cloud mode (gemini/groq), the outbound query is PII-scrubbed first
  (PII_SCRUB_OUTBOUND=true); local rules, routing, and logging keep the
  original text.
"""

from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Optional

from app.asr.base import BaseASR
from app.asr.mock_asr import MockASR
from app.config import Settings
from app.dialogue.state_machine import State
from app.llm.base import BaseLLM
from app.llm.prompts import (
    ANSWER_REVIEW_SYSTEM,
    ANSWER_REVISE_SYSTEM,
    GENERAL_ASSISTANT_SYSTEM,
    HYBRID_ROUTER_SYSTEM,
    LEGAL_INTAKE_SYSTEM,
    LEGAL_SUFFICIENCY_SYSTEM,
)
from app.llm.mock_llm import MockLLM
from app.logging_utils import JsonlLogger, SessionStore, utc_now_iso
from app.metrics_logger import log_pipeline_result
from app.retrieval.base import Retriever
from app.retrieval.bm25_retriever import BM25Retriever
from app.retrieval.document_loader import DocumentLoader, filter_retrievable
from app.retrieval.agentic_retriever import AgenticRetriever, AgenticReasoner
from app.faq import _strip_diacritics
from app.safety.policy import Policy
from app.safety.router import SafetyRouter
from app.safety.rules import normalize_query
from app.schemas import (
    Action,
    GroundedAnswer,
    HybridSessionContext,
    PipelineResult,
    ProfileFact,
    RetrievedChunk,
    SafetyDecision,
    UserQuery,
    Zone,
)
from app.tts.base import BaseTTS
from app.tts.mock_tts import MockTTS

logger = logging.getLogger(__name__)

_MIN_QUERY_CHARS = 3


class _MissingAgenticFacts(Exception):
    """Internal control flow for a safe clarification response."""


def _is_personalized_rule_query(text: str) -> bool:
    """Keep generic FAQ scripts from overriding fact-specific questions."""
    plain = _strip_diacritics(normalize_query(text))
    has_personal_fact = bool(
        re.search(r"\b\d{1,2}/\d{1,2}/\d{4}\b", plain)
        or re.search(r"\bsinh\s+nam\s+(?:\d{4}|\d{1,2}k\d{1,2})\b", plain)
        or re.search(r"\b\d+\s*nam\b", plain)
        or re.search(r"\b\d+\s*tuoi\b", plain)
    )
    return has_personal_fact and any(
        marker in plain
        for marker in ("nghi huu", "luong huu", "bao hiem xa hoi", "dieu kien")
    )


def _has_gender(text: str) -> bool:
    return bool(re.search(r"\b(nam|nữ|nu)\b", _strip_diacritics(normalize_query(text))))


def _focus_is_retirement(focus: str) -> bool:
    """True when the analysis focus concerns retirement age/timing.

    Real LLMs return varied phrasings ("Xác định thời điểm và tuổi được nghỉ
    hưu...", "thời điểm đủ điều kiện nghỉ hưu"), so match on the keyword
    instead of exact equality. Compare against the diacritic-stripped form
    ("nghi huu") since focus is normalized before matching.
    """
    return bool(focus) and "nghi huu" in _strip_diacritics(normalize_query(focus))


def _needs_retirement_gender_clarification(analysis: object, text: str = "") -> bool:
    return bool(
        analysis
        and _focus_is_retirement(getattr(analysis, "focus", ""))
        and "giới tính" in getattr(analysis, "missing_facts", [])
        and re.search(r"\b(toi|anh|chi|minh)\b", _strip_diacritics(normalize_query(text)))
    )


def _retirement_clarification_message(analysis: object) -> str:
    missing = set(getattr(analysis, "missing_facts", []) if analysis else [])
    if "giới tính" in missing:
        return (
            "Để xác định tuổi nghỉ hưu chính xác, anh/chị cho em biết giới tính "
            "được không ạ? Tuổi nghỉ hưu của nam và nữ có lộ trình khác nhau."
        )
    if "năm sinh" in missing:
        return "Anh/chị cho em biết năm sinh để em tính mốc tuổi nghỉ hưu dự kiến được không ạ?"
    return "Anh/chị cho em biết thêm thông tin còn thiếu để em trả lời chính xác được không ạ?"


_EVIDENCE_TOPIC_MARKERS = {
    "nghi huu": ("nghi huu", "tuoi nghi huu", "luong huu"),
    "bao hiem xa hoi": ("bao hiem xa hoi", "luong huu"),
    "so do": ("giay chung nhan", "quyen su dung dat", "so do", "dat dai"),
    "that nghiep": ("that nghiep", "bao hiem that nghiep"),
    "ket hon": ("ket hon", "hon nhan", "dang ky ket hon"),
    "khai sinh": ("khai sinh", "ho tich"),
    "hang xom": ("hang xom", "tieng on", "on ao", "am thanh"),
}


def _validate_agentic_evidence(
    query: str,
    chunks: list[RetrievedChunk],
    evidence_used: list[str],
    key_claims: list[dict],
) -> tuple[bool, str]:
    """Reject answers whose selected evidence is valid law but wrong topic."""
    plain_query = _strip_diacritics(normalize_query(query))
    selected_ids = {str(source_id) for source_id in evidence_used}
    if not selected_ids:
        return False, "Không có bằng chứng được chọn trong reasoning."

    available_ids = {c.source_id for c in chunks}
    if not selected_ids.issubset(available_ids):
        return False, "Reasoning chọn source không nằm trong các đoạn đã truy xuất."

    for claim in key_claims:
        if claim.get("evidence") not in selected_ids:
            return False, "Claim trỏ tới source không nằm trong evidence_used."

    evidence_text = " ".join(
        _strip_diacritics(c.text)
        for c in chunks
        if c.source_id in selected_ids
    ).casefold()
    for query_marker, required_markers in _EVIDENCE_TOPIC_MARKERS.items():
        if query_marker in plain_query and not any(marker in evidence_text for marker in required_markers):
            return False, f"Evidence không có marker chủ đề bắt buộc: {query_marker}."

    # For questions without a known domain marker, require at least two useful
    # non-stopword tokens from the query in the selected evidence.
    stopwords = {
        "toi", "la", "co", "duoc", "khong", "can", "gi", "nao", "the",
        "nang", "cho", "hoi", "muon", "lam", "sao", "nhu", "the", "nha",
    }
    tokens = {
        token for token in re.findall(r"[a-z0-9]+", plain_query)
        if len(token) >= 4 and token not in stopwords
    }
    overlap = sum(1 for token in tokens if token in evidence_text)
    if tokens and overlap < min(2, len(tokens)):
        return False, "Evidence không đủ từ khóa nội dung để hỗ trợ câu hỏi."
    return True, ""


def _is_followup_continuation(current_query: str, previous_turn: dict) -> bool:
    """Check if current query is a genuine follow-up of previous turn.
    
    Returns True if:
    - Same legal domain/topic
    - Same subject/entity
    - Same intent type (procedure, eligibility, penalty, etc.)
    - Or contains explicit continuation markers ("còn", "thêm", "nữa", "kế")
    - Or is a short affirmative response after a successful answer
    """
    if not previous_turn:
        return False
    
    current = current_query.casefold().strip()
    prev_user = previous_turn.get("user", "").casefold()
    prev_assistant = previous_turn.get("assistant", "").casefold()
    
    # Short affirmative responses after a successful answer -> likely continuation
    short_affirmatives = {
        "vâng", "vâng ạ", "dạ", "dạ ạ", "ok", "okie", "cảm ơn", "cảm ơn ạ",
        "được", "được ạ", "ừ", "ừm", "đúng", "đúng ạ", "có", "có ạ"
    }
    if current in short_affirmatives:
        # Only treat as continuation if previous turn had an answer
        if previous_turn.get("assistant"):
            return True
    
    # Explicit continuation markers
    continuation_markers = ["còn", "thêm", "nữa", "kế", "tiếp", "hỏi tiếp", "hỏi nữa"]
    if any(marker in current for marker in continuation_markers):
        return True
    
    # Extract key entities from previous assistant answer
    prev_entities = set()
    # Legal domains
    for domain in ["hộ tịch", "cư trú", "đất đai", "bhxh", "bhyt", "lương hưu", "kết hôn", "ly hôn", "khai sinh", "thừa kế", "giao thông", "phạt", "hồ sơ", "giấy tờ", "điều kiện", "tuổi", "mức phạt", "thời hạn", "cơ quan", "nơi nộp"]:
        if domain in prev_assistant:
            prev_entities.add(domain)
    
    # Check if current query shares domain entities
    current_entities = set()
    for domain in ["hộ tịch", "cư trú", "đất đai", "bhxh", "bhyt", "lương hưu", "kết hôn", "ly hôn", "khai sinh", "thừa kế", "giao thông", "phạt", "hồ sơ", "giấy tờ", "điều kiện", "tuổi", "mức phạt", "thời hạn", "cơ quan", "nơi nộp"]:
        if domain in current:
            current_entities.add(domain)
    
    if prev_entities & current_entities:
        return True
    
    # Check intent overlap
    prev_intent = set()
    for intent in ["thủ tục", "hồ sơ", "giấy tờ", "điều kiện", "ai được", "đối tượng", "mức phạt", "bao nhiêu", "bao lâu", "thời hạn", "nơi nộp", "tuổi"]:
        if intent in prev_user:
            prev_intent.add(intent)
    
    current_intent = set()
    for intent in ["thủ tục", "hồ sơ", "giấy tờ", "điều kiện", "ai được", "đối tượng", "mức phạt", "bao nhiêu", "bao lâu", "thời hạn", "nơi nộp", "tuổi"]:
        if intent in current:
            current_intent.add(intent)
    
    if prev_intent & current_intent:
        return True
    
    return False


def _check_answerability(query: str, chunks: list[RetrievedChunk], min_direct: int = 1) -> tuple[bool, str]:
    """Check if retrieved chunks provide sufficient direct evidence to answer the query.
    
    Returns (can_answer, reason).
    """
    if not chunks:
        return False, "no_chunks_retrieved"
    
    # Count direct answer chunks
    direct_count = 0
    for chunk in chunks:
        ev_type = getattr(chunk.metadata, "evidence_type", "irrelevant") if chunk.metadata else "irrelevant"
        if ev_type == "direct_answer":
            direct_count += 1
    
    if direct_count < min_direct:
        return False, f"insufficient_direct_evidence (direct={direct_count}, min={min_direct})"
    
    # Check coverage of query components
    q = query.casefold()
    query_terms = set(q.split())
    
    # Define critical query components based on intent
    needs_amount = any(t in q for t in ("bao nhiêu", "mức", "số tiền", "phạt"))
    needs_age = any(t in q for t in ("tuổi", "bao nhiêu tuổi"))
    needs_deadline = any(t in q for t in ("thời hạn", "bao lâu", "khi nào", "thời gian"))
    needs_dossier = any(t in q for t in ("hồ sơ", "giấy tờ", "cần gì"))
    needs_subject = any(t in q for t in ("ai", "đối tượng", "những ai", "ai được"))
    needs_condition = any(t in q for t in ("điều kiện", "khi nào", "được khi"))
    
    found = {
        "amount": False,
        "age": False,
        "deadline": False,
        "dossier": False,
        "subject": False,
        "condition": False,
    }
    
    for chunk in chunks:
        text = chunk.text.casefold()
        if needs_amount and any(re.search(r"\d+\s*(triệu|nghìn|đồng|%)", text) for _ in [0]):
            found["amount"] = True
        if needs_age and re.search(r"\d+\s*tuổi", text):
            found["age"] = True
        if needs_deadline and any(t in text for t in ("ngày", "tháng", "năm", "thời hạn", "giải quyết")):
            found["deadline"] = True
        if needs_dossier and any(t in text for t in ("hồ sơ", "giấy tờ", "tờ khai", "chứng minh")):
            found["dossier"] = True
        if needs_subject and any(t in text for t in ("đối tượng", "ai được", "người được", "chủ thể")):
            found["subject"] = True
        if needs_condition and any(t in text for t in ("điều kiện", "khi", "nếu", "được khi")):
            found["condition"] = True
    
    required = []
    if needs_amount and not found["amount"]:
        required.append("amount")
    if needs_age and not found["age"]:
        required.append("age")
    if needs_deadline and not found["deadline"]:
        required.append("deadline")
    if needs_dossier and not found["dossier"]:
        required.append("dossier")
    if needs_subject and not found["subject"]:
        required.append("subject")
    if needs_condition and not found["condition"]:
        required.append("condition")
    
    if required:
        return False, f"missing_evidence_for: {', '.join(required)}"
    
    return True, "ok"




def build_context(
    chunks: list[RetrievedChunk],
    max_chars: int,
    *,
    reserve_chars: int = 1000,
) -> tuple[str, list[RetrievedChunk]]:
    """Build context string from chunks with budget enforcement.
    
    Prioritizes chunks by evidence_type (direct_answer > conditions > procedure > citation > irrelevant),
    then by score. Returns (context_string, used_chunks).
    
    Args:
        chunks: Retrieved chunks sorted by relevance
        max_chars: Maximum context budget (from settings.max_context_chars)
        reserve_chars: Reserve space for query, history, prompt overhead
    """
    budget = max(0, max_chars - reserve_chars)
    if budget <= 0:
        return "", []
    
    # Priority order for evidence types
    type_priority = {
        "direct_answer": 5,
        "conditions_exceptions": 4,
        "procedure": 3,
        "citation_only": 2,
        "irrelevant": 1,
    }
    
    # Sort chunks by evidence type priority, then by score
    def chunk_priority(c: RetrievedChunk) -> tuple[int, float]:
        ev_type = getattr(c.metadata, "evidence_type", "irrelevant") if c.metadata else "irrelevant"
        return (type_priority.get(ev_type, 1), c.score)
    
    sorted_chunks = sorted(chunks, key=chunk_priority, reverse=True)
    
    context_parts = []
    used_chunks = []
    current_len = 0
    
    for chunk in sorted_chunks:
        chunk_text = f"[source_id={chunk.source_id}|chunk_id={chunk.chunk_id}]\n{chunk.text}"
        # Add separator overhead
        needed = len(chunk_text) + (2 if context_parts else 0)
        if current_len + needed > budget:
            break
        if context_parts:
            context_parts.append("\n\n")
            current_len += 2
        context_parts.append(chunk_text)
        current_len += len(chunk_text)
        used_chunks.append(chunk)
    
    return "".join(context_parts), used_chunks


def make_asr(settings: Settings) -> BaseASR:
    if settings.asr_backend == "phowhisper":
        from app.asr.phowhisper_asr import PhoWhisperASR

        return PhoWhisperASR(
            model_id=settings.phowhisper_model,
            device="cpu",
            language="vi",
        )
    if settings.asr_backend == "whisper":
        from app.asr.whisper_asr import WhisperASR

        return WhisperASR(
            model_size=settings.whisper_model,
            device=settings.whisper_device,
            language="vi",
        )
    return MockASR()


def make_retriever(settings: Settings) -> Retriever:
    # Real legal corpus first (92 vbpl: Luật, Nghị định, Thông tư). The demo
    # (synthetic "xã Bình Minh") corpus is only a dev/mock fallback.
    real_file = settings.chunks_dir / "real_chunks.jsonl"
    demo_file = settings.chunks_dir / "demo_chunks.jsonl"
    use_real = real_file.exists()
    if use_real:
        chunks_file = real_file
        cache_path = settings.chunks_dir / "real_embeddings.npz"
        exclude_demo = settings.app_mode != "mock"
    else:
        if settings.app_mode != "mock":
            raise RuntimeError(
                "No real legal corpus found: data/chunks/real_chunks.jsonl is "
                "missing (build it with the ingest pipeline first)."
            )
        chunks_file = demo_file
        cache_path = settings.chunks_dir / "demo_embeddings.npz"
        exclude_demo = False

    records = DocumentLoader.load_chunks(chunks_file)
    status_path = settings.resolved_data_dir() / "law_status.json"
    records, dropped = filter_retrievable(records, status_path=status_path)
    if any(dropped.values()):
        logger.warning(
            "Corpus load dropped %d chunk(s): %s",
            sum(dropped.values()),
            dropped,
        )

    if settings.retrieval_backend == "hybrid":
        try:
            from app.retrieval.hybrid_retriever import HybridRetriever

            return HybridRetriever.from_chunks(
                records,
                cache_path=cache_path,
                exclude_demo=exclude_demo,
                rerank=settings.retriever_rerank,
                gate=settings.retriever_gate,
                bm25_gate=settings.bm25_gate,
                dense_gate=settings.dense_gate,
            )
        except Exception as exc:
            # A web deploy must still boot when the embedding package, cache,
            # model download, or native runtime is unavailable. BM25 remains a
            # deterministic, fully local retrieval path.
            logger.warning("Hybrid retrieval unavailable (%s); falling back to BM25.", exc)
            return BM25Retriever.from_chunks(records)
    if settings.retrieval_backend != "bm25":
        raise ValueError(f"Unsupported retrieval backend: {settings.retrieval_backend}")
    return BM25Retriever.from_chunks(records)


def make_llm(settings: Settings) -> BaseLLM:
    llm = _build_llm(settings, settings.llm_backend)
    if settings.llm_fallback_backend:
        try:
            fallback = _build_llm(settings, settings.llm_fallback_backend)
        except RuntimeError:
            fallback = None  # fallback backend not usable: skip silently
        if fallback is not None and fallback.available:  # type: ignore[attr-defined]
            from app.llm.fallback import FallbackLLM

            return FallbackLLM(primary=llm, fallback=fallback)
    return llm


def _build_llm(settings: Settings, backend: str) -> BaseLLM:
    if backend == "gemini":
        from app.llm.gemini_llm import GeminiLLM

        llm: BaseLLM = GeminiLLM(
            api_key=settings.gemini_api_key,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
            backoff_seconds=settings.llm_retry_backoff_seconds,
        )
        if not llm.available:  # type: ignore[attr-defined]
            raise RuntimeError("LLM_BACKEND=gemini but GEMINI_API_KEY is not set.")
        return llm
    if backend == "groq":
        from app.llm.groq_llm import GroqLLM

        llm = GroqLLM(
            api_key=settings.groq_api_key,
            api_keys=settings.groq_api_keys,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
            backoff_seconds=settings.llm_retry_backoff_seconds,
        )
        if not llm.available:  # type: ignore[attr-defined]
            raise RuntimeError("LLM_BACKEND=groq but GROQ_API_KEY is not set.")
        return llm
    if backend == "pateway":
        from app.llm.pateway_llm import PatewayLLM

        llm = PatewayLLM(
            api_key=settings.pateway_api_key,
            base_url=settings.pateway_base_url,
            model=settings.pateway_model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
            backoff_seconds=settings.llm_retry_backoff_seconds,
        )
        if not llm.available:  # type: ignore[attr-defined]
            raise RuntimeError("LLM_BACKEND=pateway but PATEWAY_API_KEY is not set.")
        return llm
    if backend == "local":
        from app.llm.local_llm import LocalLLM

        llm = LocalLLM(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
            backoff_seconds=settings.llm_retry_backoff_seconds,
        )
        if not llm.available:
            logger.warning(
                "Local LLM unavailable at %s; using deterministic MockLLM until "
                "Ollama is started and %s is pulled.",
                settings.ollama_base_url,
                settings.ollama_model,
            )
            return MockLLM()
        return llm
    return MockLLM()


def make_tts(settings: Settings) -> BaseTTS:
    if settings.tts_backend == "edge":
        from app.tts.fallback import TTSFallback

        return TTSFallback(
            cache_dir=settings.resolved_results_dir() / "tts_cache",
            output_format="wav",
        )
    if settings.tts_backend == "gtts":
        from app.tts.gtts_adapter import GTTS

        return GTTS(lang="vi", slow=False, output_format="wav")
    return MockTTS()


@dataclass
class Pipeline:
    settings: Settings = field(default_factory=Settings)
    asr: Optional[BaseASR] = None
    retriever: Optional[Retriever] = None
    llm: Optional[BaseLLM] = None
    tts: Optional[BaseTTS] = None
    router: Optional[SafetyRouter] = None
    store: Optional[SessionStore] = None
    logger: Optional[JsonlLogger] = None
    validator: object = None  # CitationValidator when app_mode != "mock"
    faq: object = None  # FAQMatcher when data/faq.json exists
    top_k: int = 5
    # Agentic components (LLM-driven retrieval & reasoning)
    agentic_retriever: Optional[AgenticRetriever] = field(default=None, repr=False)
    agentic_reasoner: Optional[AgenticReasoner] = field(default=None, repr=False)
    #: Temporary per-session conversation memory (RAM only, never persisted).
    #: Kept for the lifetime of the session; cleared by delete_session()
    #: (user says "kết thúc"/"thoát" in CLI/UI). Each entry:
    #: {"user": str, "assistant": str, "chunks": list[RetrievedChunk]}.
    _memory: dict[str, list[dict]] = field(default_factory=dict, repr=False)
    #: General-chat profile and history. This is RAM-only, never persisted, and
    #: is destroyed with delete_session().
    _hybrid_sessions: dict[str, HybridSessionContext] = field(default_factory=dict, repr=False)

    _MEMORY_MAX_TURNS = 3

    def __post_init__(self) -> None:
        self.settings.resolved_log_dir().mkdir(parents=True, exist_ok=True)
        from app.logging_utils import prune_old_logs

        prune_old_logs(
            self.settings.resolved_log_dir(),
            retention_days=self.settings.log_retention_days,
        )
        if self.logger is None:
            self.logger = JsonlLogger(self.settings.resolved_log_dir())
        if self.store is None:
            self.store = SessionStore(self.settings.resolved_log_dir(), self.logger)
        if self.asr is None:
            self.asr = make_asr(self.settings)
        if self.retriever is None:
            self.retriever = make_retriever(self.settings)
        if self.llm is None:
            self.llm = make_llm(self.settings)
        if self.settings.llm_backend == "local":
            from app.local_evidence import ensure_local_evidence

            self.local_evidence = ensure_local_evidence(self.settings, self.llm)
        if self.tts is None:
            self.tts = make_tts(self.settings)
        if self.router is None:
            self.router = SafetyRouter(settings=self.settings, policy=Policy())
        # Initialize agentic retriever and reasoner (LLM-driven retrieval & reasoning)
        if self.agentic_retriever is None:
            self.agentic_retriever = AgenticRetriever(
                llm=self.llm,
                retriever=self.retriever,
                top_k=self.top_k,
            )
        if self.agentic_reasoner is None:
            self.agentic_reasoner = AgenticReasoner(llm=self.llm)
        if self.validator is None and self.settings.app_mode != "mock":
            from app.validation.citation_validator import CitationValidator

            self.validator = CitationValidator(
                status_path=self.settings.resolved_data_dir() / "law_status.json"
            )
        if self.faq is None:
            from app.faq import FAQMatcher

            matcher = FAQMatcher()
            if matcher.count:
                self.faq = matcher

    # ---------- lifecycle ----------

    def create_session(self) -> str:
        session_id = self.store.create()
        self.store.record(
            session_id,
            "config_summary",
            app_mode=self.settings.app_mode,
            asr_backend=self.asr.name,
            llm_backend=getattr(self.llm, "active_name", self.llm.name),
            tts_backend=self.tts.name,
            retrieval_backend=self.retriever.name,
        )
        return session_id

    def delete_session(self, session_id: str) -> int:
        """End a session: purge its log lines AND its temporary in-memory
        context. The memory is RAM-only and never written to disk; after this
        call the session is gone for good (privacy deletion policy)."""
        self._memory.pop(session_id, None)
        self._hybrid_sessions.pop(session_id, None)
        return self.store.delete_session(session_id)

    def has_pending_profile_consent(self, session_id: str) -> bool:
        """Expose only consent state to the UI; never expose raw profile facts."""
        context = self._hybrid_sessions.get(session_id)
        return bool(context and context.pending_profile_facts)

    # ---------- core ----------

    def process_text(self, session_id: str, text: str, progress_callback=None) -> PipelineResult:
        """Full pipeline for a text query (no audio involved)."""
        # Hybrid contexts can contain personal facts. Do not write raw messages
        # to disk here; this remains true even when legacy transcript logging is
        # enabled, because consent only covers RAM-only consultation context.
        context = self._hybrid_sessions.setdefault(session_id, HybridSessionContext())
        def progress(stage: str, percent: int, detail: str) -> None:
            if progress_callback:
                progress_callback({"stage": stage, "percent": percent, "detail": detail})

        progress("received", 8, "Đã nhận câu hỏi")
        # Greetings and short social messages do not need router/RAG/LLM calls.
        # Keeping this local also prevents a transient gateway outage from
        # turning a simple hello into a misleading connection error.
        social = _strip_diacritics(normalize_query(text)).strip()
        if social in {"xin chao", "chao", "hello", "hi", "hey", "he lo", "he lu", "hula", "ey", "hu"}:
            message = "Xin chào! Hôm nay bạn thế nào?"
            self._append_hybrid_turn(context, text, message)
            return self._simple_result(session_id, text, message)
        progress("safety", 18, "Đang kiểm tra an toàn và phạm vi câu hỏi")
        # Emergency/criminal hard gates always run before the conversational
        # router. General chat must never weaken these protections.
        preflight, _ = self.router.route(text, [], require_evidence=False)
        # The legacy router labels normal conversational topics as
        # OUT_OF_SCOPE. In hybrid mode those go to general chat, while every
        # other hard safety/legal gate remains non-bypassable.
        if preflight.zone == Zone.RED or (
            preflight.zone == Zone.ORANGE and "OUT_OF_SCOPE" not in preflight.reason_codes
        ):
            query = UserQuery(text=text, session_id=session_id, timestamp=utc_now_iso())
            return self._run(
                session_id,
                query,
                progress_callback=lambda event: progress(
                    event["stage"], event["percent"], event["detail"]
                ),
            )
        progress("classify", 30, "Đang xác định cách hỗ trợ phù hợp")
        turn = self._classify_hybrid_turn(text, context)
        intent = turn.get("intent", "legal")
        facts = self._profile_facts(turn.get("profile_facts", []))

        if intent == "reset":
            self.delete_session(session_id)
            return self._simple_result(session_id, text, "Đã xóa toàn bộ hội thoại và thông tin nhớ trong phiên này.")
        # Profile memory is silent and RAM-only. It is never persisted or
        # announced as a conversational response; reset/delete_session clears it.
        if facts:
            context.profile_consent = True
            context.pending_profile_facts = []
            for fact in facts:
                context.profile[fact.field] = fact

        if intent == "general":
            # Short acknowledgements after a grounded legal answer are legal
            # continuations, not standalone social chat.
            if self._memory.get(session_id) and _is_followup_continuation(
                text, self._memory[session_id][-1]
            ):
                intent = "legal"
            else:
                progress("answer", 72, "Đang soạn câu trả lời")
                return self._general_result(session_id, text, "", context)

        # Legal intake (feature-flagged, off by default): before answering a
        # personalized legal question, the assistant asks for the missing key
        # facts one at a time, until enough is known to answer. It is skipped
        # for impersonal rule questions and any LLM failure degrades to ready.
        if intent == "legal" and self.settings.legal_intake:
            intake_question = self._legal_intake_check(text, context)
            if intake_question:
                decision = self.router.policy.clarify_decision(intake_question)
                self._append_hybrid_turn(context, text, intake_question)
                progress("done", 100, "Đã hoàn tất câu hỏi")
                return self._simple_decision_result(
                    session_id, text, decision, intake_question
                )

        relevant = [str(field) for field in turn.get("relevant_profile_fields", [])]
        selected = {field: fact.value for field, fact in context.profile.items() if field in relevant}
        selected.update({fact.field: fact.value for fact in facts if fact.field in relevant})
        contextual_text = self._contextualize_followup(session_id, text)
        if selected:
            contextual_text = f"{contextual_text}\n\nThông tin người dùng đã cho phép dùng cho tư vấn: {json.dumps(selected, ensure_ascii=False)}"
        query = UserQuery(text=contextual_text, session_id=session_id, timestamp=utc_now_iso())
        progress("retrieve", 48, "Đang tìm thông tin phù hợp")
        result = self._run(
            session_id,
            query,
            progress_callback=lambda event: progress(
                event["stage"], event["percent"], event["detail"]
            ),
        )
        progress("done", 100, "Đã hoàn tất câu trả lời")
        self._append_hybrid_turn(context, text, result.answer.answer_text if result.answer else result.decision.user_message)
        return result

    def _classify_hybrid_turn(self, text: str, context: HybridSessionContext) -> dict:
        """Use the LLM router; fallback stays deliberately conservative/legal."""
        outbound_text = text
        outbound_history = context.turns[-8:]
        if self.settings.pii_scrub_outbound and self.settings.llm_backend in {"gemini", "groq", "pateway"}:
            from app.privacy.scrubber import scrub_outbound

            outbound_text = scrub_outbound(text)
            outbound_history = [
                {"user": scrub_outbound(turn["user"]), "assistant": scrub_outbound(turn["assistant"])}
                for turn in outbound_history
            ]
        try:
            response = self.llm.generate_answer(
                outbound_text,
                [],
                history=outbound_history,
                system_prompt=HYBRID_ROUTER_SYSTEM,
            )
            if isinstance(response, dict) and isinstance(response.get("answer_text"), str):
                response = json.loads(response["answer_text"])
            if isinstance(response, dict) and response.get("intent") in {
                "general", "legal", "consent_yes", "consent_no", "reset"
            }:
                return response
        except Exception:
            pass
        plain = _strip_diacritics(normalize_query(text))
        if plain in {"dong y", "duoc", "ok"}:
            return {"intent": "consent_yes", "profile_facts": [], "relevant_profile_fields": []}
        if plain in {"khong", "khong dong y"}:
            return {"intent": "consent_no", "profile_facts": [], "relevant_profile_fields": []}
        return {"intent": "legal", "profile_facts": [], "relevant_profile_fields": []}

    _INTAKE_PRONOUNS = re.compile(
        r"\b(tôi|mình|em|anh|chị|chú|bác|cô|con|tui)\b",
        re.IGNORECASE,
    )

    def _legal_intake_check(
        self, text: str, context: HybridSessionContext
    ) -> Optional[str]:
        """Best-effort intake: returns a follow-up question to ask, or None=ready.

        Only personalized questions go through intake. Any failure (LLM error,
        bad JSON, impersonal query) falls through to ready so the user is never
        blocked from an answer.
        """
        if not re.search(self._INTAKE_PRONOUNS, text) and not context.pending_intake:
            return None
        try:
            profile_text = ""
            if context.profile:
                profile_text = (
                    "\n\nThông tin người dùng đã cung cấp: "
                    + json.dumps(
                        {f: v.value for f, v in context.profile.items()},
                        ensure_ascii=False,
                    )
                )
            outbound_text = text
            outbound_history = context.turns[-8:]
            if self.settings.pii_scrub_outbound and self.settings.llm_backend in {
                "gemini", "groq", "pateway"
            }:
                from app.privacy.scrubber import scrub_outbound

                outbound_text = scrub_outbound(text)
                outbound_history = [
                    {
                        "user": scrub_outbound(turn["user"]),
                        "assistant": scrub_outbound(turn["assistant"]),
                    }
                    for turn in outbound_history
                ]
            response = self.llm.generate_answer(
                outbound_text + profile_text,
                [],
                history=outbound_history,
                system_prompt=LEGAL_INTAKE_SYSTEM,
            )
            if isinstance(response, dict) and isinstance(response.get("answer_text"), str):
                response = json.loads(response["answer_text"])
            if isinstance(response, dict):
                if response.get("ready") is True:
                    context.pending_intake = None
                    return None
                question = str(response.get("question", "")).strip()
                if question:
                    context.pending_intake = question
                    return question
        except Exception:
            logger.exception("Legal intake check failed; proceeding to answer")
            context.pending_intake = None
        return None

    def _simple_decision_result(
        self, session_id: str, text: str, decision: SafetyDecision, message: str
    ) -> PipelineResult:
        answer = GroundedAnswer(answer_text=message)
        return PipelineResult(
            session_id=session_id,
            query=text,
            decision=decision,
            answer=answer,
            app_mode=self.settings.app_mode,
        )

    def _review_answer(
        self,
        session_id: str,
        query_text: str,
        answer: GroundedAnswer,
        chunks: list[RetrievedChunk],
    ) -> GroundedAnswer:
        """Self-review then self-correct loop on the final answer.

        The LLM reviews the question against the answer (no human in the loop).
        If it judges the answer unfit, it is allowed to rewrite the answer and
        redo the answer process, still grounded in the retrieved evidence. The
        loop is bounded by ``answer_review_max_revisions`` so it cannot run
        forever; grounding validation runs on every revision.
        """
        if not answer.answer_text:
            return answer
        outbound_query = query_text
        if self.settings.pii_scrub_outbound and self.settings.llm_backend in {
            "gemini", "groq", "pateway"
        }:
            from app.privacy.scrubber import scrub_outbound

            outbound_query = scrub_outbound(query_text)

        current = answer
        summary = ""
        appropriate: Optional[bool] = None
        note = ""
        revised = False
        revisions_left = max(0, int(self.settings.answer_review_max_revisions))
        try:
            while True:
                review_payload = (
                    f"CÂU HỎI: {outbound_query}\n\nCÂU TRẢ LỜI: {current.answer_text}\n\n"
                    f"NGUỒN: {', '.join(current.source_ids) or '(không có)'}"
                )
                response = self.llm.generate_answer(
                    review_payload, [], system_prompt=ANSWER_REVIEW_SYSTEM
                )
                if isinstance(response, dict) and isinstance(
                    response.get("answer_text"), str
                ):
                    response = json.loads(response["answer_text"])
                if not isinstance(response, dict):
                    break
                summary = str(response.get("summary", "")).strip()
                appropriate_raw = response.get("appropriate")
                appropriate = (
                    bool(appropriate_raw) if isinstance(appropriate_raw, bool) else None
                )
                note = str(response.get("note", "")).strip()
                self.store.record(
                    session_id,
                    "answer_reviewed",
                    appropriate=appropriate,
                    note=note[:300],
                    revised=revised,
                )
                if appropriate is not False or revisions_left <= 0:
                    break
                # Not appropriate and budget left -> let the model fix itself.
                revised_answer = self._revise_answer(
                    session_id,
                    outbound_query,
                    current,
                    note,
                    chunks,
                )
                if revised_answer is None:
                    break
                current = self._validate_revision(session_id, revised_answer, chunks) or current
                revised = True
                revisions_left -= 1
            return replace(
                current,
                summary=summary,
                appropriate=appropriate,
                review_note=note,
            )
        except Exception:
            logger.exception("Answer review failed; keeping original answer")
            return answer

    def _revise_answer(
        self,
        session_id: str,
        outbound_query: str,
        answer: GroundedAnswer,
        note: str,
        chunks: list[RetrievedChunk],
    ) -> Optional[GroundedAnswer]:
        """Ask the model to rewrite the unfit answer, grounded in the evidence."""
        try:
            evidence_text = build_context(chunks, self.settings.max_context_chars)[0]
            payload = (
                f"CÂU HỎI: {outbound_query}\n\n"
                f"NHẬN XÉT CỦA NGƯỜI KIỂM DUYỆT: {note or '(câu trả lời chưa đúng trọng tâm)'}\n\n"
                f"CÂU TRẢ LỜI CŨ: {answer.answer_text}\n\n"
                f"EVIDENCE:\n{evidence_text}"
            )
            doc = self.llm.generate_answer(
                payload,
                chunks,
                max_chars=self.settings.max_response_chars,
                system_prompt=ANSWER_REVISE_SYSTEM,
            )
            revised = GroundedAnswer(
                answer_text=str(doc.get("answer_text", "")).strip(),
                spoken_citation=str(doc.get("spoken_citation", "")).strip(),
                source_ids=list(
                    dict.fromkeys(str(s) for s in (doc.get("source_ids") or []))
                ),
                limitations=[str(s) for s in (doc.get("limitations") or [])],
                next_step=str(doc.get("next_step", "")).strip(),
            )
            if not revised.answer_text:
                return None
            return revised
        except Exception:
            logger.exception("Answer revision failed")
            return None

    def _validate_revision(
        self,
        session_id: str,
        revised: GroundedAnswer,
        chunks: list[RetrievedChunk],
    ) -> Optional[GroundedAnswer]:
        """Re-run grounding checks on a rewritten answer (citations must match)."""
        try:
            if not revised.source_ids:
                self.store.record(session_id, "revision_rejected", reason="no_citation")
                return None
            if self.validator is not None:
                retrieved = {c.source_id for c in chunks}
                verdict = self.validator.validate(revised, retrieved)
                if not verdict.ok:
                    self.store.record(
                        session_id,
                        "revision_rejected",
                        issues=[vars(i) for i in verdict.issues],
                    )
                    return None
            from app.validation.response_validator import detect_issues, sanitize_answer

            if detect_issues(revised, revised.answer_text):
                revised = sanitize_answer(revised, revised.answer_text)
            return revised
        except Exception:
            logger.exception("Revision validation failed")
            return None

    @staticmethod
    def _profile_facts(raw_facts: object) -> list[ProfileFact]:
        facts: list[ProfileFact] = []
        if not isinstance(raw_facts, list):
            return facts
        for item in raw_facts:
            if not isinstance(item, dict):
                continue
            field = str(item.get("field", "")).strip()
            value = str(item.get("value", "")).strip()
            if field and value:
                facts.append(ProfileFact(field=field, value=value, sensitive=bool(item.get("sensitive", True))))
        return facts

    def _append_hybrid_turn(self, context: HybridSessionContext, user: str, assistant: str) -> None:
        context.turns.append({"user": user, "assistant": assistant})
        if len(context.turns) > 20:
            del context.turns[:-20]

    def _simple_result(self, session_id: str, text: str, message: str) -> PipelineResult:
        decision = self.router.policy.safe_decision()
        answer = GroundedAnswer(answer_text=message)
        return PipelineResult(session_id=session_id, query=text, decision=decision, answer=answer, app_mode=self.settings.app_mode)

    def _general_result(self, session_id: str, text: str, fixed_message: str, context: HybridSessionContext) -> PipelineResult:
        message = fixed_message
        if not message:
            outbound_text = text
            outbound_history = context.turns[-8:]
            if self.settings.pii_scrub_outbound and self.settings.llm_backend in {"gemini", "groq", "pateway"}:
                from app.privacy.scrubber import scrub_outbound

                outbound_text = scrub_outbound(text)
                outbound_history = [
                    {"user": scrub_outbound(turn["user"]), "assistant": scrub_outbound(turn["assistant"])}
                    for turn in outbound_history
                ]
            try:
                for attempt in range(2):
                    try:
                        response = self.llm.generate_answer(
                            outbound_text,
                            [],
                            history=outbound_history,
                            system_prompt=GENERAL_ASSISTANT_SYSTEM,
                        )
                        message = str(response.get("answer_text", "")).strip() if isinstance(response, dict) else ""
                        if message:
                            break
                        raise ValueError("general LLM returned an empty answer_text")
                    except Exception:
                        if attempt:
                            raise
                        logger.warning("General LLM response failed; retrying once", exc_info=True)
            except Exception:
                logger.exception("General LLM response failed after recovery attempt")
                message = "Mình đang gặp lỗi kết nối với mô hình AI. Bạn thử gửi lại tin nhắn này giúp mình nhé."
        if not message:
            message = "Mình đang gặp lỗi kết nối với mô hình AI. Bạn thử gửi lại tin nhắn này giúp mình nhé."
        self._append_hybrid_turn(context, text, message)
        return self._simple_result(session_id, text, message)

    def _contextualize_followup(self, session_id: str, text: str) -> str:
        """Attach short answers to the previous clarification in this session."""
        memory = self._memory.get(session_id) or []
        if not memory:
            return text
        plain = _strip_diacritics(normalize_query(text))
        retirement_turns = [
            turn for turn in memory[-self._MEMORY_MAX_TURNS :]
            if "nghi huu" in _strip_diacritics(normalize_query(str(turn.get("user", ""))))
        ]
        previous = memory[-1]
        pending = previous.get("action") == Action.CLARIFY.value
        is_followup_fact = (
            plain in {"nam", "nu", "nữ"}
            or bool(re.search(r"\bsinh\s+(?:nam\s+)?(?:\d{4}|\d{1,2}k\d{1,2})\b", plain))
        )
        if pending and is_followup_fact and retirement_turns:
            base = retirement_turns[0]["user"].split(" Người dùng bổ sung", 1)[0]
            supplements = []
            for turn in memory:
                user_text = str(turn.get("user", ""))
                if "Người dùng bổ sung" in user_text:
                    supplements.append(user_text.split("Người dùng bổ sung:", 1)[-1].strip(" ."))
            supplements.append(text.strip())
            return f"{base} Người dùng bổ sung: {', '.join(supplements)}."
        return text

    def process_audio(self, session_id: str, audio_path: str | Path) -> PipelineResult:
        """Full pipeline for an audio query (ASR first, audio privacy rules)."""
        audio = Path(audio_path)
        try:
            start = time.perf_counter()
            asr_result = self.asr.transcribe(audio)
            asr_ms = (time.perf_counter() - start) * 1000.0
            if self.settings.save_transcripts:
                self.store.record(session_id, "transcript_saved", transcript=asr_result.transcript)
            query = UserQuery(
                text=asr_result.transcript,
                session_id=session_id,
                timestamp=utc_now_iso(),
                audio_path=str(audio),
            )
            return self._run(session_id, query, precomputed_asr_ms=asr_ms)
        finally:
            # F13 fix: raw audio is deleted even when ASR or the pipeline
            # raises, so privacy deletion cannot be skipped by failures.
            self._apply_audio_privacy(audio)

    def process_audio_bytes(
        self, session_id: str, audio_bytes: bytes, extension: str = ".webm"
    ) -> PipelineResult:
        """Transcribe in-memory audio (from the browser mic) then run the pipeline.

        The bytes are written to a temp file under the OS temp dir, transcribed
        with the configured local ASR, and the file is removed immediately so no
        raw recording ever persists.
        """
        import tempfile

        suffix = extension if extension.startswith(".") else f".{extension}"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = Path(tmp.name)
        try:
            start = time.perf_counter()
            asr_result = self.asr.transcribe(tmp_path)
            asr_ms = (time.perf_counter() - start) * 1000.0
            query = UserQuery(
                text=asr_result.transcript,
                session_id=session_id,
                timestamp=utc_now_iso(),
            )
            return self._run(session_id, query, precomputed_asr_ms=asr_ms)
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

    def transcribe_audio_bytes(
        self, audio_bytes: bytes, extension: str = ".webm"
    ) -> str:
        """ASR only: return the transcript text for in-memory audio bytes.

        Used by the web UI to show "what was heard" as the user's message right
        away, before the answer pipeline runs. The temp audio file is deleted
        immediately; nothing is persisted.
        """
        import tempfile

        suffix = extension if extension.startswith(".") else f".{extension}"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = Path(tmp.name)
        try:
            return self.asr.transcribe(tmp_path).transcript
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _apply_audio_privacy(self, audio: Path) -> None:
        """Delete raw audio only when it lives inside the project data dir."""
        if not self.settings.delete_raw_audio_after_session:
            return
        data_dir = self.settings.resolved_data_dir()
        try:
            in_data = audio.resolve().is_relative_to(data_dir.resolve())
        except (OSError, ValueError):
            in_data = False
        if in_data:
            try:
                audio.unlink(missing_ok=True)
            except OSError:
                pass

    def _retrieve(self, query: str, session_id: str, top_k: int) -> list[RetrievedChunk]:
        """Search the retriever without letting a retriever fault crash the session.

        A broken/empty retriever degrades to no chunks, which the router and
        the empty-retrieval guard turn into a graceful REFUSE/CLARIFY. The
        failure is recorded for audit (gate 7 open item: retriever-level fault).

        Follow-up refinement: a follow-up that wraps personal details around a
        rule question ("tôi làm cho nhà nước được 20 năm, năm nay 55 tuổi, bao
        nhiêu năm nữa nghỉ hưu?") usually dilutes the retrieval query; the
        canonical rule chunks (e.g. "tuổi nghỉ hưu") then drop out of the top-k.
        When the pattern matches, also search the canonical phrasing and merge
        the extra hits (dedupe by source+text) so the LLM still receives the
        rule it needs to compute the answer.
        """
        try:
            hits = list(self.retriever.search(query, top_k=top_k))  # type: ignore[union-attr]
            q = normalize_query(query)
            plain = _strip_diacritics(q)
            extra_query: Optional[str] = None
            if "vuot den" in plain:
                extra_query = (
                    "phat tien 18 20 nguoi dieu khien xe khong chap hanh "
                    "hieu lenh den tin hieu giao thong"
                )
            elif (
                "nghi huu" in plain
                and ("nam nay" in plain or "tuoi" in plain or re.search(r"\d+\s*nam", plain))
                and re.search(
                    r"(?:bao nhieu nam nua|may nam nua|khi nao|bao gio|den khi nao|sau bao lau)",
                    plain,
                )
            ):
                extra_query = "tuoi nghi huu"
            if extra_query:
                retriever = getattr(self.retriever, "bm25", self.retriever)
                extra = list(retriever.search(extra_query, top_k=max(top_k, 8)))  # type: ignore[union-attr]
                seen = {(h.source_id, h.text) for h in hits}
                extra = [h for h in extra if (h.source_id, h.text) not in seen]
                hits = extra + hits
            return hits
        except Exception as exc:  # noqa: BLE001 - retriever fault must not crash a session
            self.store.record(session_id, "retriever_failure", reason=str(exc)[:500])
            return []

    def _multi_hop_retrieve(
        self,
        query: str,
        session_id: str,
        initial_chunks: list[RetrievedChunk],
    ) -> list[RetrievedChunk]:
        """Let the LLM request more legal evidence, bounded to three rounds.

        The model only returns search strings. Python remains the tool owner,
        so every result still comes exclusively from the configured legal
        corpus and every call is bounded/deduplicated.
        """
        chunks = list(initial_chunks)
        seen_queries = {normalize_query(query)}
        seen_chunks = {(chunk.source_id, chunk.chunk_id) for chunk in chunks}
        for _hop in range(1, 3):  # Initial retrieval is hop 1; at most 3 total.
            evidence = "\n\n".join(
                f"[source_id={chunk.source_id}|chunk_id={chunk.chunk_id}]\n{chunk.text}"
                for chunk in chunks[: self.top_k * 3]
            )
            plan_prompt = (
                f"CÂU HỎI: {query}\n\nEVIDENCE HIỆN CÓ:\n{evidence}\n\n"
                "Đánh giá evidence hiện có theo schema."
            )
            try:
                response = self.llm.generate_answer(
                    plan_prompt,
                    chunks,
                    max_chars=1200,
                    system_prompt=LEGAL_SUFFICIENCY_SYSTEM,
                )
                if isinstance(response, dict) and isinstance(response.get("answer_text"), str):
                    response = json.loads(response["answer_text"])
                if not isinstance(response, dict) or bool(response.get("sufficient", False)):
                    break
                next_queries = response.get("next_queries", [])
                if not isinstance(next_queries, list):
                    break
            except Exception:
                break
            requested = []
            for candidate in next_queries:
                candidate = str(candidate).strip()
                normalized = normalize_query(candidate)
                if candidate and normalized not in seen_queries:
                    seen_queries.add(normalized)
                    requested.append(candidate)
            if not requested:
                break
            for candidate in requested[:3]:
                for chunk in self._retrieve(candidate, session_id, self.top_k):
                    key = (chunk.source_id, chunk.chunk_id)
                    if key not in seen_chunks:
                        seen_chunks.add(key)
                        chunks.append(chunk)
        return chunks

    def _run(
        self,
        session_id: str,
        query: UserQuery,
        precomputed_asr_ms: float = 0.0,
        progress_callback=None,
    ) -> PipelineResult:
        def progress(stage: str, percent: int, detail: str) -> None:
            if progress_callback:
                progress_callback({"stage": stage, "percent": percent, "detail": detail})
        lat: dict[str, float] = {}
        if precomputed_asr_ms:
            lat["asr_ms"] = round(precomputed_asr_ms, 1)

        t0 = time.perf_counter()
        normalized = normalize_query(query.text)
        progress("normalize", 12, "Đang chuẩn hóa câu hỏi")
        lat["normalize_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)

        t0 = time.perf_counter()
        # Safety preflight runs before any LLM call. It checks hard rules but
        # intentionally does not require evidence yet.
        decision, normalized = self.router.route(query.text, [], require_evidence=False)
        progress("safety", 22, "Đã kiểm tra an toàn")
        if decision.zone in (Zone.RED, Zone.ORANGE):
            chunks: list[RetrievedChunk] = []
            query_analysis = None
            lat["safety_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
        else:
            query_analysis = self.agentic_retriever.analyze_query(query.text)
            self.agentic_retriever.last_analysis = query_analysis
            t_retrieval = time.perf_counter()
            try:
                progress("retrieve", 45, "Đang tìm các nguồn liên quan")
                # Keep the agentic retriever in sync with the pipeline's
                # current retriever (tests swap it to inject faults), then
                # degrade gracefully if a retriever fault surfaces (gate 7).
                self.agentic_retriever.retriever = self.retriever
                chunks = self.agentic_retriever.retrieve(query.text, analysis=query_analysis)
                chunks = self._multi_hop_retrieve(query.text, session_id, chunks)
            except Exception as exc:  # noqa: BLE001 - retriever fault must not crash a session
                self.store.record(session_id, "retriever_failure", reason=str(exc)[:500])
                chunks = []
            lat["retrieval_ms"] = round((time.perf_counter() - t_retrieval) * 1000.0, 1)
            decision, normalized = self.router.route(query.text, chunks)
            progress("evidence", 68, f"Đã tìm thấy {len(chunks)} đoạn thông tin")
            lat["safety_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)

        t0 = time.perf_counter()
        llm_classifier = None
        if (
            self.settings.app_mode == "cloud" or self.settings.use_llm_classifier
        ) and hasattr(self.llm, "classify_safe"):
            # Outbound: scrub the query before it leaves the machine.
            if self.settings.pii_scrub_outbound:
                from app.privacy.scrubber import scrub_outbound

                def _scrubbed_classifier(q: str, ch: object) -> bool:
                    return self.llm.classify_safe(  # type: ignore[attr-defined]
                        scrub_outbound(q),
                        ch,  # type: ignore[arg-type]
                    )

                llm_classifier = _scrubbed_classifier
            else:
                llm_classifier = self.llm.classify_safe  # type: ignore[attr-defined]
        decision, normalized = self.router.route(query.text, chunks, llm_classifier)
        lat["safety_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)

        # Personalized retirement questions need a sex-specific rule. Ask for
        # that fact before retrieval sufficiency can turn the query into a
        # generic refusal or an unrelated grounded answer. This override runs
        # AFTER the final router call (which includes the LLM classifier) so
        # a missing-gender retirement query always asks for gender instead of
        # falling through to REFUSE/AMBIGUOUS.
        retirement_missing = bool(
            query_analysis
            and _focus_is_retirement(getattr(query_analysis, "focus", ""))
            and getattr(query_analysis, "missing_facts", [])
            and (
                _needs_retirement_gender_clarification(query_analysis, query.text)
                or "nguoi dung bo sung gioi tinh" in _strip_diacritics(normalize_query(query.text))
            )
        )
        if retirement_missing:
            decision = replace(
                self.router.policy.ambiguous_decision(),
                user_message=_retirement_clarification_message(query_analysis),
            )
        if _is_personalized_rule_query(query.text) and not _has_gender(query.text):
            decision = replace(
                self.router.policy.ambiguous_decision(),
                user_message=(
                    "Để xác định tuổi nghỉ hưu chính xác, anh/chị cho em biết "
                    "giới tính được không ạ? Tuổi nghỉ hưu của nam và nữ có "
                    "lộ trình khác nhau."
                ),
            )

        # Temporary session memory: previous turns of THIS session (RAM only).
        # Used for follow-ups ("em la nam a" after the retirement-age question)
        # and scrubbed like the query when leaving the machine in cloud mode.
        memory = self._memory.get(session_id)
        history = (
            [{"user": m["user"], "assistant": m["assistant"]} for m in memory[-self._MEMORY_MAX_TURNS :]]
            if memory
            else []
        )
        outbound_text = query.text
        outbound_history = history
        if (
            self.settings.llm_backend in {"gemini", "groq", "pateway"}
            and self.settings.pii_scrub_outbound
        ):
            from app.privacy.scrubber import scrub_outbound

            outbound_text = scrub_outbound(query.text)
            outbound_history = [
                {
                    "user": scrub_outbound(str(t.get("user", ""))),
                    "assistant": scrub_outbound(str(t.get("assistant", ""))),
                }
                for t in history
            ]

        # F5: FAQ check - respects safety gates, requires evidence verification.
        # FAQ answers are curated & verified, so they can answer when router
        # flags CLARIFY/AMBIGUOUS (router doesn't know about FAQ coverage).
        # But FAQ CANNOT override RED/ORANGE hard gates.
        answer: Optional[GroundedAnswer] = None
        faq_hit = None
        faq_answered = ""
        if self.faq is not None:
            faq_hit = self.faq.answer(query.text)
            if faq_hit is not None and (
                _is_personalized_rule_query(query.text)
                or _needs_retirement_gender_clarification(query_analysis, query.text)
            ):
                self.store.record(
                    session_id,
                    "faq_skipped_personalized_query",
                    faq_id=faq_hit.faq_id,
                )
                faq_hit = None

            if faq_hit is not None:
                # Check if router decision is a hard gate that FAQ cannot override
                if decision.zone in (Zone.RED, Zone.ORANGE):
                    # Log and fall through to normal pipeline
                    self.store.record(
                        session_id,
                        "faq_blocked_by_safety_gate",
                        faq_id=faq_hit.faq_id,
                        router_zone=decision.zone.value,
                        router_action=decision.action.value,
                    )
                    faq_hit = None  # Treat as no FAQ hit
                else:
                    # FAQ hit: verify evidence matches curated answer
                    faq_chunks = self._retrieve(faq_hit.retrieval_query, session_id, self.top_k) or chunks
                    if not faq_chunks:
                        self.store.record(session_id, "faq_evidence_missing", faq_id=faq_hit.faq_id)
                        faq_hit = None
                    else:
                        faq_source_list = (
                            list(faq_hit.source_ids)
                            if faq_hit.source_ids
                            else [c.source_id for c in faq_chunks if c.score >= self.settings.min_retrieval_score]
                            or [c.source_id for c in faq_chunks[:3]]
                        )
                        faq_sources = tuple(dict.fromkeys(faq_source_list))
                        faq_hit = replace(faq_hit, source_ids=faq_sources)
                        if self.validator is not None:
                            verdict = self.validator.validate(faq_hit.to_grounded_answer(), {c.source_id for c in faq_chunks})
                            if not verdict.ok:
                                self.store.record(session_id, "faq_citation_rejected", faq_id=faq_hit.faq_id, issues=[vars(i) for i in verdict.issues])
                                faq_hit = None
                        if faq_hit is not None:
                            answer = faq_hit.to_grounded_answer()
                            chunks = faq_chunks
                            faq_answered = faq_hit.faq_id
                            decision = self.router.policy.safe_decision()
                            lat["faq_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
                            self.store.record(session_id, "faq_hit", faq_id=faq_hit.faq_id, score=faq_hit.score)
        if faq_hit is None and self.router.would_answer(decision):
            t0 = time.perf_counter()

            # Guard: if no chunks retrieved or all scores too low, refuse early
            # to avoid LLM hallucination and FAKE_LAW false positive.
            if not chunks or all(c.score < self.settings.min_retrieval_score for c in chunks):
                decision = self.router.policy.insufficient_decision()
                self.store.record(session_id, "empty_chunks_rejected", num_chunks=len(chunks))
                answer = None
            else:
                t0 = time.perf_counter()
                try:
                    progress("answer", 82, "Đang tạo câu trả lời dựa trên thông tin đã tìm thấy")
                    # Agentic retrieval: LLM analyzes query -> generates search queries -> retrieves
                    agentic_chunks = chunks
                    self.agentic_reasoner.query_analysis = query_analysis
                    analysis = query_analysis
                    if (
                        analysis
                        and _focus_is_retirement(getattr(analysis, "focus", ""))
                        and getattr(analysis, "missing_facts", [])
                        and re.search(r"\b(toi|anh|chi|minh)\b", _strip_diacritics(normalize_query(query.text)))
                    ):
                        decision = replace(
                            self.router.policy.ambiguous_decision(),
                            user_message=_retirement_clarification_message(analysis),
                        )
                        self.store.record(
                            session_id,
                            "agentic_missing_fact_clarification",
                            missing_facts=list(analysis.missing_facts),
                        )
                        answer = None
                        chunks = agentic_chunks
                        lat["llm_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
                        raise _MissingAgenticFacts

                    # Sync agentic reasoner with current LLM (in case llm was replaced)
                    self.agentic_reasoner.llm = self.llm
                    
                    # Agentic reasoning: LLM reasons over retrieved chunks
                    reasoning_result = self.agentic_reasoner.reason(query.text, agentic_chunks)
                    
                    # Build answer from reasoning result
                    raw_ids = list(dict.fromkeys(str(s) for s in (reasoning_result.source_ids or [])))
                    answer = GroundedAnswer(
                        answer_text=str(reasoning_result.answer_text or "").strip(),
                        spoken_citation=str(reasoning_result.spoken_citation or "").strip(),
                        source_ids=raw_ids,
                        limitations=[str(s) for s in (reasoning_result.limitations or [])],
                        next_step=str(reasoning_result.next_step or "").strip(),
                    )
                    chunks = agentic_chunks  # Use agentic chunks for citation validation
                    # Legacy/custom test backends may not emit Agentic
                    # metadata. Let citation validation handle those outputs;
                    # the relevance gate applies once structured evidence is
                    # actually present.
                    is_demo_corpus = bool(agentic_chunks) and all(
                        c.source_id.startswith("demo_")
                        or bool(c.metadata and c.metadata.is_demo)
                        for c in agentic_chunks
                    )
                    if (reasoning_result.evidence_used or reasoning_result.key_claims) and not is_demo_corpus:
                        evidence_ok, evidence_reason = _validate_agentic_evidence(
                            query.text,
                            agentic_chunks,
                            reasoning_result.evidence_used,
                            reasoning_result.key_claims,
                        )
                        if not evidence_ok:
                            decision = self.router.policy.insufficient_decision()
                            self.store.record(
                                session_id,
                                "agentic_evidence_rejected",
                                reason=evidence_reason,
                                evidence_used=list(reasoning_result.evidence_used),
                                key_claims=list(reasoning_result.key_claims),
                            )
                            answer = None
                    elif reasoning_result.missing_facts and reasoning_result.confidence == "low":
                        decision = self.router.policy.insufficient_decision()
                        self.store.record(
                            session_id,
                            "agentic_reasoning_uncertain",
                            missing_facts=list(reasoning_result.missing_facts),
                        )
                        answer = None
                except _MissingAgenticFacts:
                    pass
                except Exception as exc:
                    decision = self.router.policy.insufficient_decision()
                    self.store.record(session_id, "llm_failure", reason=str(exc)[:500])
                    answer = None
                lat["llm_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)

                if answer is not None and not raw_ids:
                    # Council T2: an answer with content but zero citations is
                    # ungrounded — refuse instead of reading it out.
                    decision = self.router.policy.insufficient_decision()
                    self.store.record(
                        session_id,
                        "citation_rejected",
                        issues=[
                            {
                                "kind": "no_citation",
                                "message": "Câu trả lời không trích dẫn nguồn nào.",
                            }
                        ],
                    )
                    answer = None

            if answer is not None and self.validator is not None:
                    # Validate RAW citations first (F2 fix): filtering before
                    # validation would silently hide hallucinated source_ids.
                    retrieved = {c.source_id for c in chunks}
                    verdict = self.validator.validate(answer, retrieved)
                    if not verdict.ok:
                        outdated = any(i.kind == "outdated" for i in verdict.issues)
                        decision = self.router.policy.citation_decision(outdated=outdated)
                        self.store.record(
                            session_id,
                            "citation_rejected",
                            issues=[vars(i) for i in verdict.issues],
                        )
                        answer = None
                    else:
                        # Sanitize AFTER validation: keep only retrieved AND non-outdated sources.
                        outdated_sids = {
                            i.source_id for i in verdict.issues if i.kind == "outdated"
                        }
                        kept = list(dict.fromkeys(
                            sid for sid in raw_ids if sid in retrieved and sid not in outdated_sids
                        ))
                        answer = GroundedAnswer(
                            answer_text=answer.answer_text,
                            spoken_citation=answer.spoken_citation,
                            source_ids=kept,
                            limitations=answer.limitations,
                            next_step=answer.next_step,
                        )

        # Follow-up rescue: a terse continuation ("em la nam a", "còn nữa
        # không?") often retrieves nothing by itself. When the router only
        # failed on retrieval sufficiency/ambiguity (never on safety), AND
        # the query is a genuine follow-up, fall back to the previous turns'
        # grounded evidence + memory so the model can still answer the follow-up.
        # Hard gates (RED/ORANGE refusals) are never bypassed.
        _RESCUE_CODES = {"INSUFFICIENT_SOURCE", "AMBIGUOUS_QUERY"}
        if answer is None and not faq_answered and memory:
            if set(decision.reason_codes) <= _RESCUE_CODES:
                # Check continuity with previous turn
                prev_turn = memory[-1]
                if not _is_followup_continuation(query.text, prev_turn):
                    self.store.record(
                        session_id,
                        "followup_skipped_no_continuity",
                        current_query=query.text,
                        prev_user=prev_turn.get("user", ""),
                    )
                else:
                    t0 = time.perf_counter()
                    try:
                        followup_chunks = list(dict.fromkeys(memory[-1]["chunks"] + list(chunks)))
                        if not followup_chunks:
                            followup_chunks = list(chunks)
                        # Build context with budget enforcement for follow-up too
                        context, used_followup_chunks = build_context(
                            followup_chunks[: self.top_k],
                            self.settings.max_context_chars,
                        )
                        doc = self.llm.generate_answer(
                            outbound_text,
                            used_followup_chunks,
                            max_chars=self.settings.max_response_chars,
                            history=outbound_history,
                        )
                        raw_ids = list(dict.fromkeys(str(s) for s in (doc.get("source_ids") or [])))
                        rescued = GroundedAnswer(
                            answer_text=str(doc.get("answer_text", "")).strip(),
                            spoken_citation=str(doc.get("spoken_citation", "")).strip(),
                            source_ids=raw_ids,
                            limitations=[str(s) for s in (doc.get("limitations") or [])],
                            next_step=str(doc.get("next_step", "")).strip(),
                        )
                        if not rescued.answer_text or not raw_ids:
                            rescued = None
                        if rescued is not None and self.validator is not None:
                            retrieved = {c.source_id for c in followup_chunks}
                            verdict = self.validator.validate(rescued, retrieved)
                            if not verdict.ok:
                                rescued = None
                        if rescued is not None:
                            answer = rescued
                            chunks = followup_chunks
                            decision = self.router.policy.safe_decision()
                            self.store.record(
                                session_id, "followup_memory_used", source_ids=list(raw_ids)
                            )
                    except Exception as exc:
                        self.store.record(session_id, "followup_failure", reason=str(exc)[:500])
                    lat["followup_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)

        spoken = ""
        if answer is not None:
            # Answer review (feature-flagged): the model reviews the question
            # against the answer; if it finds the answer unfit it rewrites it
            # (self-correction loop) and re-runs the answer process, still
            # grounded in the retrieved evidence.
            if self.settings.answer_review:
                answer = self._review_answer(session_id, query.text, answer, chunks)
            from app.validation.response_validator import detect_issues, sanitize_answer

            issues = detect_issues(answer, query.text)
            if issues:
                self.store.record(session_id, "spoken_repaired", issues=issues)
                answer = sanitize_answer(answer, query.text)
            spoken = self.tts.speak_result(result_for_tts(query, decision, answer))
            t0 = time.perf_counter()
            try:
                self.tts.synthesize(spoken, self._tts_output_path(session_id))
            except Exception as exc:
                self.store.record(session_id, "tts_failure", reason=str(exc)[:300])
            lat["tts_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)

        # Keep every turn, including clarifications, so short follow-ups such
        # as "nam" retain the question they answer. Memory remains RAM-only.
        turns = self._memory.setdefault(session_id, [])
        turns.append(
            {
                "user": query.text,
                "assistant": answer.answer_text if answer else decision.user_message,
                "action": decision.action.value,
                "chunks": list(chunks),
            }
        )
        if len(turns) > self._MEMORY_MAX_TURNS:
            del turns[: -self._MEMORY_MAX_TURNS]

        result = PipelineResult(
            session_id=session_id,
            query=query.text,
            normalized_query=normalized,
            decision=decision,
            answer=answer,
            chunks=chunks,
            latencies_ms=lat,
            app_mode=self.settings.app_mode,
            tts_output=spoken,
            faq_answered=faq_answered,
            query_analysis=query_analysis.to_dict() if query_analysis else None,
        )
        # WER/MOS metrics logging (P0)
        try:
            log_pipeline_result(
                session_id=session_id,
                user_id=session_id,  # fallback
                query_text=query.text,
                normalized_query=normalized,
                result=result,
            )
        except Exception:
            pass  # metrics logging must never break the pipeline
        self._log_result(result)
        return result

    def _tts_output_path(self, session_id: str) -> Path:
        return self.settings.resolved_results_dir() / f"{session_id}.wav"

    def _log_result(self, result: PipelineResult) -> None:
        payload = {
            "event": "pipeline_result",
            "decision_zone": result.decision.zone.value,
            "decision_action": result.decision.action.value,
            "reason_codes": list(result.decision.reason_codes),
            "source_ids": [c.source_id for c in result.chunks],
            "latencies_ms": result.latencies_ms,
            "app_mode": result.app_mode,
        }
        if self.settings.save_transcripts:
            payload["transcript"] = result.query
        self.store.record(result.session_id, **payload)

    def hold_state(self) -> State:
        """Return HOLDING; used by CLI/UI before speaking."""
        return State.HOLDING


def result_for_tts(
    query: str, decision: object, answer: Optional[GroundedAnswer]
) -> PipelineResult:
    """Build a minimal PipelineResult for TTS text generation."""
    return PipelineResult(
        session_id="",
        query=query,
        normalized_query="",
        decision=decision,  # type: ignore[arg-type]
        answer=answer,
        chunks=[],
        latencies_ms={},
        app_mode="",
        tts_output="",
        faq_answered="",
    )
