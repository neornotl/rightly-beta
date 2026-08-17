"""Zalo AI TTS Adapter (Zalo's native TTS - most natural for Vietnamese).

API: POST https://api.zalo.ai/v1/tts/synthesize
  Headers: apikey: <zako OA:... or v2 key>
  Body (form): input=<text>, speaker_id=<int 1-6>, speed=<0.8-1.2>
  Response: {"error_code": 0, "data": {"url": "https://...mp3"}}

Free tier: ~2000 chars per request -> long text is chunked client-side and
the resulting WAV segments are concatenated with ffmpeg (when available).
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

import requests

from app.tts.base import BaseTTS


class ZaloAI_TTS(BaseTTS):
    """Zalo AI TTS with caching, WAV conversion and 2k-char chunking."""

    name = "zalo_ai"

    # Zalo AI speaker_id mapping (per Zalo AI docs):
    # 1 = Northern female 1, 2 = Southern female 1, 3 = Northern male,
    # 4 = Southern male, 5 = Northern female 2, 6 = Southern female 2.
    VOICES = {
        "north_female": 1,
        "south_female": 2,
        "north_male": 3,
        "south_male": 4,
        "north_female_2": 5,
        "south_female_2": 6,
        "central_female": 2,
        "central_male": 4,
    }

    MAX_CHARS_PER_REQUEST = 1900  # safe margin under the 2000-char tier

    @staticmethod
    def _normalize_key(key: str) -> str:
        """Strip the 'zako OA:' display prefix if present (API rejects it)."""
        key = key.strip()
        if key.lower().startswith("zako "):
            key = key.split(":", 1)[-1].strip()
        return key

    def __init__(
        self,
        api_key: str,
        voice: str = "south_female",
        speed: float = 1.0,
        cache_dir: Path = Path("results/tts_cache"),
        output_format: str = "wav",
    ):
        self.api_key = self._normalize_key(api_key)
        self.voice = voice.lower()
        self.speaker_id = self.VOICES.get(self.voice, 2)  # default: south female
        self.speed = speed
        self.cache_dir = Path(cache_dir)
        self.output_format = output_format.lower()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.api_url = "https://api.zalo.ai/v1/tts/synthesize"
        # Circuit breaker: after a 429 burst the free tier stays exhausted for a
        # while, so skip Zalo entirely for the cooldown window (fast-fail into
        # the fallback chain instead of burning retry time).
        self._rate_limited_until: float = 0.0

    def _check_circuit_breaker(self) -> bool:
        """True when the API key is in the 429 cooldown window."""
        return time.monotonic() < self._rate_limited_until

    @staticmethod
    def _cache_key(text: str, voice: str, speed: float) -> str:
        return hashlib.sha256(f"{voice}|{speed}|{text}".encode("utf-8")).hexdigest()[:24]

    def _cached_path(self, text: str, voice: Optional[str] = None, speed: Optional[float] = None) -> Path:
        use_voice = voice if voice is not None else self.voice
        use_speed = speed if speed is not None else self.speed
        return self.cache_dir / f"{self._cache_key(text, use_voice, use_speed)}.{self.output_format}"

    @staticmethod
    def _split_for_limit(text: str, limit: int) -> list[str]:
        """Split text into <= limit chunks at sentence boundaries."""
        if len(text) <= limit:
            return [text]
        chunks: list[str] = []
        remaining = text
        while len(remaining) > limit:
            window = remaining[:limit]
            # Prefer the last sentence boundary (., !, ?, ;, newline) inside the window.
            boundary = max(window.rfind(c) for c in ".!?;\n")
            cut = boundary + 1 if boundary > limit // 2 else limit
            chunks.append(window[:cut].strip())
            remaining = remaining[cut:].lstrip()
        if remaining.strip():
            chunks.append(remaining.strip())
        return chunks

    def _convert_to_wav(self, input_path: Path, output_path: Path) -> bool:
        """Convert audio to 16k mono WAV using ffmpeg."""
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", str(input_path),
                    "-ar", "16000", "-ac", "1", "-sample_fmt", "s16",
                    str(output_path),
                ],
                check=True, capture_output=True, timeout=60,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _synthesize_one(self, text: str, out_wav: Path) -> bool:
        """Synthesize a single <=2k chunk to a 16k mono WAV. Returns True on success."""
        if self._check_circuit_breaker():
            raise RuntimeError("Zalo AI TTS: in 429 cooldown, skipping")

        headers = {"apikey": self.api_key}
        data = {
            "input": text,
            "speaker_id": self.speaker_id,
            "speed": self.speed,
        }

        # Whole cycle is retried: 429 from the synth call OR 404 on the audio
        # URL (URLs are single-use; a 404 means the URL was invalidated).
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                response = requests.post(self.api_url, headers=headers, data=data, timeout=30)
                if response.status_code == 429:
                    last_exc = RuntimeError("Zalo AI TTS rate limit (429)")
                    self._rate_limited_until = time.monotonic() + 90.0  # circuit breaker
                    time.sleep(1.5 * (attempt + 1))
                    continue
                response.raise_for_status()

                result = response.json()
                if result.get("error_code") != 0:
                    raise RuntimeError(
                        f"Zalo AI TTS error {result.get('error_code')}: {result.get('message')}"
                    )

                audio_url = result.get("data", {}).get("url")
                if not audio_url:
                    raise RuntimeError("Zalo AI TTS: no audio URL in response")

                audio_resp = requests.get(audio_url, timeout=30)
                if audio_resp.status_code == 404:
                    last_exc = RuntimeError("Zalo AI TTS audio URL invalidated (404)")
                    time.sleep(1.0)
                    continue
                audio_resp.raise_for_status()
                if len(audio_resp.content) < 100:
                    raise RuntimeError("Zalo AI TTS: empty audio payload")
            except requests.exceptions.HTTPError as exc:
                if getattr(exc.response, "status_code", None) == 429:
                    last_exc = exc
                    self._rate_limited_until = time.monotonic() + 90.0  # circuit breaker
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise RuntimeError(f"Zalo AI TTS request failed: {exc}") from exc
            except Exception as exc:
                raise RuntimeError(f"Zalo AI TTS request failed: {exc}") from exc

            if self.output_format == "wav":
                mp3_path = out_wav.with_suffix(".tmp.mp3")
                mp3_path.write_bytes(audio_resp.content)
                if self._convert_to_wav(mp3_path, out_wav):
                    mp3_path.unlink(missing_ok=True)
                    return True
                mp3_path.rename(out_wav)  # ffmpeg unavailable: keep raw bytes
            else:
                out_wav.write_bytes(audio_resp.content)
            return True

        raise RuntimeError(f"Zalo AI TTS failed after retries: {last_exc}")

    def _concat_wavs(self, segments: list[Path], out: Path) -> bool:
        """Concatenate WAV segments with ffmpeg (all 16k mono s16)."""
        list_file = out.with_suffix(".list.txt")
        list_file.write_text(
            "".join(f"file '{seg.resolve()}'\n" for seg in segments),
            encoding="utf-8",
        )
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(list_file), "-c", "copy", str(out),
                ],
                check=True, capture_output=True, timeout=120,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return False
        finally:
            list_file.unlink(missing_ok=True)

    def synthesize(
        self,
        text: str,
        output_path: str | Path,
        speed: Optional[float] = None,
    ) -> str:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        use_speed = speed if speed is not None else self.speed
        cached = self._cached_path(text, self.voice, use_speed)

        if cached.exists() and cached.stat().st_size > 0:
            if out != cached:
                shutil.copy2(cached, out)
            return str(out)
        elif cached.exists():  # corrupt 0-byte cache entry: drop it
            cached.unlink(missing_ok=True)

        text = text.strip()
        if not text:
            raise ValueError("Zalo AI TTS: empty text")

        chunks = self._split_for_limit(text, self.MAX_CHARS_PER_REQUEST)

        if len(chunks) == 1:
            self._synthesize_one(chunks[0], out)
        else:
            tmp_dir = out.parent / f".zalo_{self._cache_key(text, self.voice, use_speed)}"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            segments: list[Path] = []
            try:
                for i, chunk in enumerate(chunks):
                    seg = tmp_dir / f"seg_{i:03d}.wav"
                    self._synthesize_one(chunk, seg)
                    segments.append(seg)
                    if i < len(chunks) - 1:
                        time.sleep(1.0)  # space requests within the free-tier quota
                if not self._concat_wavs(segments, out):
                    # ffmpeg missing: keep the first segment (single-chunk fallback).
                    shutil.copy2(segments[0], out)
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

        if cached != out:
            try:
                shutil.copy2(out, cached)
            except OSError:
                pass

        return str(out)
