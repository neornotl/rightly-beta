"""Tests for the TTS fallback chain (council R20: chain order + failure cascade).

All tests are hermetic: no network, no real API keys. Note: other tests in the
suite load the real .env into os.environ, so every test here pins/clears the
key variables explicitly (monkeypatch auto-restores after each test).
"""

from pathlib import Path

from app.tts.fallback import TTSFallback

_KEY_ENV = ("FPT_AI_API_KEY", "ZALO_AI_API_KEY")


def _clear_keys(monkeypatch) -> None:
    for var in _KEY_ENV:
        monkeypatch.delenv(var, raising=False)


def test_chain_order_without_keys(monkeypatch):
    """No API keys -> chain is edge -> gtts -> mock (FPT/Zalo skipped)."""
    _clear_keys(monkeypatch)
    tts = TTSFallback()
    names = [b.name for b in tts._backends]
    assert names == ["edge", "gtts", "mock"]


def test_chain_first_backend_fpt_when_key_present(monkeypatch, tmp_path):
    """FPT_AI_API_KEY set -> FPT is the primary backend (council R19/R20)."""
    _clear_keys(monkeypatch)
    monkeypatch.setenv("FPT_AI_API_KEY", "test-key")
    tts = TTSFallback(cache_dir=tmp_path / "cache")
    names = [b.name for b in tts._backends]
    assert names[0] == "fpt_ai"


def test_chain_fpt_then_zalo_when_both_keys(monkeypatch, tmp_path):
    """Both keys set -> fpt first, zalo second, edge third (council R19 order)."""
    _clear_keys(monkeypatch)
    monkeypatch.setenv("FPT_AI_API_KEY", "test-key")
    monkeypatch.setenv("ZALO_AI_API_KEY", "test-key")
    tts = TTSFallback(cache_dir=tmp_path / "cache")
    names = [b.name for b in tts._backends]
    assert names == ["fpt_ai", "zalo_ai", "edge", "gtts", "mock"]


def test_primary_failure_falls_back_to_mock(monkeypatch, tmp_path):
    """Every non-mock backend fails -> chain lands on mock (never crashes)."""
    _clear_keys(monkeypatch)
    monkeypatch.setenv("FPT_AI_API_KEY", "test-key")
    monkeypatch.setenv("ZALO_AI_API_KEY", "test-key")
    tts = TTSFallback(cache_dir=tmp_path / "cache")

    def boom(*args, **kwargs):
        raise RuntimeError("simulated failure")

    for backend in tts._backends[:-1]:  # fail all except mock (last resort)
        monkeypatch.setattr(backend, "synthesize", boom)
    out = tmp_path / "out.wav"
    result = tts.synthesize("Chào bác", out)
    assert result.endswith(".spoken.txt")
    assert Path(result).exists()


def test_active_backend_property(monkeypatch, tmp_path):
    """active_backend reports the current primary."""
    _clear_keys(monkeypatch)
    monkeypatch.setenv("FPT_AI_API_KEY", "test-key")
    tts = TTSFallback(cache_dir=tmp_path / "cache")
    assert tts.active_backend == "fpt_ai"


def test_backend_status_nonempty():
    tts = TTSFallback()
    status = tts.get_backend_status()
    assert len(status) >= 3
    assert all("priority" in s for s in status.values())


def test_empty_text_still_lands_on_mock(monkeypatch, tmp_path):
    """Empty text -> mock .spoken.txt sidecar (chain never crashes)."""
    _clear_keys(monkeypatch)
    tts = TTSFallback(cache_dir=tmp_path / "cache")

    def boom(*args, **kwargs):
        raise RuntimeError("synthesize empty rejected")

    for backend in tts._backends[:-1]:
        monkeypatch.setattr(backend, "synthesize", boom)
    out = tmp_path / "empty.wav"
    result = tts.synthesize("", out)
    assert Path(result).exists()
