"""Mock ASR: reads a transcript from a companion .txt file or a parameter."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.asr.base import ASRResult, BaseASR


@dataclass
class MockASR(BaseASR):
    """Deterministic ASR stub.

    - If ``audio_path`` has a sibling ``.txt`` file, its content (first line,
      trimmed) is the transcript.
    - Otherwise the transcript is read from ``transcript_file`` (default:
      ``data/sources/demo_transcript.txt``).
    - If both fail, the configured ``fallback_text`` is used and
      ``used_fallback`` is set to True so callers can detect non-real ASR.
    """

    name: str = "mock"
    fallback_text: str = "Chế độ nghỉ hưu được quy định thế nào theo Luật Bảo hiểm xã hội?"
    transcript_file: Path = field(default=Path("data/sources/demo_transcript.txt"))
    latency_ms: float = 5.0
    used_fallback: bool = field(default=False, init=False)

    def transcribe(self, audio_path: str | Path) -> ASRResult:
        self.check_audio_file(audio_path)
        audio = Path(audio_path)
        sibling = audio.with_suffix(".txt")
        text: str | None = None
        if sibling.exists():
            text = self._read_first_line(sibling)
        if text is None and self.transcript_file.exists():
            text = self._read_first_line(self.transcript_file)
        if text is None:
            self.used_fallback = True
            text = self.fallback_text
        else:
            self.used_fallback = False
        return ASRResult(
            transcript=text.strip(),
            latency_ms=self.latency_ms,
            backend=self.name,
        )

    @staticmethod
    def _read_first_line(path: Path) -> str | None:
        try:
            first = path.read_text(encoding="utf-8").splitlines()
            if first and first[0].strip():
                return first[0].strip()
        except OSError:
            return None
        return None
