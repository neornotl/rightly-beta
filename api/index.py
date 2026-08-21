"""Dependency-free Vercel public fallback handler.

The full FastAPI app lives in ``webhook_server.py`` for local/Docker use.
This public function deliberately uses only the Python standard library so a
serverless build cannot fail on ML or web-framework dependencies.
"""

import json
import os
import base64
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
PATEWAY_KEY = (
    os.getenv("PATEWAY_API_KEY")
    or os.getenv("AI_API_KEY")
    or "[REDACTED]"
)
PATEWAY_BASE_URL = os.getenv("PATEWAY_BASE_URL", "https://api.pateway.ai/v1")
PATEWAY_MODEL = os.getenv("PATEWAY_MODEL", "gpt-5.6-luna")

GROQ_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "llama-3.3-70b-versatile"


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
                "status": "ok", "runtime": "public-api", "models": PATEWAY_MODEL if PATEWAY_KEY else "groq-fallback"
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
        reply = self._ask_api(text, lang) if text else self._fallback(text, lang)
        reply_lang = lang if lang in ("vi", "en") else self._detect_lang(reply)
        if self.path.startswith("/api/chat/stream"):
            events = [
                {"type": "progress", "percent": 100, "detail": "Rightly AI"},
                {"type": "answer", "reply": reply, "sources": ["Văn bản pháp luật"], "decision": "guide", "summary": "", "appropriate": True, "lang": reply_lang},
            ]
            body = "".join(f"data: {json.dumps(e, ensure_ascii=False)}\n\n" for e in events)
            self._send(200, "text/event-stream", body)
        elif self.path.startswith("/api/chat"):
            self._send(200, "application/json", json.dumps({"reply": reply, "sources": ["Văn bản pháp luật"], "lang": reply_lang}, ensure_ascii=False))
        elif self.path.startswith("/api/tts"):
            self._tts(payload)
        else:
            self._send(404, "application/json", '{"detail":"Not found"}')

    def _tts(self, payload):
        text = str(payload.get("text", "")).strip()
        if not text:
            self._send(400, "application/json", '{"detail":"Empty text"}')
            return
        lang = str(payload.get("lang", "vi")).lower()
        tl = "vi" if lang.startswith("vi") else "en"
        import re
        clean_text = re.sub(r"[*_#`~]", "", text).strip()
        # Take first 140 chars for reliable high-speed Google Translate TTS stream
        spoken_text = clean_text[:140] if len(clean_text) > 140 else clean_text
        from urllib.parse import quote
        url = "https://translate.google.com/translate_tts?ie=UTF-8&q=" + quote(spoken_text) + "&tl=" + tl + "&client=tw-ob"
        req = Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://translate.google.com/",
        })
        try:
            with urlopen(req, timeout=12) as resp:
                data = resp.read()
        except Exception as exc:
            self._send(502, "application/json", json.dumps({"detail": "TTS unavailable: " + str(exc)}))
            return
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(data)

    @staticmethod
    def _fallback(text, lang):
        if lang == "en":
            return (
                "Rightly assistant received your question: " + text + ". Please try again in a few seconds."
            )
        return (
            "Dạ thưa bác, Rightly đã ghi nhận câu hỏi: " + text + ". Hệ thống đang tra cứu dữ liệu, bác vui lòng thử lại sau vài giây nhé."
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

    @classmethod
    def _ask_api(cls, text, lang):
        if lang == "en":
            system_prompt = (
                "You are Rightly, a concise Vietnamese legal & administrative assistant. "
                "Reply in English, conclude first, under 80 words."
            )
        else:
            system_prompt = (
                "Bạn là trợ lý Rightly (Tiếng Làng) hỗ trợ người dân và người cao tuổi Việt Nam về pháp luật và thủ tục hành chính. "
                "Hãy trả lời bằng tiếng Việt lễ phép, ân cần, đưa kết luận ĐƯỢC/KHÔNG ĐƯỢC/MỨC PHẠT lên ngay đầu câu (Luật 5 từ đầu), "
                "ngắn gọn súc tích dưới 80 từ, nếu hỏi về mức phạt giao thông hãy nêu rõ số tiền phạt và hình phạt bổ sung (nếu có), "
                "kèm trích dẫn tên văn bản (Nghị định 100/2019/NĐ-CP hoặc Nghị định 123/2021/NĐ-CP...)."
            )

        # 1) Try Pateway (gpt-5.6-luna)
        if PATEWAY_KEY:
            try:
                payload = {
                    "model": PATEWAY_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": text},
                    ],
                }
                req = Request(
                    PATEWAY_BASE_URL.rstrip("/") + "/chat/completions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Authorization": "Bearer " + PATEWAY_KEY,
                        "Content-Type": "application/json",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Rightly/1.0",
                        "Accept": "application/json",
                    },
                    method="POST",
                )
                with urlopen(req, timeout=12) as response:
                    data = json.loads(response.read().decode("utf-8"))
                content = data["choices"][0]["message"]["content"]
                if isinstance(content, str) and content.strip():
                    return content.strip()
            except Exception:
                pass

        # 2) High-speed fallback to Groq (llama-3.3-70b-versatile)
        if GROQ_KEY:
            try:
                payload = {
                    "model": GROQ_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": text},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 300,
                }
                req = Request(
                    GROQ_BASE_URL.rstrip("/") + "/chat/completions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Authorization": "Bearer " + GROQ_KEY,
                        "Content-Type": "application/json",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Rightly/1.0",
                        "Accept": "application/json",
                    },
                    method="POST",
                )
                with urlopen(req, timeout=10) as response:
                    data = json.loads(response.read().decode("utf-8"))
                content = data["choices"][0]["message"]["content"]
                if isinstance(content, str) and content.strip():
                    return content.strip()
            except Exception:
                pass

        return cls._fallback(text, lang)
