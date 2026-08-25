"""Offline Piper TTS adapter.

The installer places a Vietnamese ``.onnx`` voice and its JSON sidecar in
``data/voices``.  This adapter deliberately uses an explicit model path and
never asks Piper to download a missing voice at runtime.
"""

from __future__ import annotations

import importlib
import wave
from pathlib import Path

from app.tts.base import BaseTTS


class PiperTTS(BaseTTS):
    name = "piper"

    def __init__(self, model_path: str | Path, cache_dir: str | Path = "results/tts_cache"):
        self.model_path = Path(model_path)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        if self.model_path.suffix.lower() != ".onnx":
            raise RuntimeError(f"Piper model must be .onnx: {self.model_path}")
        self.config_path = self.model_path.with_suffix(self.model_path.suffix + ".json")
        if not self.model_path.is_file() or not self.config_path.is_file():
            raise RuntimeError(
                "Piper voice is missing. Run the one-time offline setup again: "
                f"{self.model_path.name} and {self.config_path.name} are required."
            )
        self._voice = None

    def _load(self):
        if self._voice is not None:
            return self._voice
        try:
            module = importlib.import_module("piper.voice")
            voice_cls = getattr(module, "PiperVoice")
            try:
                self._voice = voice_cls.load(str(self.model_path), config_path=str(self.config_path))
            except TypeError:
                # Older piper-tts versions infer the sidecar from the model.
                self._voice = voice_cls.load(str(self.model_path))
        except Exception as exc:  # pragma: no cover - depends on optional binary wheel
            raise RuntimeError(f"Piper offline voice could not be loaded: {exc}") from exc
        return self._voice

    def synthesize(self, text: str, output_path: str | Path, rate: str = "+0%") -> str:
        text = " ".join(str(text or "").split()).strip()
        if not text:
            raise ValueError("Piper cannot synthesize empty text")
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        voice = self._load()
        try:
            with wave.open(str(out), "wb") as wav_file:
                # Current piper-tts exposes synthesize_wav(), which sets the
                # WAV rate/width/channel header from the first audio chunk.
                # Calling synthesize() directly leaves channels unset and
                # raises ``# channels not specified`` when wave closes.
                synthesize_wav = getattr(voice, "synthesize_wav", None)
                if callable(synthesize_wav):
                    synthesize_wav(text, wav_file)
                else:  # compatibility with older piper-tts releases
                    first_chunk = True
                    for chunk in voice.synthesize(text):
                        if first_chunk:
                            wav_file.setframerate(chunk.sample_rate)
                            wav_file.setsampwidth(chunk.sample_width)
                            wav_file.setnchannels(chunk.sample_channels)
                            first_chunk = False
                        wav_file.writeframes(chunk.audio_int16_bytes)
                    if first_chunk:
                        raise RuntimeError("Piper returned no audio chunks")
        except Exception as exc:
            out.unlink(missing_ok=True)
            raise RuntimeError(f"Piper synthesis failed: {exc}") from exc
        if not out.exists() or out.stat().st_size < 64:
            out.unlink(missing_ok=True)
            raise RuntimeError("Piper returned an empty audio file")
        return str(out)
