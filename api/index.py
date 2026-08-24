"""Dependency-free Vercel public fallback handler.

The full FastAPI app lives in ``webhook_server.py`` for local/Docker use.
This public function deliberately uses only the Python standard library so a
serverless build cannot fail on ML or web-framework dependencies.
"""

import json
import math
import os
import re
import sys
import uuid
import gzip
import base64
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent

# Secrets must be configured in Vercel Environment Variables.  Do not add a
# source-code fallback: it would be public in Git and impossible to rotate
# safely after a leak.
PATEWAY_KEY = os.getenv("PATEWAY_API_KEY") or os.getenv("AI_API_KEY")
PATEWAY_BASE_URL = os.getenv("PATEWAY_BASE_URL", "https://api.pateway.ai/v1")
PATEWAY_MODEL = os.getenv("PATEWAY_MODEL", "gpt-5.6-luna")

GROQ_KEY = os.getenv("GROQ_API_KEY")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
# `llama-3.3-70b-versatile` was retired by Groq on 2026-08-16.
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

# Google Gemini (primary). Keys starting with "AQ." are Vertex AI
# express-mode credentials and must hit the aiplatform endpoint; classic
# "AIza..." keys use the generativelanguage developer endpoint.
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
try:
    GEMINI_THINKING = int(os.getenv("GEMINI_THINKING_BUDGET", "512"))
except ValueError:
    GEMINI_THINKING = 512

# Per-IP abuse guard for the PUBLIC page (single warm instance, best-effort).
RATE_LIMIT_PER_IP = int(os.getenv("RATE_LIMIT_PER_IP", "20"))
RATE_LIMIT_WARN_AT = float(os.getenv("RATE_LIMIT_WARN_AT", "0.8"))
_RL_HITS: dict[str, list[float]] = {}

# ---------------------------------------------------------------------------
# Compact BM25 retrieval pack (built by scripts/build_vercel_rag.py).
# Grounds the public web app on the real legal corpus without any heavy deps.
# ---------------------------------------------------------------------------
_RAG: dict | None = None
_RAG_STOP = {
    "toi", "ban", "ong", "ba", "chu", "co", "chau", "em", "anh", "chi", "cua",
    "va", "voi", "la", "thi", "ma", "de", "cho", "tai", "o", "khong", "phai",
    "nen", "se", "da", "dang", "duoc", "bi", "nay", "kia", "day", "gi", "nao",
    "sao", "vi", "nhung", "hay", "hoac", "neu", "cung", "rat", "cac", "mot",
    "can", "muon", "hoi", "giup", "khi", "vao", "ra", "len", "xuong", "di",
    "lai", "xem", "con", "deu", "moi", "nguoi", "the", "lam",
}


def _rag_norm_tokens(text: str) -> list[str]:
    t = text.replace("đ", "d").replace("Đ", "D")
    t = unicodedata_normalize(t)
    return [t for t in re.findall(r"[a-z0-9]+", t) if t not in _RAG_STOP]


def unicodedata_normalize(text: str) -> str:
    import unicodedata as _ud

    t = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in t if not _ud.combining(ch)).casefold()


def _rag() -> dict:
    global _RAG
    if _RAG is None:
        base = Path(__file__).resolve().parent / "rag"
        try:
            with gzip.open(base / "index.json.gz", "rt", encoding="utf-8") as fh:
                idx = json.load(fh)
            with gzip.open(base / "texts.json.gz", "rt", encoding="utf-8") as fh:
                texts = json.load(fh)
            _RAG = {**idx, "texts": texts}
            print(
                json.dumps({"event": "rag_loaded", "n": idx.get("N", 0)}),
                file=sys.stderr,
                flush=True,
            )
        except Exception as exc:  # pack missing/corrupt: degrade gracefully
            print(
                json.dumps({"event": "rag_load_failed", "code": str(exc)[:120]}),
                file=sys.stderr,
                flush=True,
            )
            _RAG = {"N": 0}
    return _RAG


