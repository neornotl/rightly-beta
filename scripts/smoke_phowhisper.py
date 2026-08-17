"""Smoke test: PhoWhisper-base real ASR on a short Vietnamese audio clip.

Usage:
    python scripts/smoke_phowhisper.py [--audio path/to/file.mp3]

If --audio is omitted, a synthetic clip is generated with Edge-TTS.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _make_synthetic_audio(path: Path) -> None:
    import edge_tts

    text = "Xin chào, tôi cần đăng ký giấy khai sinh cho con tôi tại ủy ban nhân dân phường."

    async def _save() -> None:
        tts = edge_tts.Communicate(text, "vi-VN-HoaiMyNeural", rate="+0%")
        await tts.save(str(path))

    asyncio.run(_save())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", type=str, default=None)
    args = parser.parse_args()

    audio: Path
    if args.audio:
        audio = Path(args.audio)
    else:
        audio = ROOT / "logs" / "smoke_phowhisper.mp3"
        audio.parent.mkdir(exist_ok=True)
        _make_synthetic_audio(audio)

    from app.asr.phowhisper_asr import PhoWhisperASR

    asr = PhoWhisperASR()
    ok, msg = asr.check_availability()
    print(f"availability: {ok} - {msg}")
    if not ok:
        return 1
    result = asr.transcribe(audio)
    print(f"audio: {audio.name}")
    print(f"transcript: {result.transcript}")
    print(f"latency_ms: {result.latency_ms}")
    print(f"backend: {result.backend}")
    return 0 if result.transcript.strip() else 2


if __name__ == "__main__":
    raise SystemExit(main())
