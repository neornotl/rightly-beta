"""gTTS adapter (fallback TTS for Vietnamese).

Google Translate TTS. Requires network but lighter than Edge-TTS.
Good fallback when Edge-TTS fails or for quick synthesis.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from app.tts.base import BaseTTS


class GTTS(BaseTTS):
    """gTTS with caching and WAV conversion."""

    name = "gtts"

    def __init__(
        self,
        lang: str = "vi",
        slow: bool = False,        # False = normal speed, True = slower
        cache_dir: Path = Path("results/tts_cache"),
        output_format: str = "wav",
    ):
        self.lang = lang
        self.slow = slow
        self.cache_dir = Path(cache_dir)
        self.output_format = output_format.lower()
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _cache_key(text: str, lang: str, slow: bool) -> str:
        return hashlib.sha256(f"{lang}|{slow}|{text}".encode("utf-8")).hexdigest()[:24]

    def _cached_path(self, text: str) -> Path:
        return self.cache_dir / f"{self._cache_key(text, self.lang, self.slow)}.{self.output_format}"

    def _convert_to_wav(self, input_path: Path, output_path: Path) -> bool:
        """Convert audio to WAV using ffmpeg."""
        try:
            subprocess.run([
                "ffmpeg", "-y", "-i", str(input_path),
                "-ar", "16000", "-ac", "1", "-sample_fmt", "s16",
                str(output_path)
            ], check=True, capture_output=True, timeout=30)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def synthesize(
        self,
        text: str,
        output_path: str | Path,
        slow: Optional[bool] = None,
    ) -> str:
        try:
            from gtts import gTTS  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "gtts not installed. pip install gtts"
            ) from exc

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        use_slow = slow if slow is not None else self.slow
        cached = self._cached_path(text)

        if cached.exists() and cached.stat().st_size > 0:
            if out != cached:
                shutil.copy2(cached, out)
            return str(out)
        elif cached.exists():  # corrupt 0-byte cache entry: drop it
            cached.unlink(missing_ok=True)

        # Synthesize to MP3 first
        mp3_path = out.with_suffix(".mp3")
        try:
            tts = gTTS(text=text, lang=self.lang, slow=use_slow)
            tts.save(str(mp3_path))
        except Exception as exc:
            raise RuntimeError(f"gTTS synthesis failed: {exc}") from exc
        if not mp3_path.exists() or mp3_path.stat().st_size == 0:
            raise RuntimeError("gTTS: empty audio payload")

        # Convert to requested format
        if self.output_format == "wav":
            if self._convert_to_wav(mp3_path, out):
                mp3_path.unlink(missing_ok=True)
            else:
                mp3_path.rename(out)
        else:
            if mp3_path != out:
                shutil.move(str(mp3_path), str(out))

        # Cache
        if cached != out:
            shutil.copy2(out, cached)

        return str(out)
