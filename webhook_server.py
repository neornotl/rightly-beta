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
import asyncio
import re

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


def _unwrap_reply(value: str) -> str:
    """Remove provider JSON envelopes before a response reaches the UI/TTS."""
    text = str(value or "").strip()
    if text.startswith("{"):
        try:
            obj = json.loads(text)
        except (TypeError, ValueError):
            obj = None
        if isinstance(obj, dict):
            for key in ("answer_text", "answer", "reply", "response"):
                candidate = obj.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    text = _unwrap_reply(candidate)
                    break
    text = re.sub(
        r"^\s*Trích dẫn:\s*(?:null|undefined|none|n/a|na)\s*$",
        "",
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    return re.sub(r"\n{3,}", "\n\n", text).strip()
import json
import queue
import secrets
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

# Only the browser-safe Supabase publishable/anon key is sent to the UI. A
# service-role key is never read by this server's public config endpoint.
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_PUBLIC_KEY = (
    os.getenv("SUPABASE_PUBLISHABLE_KEY")
    or os.getenv("SUPABASE_ANON_KEY")
    or ""
).strip()

# Rate limiter (per client IP)
_limiter = RateLimiter(
    limit=settings.rate_limit_per_ip,
    window_seconds=settings.rate_limit_window_seconds,
)
# Daily per-IP cap (abuse guard; 0 = disabled)
_daily_limiter = RateLimiter(
    limit=getattr(settings, "rate_limit_per_ip_daily", 0),
    window_seconds=86400,
)
# Off-topic/refusal counter: too many refused queries => likely abuse
_offtopic_limiter = RateLimiter(limit=25, window_seconds=3600)
_WARN_AT = getattr(settings, "rate_limit_warn_at", 0.8)


def _quota_denied(key: str) -> bool:
    """True when the hourly OR daily cap is exhausted."""
    if not _limiter.allow(key):
        return True
    if _daily_limiter.limit > 0 and not _daily_limiter.allow(f"d|{key}"):
        return True
    return False


def _quota_warning(key: str) -> Optional[str]:
    """Friendly heads-up when the client nears their hourly cap."""
    remaining = _limiter.remaining(key)
    if _limiter.limit <= 0 or remaining > max(1, int(_limiter.limit * (1 - _WARN_AT))):
        return None
    if remaining <= 0:
        return "Anh/chị đã dùng hết lượt tra cứu trong giờ này, xin quay lại sau ạ."
    return (
        f"Anh/chị còn khoảng {remaining} lượt tra cứu trong giờ này. "
        "Vui lòng chỉ hỏi các câu cần thiết để mọi người cùng được phục vụ ạ."
    )


def _offtopic_blocked(key: str) -> bool:
    # remaining() peeks WITHOUT recording; hits are recorded only on REFUSE.
    return _offtopic_limiter.remaining(f"o|{key}") <= 0

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
_local_memory = None


def get_pipeline() -> Pipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = Pipeline(settings=settings)
    return _pipeline


def get_local_memory():
    """Best-effort encrypted local memory; cloud/deploy modes never use it."""
    global _local_memory
    if _local_memory is not None or settings.app_mode != "local":
        return _local_memory
    try:
        from app.local_memory import LocalMemoryStore
        _local_memory = LocalMemoryStore(settings.local_memory_path, settings.local_memory_retention_days)
    except Exception as exc:
        logger.warning("Encrypted local memory unavailable: %s", exc)
        _local_memory = False
    return _local_memory if _local_memory is not False else None


def _restore_client_history(session_id: str, history: list[dict]) -> None:
    """Hydrate in-process memory after a browser reload."""
    if not history:
        return
    pipeline = get_pipeline()
    memory = getattr(pipeline, "_memory", None)
    if not isinstance(memory, dict) or session_id in memory:
        return
    turns = []
    pending_user = ""
    for item in history[-12:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "")).lower()
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        if role == "user":
            pending_user = content[:2000]
        elif role == "assistant" and pending_user:
            turns.append({"user": pending_user, "assistant": content[:4000], "action": "ANSWER", "chunks": []})
            pending_user = ""
    if turns:
        memory[session_id] = turns[-3:]


