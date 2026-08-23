"""Zalo OA Webhook + Streamlit Cloud combined server (F3/F4).

Run:
    python webhook_server.py

Or with uvicorn:
    uvicorn webhook_server:app --host 0.0.0.0 --port 8000

Endpoints:
- GET  /health
- POST /zalo/webhook       # Zalo OA webhook (verification + message handling)
- GET  /streamlit          # Redirect to Streamlit (if running on same host)
"""

from __future__ import annotations

import os
import sys
import time
import logging

def _detect_lang(text: str, hint: str | None) -> str:
    """Pick the reply language. Hint from client wins; else detect."""
    if hint and hint.lower() in ("vi", "en"):
        return hint.lower()
    if not text:
        return "vi"
    try:
        import re
        if re.search(r"[ăâđêôơưăÂĐÊÔƠƯáàảãạằầậẳếẵẽềéèẻẹặệểễíìỉịẩọóòỏõọốộớởợờỡứúùủụựữửỳỹýỳỷỵỽ]", text):
            return "vi"
        letters = sum(1 for c in text if c.isascii() and c.isalpha())
        return "en" if letters >= 4 else "vi"
    except Exception:
        return "vi"
import json
import queue
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field

# Add project root to path
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.config import load_settings
from app.pipeline import Pipeline
from app.ratelimit import RateLimiter

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webhook")

# Settings
settings = load_settings()

# Rate limiter (per client IP)
_limiter = RateLimiter(
    limit=settings.rate_limit_per_ip,
    window_seconds=settings.rate_limit_window_seconds,
)

# Circuit breaker state
_circuit_open = False
_circuit_last_failure = 0.0
_CIRCUIT_THRESHOLD = 5
_CIRCUIT_WINDOW = 60.0  # seconds
_CIRCUIT_COOLDOWN = 30.0  # seconds


def _check_circuit() -> bool:
    """Return True if circuit is closed (allow requests)."""
    global _circuit_open, _circuit_last_failure
    now = time.monotonic()
    if _circuit_open:
        if now - _circuit_last_failure > _CIRCUIT_COOLDOWN:
            _circuit_open = False
            logger.info("Circuit breaker CLOSED (cooldown elapsed)")
            return True
        return False
    return True


def _record_failure():
    global _circuit_open, _circuit_last_failure
    _circuit_last_failure = time.monotonic()
    # Simple failure counting could be added here


def _record_success():
    global _circuit_open
    _circuit_open = False


# Pipeline singleton
_pipeline: Optional[Pipeline] = None


def get_pipeline() -> Pipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = Pipeline(settings=settings)
    return _pipeline


# Zalo webhook models
class ZaloMessage(BaseModel):
    message: Optional[dict] = None
    event_name: Optional[str] = None


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=1000)
    lang: str | None = None


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    lang: str | None = None


# FastAPI lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting webhook server...")
    # Warm up pipeline
    try:
        get_pipeline()
        logger.info("Pipeline ready")
    except Exception as e:
        logger.error(f"Pipeline init failed: {e}")
    yield
    # Shutdown
    logger.info("Shutting down...")


app = FastAPI(title="Rightly Webhook Server", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "circuit_open": _circuit_open, "pipeline": "ready"}


@app.get("/")
async def local_chat_ui():
    return FileResponse(os.path.join(ROOT, "web", "index.html"))