def _bm25_search(query: str, top_k: int = 6) -> list[dict]:
    """Pure-python BM25 over the shipped pack; mirrors app/bm25_retriever."""
    rag = _rag()
    if not rag.get("N"):
        return []
    q_tokens = _rag_norm_tokens(query)
    if not q_tokens:
        return []
    uniq = set(q_tokens)
    postings: dict = rag["postings"]
    doclens: list = rag["doclens"]
    meta: list = rag["meta"]
    texts: dict = rag["texts"]
    n = rag["N"]
    k1, b, avgdl = rag["k1"], rag["b"], rag["avgdl"]

    acc: dict[int, float] = {}
    for term in uniq:
        plist = postings.get(term)
        if not plist:
            continue
        df = len(plist)
        idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
        for idx, tf in plist:
            denom = tf + k1 * (1 - b + b * doclens[idx] / avgdl)
            acc[idx] = acc.get(idx, 0.0) + idf * (tf * (k1 + 1)) / denom

    # overlap guard (>=2 shared tokens for multi-token queries), then BM25 order
    scored = sorted(acc.items(), reverse=True)
    results: list[dict] = []
    sid_count: dict[str, int] = {}
    taken = 0
    for sc, idx in scored[:60]:
        m = meta[idx]
        if len(uniq) > 1:
            overlap = uniq & set(_rag_norm_tokens(texts.get(m["cid"], "")))
            if len(overlap) < 2:
                continue
        if sid_count.get(m["sid"], 0) >= 2 and taken < top_k:
            continue
        sid_count[m["sid"]] = sid_count.get(m["sid"], 0) + 1
        taken += 1
        results.append(
            {
                "cid": m["cid"],
                "sid": m["sid"],
                "title": m.get("ti", ""),
                "text": texts.get(m["cid"], ""),
                "score": round(sc, 3),
            }
        )
        if len(results) >= top_k:
            break
    return results


def _format_sources_block(hits: list[dict]) -> tuple[str, list[str]]:
    lines = []
    sids: list[str] = []
    for h in hits:
        lines.append(f"[{h['sid']}] {h['title']}\n{h['text']}")
        if h["sid"] not in sids:
            sids.append(h["sid"])
    return "\n\n".join(lines), sids[:4]


def _rate_check(ip: str) -> tuple[bool, int, str | None]:
    """(allowed, remaining, warning). Records one hit."""
    import time as _t

    now = _t.monotonic()
    hits = [t for t in _RL_HITS.get(ip, []) if now - t < 3600.0]
    if RATE_LIMIT_PER_IP <= 0 or len(hits) >= RATE_LIMIT_PER_IP:
        _RL_HITS[ip] = hits
        return False, 0, None
    hits.append(now)
    _RL_HITS[ip] = hits
    remaining = RATE_LIMIT_PER_IP - len(hits)
    warn = None
    if remaining <= max(1, int(RATE_LIMIT_PER_IP * (1 - RATE_LIMIT_WARN_AT))):
        warn = (
            f"Anh/chị còn khoảng {remaining} lượt tra cứu trong giờ này. "
            "Vui lòng chỉ hỏi các câu cần thiết để mọi người cùng được phục vụ ạ."
        )
    return True, remaining, warn


def _extract_json_obj(s: str):
    """Pull the first balanced {...} object even when strings contain raw
    newlines (models emit unescaped control chars despite JSON mime)."""
    start = s.find("{")
    if start == -1:
        return None
    depth = 0
    instr = False
    esc = False
    end = -1
    for i in range(start, len(s)):
        ch = s[i]
        if instr:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                instr = False
        else:
            if ch == '"':
                instr = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
    if end == -1:
        return None
    raw = s[start:end]
    # Repair unescaped control characters inside strings only.
    fixed: list[str] = []
    in_str = False
    esc2 = False
    for c in raw:
        if in_str:
            if esc2:
                esc2 = False
                fixed.append(c)
            elif c == "\\":
                esc2 = True
                fixed.append(c)
            elif c == '"':
                in_str = False
                fixed.append(c)
            elif c == "\n":
                fixed.append("\\n")
            elif c == "\r":
                pass
            elif c == "\t":
                fixed.append("\\t")
            else:
                fixed.append(c)
        else:
            if c == '"':
                in_str = True
            fixed.append(c)
    try:
        return json.loads("".join(fixed))
    except json.JSONDecodeError:
        return None