def _set_voice_language(request: Request) -> None:
    """Select Vietnamese, English, or Whisper auto-detect for microphone fallback."""
    requested = request.query_params.get("lang", "vi").lower()
    language = "en" if requested.startswith("en") else "vi" if requested.startswith("vi") else None
    asr = getattr(get_pipeline(), "asr", None)
    if settings.asr_backend == "whisper" and asr is not None and hasattr(asr, "language"):
        asr.language = language


def _local_chat_payload(body: "ChatRequest", request: Request) -> dict:
    client_ip = request.client.host if request.client else "unknown"
    key = f"web|{client_ip}"
    if _offtopic_blocked(key):
        raise HTTPException(status_code=429, detail="Bạn đã gửi quá nhiều câu ngoài phạm vi. Vui lòng thử lại sau ạ.")
    if _quota_denied(key):
        raise HTTPException(status_code=429, detail="Anh/chị đã vượt số lượt tra cứu cho phép. Xin vui lòng quay lại sau ạ.")
    if not _check_circuit():
        raise HTTPException(status_code=503, detail="Service temporarily unavailable")
    _restore_client_history(body.session_id, body.history)
    try:
        result = get_pipeline().process_text(body.session_id, body.text.strip())
        _record_success()
    except Exception as exc:
        _record_failure()
        logger.exception("Local chat pipeline error")
        raise HTTPException(status_code=502, detail="Chat backend unavailable") from exc
    answer = result.answer
    reply = _unwrap_reply(answer.answer_text if answer else result.decision.user_message)
    memory = get_local_memory()
    if memory:
        memory.append(body.session_id, "user", body.text.strip())
        memory.append(body.session_id, "assistant", reply)
    warning = _quota_warning(key)
    if answer is not None and getattr(getattr(result.decision, "action", None), "value", "") == "REFUSE":
        _offtopic_limiter.allow(f"o|{key}")
    return {"transcript": body.text.strip(), "reply": reply, "sources": list(answer.source_ids) if answer else [], "decision": result.decision.zone.value, "summary": answer.summary if answer else "", "appropriate": answer.appropriate if answer else None, "rate_warning": warning, "lang": _detect_lang(reply, body.lang)}


def _stream_display_chunks(text: str, max_chars: int = 96):
    """Split a completed local answer into readable SSE deltas."""
    remaining = str(text or "")
    while remaining:
        if len(remaining) <= max_chars:
            yield remaining
            return
        cut = max(remaining.rfind(" ", 0, max_chars), remaining.rfind("\n", 0, max_chars))
        if cut < max_chars // 2:
            cut = max_chars
        piece = remaining[:cut]
        rest = remaining[cut:]
        if rest.startswith((" ", "\n")):
            piece += rest[0]
            rest = rest[1:]
        yield piece
        remaining = rest.lstrip()


# Zalo webhook models
class ZaloMessage(BaseModel):
    message: Optional[dict] = None
    event_name: Optional[str] = None


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=1000)
    lang: str | None = None
    history: list[dict] = Field(default_factory=list)


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    lang: str | None = None


class MemorySyncRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    confirm: bool = False


# FastAPI lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Keep boot lightweight so the native window can open immediately.  The
    # first chat/ASR request initializes the pipeline on its worker thread;
    # the installer preflight still exercises that path before creating the
    # Desktop shortcut.
    logger.info("Starting webhook server...")
    yield
    # Shutdown
    logger.info("Shutting down...")


app = FastAPI(title="Rightly Webhook Server", lifespan=lifespan)


@app.middleware("http")
async def local_session_cookie(request: Request, call_next):
    """Issue a loopback-only browser session cookie for local deployments."""
    response = await call_next(request)
    if settings.app_mode == "local" and "rightly_session" not in request.cookies:
        response.set_cookie(
            "rightly_session",
            secrets.token_urlsafe(32),
            httponly=True,
            samesite="strict",
            secure=False,
            max_age=90 * 86400,
            path="/",
        )
    return response


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "circuit_open": _circuit_open,
        "pipeline": "ready" if _pipeline is not None else "lazy",
        "auth_configured": bool(SUPABASE_URL and SUPABASE_PUBLIC_KEY),
    }


