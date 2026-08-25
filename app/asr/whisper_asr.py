"""Local Whisper ASR adapter using faster-whisper (fully offline).

Transcribes Vietnamese speech locally via the CTranslate2-based
``faster-whisper`` engine. Model weights are downloaded once into the
HuggingFace cache on first use, then everything runs on this machine.

Engine options (smaller = faster/lighter, larger = more accurate):
    OLLAMA-free: WHISPER_MODEL=base|small|medium
  Recommended for i5 + RTX 3060 Ti 8GB: small (fast, good VN accuracy).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

from app.asr.base import ASRResult, BaseASR

logger = logging.getLogger("whisper_asr")

_SAMPLE_RATE = 16000

# A short Vietnamese hint biases Whisper toward Vietnamese output and reduces
# the common "English hallucination" of small base models.
_INITIAL_PROMPT = (
    "Đây là câu hỏi bằng tiếng Việt về thủ tục hành chính và pháp luật. "
    "Ví dụ: thủ tục cấp giấy xác nhận tình trạng hôn nhân, đăng ký khai sinh, "
    "cấp lại hộ khẩu, đăng ký kết hôn, giấy tờ cần chuẩn bị."
)


class WhisperASR(BaseASR):
    """faster-whisper adapter, lazy-loaded so the app boots without it."""

    name = "whisper"

    def __init__(
        self,
        model_size: str = "small",
        device: str = "auto",
        language: Optional[str] = "vi",
        compute_type: str = "default",
        model_path: Optional[str] = None,
    ):
        self.model_size = model_size
        self.device = device
        self.language = language
        self.compute_type = compute_type
        self.model_path = model_path
        self._model = None
        self._error: Optional[str] = None

    def check_availability(self) -> tuple[bool, str]:
        try:
            from faster_whisper import WhisperModel  # noqa: F401
        except ImportError:
            return False, "faster-whisper is not installed. pip install faster-whisper"
        if self._error:
            return False, self._error
        return True, "ready"

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "faster-whisper is not installed. pip install faster-whisper"
            ) from exc
        # CTranslate2 does not support int8 efficiently on every Windows CPU
        # backend.  Start with the user's/default choice, then fall back to a
        # compatible float32 CPU load instead of making setup fail forever.
        candidates: list[tuple[str, str]] = [(self.device, self.compute_type)]
        if self.compute_type in {"default", "int8", "int8_float16"}:
            candidates.append((self.device, "float32"))
        if self.device == "auto":
            candidates.append(("cpu", "float32"))

        errors: list[str] = []
        seen: set[tuple[str, str]] = set()
        for load_device, load_compute in candidates:
            if (load_device, load_compute) in seen:
                continue
            seen.add((load_device, load_compute))
            try:
                self._model = WhisperModel(
                    self.model_path or self.model_size,
                    device=load_device,
                    compute_type=load_compute,
                    local_files_only=bool(self.model_path),
                )
                self.device = load_device
                self.compute_type = load_compute
                return self._model
            except Exception as exc:
                errors.append(f"{load_device}/{load_compute}: {exc}")

        self._error = "Failed to load Whisper model: " + " | ".join(errors)
        raise RuntimeError(self._error)

    def transcribe(self, audio_path: str | Path) -> ASRResult:
        self.check_audio_file(audio_path)
        try:
            return self._transcribe_once(self._load(), audio_path)
        except RuntimeError as exc:
            msg = str(exc)
            # GPU picked by "auto" but the CUDA/cuDNN libs are missing
            # (e.g. cublas64_12.dll). Re-initialize on CPU and retry once so
            # the app still hears the user instead of failing.
            if self.device != "cpu" and any(
                token in msg.lower()
                for token in ("cublas", "cudnn", "cannot be loaded", "not found")
            ):
                logger.warning("Whisper GPU backend failed (%s); retrying on CPU", msg)
                self.device = "cpu"
                self._model = None
                self._error = None
                return self._transcribe_once(self._load(), audio_path)
            raise

    def _transcribe_once(self, model: object, audio_path: str | Path) -> ASRResult:
        start = time.perf_counter()
        try:
            transcribe_options = {
                "language": self.language,
                "vad_filter": True,
                "vad_parameters": {"threshold": 0.5, "min_silence_duration_ms": 300},
                "beam_size": 5,
                "best_of": 5,
                "temperature": (0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
                "condition_on_previous_text": False,
                "compression_ratio_threshold": 2.2,
                "log_prob_threshold": -1.2,
                "no_speech_threshold": 0.6,
            }
            if self.language in {None, "vi"}:
                transcribe_options["initial_prompt"] = _INITIAL_PROMPT
            segments, info = model.transcribe(
                str(audio_path),
                **transcribe_options,
            )
            transcript = " ".join(seg.text.strip() for seg in segments).strip()
        except Exception as exc:
            self._error = f"Whisper transcribe failed: {exc}"
            raise RuntimeError(self._error) from exc
        latency_ms = (time.perf_counter() - start) * 1000.0
        if not transcript:
            raise RuntimeError("Whisper returned empty transcript.")
        return ASRResult(
            transcript=transcript,
            latency_ms=round(latency_ms, 1),
            backend=self.name,
        )