def _pick_answer(obj) -> str:
    if isinstance(obj, dict):
        for k in ("answer_text", "answer", "reply"):
            v = str(obj.get(k) or "").strip()
            if v:
                return v
        for v in obj.values():
            sv = str(v).strip()
            if len(sv) > 20:
                return sv
    elif isinstance(obj, list):
        for item in obj:
            t = _pick_answer(item)
            if t:
                return t
    return ""


def _loose_field(s: str, keys=("answer_text", "answer", "reply")) -> str:
    """Scan-based extraction of a top-level string field, tolerant of raw
    newlines and escaped/inner quotes inside the value."""
    for key in keys:
        marker = f'"{key}"'
        kpos = s.find(marker)
        while kpos != -1:
            i = kpos + len(marker)
            # skip whitespace then expect ':'
            while i < len(s) and s[i] in " \t\r\n":
                i += 1
            if i >= len(s) or s[i] != ":":
                kpos = s.find(marker, kpos + 1)
                continue
            i += 1
            while i < len(s) and s[i] in " \t\r\n":
                i += 1
            if i >= len(s) or s[i] != '"':
                kpos = s.find(marker, kpos + 1)
                continue
            i += 1
            out: list[str] = []
            while i < len(s):
                c = s[i]
                if c == "\\" and i + 1 < len(s):
                    nxt = s[i + 1]
                    pair = {"n": "\n", "t": "\t", "r": "", '"': '"', "\\": "\\"}
                    out.append(pair.get(nxt, "\\" + nxt))
                    i += 2
                    continue
                if c == '"':
                    return "".join(out).strip()
                out.append(c)
                i += 1
            # unterminated (raw newlines are fine — they stay literal)
            val = "".join(out).strip()
            if val:
                return val
            kpos = s.find(marker, kpos + 1)
    return ""


def _gemini_reply(system_prompt: str, text: str, history) -> str:
    """One Gemini call through stdlib only; raises on any failure."""
    key = str(GEMINI_KEY).strip()
    model = GEMINI_MODEL
    if key.startswith("AQ."):
        url = (
            "https://aiplatform.googleapis.com/v1beta1/publishers/google/models/"
            f"{model}:generateContent"
        )
        headers = {"x-goog-api-key": key}
    else:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={key}"
        )
        headers = {}
    gen_cfg: dict = {
        "temperature": 0.2,
        "maxOutputTokens": 700,
        "responseMimeType": "application/json",
    }
    if model.startswith("gemini-2.5") and GEMINI_THINKING >= 0:
        gen_cfg["thinkingConfig"] = {"thinkingBudget": GEMINI_THINKING}
    parts = [{"text": system_prompt}]
    for turn in (history or [])[-4:]:
        prefix = "Trả lời trước của Rightly: " if turn.get("role") == "assistant" else ""
        parts.append({"text": (prefix + str(turn.get("content", "")))[:1500]})
    parts.append({"text": text})
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": gen_cfg,
    }
    req = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urlopen(req, timeout=14) as response:
        data = json.loads(response.read().decode("utf-8"))
    cand = (data.get("candidates") or [{}])[0]
    content = "".join(
        p.get("text", "") for p in ((cand.get("content") or {}).get("parts") or [])
    )
    cleaned = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    obj = None
    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError:
        obj = _extract_json_obj(cleaned or content)
    reply_text = _pick_answer(obj) if obj is not None else ""
    if not reply_text:
        reply_text = _loose_field(cleaned or content)
    if reply_text:
        return reply_text
    if content.strip():
        return content.strip()
    raise RuntimeError("empty gemini response")


class LLMUnavailableError(RuntimeError):
    """Raised when no configured provider can produce an answer."""

    def __init__(self, failures: list[dict[str, str]]):
        self.failures = failures
        super().__init__("No LLM provider is available")


def _failure_code(exc: Exception) -> str:
    """Return a safe, compact error category for logs and diagnostics."""
    status = getattr(exc, "code", None)
    if isinstance(status, int):
        return f"http_{status}"
    if isinstance(exc, TimeoutError):
        return "timeout"
    return type(exc).__name__.lower()