@app.get("/api/config")
async def public_config():
    """Return browser-safe feature configuration, never provider secrets."""
    return {
        "supabase": {
            "enabled": bool(SUPABASE_URL and SUPABASE_PUBLIC_KEY),
            "url": SUPABASE_URL,
            "publishableKey": SUPABASE_PUBLIC_KEY,
        }
    }


@app.get("/")
async def local_chat_ui():
    return FileResponse(os.path.join(ROOT, "web", "index.html"))


@app.post("/api/chat")
async def local_chat(body: ChatRequest, request: Request):
    return _local_chat_payload(body, request)


@app.post("/api/chat/stream")
async def local_chat_stream(body: ChatRequest, request: Request):
    """SSE contract shared with the Vercel public handler."""
    async def events():
        task = asyncio.create_task(asyncio.to_thread(_local_chat_payload, body, request))
        percent = 5
        while not task.done():
            yield f"data: {json.dumps({'type': 'progress', 'percent': percent, 'detail': 'Rightly đang tra cứu'}, ensure_ascii=False)}\n\n"
            percent = min(90, percent + 10)
            await asyncio.sleep(1.0)
        try:
            payload = task.result()
        except HTTPException as exc:
            yield f"data: {json.dumps({'type': 'error', 'detail': exc.detail}, ensure_ascii=False)}\n\n"
            return
        except Exception as exc:
            logger.exception("Local chat stream failed")
            yield f"data: {json.dumps({'type': 'error', 'detail': 'Chat backend unavailable'}, ensure_ascii=False)}\n\n"
            return
        for piece in _stream_display_chunks(payload["reply"]):
            yield f"data: {json.dumps({'type': 'delta', 'text': piece}, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.015)
        yield f"data: {json.dumps({'type': 'progress', 'percent': 100, 'detail': 'Đã hoàn tất'}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'answer', 'reply': payload['reply'], 'sources': payload['sources'], 'summary': payload['summary'], 'appropriate': payload['appropriate'], 'lang': payload['lang']}, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/local-memory")
async def local_memory_history(session_id: str):
    memory = get_local_memory()
    return {"history": memory.history(session_id, limit=1000) if memory else [], "available": bool(memory)}


@app.delete("/api/local-memory")
async def local_memory_clear(session_id: str | None = None):
    memory = get_local_memory()
    deleted = memory.clear(session_id) if memory else 0
    if not session_id and settings.app_mode == "local":
        pipeline = get_pipeline()
        getattr(pipeline, "_memory", {}).clear()
        getattr(pipeline, "_hybrid_sessions", {}).clear()
    return {"deleted": deleted}


@app.post("/api/local-memory/sync")
async def local_memory_sync(body: MemorySyncRequest, request: Request):
    """Opt-in cloud backup; never runs merely because a network is present."""
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Explicit sync confirmation is required")
    token = request.headers.get("authorization", "")
    if not token.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Sign in to Supabase before syncing")
    memory = get_local_memory()
    if not memory:
        raise HTTPException(status_code=503, detail="Encrypted local memory is unavailable")
    try:
        from app.supabase_memory import SupabaseSync

        sync = SupabaseSync(token.split(" ", 1)[1].strip())
        sync.push(body.session_id, memory.history(body.session_id, limit=100))
    except Exception as exc:
        logger.warning("Supabase context sync failed: %s", exc)
        raise HTTPException(status_code=502, detail="Supabase sync unavailable") from exc
    return {"synced": True, "session_id": body.session_id}


