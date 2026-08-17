"""Mock TTS: writes the spoken text to a .txt (and metadata) file."""

from __future__ import annotations

from pathlib import Path

from app.tts.base import BaseTTS


class MockTTS(BaseTTS):
    """Deterministic stub that never touches audio hardware.

    Writes ``<stem>.spoken.txt`` next to the requested output path and a small
    JSON sidecar; the requested ``.wav`` file is NOT created (documented
    behavior) so no fake audio is ever produced.
    """

    name = "mock"

    def synthesize(
        self,
        text: str,
        output_path: str | Path,
        rate: str = "+0%",
    ) -> str:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        txt_path = out.with_suffix(out.suffix + ".spoken.txt")
        txt_path.write_text(text, encoding="utf-8")
        return str(txt_path)
