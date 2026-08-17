"""Base TTS interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from app.llm.prompts import shorten_spoken_citation
from app.schemas import PipelineResult


class BaseTTS(ABC):
    """Interface for text-to-speech backends."""

    name: str = "base"

    @abstractmethod
    def synthesize(
        self,
        text: str,
        output_path: str | Path,
        rate: str = "+0%",
    ) -> str:
        """Synthesize text to an audio file; return the written path."""

    def speak_result(self, result: PipelineResult) -> str:
        """High-level helper: build TTS text from a pipeline result."""
        if result.answer is None:
            text = result.decision.user_message
        else:
            parts = [result.answer.answer_text]
            if result.answer.spoken_citation:
                parts.append(shorten_spoken_citation(result.answer.spoken_citation))
            if result.answer.next_step:
                parts.append(result.answer.next_step)
            text = " ".join(parts)
        return text
