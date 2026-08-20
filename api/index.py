"""Slim Vercel entrypoint without the optional ML stack."""

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="Rightly public demo")


class ChatRequest(BaseModel):
    session_id: str
    text: str


@app.get("/health")
def health():
    return {"status": "ok", "runtime": "public-slim", "models": "fallback-only"}


@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "index.html")


def fallback_answer(text: str) -> str:
    return (
        "Bản web public đang ở chế độ demo an toàn. Để tra cứu đầy đủ bằng "
        "Whisper và LLM local, hãy chạy start.bat trên máy của bạn. "
        "Câu hỏi đã được ghi nhận: " + text[:300]
    )


@app.post("/api/chat")
def chat(body: ChatRequest):
    reply = fallback_answer(body.text.strip())
    return {"reply": reply, "sources": [], "decision": "guide", "summary": "", "appropriate": True}


@app.post("/api/chat/stream")
def chat_stream(body: ChatRequest):
    reply = fallback_answer(body.text.strip())
    payload = [
        {"type": "progress", "percent": 100, "detail": "Chế độ demo public"},
        {"type": "answer", "reply": reply, "sources": [], "decision": "guide", "summary": "", "appropriate": True},
    ]
    body_text = "".join(f"data: {json.dumps(item, ensure_ascii=False)}\n\n" for item in payload)
    return StreamingResponse(iter([body_text]), media_type="text/event-stream")


@app.post("/api/tts")
def tts_unavailable():
    return {"detail": "Use local mode for TTS."}
