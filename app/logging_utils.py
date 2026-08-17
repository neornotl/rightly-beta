"""Anonymized JSONL logging and session management.

Design goals:
- Never log raw audio paths unless needed.
- Never log transcripts unless SAVE_TRANSCRIPTS=true.
- Random session IDs only.
- scrub_logs(): heuristic removal of emails / phone numbers / long ID strings.
  The scrubber is a best-effort heuristic, NOT a replacement for deletion.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<!\d)(\+?\d[\d\s\.\-]{7,}\d)(?!\d)")
_LONG_ID_RE = re.compile(r"\b[A-Za-z0-9_\-]{24,}\b")

# Metadata keys that must survive scrubbing untouched: session ids and
# timestamps are machine-generated and are not user PII. Scrubbing them
# corrupts the log (F1 fix) and silently breaks SessionStore.delete_session.
_PRESERVED_KEYS = {"session_id", "timestamp", "chunk_id", "source_id"}


def new_session_id() -> str:
    return uuid.uuid4().hex[:16]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _scrub_phones(text: str) -> str:
    """Redact phone-like strings only when the candidate has 9-15 digits.

    The raw regex also matches hex session ids and ISO timestamps (e.g.
    "2026-08-07T10:46:27"); counting digits keeps those intact while
    real Vietnamese phone numbers (9-11 digits, incl. separators) are
    still redacted.
    """

    def _repl(match: re.Match) -> str:
        digits = sum(ch.isdigit() for ch in match.group(0))
        return "[PHONE_REDACTED]" if 9 <= digits <= 15 else match.group(0)

    return _PHONE_RE.sub(_repl, text)


def scrub_text(text: str) -> str:
    """Heuristic scrub of emails, phone-like strings, and long ID strings.

    Limitations (documented): Vietnamese phone formats with special codes,
    short national numbers (e.g. 113) and numbers embedded in prose may
    survive; never rely on this alone for legal-grade redaction.
    """
    text = _EMAIL_RE.sub("[EMAIL_REDACTED]", text)
    text = _scrub_phones(text)
    text = _LONG_ID_RE.sub("[ID_REDACTED]", text)
    return text


def scrub_value(value: Any) -> Any:
    """Recursively scrub a JSON-serializable value (in place on containers).

    Keys in :data:`_PRESERVED_KEYS` (session_id, timestamp, chunk_id,
    source_id) are machine-generated identifiers and are never scrubbed.
    """
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, dict):
        for key in list(value.keys()):
            if isinstance(key, str) and key.lower() in _PRESERVED_KEYS:
                continue
            if isinstance(key, str) and key.lower() in {"transcript", "query", "text"}:
                value[key] = scrub_text(str(value[key]))
            else:
                value[key] = scrub_value(value[key])
    elif isinstance(value, list):
        return [scrub_value(item) for item in value]
    return value


def prune_old_logs(log_dir: Path, retention_days: int = 30) -> int:
    """Delete JSONL log files older than ``retention_days``; return count.

    Retention policy (privacy review #2): 0 = disabled, otherwise files with
    mtime older than the window are removed at startup.
    """
    if retention_days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc).timestamp() - retention_days * 86400
    removed = 0
    if not Path(log_dir).exists():
        return 0
    for path in Path(log_dir).glob("*.jsonl"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
        except OSError:
            continue
    return removed


class JsonlLogger:
    """Appends scrubbed JSONL records to a log file."""

    def __init__(self, log_dir: Path, filename: str = "session.log.jsonl"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.log_dir / filename

    def log(self, record: dict[str, Any], scrub: bool = True) -> None:
        safe = scrub_value(record) if scrub else record
        line = json.dumps(safe, ensure_ascii=False, default=str)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def read_records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return records


class SessionStore:
    """Tracks sessions; supports deletion (log lines + optional artifacts)."""

    def __init__(self, log_dir: Path, logger: Optional[JsonlLogger] = None):
        self.log_dir = Path(log_dir)
        self.logger = logger or JsonlLogger(self.log_dir)

    def create(self) -> str:
        session_id = new_session_id()
        self.logger.log(
            {
                "event": "session_start",
                "session_id": session_id,
                "timestamp": utc_now_iso(),
            }
        )
        return session_id

    def record(self, session_id: str, event: str, **fields: Any) -> None:
        record = {
            "event": event,
            "session_id": session_id,
            "timestamp": utc_now_iso(),
        }
        record.update(fields)
        self.logger.log(record)

    def delete_session(self, session_id: str, log_file: Optional[Path] = None) -> int:
        """Remove every log line belonging to a session; return lines removed.

        Note: scrubbed records may not contain full data; this only removes
        what the logger has (see docs/privacy_deletion_policy.md).
        """
        target = log_file or self.logger.path
        if not Path(target).exists():
            return 0
        kept: list[str] = []
        removed = 0
        with Path(target).open("r", encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                except json.JSONDecodeError:
                    kept.append(line)
                    continue
                if record.get("session_id") == session_id:
                    removed += 1
                else:
                    kept.append(line)
        if removed:
            tmp = Path(target).with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                fh.writelines(kept)
            tmp.replace(target)
        return removed
