"""TTS Fallback Chain (F4): Primary → Fallback → Last Resort.

Council R19 (12/08): Zalo free tier (1-2 req/min) is NOT viable as primary.
  1. FPT.AI TTS      ← REQUIRED key (best natural VN voice, 20k req/mo free)
  2. Zalo AI TTS     ← optional key (demoted, small quota)
  3. Edge-TTS        ← always available (HoaiMyNeural, rate -15%, pitch +5Hz)
  4. gTTS            ← always available (decent)
  5. MockTTS         ← never fails, last resort
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from app.tts.base import BaseTTS
from app.tts.edge_tts import EdgeTTS
from app.tts.gtts_adapter import GTTS
from app.tts.mock_tts import MockTTS

logger = logging.getLogger(__name__)


class TTSFallback(BaseTTS):
    """Chained TTS backends with automatic fallback."""

    name = "fallback"

    def __init__(
        self,
        primary: Optional[BaseTTS] = None,
        fallback: Optional[BaseTTS] = None,
        last_resort: Optional[BaseTTS] = None,
        cache_dir: Path = Path("results/tts_cache"),
        output_format: str = "wav",
    ):
        self.cache_dir = Path(cache_dir)
        self.output_format = output_format
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Build backend chain based on available API keys (council R19 order).
        backends = []

        # 1. FPT.AI TTS (primary per council R19: best voice, roomiest quota)
        fpt_key = os.environ.get("FPT_AI_API_KEY")
        if fpt_key:
            try:
                from app.tts.fpt_ai_tts import FPTAI_TTS

                backends.append(FPTAI_TTS(
                    api_key=fpt_key,
                    voice="thuminh",
                    speed=1.0,
                    cache_dir=self.cache_dir,
                    output_format=output_format,
                ))
                logger.info("FPT.AI TTS enabled (primary)")
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Failed to init FPT.AI TTS: {exc}")

        # 2. Zalo AI TTS (demoted from primary - free tier 1-2 req/min)
        zalo_key = os.environ.get("ZALO_AI_API_KEY")
        if zalo_key:
            try:
                from app.tts.zalo_ai_tts import ZaloAI_TTS

                backends.append(ZaloAI_TTS(
                    api_key=zalo_key,
                    voice="south_female",
                    speed=0.9,
                    cache_dir=self.cache_dir,
                    output_format=output_format,
                ))
                logger.info("Zalo AI TTS enabled")
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Failed to init Zalo AI TTS: {exc}")

        # 3. Edge-TTS (always available; council R19: rate -15%, pitch +5Hz)
        backends.append(EdgeTTS(
            voice="hoaimy",
            rate="-15%",
            pitch="+5Hz",
            cache_dir=self.cache_dir,
            output_format=output_format,
        ))
        logger.info("Edge-TTS enabled")

        # 4. gTTS
        backends.append(GTTS(
            lang="vi",
            slow=False,
            cache_dir=self.cache_dir,
            output_format=output_format,
        ))
        logger.info("gTTS enabled")

        # 5. MockTTS (last resort)
        backends.append(MockTTS())
        logger.info("MockTTS enabled (last resort)")

        self._backends = backends
        logger.info(f"TTS fallback chain: {' -> '.join(b.name for b in self._backends)}")

    def synthesize(
        self,
        text: str,
        output_path: str | Path,
        rate: Optional[str] = None,
        pitch: Optional[str] = None,
        slow: Optional[bool] = None,
        speed: Optional[float] = None,
    ) -> str:
        """Try each backend in order until one succeeds."""
        last_error = None

        for i, backend in enumerate(self._backends):
            try:
                # Pass backend-specific params
                kwargs = {}
                if hasattr(backend, 'synthesize'):
                    import inspect

                    sig = inspect.signature(backend.synthesize)
                    if 'rate' in sig.parameters:
                        kwargs['rate'] = rate
                    if 'pitch' in sig.parameters:
                        kwargs['pitch'] = pitch
                    if 'slow' in sig.parameters:
                        kwargs['slow'] = slow
                    if 'speed' in sig.parameters:
                        kwargs['speed'] = speed

                result = backend.synthesize(text, output_path, **kwargs)
                if i > 0:
                    logger.warning(
                        f"TTS fallback used: {backend.name} (primary {self._backends[0].name} failed)"
                    )
                return result
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning(f"TTS backend {backend.name} failed: {exc}")
                continue

        # Should never reach here (MockTTS never fails)
        raise RuntimeError(f"All TTS backends failed. Last error: {last_error}")

    @property
    def active_backend(self) -> str:
        return self._backends[0].name if self._backends else "none"

    def get_backend_status(self) -> dict:
        """Return status of all backends for health checks."""
        return {
            b.name: {"name": b.name, "available": True, "priority": i}
            for i, b in enumerate(self._backends)
        }
