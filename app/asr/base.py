"""Base ASR interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


class AudioFormatError(ValueError):
    """Raised when an audio file is missing or has an unsupported format."""

    _SUPPORTED = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm", ".mp4"}

    def __init__(self, message: str = ""):
        super().__init__(message or "Unsupported or missing audio file.")


@dataclass(frozen=True)
class ASRResult:
    transcript: str
    latency_ms: float = 0.0
    backend: str = "mock"


class BaseASR(ABC):
    """Interface all ASR backends must implement."""

    name: str = "base"

    @abstractmethod
    def transcribe(self, audio_path: str | Path) -> ASRResult:
        """Transcribe an audio file to Vietnamese text."""

    @staticmethod
    def check_audio_file(path: str | Path) -> Path:
        """Validate that an audio file exists and has a supported extension."""
        p = Path(path)
        if not p.exists():
            raise AudioFormatError(f"Audio file not found: {p}")
        if not p.is_file():
            raise AudioFormatError(f"Not a regular file: {p}")
        if p.suffix.lower() not in AudioFormatError._SUPPORTED:
            raise AudioFormatError(
                f"Unsupported audio format {p.suffix!r}. "
                f"Supported: {sorted(AudioFormatError._SUPPORTED)}"
            )
        return p
