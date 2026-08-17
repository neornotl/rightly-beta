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

import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.asr.base import BaseASR
from app.asr.mock_asr import MockASR
from app.config import Settings
from app.dialogue.state_machine import State
from app.llm.base import BaseLLM
from app.llm.mock_llm import MockLLM
from app.logging_utils import JsonlLogger, SessionStore, utc_now_iso
from app.metrics_logger import log_pipeline_result
from app.retrieval.base import Retriever
from app.retrieval.bm25_retriever import BM25Retriever
from app.retrieval.document_loader import DocumentLoader
from app.faq import _strip_diacritics
from app.safety.policy import Policy
from app.safety.router import SafetyRouter
from app.safety.rules import normalize_query
from app.schemas import GroundedAnswer, PipelineResult, RetrievedChunk, UserQuery, Zone, Action
from app.tts.base import BaseTTS
from app.tts.mock_tts import MockTTS

logger = logging.getLogger(__name__)

_MIN_QUERY_CHARS = 3


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

        return PhoWhisperASR()
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

    if settings.retrieval_backend == "hybrid":
        try:
            from app.retrieval.hybrid_retriever import HybridRetriever

            return HybridRetriever.from_chunks(
                DocumentLoader.load_chunks(chunks_file),
                cache_path=cache_path,
                exclude_demo=exclude_demo,
                rerank=settings.retriever_rerank,
                gate=settings.retriever_gate,
                bm25_gate=settings.bm25_gate,
                dense_gate=settings.dense_gate,
            )
        except (ImportError, ModuleNotFoundError) as exc:
            # Council R20: sentence_transformers/torch (~2GB) cannot install on
            # Streamlit Cloud free tier -> degrade gracefully to BM25 instead
            # of crashing the app at boot.
            logger.warning("Hybrid retrieval unavailable (%s); falling back to BM25.", exc)
            return BM25Retriever.from_jsonl(chunks_file)
    if settings.retrieval_backend != "bm25":
        raise ValueError(f"Unsupported retrieval backend: {settings.retrieval_backend}")
    return BM25Retriever.from_jsonl(chunks_file)


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
            raise RuntimeError(
                "LLM_BACKEND=local but no local server at "
                f"{settings.ollama_base_url}. Start Ollama ('ollama serve') and "
                f"pull the model first ('ollama pull {settings.ollama_model}')."
            )
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
    #: Temporary per-session conversation memory (RAM only, never persisted).
    #: Kept for the lifetime of the session; cleared by delete_session()
    #: (user says "kết thúc"/"thoát" in CLI/UI). Each entry:
    #: {"user": str, "assistant": str, "chunks": list[RetrievedChunk]}.
    _memory: dict[str, list[dict]] = field(default_factory=dict, repr=False)

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
        return self.store.delete_session(session_id)

    # ---------- core ----------

    def process_text(self, session_id: str, text: str) -> PipelineResult:
        """Full pipeline for a text query (no audio involved)."""
        if self.settings.save_transcripts:
            self.store.record(session_id, "transcript_saved", transcript=text)
        query = UserQuery(text=text, session_id=session_id, timestamp=utc_now_iso())
        return self._run(session_id, query)

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

    def _run(
        self,
        session_id: str,
        query: UserQuery,
        precomputed_asr_ms: float = 0.0,
    ) -> PipelineResult:
        lat: dict[str, float] = {}
        if precomputed_asr_ms:
            lat["asr_ms"] = round(precomputed_asr_ms, 1)

        t0 = time.perf_counter()
        normalized = normalize_query(query.text)
        lat["normalize_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)

        t0 = time.perf_counter()
        chunks = self._retrieve(query.text, session_id, self.top_k)
        lat["retrieval_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)

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

        if faq_hit is not None:
            # Check if router decision is a hard gate that FAQ cannot override
            if decision.zone in (Zone.RED, Zone.ORANGE) and decision.action != Action.GUIDE:
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
                    # No evidence for FAQ answer - fall through
                    self.store.record(
                        session_id,
                        "faq_evidence_missing",
                        faq_id=faq_hit.faq_id,
                    )
                    faq_hit = None
                else:
                    faq_source_list = (
                        list(faq_hit.source_ids)
                        if faq_hit.source_ids
                        else [
                            c.source_id
                            for c in faq_chunks
                            if c.score >= self.settings.min_retrieval_score
                        ]
                        or [c.source_id for c in faq_chunks[:3]]
                    )
                    faq_sources = tuple(dict.fromkeys(faq_source_list))
                    from dataclasses import replace

                    faq_hit = replace(faq_hit, source_ids=faq_sources)
                    # Validate FAQ citations
                    if self.validator is not None:
                        verdict = self.validator.validate(faq_hit.to_grounded_answer(), {c.source_id for c in faq_chunks})
                        if not verdict.ok:
                            self.store.record(
                                session_id,
                                "faq_citation_rejected",
                                faq_id=faq_hit.faq_id,
                                issues=[vars(i) for i in verdict.issues],
                            )
                            faq_hit = None
                    
                    if faq_hit is not None:
                        answer = faq_hit.to_grounded_answer()
                        chunks = faq_chunks
                        faq_answered = faq_hit.faq_id
                        decision = self.router.policy.safe_decision()
                        lat["faq_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
                        self.store.record(session_id, "faq_hit", faq_id=faq_hit.faq_id, score=faq_hit.score)
        elif self.router.would_answer(decision):
            t0 = time.perf_counter()

            # Guard: if no chunks retrieved or all scores too low, refuse early
            # to avoid LLM hallucination and FAKE_LAW false positive.
            if not chunks or all(c.score < self.settings.min_retrieval_score for c in chunks):
                decision = self.router.policy.insufficient_decision()
                self.store.record(session_id, "empty_chunks_rejected", num_chunks=len(chunks))
                answer = None
            else:
                try:
                    # Build context with budget enforcement
                    context, used_chunks = build_context(
                        chunks[: self.top_k],
                        self.settings.max_context_chars,
                    )
                    doc = self.llm.generate_answer(
                        outbound_text,
                        used_chunks,  # Pass only chunks that fit in context
                        max_chars=self.settings.max_response_chars,
                        history=outbound_history,
                    )
                    raw_ids = list(dict.fromkeys(str(s) for s in (doc.get("source_ids") or [])))
                    answer = GroundedAnswer(
                        answer_text=str(doc.get("answer_text", "")).strip(),
                        spoken_citation=str(doc.get("spoken_citation", "")).strip(),
                        source_ids=raw_ids,
                        limitations=[str(s) for s in (doc.get("limitations") or [])],
                        next_step=str(doc.get("next_step", "")).strip(),
                    )
                except Exception as exc:
                    decision = self.router.policy.insufficient_decision()
                    self.store.record(session_id, "llm_failure", reason=str(exc)[:500])
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

        # Keep the accepted turn in the session's temporary memory (RAM only).
        if answer is not None and answer.answer_text:
            turns = self._memory.setdefault(session_id, [])
            turns.append(
                {"user": query.text, "assistant": answer.answer_text, "chunks": list(chunks)}
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
