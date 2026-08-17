"""Outbound privacy scrubber for cloud LLM calls.

Stronger than the log scrubber in :mod:`app.logging_utils` because this
text LEAVES the machine: Vietnamese identifiers (CMND/CCCD, passport,
address patterns) are additionally redacted with clear placeholders.

Conservative by design:
- Only high-confidence patterns are redacted (no Vietnamese name detection).
- Address redaction requires a street/area marker (``số 12 đường X``), so
  law-text fragments like "số 123/2021/QĐ-UBND" are left intact.
- Quasi-identifiers (age, commune) in the QUERY are intentionally kept: they
  are needed for a correct personalized answer; the residual re-identification
  risk is mitigated by scripted pilot data and no cross-session identity.
"""

from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# CMND (9 digits) or CCCD (12 digits), as a standalone digit run.
_CCCD_RE = re.compile(r"(?<!\d)(?:\d{12}|\d{9})(?!\d)")

# Vietnamese passports: 1-2 letters + 7 digits (e.g. C1234567, NC1234567).
_PASSPORT_RE = re.compile(r"\b[A-Z]{1,2}\d{7}\b")

# "số 12 đường X" / "nhà số 5 ngõ Y" / "số 12 thôn Z" — requires a marker.
_STREET_MARKERS = "đường|phố|ngõ|ngách|hẻm|kiệt|thôn|xóm|ấp|bản|buôn|sóc|khu phố|tổ dân phố|làng"
_ADDRESS_RE = re.compile(r"(?:nhà\s+)?số\s+\d+(?:\s*[/\-]\s*\d+)?\s+(" + _STREET_MARKERS + r")\b")

_PHONE_RE = re.compile(r"(?<!\d)(\+?\d[\d\s.\-]{7,}\d)(?!\d)")
_LONG_ID_RE = re.compile(r"\b[A-Za-z0-9_\-]{24,}\b")


def _scrub_phones(text: str) -> str:
    def _repl(match: re.Match) -> str:
        digits = sum(ch.isdigit() for ch in match.group(0))
        return "[SĐT]" if 9 <= digits <= 15 else match.group(0)

    return _PHONE_RE.sub(_repl, text)


def scrub_outbound(text: str) -> str:
    """Redact high-confidence PII before the text leaves the machine.

    Replacement order matters: specific identifiers run before the generic
    phone pattern so 9/12-digit national IDs keep their own placeholder.
    """
    text = _CCCD_RE.sub("[CCCD]", text)
    text = _PASSPORT_RE.sub("[HỘ CHIẾU]", text)
    text = _EMAIL_RE.sub("[EMAIL]", text)
    text = _ADDRESS_RE.sub("[ĐỊA CHỈ]", text)
    text = _scrub_phones(text)
    text = _LONG_ID_RE.sub("[ID]", text)
    return text
