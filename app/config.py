"""Configuration for Rightly.

Environment-variable driven with safe defaults. Supports `.env` files via
python-dotenv when available, with an internal fallback parser so mock mode
needs zero third-party dependencies.

Secrets are never printed; :func:`safe_repr` is provided for that purpose.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

_SECRET_KEYS = {"api_key", "token", "secret", "password"}


class ConfigError(ValueError):
    """Raised when the configuration is invalid or inconsistent."""


def _load_env_file(path: Path) -> None:
    """Minimal .env parser (used only when python-dotenv is unavailable)."""
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv(path)
        return
    except ImportError:
        pass
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def _merge_streamlit_secrets() -> None:
    """Make Streamlit Cloud dashboard secrets visible as env vars.

    T1 fix: the app config reads environment variables; without this merge
    the Streamlit dashboard secrets never reach :func:`load_settings`.
    Uses setdefault so a real .env / OS env still wins.

    Note: accessing ``st.secrets`` mutates ``os.environ`` (secrets.toml
    values overwrite existing env vars). We snapshot the environment first
    and restore it so a real .env / OS env keeps priority.
    """
    try:
        import streamlit as st  # type: ignore
    except ImportError:
        return
    secrets = getattr(st, "secrets", None)
    if secrets is None:
        return
    before = os.environ.copy()
    try:
        items = secrets.to_dict() if hasattr(secrets, "to_dict") else dict(secrets)
    except Exception:
        return
    os.environ.clear()
    os.environ.update(before)
    for key, value in items.items():
        if isinstance(key, str) and isinstance(value, str) and value:
            os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    app_mode: str = "mock"
    asr_backend: str = "mock"
    retrieval_backend: str = "bm25"
    llm_backend: str = "mock"
    tts_backend: str = "mock"
    data_dir: Path = Path("data")
    results_dir: Path = Path("results")
    log_dir: Path = Path("logs")
    gemini_api_key: str = ""
    groq_api_key: str = ""
    groq_api_keys: tuple[str, ...] = ()
    pateway_api_key: str = ""
    pateway_base_url: str = ""
    pateway_model: str = ""
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen2.5:7b-instruct-q4_k_m"
    llm_fallback_backend: str = ""
    rate_limit_per_ip: int = 60
    rate_limit_window_seconds: int = 3600
    delete_raw_audio_after_session: bool = True
    save_transcripts: bool = False
    max_context_chars: int = 12000
    max_response_chars: int = 2000
    pii_scrub_outbound: bool = True
    use_llm_classifier: bool = False
    log_retention_days: int = 30
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 3
    llm_retry_backoff_seconds: float = 1.0
    min_retrieval_score: float = 0.01
    retriever_rerank: bool = False
    retriever_gate: str = "bm25_dense"
    bm25_gate: float = 12.2
    dense_gate: float = 0.84
    edge_tts_voice: str = "vi-VN-HoaiMyNeural"
    edge_tts_rate: str = "+0%"
    official_hotline_label: str = "Đường dây nóng khẩn cấp (113)"
    official_hotline_value: str = "113"
    official_one_stop_label: str = "Bộ phận một cửa - Tổng đài dịch vụ công 1022"
    official_one_stop_value: str = "1022"
    hold_message: str = "Xin chờ chút, tôi đang tìm thông tin chính thức cho câu hỏi của bạn."

    # Derived paths (relative to project root).
    chunks_dir: Optional[Path] = field(default=None, repr=False)
    sources_dir: Optional[Path] = field(default=None, repr=False)
    eval_dir: Optional[Path] = field(default=None, repr=False)

    def __post_init__(self) -> None:
        root = Path.cwd()
        # Paths are stored as given; helpers below resolve relative to root.
        object.__setattr__(self, "chunks_dir", self._resolve(root, self.data_dir) / "chunks")
        object.__setattr__(self, "sources_dir", self._resolve(root, self.data_dir) / "sources")
        object.__setattr__(self, "eval_dir", self._resolve(root, self.data_dir) / "eval")

    @staticmethod
    def _resolve(root: Path, p: Path) -> Path:
        if p.is_absolute():
            return p
        return root / p

    def resolved_data_dir(self) -> Path:
        return self._resolve(Path.cwd(), self.data_dir)

    def resolved_results_dir(self) -> Path:
        return self._resolve(Path.cwd(), self.results_dir)

    def resolved_log_dir(self) -> Path:
        return self._resolve(Path.cwd(), self.log_dir)

    @property
    def red_contact_message(self) -> str:
        return (
            f"Nếu bạn đang gặp tình huống khẩn cấp hoặc nguy hiểm, hãy liên hệ "
            f"{self.official_hotline_label}: {self.official_hotline_value} "
            f"(PHẢI XÁC MINH TRƯỚC KHI TRIỂN KHAI). Tôi không phải cơ quan "
            f"khẩn cấp và không thể thay thế hỗ trợ của con người."
        )


def _bool_env(key: str, default: bool) -> bool:
    val = os.environ.get(key)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(key: str, default: int) -> int:
    val = os.environ.get(key)
    if val is None or not val.strip():
        return default
    try:
        return int(val)
    except ValueError as exc:
        raise ConfigError(f"Invalid integer for {key}: {val!r}") from exc


def _float_env(key: str, default: float) -> float:
    val = os.environ.get(key)
    if val is None or not val.strip():
        return default
    try:
        return float(val)
    except ValueError as exc:
        raise ConfigError(f"Invalid float for {key}: {val!r}") from exc


_VALID_MODES = {"mock", "local", "cloud"}
_VALID_ASR = {"mock", "phowhisper"}
_VALID_RETRIEVAL = {"bm25", "hybrid"}
_VALID_LLM = {"mock", "gemini", "groq", "pateway", "local"}
_VALID_FALLBACK = {"", "gemini", "groq", "pateway", "local"}
_VALID_TTS = {"mock", "edge"}


def _multi_env(prefix: str, key1: str) -> tuple[str, ...]:
    """Collect GROQ_API_KEY, GROQ_API_KEY_2, ... GROQ_API_KEY_5 (stop at gap).

    Order matters: the first non-empty key is the primary.
    """
    keys = [k for k in (os.environ.get(key1, "").strip(),) if k]
    for idx in range(2, 6):
        val = os.environ.get(f"{prefix}_{idx}", "").strip()
        if not val:
            break
        keys.append(val)
    return tuple(keys)


def load_settings(env_file: Optional[Path] = None) -> Settings:
    """Build :class:`Settings` from environment variables with validation."""
    explicit_env = env_file is not None
    if env_file is None:
        env_file = Path.cwd() / ".env"
    _load_env_file(env_file)
    # Hermetic test support: merge Streamlit secrets only when no explicit
    # env file was requested (tests pass their own file to stay isolated
    # from .streamlit/secrets.toml on disk).
    if not explicit_env:
        _merge_streamlit_secrets()

    app_mode = os.environ.get("APP_MODE", "mock").strip().lower()
    asr_backend = os.environ.get("ASR_BACKEND", "mock").strip().lower()
    retrieval_backend = os.environ.get("RETRIEVAL_BACKEND", "bm25").strip().lower()
    llm_backend = os.environ.get("LLM_BACKEND", "mock").strip().lower()
    tts_backend = os.environ.get("TTS_BACKEND", "mock").strip().lower()
    llm_fallback_backend = os.environ.get("LLM_FALLBACK_BACKEND", "").strip().lower()

    if app_mode not in _VALID_MODES:
        raise ConfigError(
            f"APP_MODE={app_mode!r} is invalid. Choose one of {sorted(_VALID_MODES)}."
        )
    if asr_backend not in _VALID_ASR:
        raise ConfigError(
            f"ASR_BACKEND={asr_backend!r} is invalid. Choose one of {sorted(_VALID_ASR)}."
        )
    if retrieval_backend not in _VALID_RETRIEVAL:
        raise ConfigError(
            f"RETRIEVAL_BACKEND={retrieval_backend!r} is invalid. "
            f"Choose one of {sorted(_VALID_RETRIEVAL)}."
        )
    if llm_backend not in _VALID_LLM:
        raise ConfigError(
            f"LLM_BACKEND={llm_backend!r} is invalid. Choose one of {sorted(_VALID_LLM)}."
        )
    if tts_backend not in _VALID_TTS:
        raise ConfigError(
            f"TTS_BACKEND={tts_backend!r} is invalid. Choose one of {sorted(_VALID_TTS)}."
        )
    if llm_fallback_backend not in _VALID_FALLBACK:
        raise ConfigError(
            f"LLM_FALLBACK_BACKEND={llm_fallback_backend!r} is invalid. "
            f"Choose one of {sorted(_VALID_FALLBACK)}."
        )
    if llm_fallback_backend == llm_backend and llm_backend in {
        "gemini",
        "groq",
        "pateway",
        "local",
    }:
        raise ConfigError("LLM_FALLBACK_BACKEND must differ from LLM_BACKEND.")

    rate_limit_per_ip = _int_env("RATE_LIMIT_PER_IP", 60)
    rate_limit_window = _int_env("RATE_LIMIT_WINDOW_SECONDS", 3600)
    if rate_limit_per_ip < 0 or rate_limit_window <= 0:
        raise ConfigError("RATE_LIMIT_PER_IP >= 0 and RATE_LIMIT_WINDOW_SECONDS > 0 required.")

    max_context = _int_env("MAX_CONTEXT_CHARS", 12000)
    max_response = _int_env("MAX_RESPONSE_CHARS", 2000)
    if max_context <= 0 or max_response <= 0:
        raise ConfigError("MAX_CONTEXT_CHARS and MAX_RESPONSE_CHARS must be positive.")
    if max_response > max_context:
        raise ConfigError("MAX_RESPONSE_CHARS must not exceed MAX_CONTEXT_CHARS.")

    pii_scrub_outbound = _bool_env("PII_SCRUB_OUTBOUND", True)

    use_llm_classifier = _bool_env("USE_LLM_CLASSIFIER", False)

    log_retention = _int_env("LOG_RETENTION_DAYS", 30)
    if log_retention < 0:
        raise ConfigError("LOG_RETENTION_DAYS must be >= 0 (0 = keep forever).")

    llm_timeout = _float_env("LLM_TIMEOUT_SECONDS", 60.0)
    llm_max_retries = _int_env("LLM_MAX_RETRIES", 3)
    llm_backoff = _float_env("LLM_RETRY_BACKOFF_SECONDS", 1.0)
    if llm_timeout <= 0 or llm_max_retries < 0 or llm_backoff < 0:
        raise ConfigError("Invalid LLM timeout/retry settings.")

    min_score = _float_env("MIN_RETRIEVAL_SCORE", 0.01)
    if min_score < 0:
        raise ConfigError("MIN_RETRIEVAL_SCORE must be >= 0.")
    # Hybrid RRF scores live in ~[0, 0.1]; a threshold > 0.5 silently
    # refuses every query (F3 fix). Warn loudly instead of failing silently.
    if min_score > 0.5:
        import warnings

        warnings.warn(
            "MIN_RETRIEVAL_SCORE={} is far above the RRF score scale (~0.01-0.1); "
            "every hybrid query will be refused.".format(min_score),
            RuntimeWarning,
            stacklevel=2,
        )

    retriever_gate = os.environ.get("RETRIEVER_GATE", "bm25_dense").strip().lower()
    if retriever_gate not in {"none", "bm25_dense"}:
        raise ConfigError(
            f"RETRIEVER_GATE={retriever_gate!r} is invalid. Choose one of {{'none', 'bm25_dense'}}."
        )
    bm25_gate = _float_env("RETRIEVAL_BM25_GATE", 12.2)
    dense_gate = _float_env("RETRIEVAL_DENSE_GATE", 0.84)
    if bm25_gate < 0 or not (0 < dense_gate <= 1):
        raise ConfigError("Invalid retrieval gate thresholds.")

    return Settings(
        app_mode=app_mode,
        asr_backend=asr_backend,
        retrieval_backend=retrieval_backend,
        llm_backend=llm_backend,
        tts_backend=tts_backend,
        data_dir=Path(os.environ.get("DATA_DIR", "data")),
        results_dir=Path(os.environ.get("RESULTS_DIR", "results")),
        log_dir=Path(os.environ.get("LOG_DIR", "logs")),
        gemini_api_key=os.environ.get("GEMINI_API_KEY", "").strip(),
        groq_api_key=os.environ.get("GROQ_API_KEY", "").strip(),
        groq_api_keys=_multi_env("GROQ_API_KEY", "GROQ_API_KEY"),
        pateway_api_key=os.environ.get("PATEWAY_API_KEY", "").strip(),
        pateway_base_url=os.environ.get("PATEWAY_BASE_URL", "").strip(),
        pateway_model=os.environ.get("PATEWAY_MODEL", "").strip(),
        ollama_base_url=os.environ.get(
            "OLLAMA_BASE_URL", "http://localhost:11434/v1"
        ).strip(),
        ollama_model=os.environ.get("OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_k_m").strip(),
        llm_fallback_backend=llm_fallback_backend,
        rate_limit_per_ip=rate_limit_per_ip,
        rate_limit_window_seconds=rate_limit_window,
        delete_raw_audio_after_session=_bool_env("DELETE_RAW_AUDIO_AFTER_SESSION", True),
        save_transcripts=_bool_env("SAVE_TRANSCRIPTS", False),
        max_context_chars=max_context,
        max_response_chars=max_response,
        pii_scrub_outbound=pii_scrub_outbound,
        use_llm_classifier=use_llm_classifier,
        log_retention_days=log_retention,
        llm_timeout_seconds=llm_timeout,
        llm_max_retries=llm_max_retries,
        llm_retry_backoff_seconds=llm_backoff,
        min_retrieval_score=min_score,
        retriever_rerank=_bool_env("RETRIEVER_RERANK", False),
        retriever_gate=retriever_gate,
        bm25_gate=bm25_gate,
        dense_gate=dense_gate,
        edge_tts_voice=os.environ.get("EDGE_TTS_VOICE", "vi-VN-HoaiMyNeural"),
        edge_tts_rate=os.environ.get("EDGE_TTS_RATE", "+0%"),
        official_hotline_label=os.environ.get(
            "OFFICIAL_HOTLINE_LABEL", "Đường dây nóng (chưa xác minh)"
        ),
        official_hotline_value=os.environ.get("OFFICIAL_HOTLINE_VALUE", "1900XXXX"),
        official_one_stop_label=os.environ.get(
            "OFFICIAL_ONE_STOP_LABEL", "Bộ phận một cửa (chưa xác minh)"
        ),
        official_one_stop_value=os.environ.get("OFFICIAL_ONE_STOP_VALUE", "Chưa có"),
    )


def is_secret_key(key: str) -> bool:
    """True when a config/env key looks secret (for redaction)."""
    lowered = key.lower()
    return any(s in lowered for s in _SECRET_KEYS)


def safe_repr(value: Any, key: str = "") -> Any:
    """Redact values whose key or name looks secret."""
    if is_secret_key(key):
        if isinstance(value, str) and value:
            return "<REDACTED>"
        return value
    return value


def safe_settings_summary(settings: Settings) -> dict[str, Any]:
    """Non-secret summary of settings, safe for logging/UI."""
    return {
        "app_mode": settings.app_mode,
        "asr_backend": settings.asr_backend,
        "retrieval_backend": settings.retrieval_backend,
        "llm_backend": settings.llm_backend,
        "tts_backend": settings.tts_backend,
        "delete_raw_audio_after_session": settings.delete_raw_audio_after_session,
        "save_transcripts": settings.save_transcripts,
        "max_context_chars": settings.max_context_chars,
        "max_response_chars": settings.max_response_chars,
        "pii_scrub_outbound": settings.pii_scrub_outbound,
        "use_llm_classifier": settings.use_llm_classifier,
        "log_retention_days": settings.log_retention_days,
        "llm_timeout_seconds": settings.llm_timeout_seconds,
        "llm_max_retries": settings.llm_max_retries,
        "min_retrieval_score": settings.min_retrieval_score,
        "gemini_api_key": "set" if settings.gemini_api_key else "unset",
        "groq_api_key": "set" if settings.groq_api_key else "unset",
        "groq_key_count": len(settings.groq_api_keys) or (1 if settings.groq_api_key else 0),
        "pateway_api_key": "set" if settings.pateway_api_key else "unset",
        "llm_fallback_backend": settings.llm_fallback_backend or "none",
        "rate_limit_per_ip": settings.rate_limit_per_ip,
        "rate_limit_window_seconds": settings.rate_limit_window_seconds,
    }
