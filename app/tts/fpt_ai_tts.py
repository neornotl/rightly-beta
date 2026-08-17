"""FPT.AI TTS Adapter (High-quality Vietnamese TTS with free tier).

Council R24: primary voice thuminh (natural Southern, hotline tone).
Council R19: FPT.AI primary provider; R20: chunking <=450 chars (free tier
limit 500 chars/request), 0-byte guard before caching, tighter async polling.
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


class FPTAI_TTS(BaseTTS):
    """FPT.AI TTS with chunking, caching and WAV conversion."""

    name = "fpt_ai"

    # Available voices (FPT.AI) — council R24 picks:
    # thuminh: female, Southern, natural, best for hotline tone (primary);
    # banmai: neutral warm; linhsan: youthful; linh/mai alternatives.
    VOICES = {
        "thuminh": "thuminh",      # Female, Southern, natural (R24 primary)
        "banmai": "banmai",        # Female, neutral accent, warm
        "linhsan": "linhsan",      # Female, youthful
        "linh": "linh",            # Female, young, energetic
        "mai": "mai",              # Female, warm, clear
        "leminh": "leminh",        # Male, deep, professional
        "quynh": "quynh",          # Female, standard
        "hoa": "hoa",              # Female, soft
    }

    #: FPT.AI free tier: 500 chars per request. Keep 10% headroom (450).
    MAX_CHUNK_CHARS = 450
    #: Minimum payload size for a plausible MP3 (0-byte guard).
    MIN_AUDIO_BYTES = 100

    def __init__(
        self,
        api_key: str,
        voice: str = "thuminh",    # Council R24 primary (natural Southern)
        speed: float = 1.0,        # Council R19: default speed (0.9 sounded old)
        cache_dir: Path = Path("results/tts_cache"),
        output_format: str = "wav",
    ):
        self.api_key = api_key
        self.voice = self.VOICES.get(voice.lower(), voice)
        self.speed = speed
        self.cache_dir = Path(cache_dir)
        self.output_format = output_format.lower()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.api_url = "https://api.fpt.ai/hmi/tts/v5"
        #: Free-tier burst guard (council R20: saw 429 on consecutive requests).
        self._rate_limited_until = 0.0
        self._max_429_retries = 2
        self._429_cooldown_s = 60.0

    @staticmethod
    def _cache_key(text: str, voice: str, speed: float) -> str:
        return hashlib.sha256(f"{voice}|{speed}|{text}".encode("utf-8")).hexdigest()[:24]

    def _cached_path(self, text: str, speed: float) -> Path:
        return self.cache_dir / f"{self._cache_key(text, self.voice, speed)}.{self.output_format}"

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
                check=True, capture_output=True, timeout=60,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return False
        finally:
            list_file.unlink(missing_ok=True)

    def _synthesize_one(self, text: str, out_wav: Path) -> bool:
        """Synthesize a single <=450-char chunk. Returns True on success."""
        if time.monotonic() < self._rate_limited_until:
            raise RuntimeError("FPT.AI TTS: in 429 cooldown, skipping")

        headers = {
            "api-key": self.api_key,
            "speed": str(self.speed),
            "voice": self.voice,
        }

        last_exc: Exception | None = None
        for attempt in range(self._max_429_retries + 1):
            try:
                response = requests.post(
                    self.api_url,
                    headers=headers,
                    data=text.encode("utf-8"),
                    timeout=30
                )
                if response.status_code == 429:
                    last_exc = RuntimeError("FPT.AI TTS rate limit (429)")
                    self._rate_limited_until = time.monotonic() + self._429_cooldown_s
                    time.sleep(1.5 * (attempt + 1))
                    continue
                response.raise_for_status()
                break
            except requests.exceptions.HTTPError as exc:
                if getattr(exc.response, "status_code", None) == 429:
                    last_exc = exc
                    self._rate_limited_until = time.monotonic() + self._429_cooldown_s
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise RuntimeError(f"FPT.AI TTS request failed: {exc}") from exc
            except Exception as exc:
                raise RuntimeError(f"FPT.AI TTS request failed: {exc}") from exc
        else:
            raise RuntimeError(f"FPT.AI TTS request failed: {last_exc}")
        response_body = response.json()
        if response_body.get("error") != 0:
            raise RuntimeError(
                f"FPT.AI TTS error: {response_body.get('message', 'Unknown error')}"
            )

        audio_url = response_body.get("async")
        if not audio_url:
            raise RuntimeError("FPT.AI TTS: No audio URL in response")

        # Poll for audio file (council R20: 8s GET timeout, 20 attempts max,
        # 0-byte guard on the payload).
        audio_content = None
        for _ in range(20):
            try:
                audio_resp = requests.get(audio_url, timeout=8)
                payload = audio_resp.content
                if audio_resp.status_code == 200 and len(payload) > self.MIN_AUDIO_BYTES:
                    audio_content = payload
                    break
            except Exception:
                pass
            time.sleep(1)
        if audio_content is None:
            raise RuntimeError("FPT.AI TTS: Timeout waiting for audio generation")

        # Save audio (FPT.AI returns MP3)
        mp3_path = out_wav.with_suffix(".tmp.mp3")
        mp3_path.write_bytes(audio_content)

        # Convert to requested format
        if self.output_format == "wav":
            if self._convert_to_wav(mp3_path, out_wav):
                mp3_path.unlink(missing_ok=True)
                return True
            mp3_path.rename(out_wav)  # ffmpeg unavailable: keep raw bytes
        else:
            if mp3_path != out_wav:
                shutil.move(str(mp3_path), str(out_wav))
        return True

    def synthesize(
        self,
        text: str,
        output_path: str | Path,
        speed: Optional[float] = None,
    ) -> str:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        use_speed = speed if speed is not None else self.speed
        cached = self._cached_path(text, use_speed)

        if cached.exists():
            if cached.stat().st_size > self.MIN_AUDIO_BYTES:
                if out != cached:
                    shutil.copy2(cached, out)
                return str(out)
            cached.unlink(missing_ok=True)  # corrupt cache entry: drop it

        chunks = self._split_for_limit(text, self.MAX_CHUNK_CHARS)
        if len(chunks) == 1:
            if not self._synthesize_one(chunks[0], out):
                raise RuntimeError("FPT.AI TTS: synthesis failed")
        else:
            # Multi-chunk: synthesize each to a temp WAV, then concat.
            parts: list[Path] = []
            try:
                for idx, chunk in enumerate(chunks):
                    part = out.with_suffix(f".part{idx}.wav")
                    if not self._synthesize_one(chunk, part):
                        raise RuntimeError("FPT.AI TTS: chunk synthesis failed")
                    parts.append(part)
                    time.sleep(0.5)  # council R20: avoid free-tier 429 on burst
                if not self._concat_wavs(parts, out):
                    raise RuntimeError("FPT.AI TTS: WAV concat failed (no ffmpeg?)")
            finally:
                for part in parts:
                    part.unlink(missing_ok=True)

        # Cache (only on success - never cache a failed/empty synth)
        if cached != out:
            shutil.copy2(out, cached)

        return str(out)
