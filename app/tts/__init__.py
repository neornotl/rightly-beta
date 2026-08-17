"""TTS package: speech-synthesis adapters."""

from app.tts.base import BaseTTS
from app.tts.edge_tts import EdgeTTS
from app.tts.fallback import TTSFallback
from app.tts.fpt_ai_tts import FPTAI_TTS
from app.tts.gtts_adapter import GTTS
from app.tts.mock_tts import MockTTS
from app.tts.zalo_ai_tts import ZaloAI_TTS

__all__ = [
    "BaseTTS",
    "EdgeTTS",
    "FPTAI_TTS",
    "GTTS",
    "MockTTS",
    "TTSFallback",
    "ZaloAI_TTS",
]
