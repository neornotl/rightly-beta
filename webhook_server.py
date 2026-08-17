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
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

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