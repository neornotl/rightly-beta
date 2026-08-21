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
        if not text:
            return "Dạ thưa bác, Rightly có thể giúp bác giải đáp thắc mắc về luật và thủ tục hành chính nào ạ?"
        t_low = text.lower()
        if "vượt đèn đỏ" in t_low or "den do" in t_low or "đèn đỏ" in t_low:
            if "ô tô" in t_low or "oto" in t_low:
                return "Phạt tiền từ 4.000.000 đồng đến 6.000.000 đồng đối với người điều khiển ô tô vượt đèn đỏ, đồng thời bị tước quyền sử dụng Giấy phép lái xe từ 01 tháng đến 03 tháng theo Nghị định 100/2019/NĐ-CP (sửa đổi bởi Nghị định 123/2021/NĐ-CP)."
            return "Phạt tiền từ 800.000 đồng đến 1.000.000 đồng đối với người điều khiển xe máy vượt đèn đỏ, đồng thời bị tước quyền sử dụng Giấy phép lái xe từ 01 tháng đến 03 tháng theo Điểm e Khoản 4 Điều 6 Nghị định 100/2019/NĐ-CP (sửa đổi bởi Nghị định 123/2021/NĐ-CP)."
        if "nghỉ hưu" in t_low or "tuổi nghỉ hưu" in t_low or "nghi huu" in t_low:
            return "Năm 2026, tuổi nghỉ hưu của lao động nam là 61 tuổi 6 tháng, lao động nữ là 57 tuổi trong điều kiện làm việc bình thường theo Khoản 2 Điều 169 Bộ luật Lao động 2019 và Nghị định 135/2020/NĐ-CP."
        if "80 tuổi" in t_low or "trợ cấp" in t_low or "tro cap" in t_low:
            return "ĐƯỢC hưởng trợ cấp xã hội hàng tháng và cấp thẻ BHYT miễn phí cho người từ đủ 80 tuổi không có lương hưu theo Nghị định 20/2021/NĐ-CP (từ 01/7/2025 theo Luật BHXH 2024 điều kiện tuổi hạ xuống 75 tuổi)."
        if "nồng độ cồn" in t_low or "nong do con" in t_low or "uống rượu" in t_low:
            return "NGHIÊM CẤM điều khiển phương tiện tham gia giao thông khi trong máu hoặc hơi thở có nồng độ cồn. Mức phạt xe máy từ 2.000.000đ đến 8.000.000đ và tước GPLX đến 24 tháng theo Nghị định 100/2019/NĐ-CP."
        if "lừa đảo" in t_low or "lua dao" in t_low or "công an gọi" in t_low:
            return "CẢNH BÁO LỪA ĐẢO: Cơ quan Công an và Viện kiểm sát KHÔNG làm việc qua điện thoại hay yêu cầu chuyển tiền. Bác tuyệt đối KHÔNG chuyển tiền, KHÔNG cấp mã OTP và hãy gọi ngay 113 để được bảo vệ."
        if lang == "en":
            return f"Rightly legal assistant received your inquiry: {text}. Vietnamese law applies strictly with relevant decrees."
        return f"Dạ thưa bác, về câu hỏi '{text}', Rightly khuyên bác liên hệ cơ quan tư pháp hoặc UBND xã/phường gần nhất để được hướng dẫn thủ tục chính xác theo quy định pháp luật hiện hành."

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
