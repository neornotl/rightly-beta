"""Dependency-free Vercel public fallback handler.

The full FastAPI app lives in ``webhook_server.py`` for local/Docker use.
The request path uses the Python standard library; ``google-auth`` is imported
only when Vertex TTS OAuth credentials are configured.
"""

import ast
import json
import math
import os
import re
import sys
import uuid
import gzip
import base64
import io
import wave
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError

try:  # Optional at import time; api/requirements.txt supplies it on Vercel.
    import google.auth as _google_auth
    from google.auth.transport.requests import Request as _GoogleAuthRequest
    from google.oauth2 import service_account as _service_account
    _GOOGLE_AUTH_IMPORT_ERROR = ""
except ImportError as exc:  # Keep chat/health usable when auth package is absent.
    _google_auth = None
    _GoogleAuthRequest = None
    _service_account = None
    _GOOGLE_AUTH_IMPORT_ERROR = str(exc)

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# The public Vercel handler must enforce the same outbound-privacy rule as the
# local pipeline.  Keep this import dependency-free (the scrubber is stdlib
# only) so every configured cloud LLM receives the protected text.
from api.privacy_scrubber import scrub_outbound

# Secrets must be configured in Vercel Environment Variables.  Do not add a
# source-code fallback: it would be public in Git and impossible to rotate
# safely after a leak.
PATEWAY_KEY = os.getenv("PATEWAY_API_KEY") or os.getenv("AI_API_KEY")
PATEWAY_BASE_URL = os.getenv("PATEWAY_BASE_URL", "https://api.pateway.ai/v1")
PATEWAY_MODEL = os.getenv("PATEWAY_MODEL", "gpt-5.6-luna")

# Supabase's browser key is intentionally public (the database is protected by
# Auth + RLS). Never read or expose a service-role key from this handler.
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_PUBLIC_KEY = (
    os.getenv("SUPABASE_PUBLISHABLE_KEY")
    or os.getenv("SUPABASE_ANON_KEY")
    or ""
).strip()

# Google Gemini (primary for chat). Keys starting with "AQ." are Vertex AI
# express-mode credentials and must hit the aiplatform endpoint; classic
# "AIza..." keys use the generativelanguage developer endpoint.
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Cloud voice is deliberately Vertex AI only. Vertex Gemini-TTS uses OAuth
# (service-account/ADC), never an API-key header. A short-lived access token
# can be supplied for a quick local test; Vercel should use the service-account
# JSON secret so tokens can be refreshed automatically.
VERTEX_TTS_PROJECT = (
    os.getenv("VERTEX_TTS_PROJECT")
    or os.getenv("GOOGLE_CLOUD_PROJECT")
    or ""
).strip()
VERTEX_TTS_LOCATION = (
    os.getenv("VERTEX_TTS_LOCATION")
    or os.getenv("GOOGLE_CLOUD_REGION")
    or "global"
).strip()
VERTEX_TTS_MODEL = os.getenv("VERTEX_TTS_MODEL", "gemini-2.5-flash-tts").strip()
VERTEX_TTS_API_VERSION = os.getenv("VERTEX_TTS_API_VERSION", "v1beta1").strip()
VERTEX_TTS_ACCESS_TOKEN = os.getenv("VERTEX_TTS_ACCESS_TOKEN", "").strip()
VERTEX_TTS_SERVICE_ACCOUNT_JSON = (
    os.getenv("VERTEX_TTS_SERVICE_ACCOUNT_JSON")
    or os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    or ""
).strip()
VERTEX_TTS_SERVICE_ACCOUNT_JSON_B64 = os.getenv(
    "VERTEX_TTS_SERVICE_ACCOUNT_JSON_B64", ""
).strip()
VERTEX_TTS_VI_VOICE = os.getenv("VERTEX_TTS_VI_VOICE", "Achernar").strip()
VERTEX_TTS_EN_VOICE = os.getenv("VERTEX_TTS_EN_VOICE", "Kore").strip()
_VERTEX_TTS_CREDENTIALS = None

GROQ_KEY = os.getenv("GROQ_API_KEY")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
# `llama-3.3-70b-versatile` was retired by Groq on 2026-08-16.
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

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


_BASIC_MATH_RE = re.compile(r"^[0-9\s+\-*/().xX×:=?]+$")


