"""PhoWhisper ASR adapter (optional, lazy, transformers-based).

Loads the official ``vinai/PhoWhisper-base`` PyTorch checkpoint from the
HuggingFace cache (downloaded at runtime via ``huggingface_hub``) and
transcribes 16 kHz mono audio on CPU. No weights are committed to the repo.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.asr.base import ASRResult, BaseASR

_MODEL_ID = "vinai/PhoWhisper-base"
_SAMPLE_RATE = 16000


class PhoWhisperASR(BaseASR):
    """Whisper ASR tuned for Vietnamese (PhoWhisper-base), CPU, lazy load.

    The heavy imports (torch/transformers) happen lazily in ``_load`` so the
    rest of the app runs fine without them. Availability is reported without
    downloading anything; the first ``transcribe`` call downloads the model
    into the HF cache if it is not already there.
    """

    name = "phowhisper"

    def __init__(
        self,
        model_id: str = _MODEL_ID,
        device: str = "cpu",
        language: str = "vi",
        task: str = "transcribe",
        model_path: Optional[str] = None,
    ):
        self.model_id = model_id
        self.device = device
        self.language = language
        self.task = task
        self.model_path = model_path
        self._model = None
        self._processor = None
        self._model_error: Optional[str] = None

    def check_availability(self) -> tuple[bool, str]:
        """Return (available, message). Does NOT download anything."""
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401
        except ImportError:
            return False, (
                "torch/transformers are not installed. Run: pip install torch transformers"
            )
        if self._model_error:
            return False, self._model_error
        return True, "ready"

    def _load(self):
        if self._model is not None:
            return self._model, self._processor
        try:
            import torch  # noqa: F401
            from transformers import AutoProcessor, WhisperForConditionalGeneration
        except ImportError as exc:
            raise RuntimeError(
                "torch/transformers are not installed. Run: pip install torch transformers"
            ) from exc
        try:
            model = WhisperForConditionalGeneration.from_pretrained(
                self.model_path or self.model_id
            )
            model.eval()
            processor = AutoProcessor.from_pretrained(self.model_path or self.model_id)
        except Exception as exc:  # network errors, OOM, missing weights
            self._model_error = f"Failed to load PhoWhisper model: {exc}"
            raise RuntimeError(self._model_error) from exc
        self._model, self._processor = model, processor
        return model, processor

    @staticmethod
    def _decode_to_numpy(audio_path: str | Path) -> tuple[object, int]:
        """Decode audio to (float32 mono numpy array, 16000) using PyAV."""
        import av
        import numpy as np

        container = av.open(str(audio_path))
        audio_stream = next(s for s in container.streams if s.type == "audio")
        resampler = av.AudioResampler(format="fltp", layout="mono", rate=_SAMPLE_RATE)
        frames = []
        for frame in container.decode(audio_stream):
            for out_frame in resampler.resample(frame):
                frames.append(out_frame.to_ndarray())
        container.close()
        if not frames:
            raise RuntimeError("No audio frames decoded.")
        audio = np.concatenate(frames, axis=1).reshape(-1)
        return audio.astype("float32"), _SAMPLE_RATE

    def transcribe(self, audio_path: str | Path) -> ASRResult:
        import time

        import torch

        self.check_audio_file(audio_path)
        model, processor = self._load()
        audio, sr = self._decode_to_numpy(audio_path)
        inputs = processor(audio, sampling_rate=sr, return_tensors="pt").input_features
        start = time.perf_counter()
        with torch.no_grad():
            generated = model.generate(
                inputs,
                language=self.language,
                task=self.task,
                num_beams=5,
            )
        latency_ms = (time.perf_counter() - start) * 1000.0
        transcript = processor.decode(generated[0], skip_special_tokens=True).strip()
        if not transcript:
            raise RuntimeError("PhoWhisper returned empty transcript.")
        return ASRResult(
            transcript=transcript,
            latency_ms=round(latency_ms, 1),
            backend=self.name,
        )
