"""Config tests: defaults, validation, and secret redaction."""

from __future__ import annotations

from pathlib import Path

from app.config import ConfigError, load_settings, safe_repr, safe_settings_summary

# Tests must be hermetic: never read a real .env from the repo root.
_NO_ENV = Path(__file__).resolve().parent / "_no_such_env_file.env"


def test_defaults_are_mock(monkeypatch):
    for key in ("APP_MODE", "ASR_BACKEND", "LLM_BACKEND", "TTS_BACKEND"):
        monkeypatch.delenv(key, raising=False)
    settings = load_settings(env_file=_NO_ENV)
    assert settings.app_mode == "mock"
    assert settings.asr_backend == "mock"
    assert settings.llm_backend == "mock"
    assert settings.tts_backend == "mock"
    assert settings.save_transcripts is False
    assert settings.delete_raw_audio_after_session is True


def test_invalid_mode_raises(monkeypatch):
    monkeypatch.setenv("APP_MODE", "bogus")
    try:
        load_settings(env_file=_NO_ENV)
        assert False, "expected ConfigError"
    except ConfigError as exc:
        assert "APP_MODE" in str(exc)


def test_boolean_env_parsing(monkeypatch):
    monkeypatch.setenv("SAVE_TRANSCRIPTS", "true")
    settings = load_settings(env_file=_NO_ENV)
    assert settings.save_transcripts is True


def test_safe_repr_redacts_secret_keys():
    assert safe_repr("sk-abc123", key="GEMINI_API_KEY") == "<REDACTED>"
    assert safe_repr("sk-abc123", key="API_KEY") == "<REDACTED>"
    assert safe_repr("hello", key="LLM_BACKEND") == "hello"


def test_settings_summary_never_contains_key_values():
    import os

    os.environ["GEMINI_API_KEY"] = "FAKE_GEMINI_KEY_FOR_LOGGING_TEST"
    settings = load_settings(env_file=_NO_ENV)
    summary = str(safe_settings_summary(settings))
    assert "FAKE_GEMINI_KEY_FOR_LOGGING_TEST" not in summary
    assert "set" in summary


def test_utf8_vietnamese_text_roundtrip():
    settings = load_settings(env_file=_NO_ENV)
    assert "Bộ phận một cửa" in settings.official_one_stop_label
    assert "Đường dây nóng" in settings.official_hotline_label


def test_default_min_retrieval_score_matches_rrf_scale(monkeypatch):
    monkeypatch.delenv("MIN_RETRIEVAL_SCORE", raising=False)
    settings = load_settings(env_file=_NO_ENV)
    assert settings.min_retrieval_score == 0.01


def test_pateway_env_parsing(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "pateway")
    monkeypatch.setenv("PATEWAY_API_KEY", "pk-test")
    monkeypatch.setenv("PATEWAY_BASE_URL", "https://gw.example.com/v1")
    monkeypatch.setenv("PATEWAY_MODEL", "gpt-5.6-luna")
    settings = load_settings(env_file=_NO_ENV)
    assert settings.llm_backend == "pateway"
    assert settings.pateway_api_key == "pk-test"
    assert settings.pateway_base_url == "https://gw.example.com/v1"
    assert settings.pateway_model == "gpt-5.6-luna"


def test_pateway_in_valid_backends(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "pateway")
    monkeypatch.setenv("LLM_FALLBACK_BACKEND", "groq")
    settings = load_settings(env_file=_NO_ENV)
    assert settings.llm_fallback_backend == "groq"


def test_pateway_same_primary_and_fallback_raises(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "pateway")
    monkeypatch.setenv("LLM_FALLBACK_BACKEND", "pateway")
    try:
        load_settings(env_file=_NO_ENV)
        assert False, "expected ConfigError"
    except ConfigError as exc:
        assert "must differ" in str(exc)


def test_pateway_secret_redacted_in_summary(monkeypatch):
    monkeypatch.setenv("PATEWAY_API_KEY", "SUPER_SECRET_PK")
    settings = load_settings(env_file=_NO_ENV)
    summary = str(safe_settings_summary(settings))
    assert "SUPER_SECRET_PK" not in summary
    assert "pateway_api_key" in summary


def test_local_llm_defaults(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "local")
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    settings = load_settings(env_file=_NO_ENV)
    assert settings.llm_backend == "local"
    assert settings.ollama_base_url == "http://localhost:11434/v1"
    assert settings.ollama_model == "qwen2.5:7b-instruct-q4_k_m"


def test_local_llm_env_parsing(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "local")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:8888/v1")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")
    settings = load_settings(env_file=_NO_ENV)
    assert settings.ollama_base_url == "http://127.0.0.1:8888/v1"
    assert settings.ollama_model == "qwen2.5:7b-instruct"


def test_local_llm_same_primary_and_fallback_raises(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "local")
    monkeypatch.setenv("LLM_FALLBACK_BACKEND", "local")
    try:
        load_settings(env_file=_NO_ENV)
        assert False, "expected ConfigError"
    except ConfigError as exc:
        assert "must differ" in str(exc)