@app.post("/api/chat")
async def local_chat(body: ChatRequest, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    if not _limiter.allow(f"web|{client_ip}"):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    if not _check_circuit():
        raise HTTPException(status_code=503, detail="Service temporarily unavailable")
    try:
        result = get_pipeline().process_text(body.session_id, body.text.strip())
        _record_success()
    except Exception as exc:
        _record_failure()
        logger.exception("Local chat pipeline error")
        raise HTTPException(status_code=502, detail="Chat backend unavailable") from exc
    answer = result.answer
    """
    client_ip = request.client.host if request.client else "unknown"
    if not _limiter.allow(f"web|{client_ip}"):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    if not _check_circuit():
        raise HTTPException(status_code=503, detail="Service temporarily unavailable")
    if request.headers.get("content-length", "0").isdigit() and int(request.headers["content-length"]) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audio too large")
    try:
        audio = await request.body()
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read audio body")
    if not audio:
        raise HTTPException(status_code=400, detail="Empty audio body")
    logger.info(
        "VOICE_TRANSCRIBE received session=%s ext=%s bytes=%d ctype=%s",
        request.query_params.get("session_id", ""),
        request.query_params.get("ext", ".webm"),
        len(audio),
        request.headers.get("content-type", ""),
    )
    try:
        transcript = get_pipeline().transcribe_audio_bytes(
            audio, extension=request.query_params.get("ext", ".webm")
        )
        _record_success()
        logger.info("VOICE_TRANSCRIBE OK bytes=%d transcript=%r", len(audio), transcript)
    except Exception as exc:
        _record_failure()
        logger.exception("VOICE_TRANSCRIBE FAILED bytes=%d", len(audio))
        raise HTTPException(status_code=502, detail="ASR unavailable") from exc
    return {"transcript": transcript}


@app.post("/api/voice")
async def local_voice(request: Request):
    """Transcribe a browser-recorded clip (webm/ogg/wav) and answer by voice.

    The audio is sent as raw bytes (Content-Type: application/octet-stream).
    Session is passed as ?session_id=... . Nothing is persisted: the temp
    audio file is deleted immediately after transcription.
    """
    client_ip = request.client.host if request.client else "unknown"
    if not _limiter.allow(f"web|{client_ip}"):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    if not _check_circuit():
        raise HTTPException(status_code=503, detail="Service temporarily unavailable")
    session_id = request.query_params.get("session_id", "")
    if not session_id or len(session_id) > 100:
        raise HTTPException(status_code=400, detail="Missing session_id")
    if request.headers.get("content-length", "0").isdigit() and int(request.headers["content-length"]) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audio too large")
    try:
        audio = await request.body()
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read audio body")
    if not audio:
        raise HTTPException(status_code=400, detail="Empty audio body")
    try:
        result = get_pipeline().process_audio_bytes(
            session_id, audio, extension=request.query_params.get("ext", ".webm")
        )
        _record_success()
    except Exception as exc:
        _record_failure()
        logger.exception("Voice pipeline error")
        raise HTTPException(status_code=502, detail="Voice backend unavailable") from exc
    answer = result.answer
    return {
        "transcript": result.query,
        "reply": answer.answer_text if answer else result.decision.user_message,
        "sources": list(answer.source_ids) if answer else [],
        "decision": result.decision.zone.value,
        "summary": answer.summary if answer else "",
        "appropriate": answer.appropriate if answer else None,
    }


@app.delete("/api/session/{session_id}")
async def delete_local_session(session_id: str):
    get_pipeline().delete_session(session_id)
    return {"status": "ok"}


@app.post("/api/tts")
def local_tts(body: TTSRequest, request: Request):
    """Synthesize speech via Edge-TTS (vi-VN-HoaiMyNeural or en-US-*).

    The browser's built-in speechSynthesis often has no Vietnamese voice and
    falls back to an English voice that mispronounces Vietnamese text. This
    endpoint produces a real neural voice matching the requested language.
    The audio file is written to the project TTS cache and reused for
    identical text.

    Note: sync def on purpose — EdgeTTS calls asyncio.run() internally, which
    cannot run inside the FastAPI event loop (FastAPI executes sync defs in a
    threadpool).
    """
    client_ip = request.client.host if request.client else "unknown"
    if not _limiter.allow(f"web|{client_ip}"):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty text")
    lang = (body.lang or "vi").lower()
    voice_key = "hoaimy" if lang.startswith("vi") else "aria"
    try:
        from app.tts.edge_tts import EdgeTTS

        tts = EdgeTTS(
            voice=voice_key,
            rate="-10%",
            pitch="+0Hz",
            cache_dir=settings.resolved_results_dir() / "tts_cache",
            output_format="mp3",
        )
        out = Path(settings.resolved_results_dir()) / "tts_cache" / f"live_{uuid.uuid4().hex}.mp3"
        path = tts.synthesize(text, out)
        if Path(path).suffix.lower() not in {".mp3", ".wav", ".ogg"}:
            raise RuntimeError("TTS returned no audio file")
    except Exception as exc:
        logger.exception("TTS synthesis failed")
        raise HTTPException(status_code=502, detail="TTS unavailable") from exc
    return FileResponse(path, media_type="audio/mpeg")


@app.post("/zalo/webhook")
async def zalo_webhook(
    request: Request,
    x_zalo_signature: Optional[str] = Header(None),
):
    """Zalo OA webhook endpoint.

    Verification: Zalo sends a challenge request with `type=challenge`.
    Message handling: Zalo sends `event_name="user_send_text"` or similar.
    """
    # Rate limit by client IP
    client_ip = request.client.host if request.client else "unknown"
    if not _limiter.allow(f"zalo|{client_ip}"):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    # Circuit breaker
    if not _check_circuit():
        raise HTTPException(status_code=503, detail="Service temporarily unavailable (circuit open)")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Handle Zalo verification challenge
    if body.get("type") == "challenge":
        challenge = body.get("challenge", "")
        logger.info("Zalo verification challenge received")
        return JSONResponse({"challenge": challenge})

    # Handle incoming messages
    event_name = body.get("event_name")
    message = body.get("message", {})
    user_id = message.get("from_id") or message.get("user_id", "unknown")
    text = message.get("text", "").strip()

    logger.info(f"Zalo event: {event_name}, user: {user_id}, text: {text[:100]}")

    if not text:
        return JSONResponse({"status": "ok", "message": "empty text ignored"})

    # Process through pipeline
    pipeline = get_pipeline()
    session_id = f"zalo_{user_id}"

    try:
        result = pipeline.process_text(session_id, text)
        _record_success()
    except Exception as e:
        _record_failure()
        logger.error(f"Pipeline error: {e}")
        # Graceful fallback response
        return JSONResponse({
            "status": "error",
            "reply": "Hiện tại tôi chưa tìm được căn cứ pháp lý đủ tin cậy. Vui lòng liên hệ cán bộ địa phương hoặc gọi lại sau."
        })

    # Build response
    if result.answer:
        reply = result.answer.answer_text
        if len(reply) > 1000:
            reply = reply[:1000] + "... (xem đầy đủ trên web)"
    else:
        reply = result.decision.user_message

    return JSONResponse({
        "status": "ok",
        "reply": reply,
        "decision": result.decision.zone.value,
        "session_id": session_id,
    })


# Streamlit redirect (optional - for single-host deployment)
@app.get("/streamlit")
async def streamlit_redirect():
    return RedirectResponse(url="/")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