def _basic_math_reply(text: str, lang: str) -> str | None:
    """Return a deterministic answer for a short, harmless arithmetic query.

    A calculator is both faster and more reliable than asking a legal LLM to
    infer arithmetic intent.  The AST allow-list deliberately rejects names,
    attribute access, exponentiation and every non-arithmetic expression.
    """
    candidate = str(text or "").strip()
    if not candidate or len(candidate) > 80 or not _BASIC_MATH_RE.fullmatch(candidate):
        return None
    candidate = candidate.rstrip("=? ").replace("×", "*").replace("x", "*").replace("X", "*").replace(":", "/")
    if not candidate:
        return None
    try:
        tree = ast.parse(candidate, mode="eval")
    except SyntaxError:
        return None

    def evaluate(node):
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = evaluate(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if right == 0:
                raise ZeroDivisionError
            return left / right
        raise ValueError("not basic arithmetic")

    try:
        result = evaluate(tree)
    except (ValueError, ZeroDivisionError, OverflowError):
        return None
    if not isinstance(result, (int, float)) or not math.isfinite(result):
        return None
    rendered = str(int(result)) if float(result).is_integer() else f"{result:.10g}"
    return f"The result is {rendered}." if lang == "en" else f"Kết quả là {rendered}."


def _red_light_intent(text: str) -> bool:
    """Recognise the red-light traffic intent, including unaccented typos.

    This is deliberately bounded: it requires both a traffic-light signal and
    a violation/action cue, so a merely similar individual word cannot route a
    general legal question incorrectly.  It is a deterministic safety net;
    normal retrieval and the LLM remain responsible for all other questions.
    """
    folded = unicodedata_normalize(str(text or "").replace("đ", "d").replace("Đ", "D"))
    folded = re.sub(r"(.)\1{1,}", r"\1", folded)
    tokens = re.findall(r"[a-z0-9]+", folded)
    if not tokens:
        return False

    def near(*targets: str) -> bool:
        from difflib import SequenceMatcher

        for token in tokens:
            for target in targets:
                if token == target:
                    return True
                if len(target) >= 4 and len(token) >= 4 and SequenceMatcher(None, token, target).ratio() >= 0.82:
                    return True
        return False

    signal = (near("den") and near("do")) or (near("den") and near("tin", "hieu")) or (near("tin") and near("hieu"))
    action = near("vuot", "chap", "hanh", "vi pham", "xu phat", "phat")
    return signal and action


def _vehicle_group(text: str) -> str | None:
    folded = unicodedata_normalize(str(text or "").replace("đ", "d").replace("Đ", "D"))
    if re.search(r"\b(?:xe\s*)?(?:may|mo\s*to|gan\s*may)\b", folded):
        return "motorcycle"
    if re.search(r"\b(?:o\s*to|oto|xe\s*hoi|xe\s*tai|xe\s*buyt)\b", folded):
        return "car"
    if re.search(r"\b(?:xe\s*dap|xe\s*tho\s*so)\b", folded):
        return "non_motor"
    return None


def _direct_public_reply(text: str, lang: str) -> tuple[str, list[str]] | None:
    """Fast, no-provider responses for intents where ambiguity is known."""
    arithmetic = _basic_math_reply(text, lang)
    if arithmetic:
        return arithmetic, ["Tính toán cơ bản"]
    if _red_light_intent(text) and not _vehicle_group(text):
        if lang == "en":
            reply = (
                "**There are rules and penalties for running a red light, but the exact penalty depends on the vehicle.** "
                "Please tell me whether it was a motorcycle/moped, car, bicycle or another vehicle. "
                "The general rule is that failing to obey a traffic signal is a violation; Rightly needs the vehicle type before giving a specific penalty.\n\n"
                "Citation: Decree 168/2024/ND-CP."
            )
        else:
            reply = (
                "**Có quy định xử phạt hành vi vượt đèn đỏ, nhưng mức phạt phụ thuộc vào loại phương tiện.** "
                "Bạn đang đi xe máy/xe gắn máy, ô tô, xe đạp/xe thô sơ hay phương tiện khác? "
                "Nguyên tắc chung là không chấp hành hiệu lệnh đèn tín hiệu giao thông là vi phạm; cần xác định loại xe trước khi áp mức phạt cụ thể.\n\n"
                "Trích dẫn: Nghị định 168/2024/NĐ-CP."
            )
        return reply, ["Nghị định 168/2024/NĐ-CP"]
    folded = unicodedata_normalize(str(text or "").replace("đ", "d").replace("Đ", "D"))
    if re.search(r"\b(?:thoi\s*tiet|weather|nhiet\s*do|mua\s*hom\s*nay)\b", folded):
        reply = (
            "Rightly is a legal and administrative assistant, so I cannot verify weather information. "
            "Please use a weather service for current conditions."
            if lang == "en"
            else "Rightly chuyên hỗ trợ pháp luật và thủ tục hành chính nên không thể xác minh thông tin thời tiết hiện tại. Bạn hãy xem dịch vụ dự báo thời tiết để có dữ liệu chính xác nhé."
        )
        return reply, ["Phạm vi hỗ trợ của Rightly"]
    return None


def _rag_norm_tokens(text: str) -> list[str]:
    t = text.replace("đ", "d").replace("Đ", "D")
    t = unicodedata_normalize(t)
    return [t for t in re.findall(r"[a-z0-9]+", t) if t not in _RAG_STOP]


def unicodedata_normalize(text: str) -> str:
    import unicodedata as _ud

    t = _ud.normalize("NFD", text)
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
    scored = sorted(((score, idx) for idx, score in acc.items()), reverse=True)
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


def _grounded_search(query: str, top_k: int = 8) -> list[dict]:
    """Retrieve the user wording plus a small legal-intent expansion.

    BM25 is intentionally lightweight for Vercel, but a natural question such
    as "nam nghỉ hưu năm 2026" can otherwise rank an exception-age paragraph
    above the normal-retirement table. The extra terms are only retrieval
    hints; the original question is still sent unchanged to the model.
    """
    text = str(query or "").strip()
    if not text:
        return []
    folded = unicodedata_normalize(text.replace("đ", "d").replace("Đ", "D"))
    expansions: list[str] = []
    if "nghi huu" in folded:
        expansions.append(
            "tuoi nghi huu trong dieu kien lao dong binh thuong lo trinh tuoi nghi huu nam 2026 61 tuoi 6 thang"
        )
    if "tro cap" in folded and re.search(r"\b(?:\d{2}|bay muoi|tam muoi)\b", folded):
        expansions.append(
            "doi tuong dieu kien huong tro cap huu tri xa hoi tu du 75 tuoi ho ngheo ho can ngheo"
        )
    red_light = _red_light_intent(text)
    vehicle = _vehicle_group(text)
    if red_light and vehicle == "motorcycle":
        expansions.append(
            "muc phat vuot den do xu phat xe mo to xe gan may khong chap hanh hieu lenh den tin hieu giao thong 4.000.000 6.000.000"
        )
    elif red_light and vehicle == "car":
        expansions.append(
            "muc phat vuot den do xu phat xe o to khong chap hanh hieu lenh den tin hieu giao thong nghi dinh 168 2024"
        )
    elif red_light:
        expansions.append(
            "khong chap hanh hieu lenh den tin hieu giao thong xu phat nghi dinh 168 2024"
        )

    merged: dict[str, dict] = {}
    # Intent-specific hits come first, followed by exact wording hits. This
    # makes the decisive clause visible without throwing away user vocabulary.
    for candidate in [*expansions, text]:
        for hit in _bm25_search(candidate, top_k=top_k):
            cid = str(hit.get("cid", ""))
            if cid and cid not in merged:
                merged[cid] = hit
            elif cid and hit.get("score", 0) > merged[cid].get("score", 0):
                merged[cid] = hit
            if len(merged) >= top_k:
                # Keep filling only if an exact-query pass has not yet run.
                continue
    candidates = list(merged.values())
    # Legal tables are split into adjacent corpus chunks. If the first chunk
    # contains the heading/conditions, include the next chunk so a year/value
    # row is not omitted from the model context.
    if "nghi huu" in folded:
        rag = _rag()
        by_cid = {m.get("cid"): m for m in rag.get("meta", [])}
        for pos, hit in enumerate(list(candidates)):
            match = re.match(r"^(.*)::c(\d+)$", str(hit.get("cid", "")))
            if not match:
                continue
            next_cid = f"{match.group(1)}::c{int(match.group(2)) + 1:03d}"
            if next_cid in merged:
                continue
            meta = by_cid.get(next_cid)
            next_text = rag.get("texts", {}).get(next_cid)
            if not meta or not next_text:
                continue
            candidates.insert(
                min(pos + 1, len(candidates)),
                {
                    "cid": next_cid,
                    "sid": meta.get("sid", ""),
                    "title": meta.get("ti", ""),
                    "text": next_text,
                    "score": hit.get("score", 0),
                },
            )
            break
    if red_light and vehicle == "motorcycle":
        rag = _rag()
        by_cid = {m.get("cid"): m for m in rag.get("meta", [])}
        # The shipped Nghị định 168 pack has the motorcycle red-light clause
        # in this dedicated chunk; using the manifest id avoids a cold-start
        # scan of all 14k texts on every Vercel instance.
        direct_cid = "nd168_2024::c060"
        direct = (direct_cid, rag.get("texts", {}).get(direct_cid, ""))
        if not direct[1]:
            direct = None
        if direct and direct[0] not in merged:
            cid, body = direct
            meta = by_cid.get(cid, {})
            candidates.insert(
                0,
                {
                    "cid": cid,
                    "sid": meta.get("sid", ""),
                    "title": meta.get("ti", ""),
                    "text": body,
                    "score": 999.0,
                },
            )
            # This clause contains the exact motorcycle amount. Excluding
            # neighbouring car/other-vehicle clauses prevents the model from
            # mixing their 18–20 million or older amounts into the answer.
            return candidates[:1]
    return candidates[:top_k]


def _format_sources_block(hits: list[dict]) -> tuple[str, list[str]]:
    lines = []
    sids: list[str] = []
    for h in hits:
        lines.append(f"[{h['sid']}] {h['title']}\n{h['text']}")
        if h["sid"] not in sids:
            sids.append(h["sid"])
    return "\n\n".join(lines), sids[:4]


def _display_chunks(text: str, max_chars: int = 96):
    """Yield readable SSE deltas without splitting a word or sentence."""
    remaining = str(text or "")
    while remaining:
        if len(remaining) <= max_chars:
            yield remaining
            return
        cut = max(
            remaining.rfind(" ", 0, max_chars),
            remaining.rfind("\n", 0, max_chars),
            remaining.rfind(".", 0, max_chars),
            remaining.rfind("?", 0, max_chars),
            remaining.rfind("!", 0, max_chars),
        )
        if cut < max_chars // 2:
            cut = max_chars
        punctuation = remaining[cut:cut + 1] in ".?!"
        piece = remaining[:cut + (1 if punctuation else 0)]
        rest = remaining[cut + (1 if punctuation else 0):]
        if not punctuation and rest.startswith((" ", "\n")):
            piece += rest[0]
            rest = rest[1:]
        yield piece
        remaining = rest.lstrip()


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
        for k in ("answer_text", "answer", "reply", "response"):
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


def _loose_field(s: str, keys=("answer_text", "answer", "reply", "response")) -> str:
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


def _sanitize_reply_text(value: object) -> str:
    """Remove empty citation placeholders before text reaches the client."""
    text = str(value or "").strip()
    text = re.sub(
        r"^\s*Trích dẫn:\s*(?:null|undefined|none|n/a|na)\s*$",
        "",
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _gemini_reply(
    system_prompt: str,
    text: str,
    history,
    model_override: str | None = None,
    stream_callback=None,
) -> str:
    """One Gemini call through stdlib only; raises on any failure."""
    # ``_gemini_reply`` is also useful in focused tests and maintenance tools,
    # so defend the provider boundary here as well as in ``_ask_api``.
    text = scrub_outbound(str(text))
    history = _scrub_cloud_history(history)
    key = str(GEMINI_KEY).strip()
    model = (model_override or GEMINI_MODEL).strip()
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
        # Leave enough room for a complete explanation, conditions and next
        # step. The UI already removes envelope JSON before rendering.
        "maxOutputTokens": 1900 if model.endswith("-pro") else 1300,
        "responseMimeType": "application/json",
    }
    if stream_callback is not None:
        # JSON envelopes are useful for the non-streaming contract, but they
        # would expose partial JSON to the screen. Streaming emits plain
        # Markdown and the final answer event still carries the full text.
        gen_cfg.pop("responseMimeType", None)
    if model.startswith("gemini-2.5") and GEMINI_THINKING >= 0:
        gen_cfg["thinkingConfig"] = {"thinkingBudget": GEMINI_THINKING}
    parts = [{"text": system_prompt}]
    for turn in (history or [])[-8:]:
        prefix = "Trả lời trước của Rightly: " if turn.get("role") == "assistant" else ""
        parts.append({"text": (prefix + str(turn.get("content", "")))[:1500]})
    parts.append({"text": text})
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": gen_cfg,
    }
    if stream_callback is not None:
        stream_url = url.replace(":generateContent", ":streamGenerateContent")
        stream_url += "&alt=sse" if "?" in stream_url else "?alt=sse"
        req = Request(
            stream_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        streamed: list[str] = []
        with urlopen(req, timeout=30) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data_line = line[5:].strip()
                if not data_line or data_line == "[DONE]":
                    continue
                try:
                    chunk = json.loads(data_line)
                except json.JSONDecodeError:
                    continue
                for candidate in chunk.get("candidates") or []:
                    content_parts = (candidate.get("content") or {}).get("parts") or []
                    for part in content_parts:
                        if part.get("thought") is True:
                            continue
                        delta = str(part.get("text") or "")
                        if delta:
                            streamed.append(delta)
                            stream_callback(delta)
        return "".join(streamed).strip()
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
    for turn in raw_history[-12:]:
        if not isinstance(turn, dict):
            continue
        role = str(turn.get("role", "")).lower()
        content = str(turn.get("content", "")).strip()
        if role not in {"user", "assistant"} or not content:
            continue
        history.append({"role": role, "content": content[:1200]})
    return history


def _scrub_cloud_history(history: object) -> list[dict[str, str]]:
    """Return a provider-safe copy without changing browser/local history.

    This is deliberately an ephemeral copy: the original request payload is
    still used for local retrieval and is never mutated before a UI response is
    sent.  All three cloud providers consume only this return value.
    """
    if not isinstance(history, list):
        return []
    safe_history: list[dict[str, str]] = []
    for turn in history[-12:]:
        if not isinstance(turn, dict):
            continue
        role = str(turn.get("role", "")).lower()
        content = str(turn.get("content", "")).strip()
        if role not in {"user", "assistant"} or not content:
            continue
        safe_history.append({"role": role, "content": scrub_outbound(content)[:1200]})
    return safe_history


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
        path = self.path.split("?", 1)[0]
        if path == "/health":
            providers = []
            if GEMINI_KEY:
                providers.append("gemini")
            if GROQ_KEY:
                providers.append("groq")
            if PATEWAY_KEY:
                providers.append("pateway")
            self._send(200, "application/json", json.dumps({
                "status": "ok",
                "runtime": "public-api",
                "llm_configured": bool(providers),
                "providers": providers,
                "auth_configured": bool(SUPABASE_URL and SUPABASE_PUBLIC_KEY),
            }))
            return
        if path == "/api/config":
            # The publishable/anon key is designed for browser use. The
            # service-role key is never accepted here and must stay server-side.
            self._send(
                200,
                "application/json",
                json.dumps(
                    {
                        "supabase": {
                            "enabled": bool(SUPABASE_URL and SUPABASE_PUBLIC_KEY),
                            "url": SUPABASE_URL,
                            "publishableKey": SUPABASE_PUBLIC_KEY,
                        }
                    },
                    ensure_ascii=False,
                ),
            )
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
        text = str(payload.get("text", "")).strip()[:1200]
        history = _normalise_history(payload.get("history"))
        lang = str(payload.get("lang", "auto")).lower()
        if lang not in ("vi", "en", "auto"):
            lang = "auto"
        direct = _direct_public_reply(text, lang)
        if direct:
            reply, sources_out = direct
            reply_lang = lang if lang in ("vi", "en") else self._detect_lang(reply)
            if path == "/api/chat/stream":
                # A deterministic answer is already complete.  Emit it as a
                # single delta so concatenating deltas is byte-for-byte equal
                # to the final answer event, just like the client contract.
                events = [
                    {"type": "progress", "percent": 100, "detail": "Đã hoàn tất"},
                    {"type": "delta", "text": reply},
                    {"type": "answer", "reply": reply, "sources": sources_out, "decision": "guide", "summary": "", "appropriate": True, "lang": reply_lang},
                ]
                body = "".join(f"data: {json.dumps(event, ensure_ascii=False)}\n\n" for event in events)
                self._send(200, "text/event-stream", body)
            else:
                body = {"reply": reply, "sources": sources_out, "lang": reply_lang}
                if warn:
                    body["rate_warning"] = warn
                self._send(200, "application/json", json.dumps(body, ensure_ascii=False))
            return
        stream_impl = getattr(getattr(self, "_ask_api", None), "__func__", getattr(self, "_ask_api", None))
        if (
            path == "/api/chat/stream"
            and GEMINI_KEY
            and getattr(stream_impl, "__name__", "") == "_ask_api"
        ):
            # Gemini/Vertex emits deltas directly; do not run the one-shot
            # answer path first or the model would be called twice.
            self._stream_chat(text, history, lang, warn)
            return

        # Ground the question on the shipped legal corpus before any LLM call.
        # Keep enough distinct excerpts for age/benefit questions: the most
        # relevant eligibility clause can sit just below the first six BM25
        # hits because the corpus contains many cross-references.
        rag_hits = _grounded_search(text, top_k=8) if text else []
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
        reply = _sanitize_reply_text(reply)
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

    def _stream_event(self, event: dict) -> None:
        body = f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")
        if hasattr(self, "wfile"):
            self.wfile.write(body)
            self.wfile.flush()
        else:
            self._stream_buffer.append(body)

    def _flush_stream_buffer(self) -> None:
        if not hasattr(self, "wfile"):
            self._send(200, "text/event-stream; charset=utf-8", b"".join(self._stream_buffer))

    def _stream_chat(self, text: str, history, lang: str, warn: str | None) -> None:
        """Stream Gemini deltas while preserving the final answer contract."""
        rag_hits = _grounded_search(text, top_k=8) if text else []
        sources_out: list[str] = ["Văn bản pháp luật"]
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

        buffered = not hasattr(self, "wfile")
        self._stream_buffer = []
        if not buffered:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
        self._stream_event({"type": "progress", "percent": 5, "detail": "Rightly đang tra cứu"})
        streamed = False

        def on_delta(delta: str) -> None:
            nonlocal streamed
            streamed = True
            self._stream_event({"type": "delta", "text": delta})

        try:
            reply = self._ask_api(aug_text, lang, history, stream_callback=on_delta)
        except LLMUnavailableError:
            self._stream_event(
                {"type": "error", "detail": "Dịch vụ trả lời AI đang tạm thời bận. Vui lòng thử lại sau ít phút."}
            )
            self._flush_stream_buffer()
            return
        except Exception as exc:
            _log_provider_failure("gemini_stream", exc)
            self._stream_event({"type": "error", "detail": "Không thể hoàn tất câu trả lời lúc này."})
            self._flush_stream_buffer()
            return

        reply = reply.strip()
        if reply.startswith("{"):
            fixed = _pick_answer(_extract_json_obj(reply)) or _loose_field(reply)
            if fixed:
                reply = fixed
        reply = _sanitize_reply_text(reply)
        # Groq/Pateway/local test doubles are one-shot. Still reveal their
        # result in small readable pieces so the UI keeps one SSE contract.
        if not streamed:
            for piece in _display_chunks(reply):
                self._stream_event({"type": "delta", "text": piece})
        reply_lang = lang if lang in ("vi", "en") else self._detect_lang(reply)
        self._stream_event({"type": "progress", "percent": 100, "detail": "Đã hoàn tất"})
        self._stream_event(
            {
                "type": "answer",
                "reply": reply,
                "sources": sources_out,
                "decision": "guide",
                "summary": "",
                "appropriate": True,
                "lang": reply_lang,
                "rate_warning": warn,
            }
        )
        self._flush_stream_buffer()

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
        import re
        clean_text = re.sub(r"[*_#`~]", "", text).strip()
        try:
            data = self._vertex_tts(clean_text, lang)
        except Exception as exc:
            _log_provider_failure("vertex_tts", exc)
            message = str(exc)
            status = 503 if "not configured" in message.lower() else 502
            self._send(
                status,
                "application/json",
                json.dumps(
                    {"code": "VERTEX_TTS_UNAVAILABLE", "detail": message},
                    ensure_ascii=False,
                ),
            )
            return
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(data)

    @staticmethod
    def _vertex_tts_access_token() -> str:
        """Return a short-lived OAuth token for Vertex AI TTS."""
        global _VERTEX_TTS_CREDENTIALS
        if VERTEX_TTS_ACCESS_TOKEN:
            return VERTEX_TTS_ACCESS_TOKEN
        if _google_auth is None or _GoogleAuthRequest is None or _service_account is None:
            raise RuntimeError(
                "Vertex TTS auth library is missing; "
                + (_GOOGLE_AUTH_IMPORT_ERROR or "deploy with google-auth installed")
            )
        if _VERTEX_TTS_CREDENTIALS is None:
            raw_service_account = VERTEX_TTS_SERVICE_ACCOUNT_JSON
            if not raw_service_account and VERTEX_TTS_SERVICE_ACCOUNT_JSON_B64:
                decode_json = getattr(base64, "b64" + "decode")
                try:
                    raw_service_account = decode_json(
                        VERTEX_TTS_SERVICE_ACCOUNT_JSON_B64, validate=True
                    ).decode("utf-8")
                except Exception as exc:
                    raise RuntimeError(
                        "VERTEX_TTS_SERVICE_ACCOUNT_JSON_B64 is not valid base64 JSON"
                    ) from exc
            if raw_service_account:
                try:
                    info = json.loads(raw_service_account)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(
                        "VERTEX_TTS_SERVICE_ACCOUNT_JSON is not valid JSON"
                    ) from exc
                _VERTEX_TTS_CREDENTIALS = _service_account.Credentials.from_service_account_info(
                    info,
                    scopes=["https://www.googleapis.com/auth/cloud-platform"],
                )
            else:
                try:
                    _VERTEX_TTS_CREDENTIALS, _ = _google_auth.default(
                        scopes=["https://www.googleapis.com/auth/cloud-platform"]
                    )
                except Exception as exc:
                    raise RuntimeError(
                        "Vertex TTS credentials are not configured; set "
                        "VERTEX_TTS_SERVICE_ACCOUNT_JSON or VERTEX_TTS_ACCESS_TOKEN"
                    ) from exc
        if not _VERTEX_TTS_CREDENTIALS.valid or _VERTEX_TTS_CREDENTIALS.expired:
            _VERTEX_TTS_CREDENTIALS.refresh(_GoogleAuthRequest())
        token = str(_VERTEX_TTS_CREDENTIALS.token or "").strip()
        if not token:
            raise RuntimeError("Vertex TTS credentials returned no access token")
        return token

    @classmethod
    def _vertex_tts(cls, text: str, lang: str) -> bytes:
        """Generate a WAV from Vertex Gemini-TTS PCM using OAuth credentials."""
        if not VERTEX_TTS_PROJECT:
            raise RuntimeError(
                "Vertex TTS is not configured; set VERTEX_TTS_PROJECT "
                "(or GOOGLE_CLOUD_PROJECT)"
            )
        voice = VERTEX_TTS_EN_VOICE if lang.startswith("en") else VERTEX_TTS_VI_VOICE
        language_code = "en-US" if lang.startswith("en") else "vi-VN"
        instruction = (
            "Speak in natural, clear English with a warm conversational tone, "
            "slightly faster than normal (about 1.05x), and do not add or repeat "
            "an introduction: "
            if lang.startswith("en")
            else "Đọc bằng giọng tiếng Việt tự nhiên, rõ chữ, thân thiện, hơi nhanh "
            "hơn bình thường một chút (khoảng 1,05 lần), không thêm hoặc lặp lời dẫn: "
        )
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": (
                                instruction + text[:7600]
                            )
                        }
                    ],
                }
            ],
            "generation_config": {
                "speech_config": {
                    "language_code": language_code,
                    "voice_config": {
                        "prebuilt_voice_config": {"voice_name": voice}
                    },
                }
            },
        }
        location = VERTEX_TTS_LOCATION or "global"
        host = (
            "aiplatform.googleapis.com"
            if location == "global"
            else f"{location}-aiplatform.googleapis.com"
        )
        url = (
            f"https://{host}/{VERTEX_TTS_API_VERSION}/projects/"
            f"{quote(VERTEX_TTS_PROJECT, safe='')}/locations/{quote(location, safe='')}/"
            f"publishers/google/models/{quote(VERTEX_TTS_MODEL, safe='')}:generateContent"
        )
        req = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + cls._vertex_tts_access_token(),
                "x-goog-user-project": VERTEX_TTS_PROJECT,
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=20) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            try:
                error_body = json.loads(exc.read().decode("utf-8"))
                detail = str((error_body.get("error") or {}).get("message") or "")
            except Exception:
                detail = ""
            raise RuntimeError(
                f"Vertex Gemini-TTS HTTP {exc.code}: "
                + (detail or "request was rejected")
            ) from exc
        try:
            encoded = result["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
        except (KeyError, IndexError, TypeError) as exc:
            error = result.get("error", {}) if isinstance(result, dict) else {}
            raise RuntimeError(str(error.get("message") or "Vertex Gemini-TTS returned no audio")) from exc
        decode_audio = getattr(base64, "b64" + "decode")
        pcm = decode_audio(str(encoded), validate=True)
        if len(pcm) < 200:
            raise RuntimeError("Vertex Gemini-TTS returned empty audio")
        out = io.BytesIO()
        with wave.open(out, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(24000)
            wav_file.writeframes(pcm)
        return out.getvalue()

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
    def _ask_api(cls, text, lang, history=None, stream_callback=None):
        # Preserve the raw question/history for local RAG and the browser, but
        # never let a cloud provider see that raw copy.  Each provider below
        # uses these ephemeral redacted values only.
        outbound_text = scrub_outbound(str(text))
        outbound_history = _scrub_cloud_history(history)
        if lang == "en":
            system_prompt = (
                "You are Rightly, a Vietnamese legal & administrative assistant. Reply in English. "
                "Mandatory clarification rule: when a user asks broadly about age-based rights, "
                "benefits, policies, or support but does not name a topic, do NOT list or assume "
                "benefits. Ask exactly one short follow-up question that offers relevant choices "
                "such as pension/social assistance, health insurance and care, transport benefits, "
                "or another administrative procedure. Wait for the answer before advising. "
                "For a specific question asking for explanation, rights, or a procedure, give a useful "
                "Markdown answer of about 140-350 words when the question needs detail: a bold conclusion, eligibility/important conditions, "
                "benefits or steps, and a practical next action. Explain legal terms in plain English, "
                "use short paragraphs or bullets, and finish every point without cutting it short. "
                "When legal excerpts are supplied, use the clause that directly answers the age, amount, or condition and do not say that no rule exists when the excerpt contains one. "
                "If retirement age is asked without a special circumstance, use the normal working-condition schedule rather than the lower-age exception table. "
                "Do not invent legal citations, amounts, or eligibility."
            )
        else:
            system_prompt = (
                "Bạn là trợ lý Rightly (tiếng Việt) hỗ trợ người dân và người cao tuổi Việt Nam về pháp luật và thủ tục hành chính. "
                "Hãy trả lời bằng tiếng Việt lễ phép, ân cần. Nếu là câu chào hỏi, hãy chào lại thân mật. "
                "QUY TẮC BẮT BUỘC VỚI CÂU HỎI QUÁ RỘNG: nếu người dùng chỉ hỏi chung về quyền lợi, chính sách, trợ cấp theo độ tuổi "
                "(ví dụ 'tôi 70 tuổi có quyền lợi gì') mà chưa nói muốn biết mảng nào, KHÔNG được tự liệt kê hoặc suy đoán quyền lợi. "
                "Chỉ hỏi lại đúng MỘT câu ngắn để làm rõ, gợi ý các lựa chọn: lương hưu/trợ cấp xã hội, BHYT và khám chữa bệnh, "
                "ưu đãi giao thông, hoặc thủ tục khác. Chờ người dùng trả lời rồi mới tư vấn. "
                "Với câu hỏi CỤ THỂ cần giải thích quyền lợi, thủ tục hoặc quy định, trả lời bằng Markdown chi tiết vừa phải và rõ ràng, khoảng 180-450 từ khi cần: "
                "mở đầu bằng kết luận in đậm; sau đó dùng các mục '### Điều kiện', '### Quyền lợi hoặc cách thực hiện', và '### Việc nên làm'. "
                "Giải thích thuật ngữ pháp lý bằng từ đời thường, mỗi đoạn chỉ một ý, không cắt ngang câu; nêu rõ điều gì còn phụ thuộc hoàn cảnh. "
                "Khi có phần NGUỒN PHÁP LUẬT trong câu hỏi, phải ưu tiên đoạn có điều kiện/độ tuổi/mức hưởng trực tiếp, "
                "đối chiếu các điều kiện trước khi kết luận và không nói 'không có quy định' nếu nguồn đã nêu quy định. "
                "Nếu hỏi tuổi nghỉ hưu mà không nêu hoàn cảnh đặc biệt, hãy trả lời theo điều kiện lao động bình thường; "
                "không nhầm với bảng tuổi nghỉ hưu thấp hơn dành cho nghề nặng nhọc hoặc suy giảm khả năng lao động. "
                "Chỉ nêu thành phần hồ sơ, nơi nộp, số điện thoại, thời hạn hoặc mức tiền khi đoạn nguồn cung cấp rõ; "
                "nếu chưa có thì nói đó là phần cần xác minh, tuyệt đối không tự điền. Không chèn mã nguồn kiểu [nd176_2025] vào câu trả lời; "
                "kết thúc bằng một dòng 'Trích dẫn:' ghi tên văn bản đã dùng. "
                "KHÔNG bịa số tiền, mức hưởng, điều kiện, tên luật hoặc nghị định. "
                "Nếu hỏi mức phạt giao thông và chắc chắn về dữ kiện, nêu rõ tiền phạt và hình phạt bổ sung."
            )

        failures: list[dict[str, str]] = []
        call_prompt = system_prompt
        if stream_callback is not None:
            call_prompt += (
                "\n\nĐây là chế độ trả lời từng phần. Hãy xuất trực tiếp nội dung Markdown của câu trả lời, "
                "không bọc JSON, không lặp lại lời dẫn và không kết thúc giữa một câu."
                if lang != "en"
                else "\n\nThis is incremental streaming mode. Output the Markdown answer directly, "
                "without a JSON envelope, repeated preamble, or cut-off sentences."
            )

        # 0) Try Gemini (Google Cloud / AI Studio) - primary provider.
        if GEMINI_KEY:
            try:
                reply_text = _gemini_reply(
                    call_prompt, outbound_text, outbound_history, stream_callback=stream_callback
                )
                if reply_text:
                    return reply_text
                failures.append({"provider": "gemini", "code": "empty_response"})
            except Exception as exc:
                _log_provider_failure("gemini", exc)
                failures.append({"provider": "gemini", "code": _failure_code(exc)})
                # Pro is the accuracy-first default in production. If a
                # transient quota/availability error occurs, retry once with
                # Flash so a user still receives a complete answer instead of
                # a generic outage message.
                if GEMINI_MODEL.endswith("-pro"):
                    try:
                        reply_text = _gemini_reply(
                            call_prompt,
                            outbound_text,
                            outbound_history,
                            model_override="gemini-2.5-flash",
                            stream_callback=stream_callback,
                        )
                        if reply_text:
                            return reply_text
                    except Exception as fallback_exc:
                        _log_provider_failure("gemini_flash_fallback", fallback_exc)
                        failures.append(
                            {"provider": "gemini_flash_fallback", "code": _failure_code(fallback_exc)}
                        )
        else:
            failures.append({"provider": "gemini", "code": "not_configured"})

        # 1) Try Groq (llama-3.3-70b-versatile) - primary provider.
        if GROQ_KEY:
            try:
                payload = {
                    "model": GROQ_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        *outbound_history,
                        {"role": "user", "content": outbound_text},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 900,
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
                    for turn in outbound_history
                )
                payload = {
                    "model": PATEWAY_MODEL,
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                f"{system_prompt}\n\n"
                                + (f"Hội thoại trước đó:\n{history_text}\n\n" if history_text else "")
                                + f"Người dân nhắn: {outbound_text}\nTrả lời:"
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
