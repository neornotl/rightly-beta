"""Edge-TTS adapter (primary TTS for Vietnamese - best quality).

Uses Microsoft Edge TTS endpoint. Requires network at runtime.
Includes caching, WAV conversion, and rate/pitch control for elderly users.
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from app.tts.base import BaseTTS


class EdgeTTS(BaseTTS):
    """Edge-TTS with caching, WAV output, and Vietnamese-optimized settings."""

    name = "edge"

    # Vietnamese voices optimized for elderly: slower, clearer
    VIETNAMESE_VOICES = {
        "hoaimy": "vi-VN-HoaiMyNeural",      # Female, warm, clear (DEFAULT)
        "namminh": "vi-VN-NamMinhNeural",    # Male, calm, steady
    }

    def __init__(
        self,
        voice: str = "hoaimy",
        rate: str = "-10%",        # Slower for elderly
        pitch: str = "+0Hz",
        cache_dir: Path = Path("results/tts_cache"),
        output_format: str = "wav",  # WAV for telephony compatibility
    ):
        self.voice_key = voice.lower()
        self.voice = self.VIETNAMESE_VOICES.get(self.voice_key, voice)
        self.rate = rate
        self.pitch = pitch
        self.cache_dir = Path(cache_dir)
        self.output_format = output_format.lower()
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _cache_key(text: str, voice: str, rate: str, pitch: str) -> str:
        return hashlib.sha256(f"{voice}|{rate}|{pitch}|{text}".encode("utf-8")).hexdigest()[:24]

    def _cached_path(self, text: str) -> Path:
        return self.cache_dir / f"{self._cache_key(text, self.voice, self.rate, self.pitch)}.{self.output_format}"

    def _convert_to_wav(self, input_path: Path, output_path: Path) -> bool:
        """Convert audio to WAV using ffmpeg (if available)."""
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
        rate: Optional[str] = None,
        pitch: Optional[str] = None,
    ) -> str:
        try:
            import edge_tts  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "edge-tts not installed. pip install edge-tts"
            ) from exc

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        # Use provided rate/pitch or defaults
        synth_rate = rate if rate is not None else self.rate
        synth_pitch = pitch if pitch is not None else self.pitch

        # Check cache
        cached = self._cached_path(text)
        if cached.exists() and cached.stat().st_size > 0:
            if self.output_format == "wav" and cached.suffix == ".wav":
                if out != cached:
                    shutil.copy2(cached, out)
                return str(out)
            elif self.output_format == "mp3" and cached.suffix == ".mp3":
                if out != cached:
                    shutil.copy2(cached, out)
                return str(out)
        elif cached.exists():  # corrupt 0-byte cache entry: drop it
            cached.unlink(missing_ok=True)

        # Synthesize
        try:
            # Edge-TTS outputs MP3 by default
            mp3_path = out.with_suffix(".mp3")
            asyncio.run(edge_tts.Communicate(
                text=text,
                voice=self.voice,
                rate=synth_rate,
                pitch=synth_pitch
            ).save(str(mp3_path)))
        except Exception as exc:
            raise RuntimeError(f"Edge-TTS synthesis failed: {exc}") from exc
        if not mp3_path.exists() or mp3_path.stat().st_size == 0:
            raise RuntimeError("Edge-TTS: empty audio payload")

        # Convert to requested format
        if self.output_format == "wav":
            if self._convert_to_wav(mp3_path, out):
                mp3_path.unlink(missing_ok=True)
            else:
                # Fallback: rename mp3 to wav (not ideal but works)
                mp3_path.rename(out)
        else:
            # Keep as MP3
            if mp3_path != out:
                shutil.move(str(mp3_path), str(out))

        # Cache the result
        if cached != out:
            shutil.copy2(out, cached)

        return str(out)