@app.post("/api/voice")
async def local_voice(request: Request):
    """Transcribe a browser-recorded clip (webm/ogg/wav) and answer by voice.

    The audio is sent as raw bytes (Content-Type: application/octet-stream).
    Session is passed as ?session_id=... . Nothing is persisted: the temp
    audio file is deleted immediately after transcription.
    """
    client_ip = request.client.host if request.client else "unknown"
    key = f"web|{client_ip}"
    if _quota_denied(key):
        raise HTTPException(
            status_code=429,
            detail="Anh/chị đã vượt số lượt tra cứu cho phép. Xin vui lòng quay lại sau ạ.",
        )
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
        _set_voice_language(request)
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
        "reply": _unwrap_reply(answer.answer_text if answer else result.decision.user_message),
        "sources": list(answer.source_ids) if answer else [],
        "decision": result.decision.zone.value,
        "summary": answer.summary if answer else "",
        "appropriate": answer.appropriate if answer else None,
    }


@app.post("/api/voice/transcribe")
async def voice_transcribe_only(request: Request):
    """Transcribe-only endpoint matching the Vercel handler contract.

    The web UI's MediaRecorder fallback posts here; browser
    SpeechRecognition remains the primary input path.
    """
    client_ip = request.client.host if request.client else "unknown"
    key = f"web|{client_ip}"
    if _quota_denied(key):
        raise HTTPException(
            status_code=429,
            detail="Anh/chị đã vượt số lượt tra cứu cho phép. Xin vui lòng quay lại sau ạ.",
        )
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
    try:
        _set_voice_language(request)
        transcript = get_pipeline().transcribe_audio_bytes(
            audio, extension=request.query_params.get("ext", ".webm")
        )
        _record_success()
    except Exception as exc:
        _record_failure()
        logger.exception("Voice transcribe failed")
        raise HTTPException(status_code=502, detail="ASR unavailable") from exc
    return {"transcript": transcript}


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
        if settings.tts_backend == "piper" or settings.offline_mode:
            from app.tts.piper_tts import PiperTTS

            configured = settings.piper_model_path_en if lang.startswith("en") else settings.piper_model_path
            model_path = configured or str(
                settings.resolved_data_dir() / "voices" / (
                    "en_US-lessac-medium.onnx" if lang.startswith("en") else "vi_VN-vais1000-medium.onnx"
                )
            )
            tts = PiperTTS(model_path=model_path, cache_dir=settings.resolved_results_dir() / "tts_cache")
            out = Path(settings.resolved_results_dir()) / "tts_cache" / f"live_{uuid.uuid4().hex}.wav"
            path = tts.synthesize(text, out)
            media_type = "audio/wav"
        elif settings.tts_backend == "google" or any(
            os.getenv(name)
            for name in (
                "VERTEX_TTS_SERVICE_ACCOUNT_JSON",
                "VERTEX_TTS_ACCESS_TOKEN",
                "VERTEX_TTS_PROJECT",
                "GOOGLE_APPLICATION_CREDENTIALS",
                "GOOGLE_APPLICATION_CREDENTIALS_JSON",
            )
        ):
            from app.tts.google_cloud_tts import GoogleCloudTTS

            tts = GoogleCloudTTS(lang=lang)
            suffix = ".wav" if getattr(tts, "output_format", "mp3") == "wav" else ".mp3"
            out = Path(settings.resolved_results_dir()) / "tts_cache" / f"live_{uuid.uuid4().hex}{suffix}"
            path = tts.synthesize(text, out)
            media_type = "audio/wav" if suffix == ".wav" else "audio/mpeg"
        else:
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
            media_type = "audio/mpeg"
        if Path(path).suffix.lower() not in {".mp3", ".wav", ".ogg"}:
            raise RuntimeError("TTS returned no audio file")
    except Exception as exc:
        logger.exception("TTS synthesis failed")
        raise HTTPException(status_code=502, detail="TTS unavailable") from exc
    return FileResponse(path, media_type=media_type)


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
    if _quota_denied(f"zalo|{client_ip}"):
        raise HTTPException(
            status_code=429,
            detail="Anh/chị đã vượt số lượt tra cứu cho phép. Xin vui lòng quay lại sau ạ.",
        )

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
    # Rightly's desktop launcher and installer contract use 8010.  Hosted
    # deployments can still provide PORT explicitly (for example 8000).
    port = int(os.environ.get("PORT", 8010))
    uvicorn.run(app, host="127.0.0.1", port=port)
