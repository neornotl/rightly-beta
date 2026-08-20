"""Dependency-free Vercel public fallback handler.

The full FastAPI app lives in ``webhook_server.py`` for local/Docker use.
This public function deliberately uses only the Python standard library so a
serverless build cannot fail on ML or web-framework dependencies.
"""

import json
import os
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
API_KEY = os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY", "")
API_BASE_URL = os.getenv("AI_BASE_URL") or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
MODEL = os.getenv("AI_MODEL") or os.getenv("OPENAI_MODEL", "gpt-4o-mini")


class handler(BaseHTTPRequestHandler):
    def _send(self, status, content_type, body):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/health":
            self._send(200, "application/json", json.dumps({
                "status": "ok", "runtime": "public-api", "models": MODEL if API_KEY else "fallback-only"
            }))
            return
        page = (ROOT / "web" / "index.html").read_bytes()
        self._send(200, "text/html; charset=utf-8", page)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send(400, "application/json", '{"detail":"Invalid JSON"}')
            return
        text = str(payload.get("text", "")).strip()[:300]
        reply = self._fallback(text)
        if API_KEY and text:
            try:
                reply = self._ask_api(text)
            except Exception:
                reply = self._fallback(text) + " (API tạm thời không khả dụng.)"
        if self.path.startswith("/api/chat/stream"):
            events = [
                {"type": "progress", "percent": 100, "detail": "Chế độ demo public"},
                {"type": "answer", "reply": reply, "sources": [], "decision": "guide", "summary": "", "appropriate": True},
            ]
            body = "".join(f"data: {json.dumps(e, ensure_ascii=False)}\n\n" for e in events)
            self._send(200, "text/event-stream", body)
        elif self.path.startswith("/api/chat"):
            self._send(200, "application/json", json.dumps({"reply": reply, "sources": []}, ensure_ascii=False))
        else:
            self._send(404, "application/json", '{"detail":"Not found"}')

    @staticmethod
    def _fallback(text):
        return (
            "Bản web public đang ở chế độ demo an toàn. Để tra cứu đầy đủ bằng "
            "Whisper và LLM local, hãy chạy start.bat trên máy của bạn. "
            "Câu hỏi đã được ghi nhận: " + text
        )

    @staticmethod
    def _ask_api(text):
        request = Request(
            API_BASE_URL.rstrip("/") + "/chat/completions",
            data=json.dumps({
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": "Bạn là trợ lý Rightly. Trả lời bằng tiếng Việt, ngắn gọn và hữu ích."},
                    {"role": "user", "content": text},
                ],
                "temperature": 0.2,
            }).encode("utf-8"),
            headers={"Authorization": "Bearer " + API_KEY, "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=25) as response:
            data = json.loads(response.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Provider returned empty content")
        return content.strip()