def _log_provider_failure(provider: str, exc: Exception) -> None:
    """Emit a secret-free structured log that can be inspected in Vercel."""
    print(
        json.dumps(
            {"event": "llm_provider_failure", "provider": provider, "code": _failure_code(exc)}
        ),
        file=sys.stderr,
        flush=True,
    )


def _normalise_history(raw_history: object) -> list[dict[str, str]]:
    """Keep a small, user-supplied conversation window for stateless functions."""
    if not isinstance(raw_history, list):
        return []
    history: list[dict[str, str]] = []
    for turn in raw_history[-6:]:
        if not isinstance(turn, dict):
            continue
        role = str(turn.get("role", "")).lower()
        content = str(turn.get("content", "")).strip()
        if role not in {"user", "assistant"} or not content:
            continue
        history.append({"role": role, "content": content[:500]})
    return history


class handler(BaseHTTPRequestHandler):
    def _send(self, status, content_type, body):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("x-rightly-build", "v3-loosefield")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/health":
            providers = []
            if GROQ_KEY:
                providers.append("groq")
            if PATEWAY_KEY:
                providers.append("pateway")
            self._send(200, "application/json", json.dumps({
                "status": "ok",
                "runtime": "public-api",
                "llm_configured": bool(providers),
                "providers": providers,
            }))
            return
        page = (ROOT / "web" / "index.html").read_bytes()
        self._send(200, "text/html; charset=utf-8", page)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send(400, "application/json", '{"detail":"Invalid Content-Length"}')
            return
        raw = self.rfile.read(length) if length else b"{}"
        if path == "/api/voice/transcribe":
            self._transcribe_audio(raw)
            return
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send(400, "application/json", '{"detail":"Invalid JSON"}')
            return
        if path == "/api/tts":
            self._tts(payload)
            return
        if path not in {"/api/chat", "/api/chat/stream"}:
            self._send(404, "application/json", '{"detail":"Not found"}')
            return
        client_ip = self.headers.get("x-forwarded-for", "").split(",")[0].strip() or "anon"
        allowed, _remaining, warn = _rate_check(client_ip)
        if not allowed:
            self._send(
                429,
                "application/json",
                json.dumps(
                    {
                        "code": "RATE_LIMITED",
                        "detail": "Anh/chị đã vượt số lượt tra cứu cho phép trong giờ này. "
                        "Xin vui lòng quay lại sau ạ.",
                    },
                    ensure_ascii=False,
                ),
            )
            return
        text = str(payload.get("text", "")).strip()[:300]
        history = _normalise_history(payload.get("history"))
        lang = str(payload.get("lang", "auto")).lower()
        if lang not in ("vi", "en", "auto"):
            lang = "auto"

        # Ground the question on the shipped legal corpus before any LLM call.
        rag_hits = _bm25_search(text, top_k=6) if text else []
        sources_out: list[str] = ["Văn bản pháp luật"]
        if text:
            try:
                aug_text = text
                if rag_hits:
                    block, sids = _format_sources_block(rag_hits)
                    sources_out = sids
                    aug_text = (
                        f"{text}\n\n=== NGUỒN PHÁP LUẬT (CHỈ được dùng các đoạn dưới đây, "
                        f"KHÔNG bịa số liệu/tên văn bản ngoài nguồn) ===\n{block}\n"
                        f"=== HẾT NGUỒN ===\nNếu nguồn trên không đủ để trả lời chính xác, "
                        f"hãy nói thẳng 'hiện chưa có dữ liệu chính xác trong nguồn' và gợi ý "
                        f"liên hệ cơ quan có thẩm quyền. Kết thúc bằng dòng: "
                        f"Trích dẫn: <tên các văn bản đã dùng>."
                    )
                reply = self._ask_api(aug_text, lang, history)
            except LLMUnavailableError:
                self._send(
                    503,
                    "application/json",
                    json.dumps(
                        {
                            "code": "LLM_UNAVAILABLE",
                            "detail": "Dịch vụ trả lời AI đang tạm thời bận. Vui lòng thử lại sau ít phút.",
                        },
                        ensure_ascii=False,
                    ),
                )
                return
        else:
            reply = self._fallback(text, lang)
            rag_hits = []
        reply_lang = lang if lang in ("vi", "en") else self._detect_lang(reply)
        # Final safety net: any provider that wrapped its answer in a JSON
        # envelope gets unwrapped so the UI never shows raw JSON.
        if reply.lstrip().startswith("{"):
            fixed = _pick_answer(_extract_json_obj(reply))
            if not fixed:
                fixed = _loose_field(reply)
            if fixed:
                reply = fixed
        if path == "/api/chat/stream":
            events = [
                {"type": "progress", "percent": 100, "detail": "Rightly AI"},
                {"type": "answer", "reply": reply, "sources": sources_out, "decision": "guide", "summary": "", "appropriate": True, "lang": reply_lang},
            ]
            body = "".join(f"data: {json.dumps(e, ensure_ascii=False)}\n\n" for e in events)
            self._send(200, "text/event-stream", body)
        elif path == "/api/chat":
            body = {"reply": reply, "sources": sources_out, "lang": reply_lang}
            if warn:
                body["rate_warning"] = warn
            self._send(200, "application/json", json.dumps(body, ensure_ascii=False))

    def _transcribe_audio(self, audio: bytes):
        """Browser-audio transcription: Gemini (multimodal) first, Groq Whisper
        as fallback. Both are remote; this handler stays stdlib-only."""
        if not audio:
            self._send(400, "application/json", '{"detail":"Empty audio body"}')
            return
        if len(audio) > 20 * 1024 * 1024:
            self._send(413, "application/json", '{"detail":"Audio too large"}')
            return

        query = parse_qs(urlparse(self.path).query)
        ext = query.get("ext", [".webm"])[0].lower()
        if ext not in {".webm", ".ogg", ".m4a", ".mp3", ".wav"}:
            ext = ".webm"
        content_type = self.headers.get("Content-Type", "application/octet-stream").split(";", 1)[0]
        if not content_type.startswith("audio/"):
            content_type = "audio/webm" if ext == ".webm" else "application/octet-stream"

        failures: list[dict[str, str]] = []

        # 1) Gemini multimodal transcription (works with express keys).
        if GEMINI_KEY:
            try:
                mime_map = {
                    ".webm": "audio/webm",
                    ".ogg": "audio/ogg",
                    ".m4a": "audio/mp4",
                    ".mp3": "audio/mpeg",
                    ".wav": "audio/wav",
                }
                inline = {
                    "mime_type": mime_map.get(ext, "audio/webm"),
                    "data": base64.b64encode(audio).decode("ascii"),
                }
                payload = {
                    "contents": [
                        {
                            "role": "user",
                            "parts": [
                                {
                                    "text": (
                                        "Transcribe this audio recording verbatim in its "
                                        "spoken language. Output ONLY the transcript text, "
                                        "no commentary."
                                    )
                                },
                                {"inline_data": inline},
                            ],
                        }
                    ],
                    "generationConfig": {"temperature": 0.0, "maxOutputTokens": 300},
                }
                key = str(GEMINI_KEY).strip()
                if key.startswith("AQ."):
                    url = (
                        "https://aiplatform.googleapis.com/v1beta1/publishers/google/models/"
                        f"{GEMINI_MODEL}:generateContent"
                    )
                    headers = {"x-goog-api-key": key}
                else:
                    url = (
                        "https://generativelanguage.googleapis.com/v1beta/models/"
                        f"{GEMINI_MODEL}:generateContent?key={key}"
                    )
                    headers = {}
                req = Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json", **headers},
                    method="POST",
                )
                with urlopen(req, timeout=25) as response:
                    data = json.loads(response.read().decode("utf-8"))
                cand = (data.get("candidates") or [{}])[0]
                text = "".join(
                    p.get("text", "")
                    for p in ((cand.get("content") or {}).get("parts") or [])
                ).strip()
                if text:
                    self._send(200, "application/json", json.dumps({"transcript": text}, ensure_ascii=False))
                    return
                failures.append({"provider": "gemini_asr", "code": "empty_response"})
            except Exception as exc:
                _log_provider_failure("gemini_asr", exc)
                failures.append({"provider": "gemini_asr", "code": _failure_code(exc)})

        # 2) Groq Whisper fallback.
        if GROQ_KEY:
            boundary = f"----Rightly{uuid.uuid4().hex}"
            body = b"".join(
                [
                    f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\nwhisper-large-v3-turbo\r\n".encode(),
                    (
                        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                        f"filename=\"recording{ext}\"\r\nContent-Type: {content_type}\r\n\r\n"
                    ).encode(),
                    audio,
                    f"\r\n--{boundary}--\r\n".encode(),
                ]
            )
            try:
                request = Request(
                    GROQ_BASE_URL.rstrip("/") + "/audio/transcriptions",
                    data=body,
                    headers={
                        "Authorization": "Bearer " + str(GROQ_KEY).strip(),
                        "Content-Type": f"multipart/form-data; boundary={boundary}",
                        "Accept": "application/json",
                    },
                    method="POST",
                )
                with urlopen(request, timeout=20) as response:
                    transcript = str(json.loads(response.read().decode("utf-8")).get("text", "")).strip()
                self._send(200, "application/json", json.dumps({"transcript": transcript}, ensure_ascii=False))
                return
            except Exception as exc:
                _log_provider_failure("groq_asr", exc)
                failures.append({"provider": "groq_asr", "code": _failure_code(exc)})

        _log_provider_failure("asr_all", Exception(json.dumps(failures)))
        self._send(502, "application/json", '{"detail":"Speech recognition is temporarily unavailable"}')

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
        t_low = text.lower().strip()

        # 1. Chào hỏi & Giao tiếp thông thường (Greetings & Smalltalk)
        greetings = ("hello", "helo", "hi", "xin chào", "chào", "chao", "alo", "rightly ơi", "ơi", "hey", "good morning", "good evening")
        if any(t_low == g or t_low.startswith(g + " ") or t_low.endswith(" " + g) for g in greetings) or t_low in ("bạn là ai", "ai đó", "tro ly gi", "bạn tên gì", "la ai"):
            if lang == "en":
                return "Hello! I am Rightly, your dedicated Vietnamese legal and administrative assistant. How can I help you today?"
            return "Dạ, Rightly xin chào bác! Rightly là trợ lý tư vấn pháp luật và thủ tục hành chính cho người dân. Bác đang cần tìm hiểu về luật hay thủ tục nào, cứ nói cho Rightly biết nhé!"

        # 2. Cảm ơn & Tạm biệt (Thanks & Goodbye)
        if any(w in t_low for w in ("cảm ơn", "cam on", "thank", "tks", "tạm biệt", "tam biet", "bye", "ok", "oke")):
            if lang == "en":
                return "You're very welcome! Feel free to ask whenever you need legal guidance. Wishing you a great day!"
            return "Dạ không có gì ạ! Giúp được bác là niềm vui của Rightly. Bác giữ gìn sức khỏe nhé!"

        # 3. Pháp luật phổ biến (Common Legal FAQs)
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
    def _ask_api(cls, text, lang, history=None):
        if lang == "en":
            system_prompt = (
                "You are Rightly, a Vietnamese legal & administrative assistant. Reply in English. "
                "Mandatory clarification rule: when a user asks broadly about age-based rights, "
                "benefits, policies, or support but does not name a topic, do NOT list or assume "
                "benefits. Ask exactly one short follow-up question that offers relevant choices "
                "such as pension/social assistance, health insurance and care, transport benefits, "
                "or another administrative procedure. Wait for the answer before advising. "
                "For a specific question asking for explanation, rights, or a procedure, give a useful "
                "Markdown answer of about 120-220 words: a bold conclusion, eligibility/important conditions, "
                "benefits or steps, and a practical next action. Do not invent legal citations, amounts, or eligibility."
            )
        else:
            system_prompt = (
                "Bạn là trợ lý Rightly (Tiếng Làng) hỗ trợ người dân và người cao tuổi Việt Nam về pháp luật và thủ tục hành chính. "
                "Hãy trả lời bằng tiếng Việt lễ phép, ân cần. Nếu là câu chào hỏi, hãy chào lại thân mật. "
                "QUY TẮC BẮT BUỘC VỚI CÂU HỎI QUÁ RỘNG: nếu người dùng chỉ hỏi chung về quyền lợi, chính sách, trợ cấp theo độ tuổi "
                "(ví dụ 'tôi 70 tuổi có quyền lợi gì') mà chưa nói muốn biết mảng nào, KHÔNG được tự liệt kê hoặc suy đoán quyền lợi. "
                "Chỉ hỏi lại đúng MỘT câu ngắn để làm rõ, gợi ý các lựa chọn: lương hưu/trợ cấp xã hội, BHYT và khám chữa bệnh, "
                "ưu đãi giao thông, hoặc thủ tục khác. Chờ người dùng trả lời rồi mới tư vấn. "
                "Với câu hỏi CỤ THỂ cần giải thích quyền lợi, thủ tục hoặc quy định, trả lời bằng Markdown chi tiết vừa phải, khoảng 120-220 từ: "
                "mở đầu bằng kết luận in đậm; sau đó dùng các mục '### Điều kiện', '### Quyền lợi hoặc cách thực hiện', và '### Việc nên làm'. "
                "Nêu rõ điều gì còn phụ thuộc hoàn cảnh; KHÔNG bịa số tiền, mức hưởng, điều kiện, tên luật hoặc nghị định. "
                "Nếu hỏi mức phạt giao thông và chắc chắn về dữ kiện, nêu rõ tiền phạt và hình phạt bổ sung."
            )

        failures: list[dict[str, str]] = []

        # 0) Try Gemini (Google Cloud / AI Studio) - primary provider.
        if GEMINI_KEY:
            try:
                reply_text = _gemini_reply(system_prompt, text, history)
                if reply_text:
                    return reply_text
                failures.append({"provider": "gemini", "code": "empty_response"})
            except Exception as exc:
                _log_provider_failure("gemini", exc)
                failures.append({"provider": "gemini", "code": _failure_code(exc)})
        else:
            failures.append({"provider": "gemini", "code": "not_configured"})

        # 1) Try Groq (llama-3.3-70b-versatile) - primary provider.
        if GROQ_KEY:
            try:
                payload = {
                    "model": GROQ_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        *(history or []),
                        {"role": "user", "content": text},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 500,
                }
                req = Request(
                    GROQ_BASE_URL.rstrip("/") + "/chat/completions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Authorization": "Bearer " + str(GROQ_KEY).strip(),
                        "Content-Type": "application/json",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Rightly/1.0",
                        "Accept": "application/json",
                    },
                    method="POST",
                )
                with urlopen(req, timeout=6) as response:
                    data = json.loads(response.read().decode("utf-8"))
                content = data["choices"][0]["message"]["content"]
                if isinstance(content, str) and content.strip():
                    return content.strip()
                failures.append({"provider": "groq", "code": "empty_response"})
            except Exception as exc:
                _log_provider_failure("groq", exc)
                failures.append({"provider": "groq", "code": _failure_code(exc)})
        else:
            failures.append({"provider": "groq", "code": "not_configured"})

        # 2) Fallback to Pateway (gpt-5.6-luna)
        if PATEWAY_KEY:
            try:
                history_text = "\n".join(
                    f"{'Người dân' if turn['role'] == 'user' else 'Rightly'}: {turn['content']}"
                    for turn in (history or [])
                )
                payload = {
                    "model": PATEWAY_MODEL,
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                f"{system_prompt}\n\n"
                                + (f"Hội thoại trước đó:\n{history_text}\n\n" if history_text else "")
                                + f"Người dân nhắn: {text}\nTrả lời:"
                            ),
                        },
                    ],
                }
                req = Request(
                    PATEWAY_BASE_URL.rstrip("/") + "/chat/completions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Authorization": "Bearer " + str(PATEWAY_KEY).strip(),
                        "Content-Type": "application/json",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Rightly/1.0",
                        "Accept": "application/json",
                    },
                    method="POST",
                )
                with urlopen(req, timeout=6) as response:
                    data = json.loads(response.read().decode("utf-8"))
                content = data["choices"][0]["message"]["content"]
                if isinstance(content, str) and content.strip():
                    return content.strip()
                failures.append({"provider": "pateway", "code": "empty_response"})
            except Exception as exc:
                _log_provider_failure("pateway", exc)
                failures.append({"provider": "pateway", "code": _failure_code(exc)})
        else:
            failures.append({"provider": "pateway", "code": "not_configured"})

        raise LLMUnavailableError(failures)
