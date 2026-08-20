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
API_KEY = os.getenv("PATEWAY_API_KEY") or os.getenv("AI_API_KEY", "")
API_BASE_URL = os.getenv("PATEWAY_BASE_URL", "https://api.pateway.ai/v1")
MODEL = os.getenv("PATEWAY_MODEL", "gpt-5.6-luna")


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
        lang = str(payload.get("lang", "auto")).lower()
        if lang not in ("vi", "en", "auto"):
            lang = "auto"
        reply = self._fallback(text, lang)
        if API_KEY and text:
            try:
                reply = self._ask_api(text, lang)
            except Exception:
                reply = self._fallback(text, lang) + (" (API temporarily unavailable.)" if lang == "en" else " (API tạm thời không khả dụng.)")
        reply_lang = lang if lang in ("vi", "en") else self._detect_lang(reply)
        if self.path.startswith("/api/chat/stream"):
            events = [
                {"type": "progress", "percent": 100, "detail": "Public demo"},
                {"type": "answer", "reply": reply, "sources": [], "decision": "guide", "summary": "", "appropriate": True, "lang": reply_lang},
            ]
            body = "".join(f"data: {json.dumps(e, ensure_ascii=False)}\n\n" for e in events)
            self._send(200, "text/event-stream", body)
        elif self.path.startswith("/api/chat"):
            self._send(200, "application/json", json.dumps({"reply": reply, "sources": [], "lang": reply_lang}, ensure_ascii=False))
        else:
            self._send(404, "application/json", '{"detail":"Not found"}')

    @staticmethod
    def _fallback(text, lang):
        if lang == "en":
            return (
                "The public demo runs in safe mode. For full Whisper + LLM local "
                "search, run start.bat on your machine. Question received: " + text
            )
        return (
            "Bản web public đang ở chế độ demo an toàn. Để tra cứu đầy đủ bằng "
            "Whisper và LLM local, hãy chạy start.bat trên máy của bạn. "
            "Câu hỏi đã được ghi nhận: " + text
        )

    @staticmethod
    def _detect_lang(text):
        if not text:
            return "vi"
        import re
        if re.search(r"[ăâđêôơưáàảãạằẳẵặắấầẩẫậéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]", text):
            return "vi"
        letters = sum(1 for c in text if c.isascii() and c.isalpha())
        return "en" if letters >= 4 else "vi"

    @staticmethod
    def _ask_api(text, lang):
        if lang == "en":
            system_prompt = "You are Rightly, a concise and helpful Vietnamese legal/administrative assistant. Reply in English when the user writes in English."
        else:
            system_prompt = "Bạn là trợ lý Rightly. Trả lời bằng tiếng Việt, ngắn gọn và hữu ích."
        request = Request(
            API_BASE_URL.rstrip("/") + "/chat/completions",
            data=json.dumps({
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
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
