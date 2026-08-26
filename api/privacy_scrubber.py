"""Stdlib-only outbound PII scrubber bundled with the Vercel function."""
from __future__ import annotations
import re

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_CCCD_RE = re.compile(r"(?<!\d)(?:\d{12}|\d{9})(?!\d)")
_PASSPORT_RE = re.compile(r"\b[A-Z]{1,2}\d{7}\b")
_STREET_MARKERS = "đường|phố|ngõ|ngách|hẻm|kiệt|thôn|xóm|ấp|bản|buôn|sóc|khu phố|tổ dân phố|làng"
_ADDRESS_RE = re.compile(r"(?:nhà\s+)?số\s+\d+(?:\s*[/\-]\s*\d+)?\s+(" + _STREET_MARKERS + r")\b")
_PHONE_RE = re.compile(r"(?<!\d)(\+?\d[\d\s.\-]{7,}\d)(?!\d)")
_LONG_ID_RE = re.compile(r"\b[A-Za-z0-9_\-]{24,}\b")

def _scrub_phones(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        digits = sum(ch.isdigit() for ch in match.group(0))
        return "[SĐT]" if 9 <= digits <= 15 else match.group(0)
    return _PHONE_RE.sub(replace, text)

def scrub_outbound(text: str) -> str:
    text = _CCCD_RE.sub("[CCCD]", text)
    text = _PASSPORT_RE.sub("[HỘ CHIẾU]", text)
    text = _EMAIL_RE.sub("[EMAIL]", text)
    text = _ADDRESS_RE.sub("[ĐỊA CHỈ]", text)
    text = _scrub_phones(text)
    return _LONG_ID_RE.sub("[ID]", text)
