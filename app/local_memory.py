"""Windows-user-bound encrypted local conversation memory.

Only ciphertext is stored in SQLite.  The AES-GCM key is wrapped by Windows
DPAPI for the current Windows user, so copying the database to another user or
machine does not reveal the conversation.  This module is intentionally local
only; it contains no HTTP or cloud integration.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import secrets
import sqlite3
import sys
import time
from ctypes import wintypes
from pathlib import Path


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes):
    buf = (ctypes.c_byte * len(data)).from_buffer_copy(data)
    return _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte))), buf


def _dpapi_protect(data: bytes) -> bytes:
    if sys.platform != "win32":
        raise RuntimeError("Encrypted local memory requires Windows DPAPI")
    inp, _buf = _blob(data)
    out = _DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptProtectData(ctypes.byref(inp), None, None, None, None, 1, ctypes.byref(out)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    if sys.platform != "win32":
        raise RuntimeError("Encrypted local memory requires Windows DPAPI")
    inp, _buf = _blob(data)
    out = _DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptUnprotectData(ctypes.byref(inp), None, None, None, None, 1, ctypes.byref(out)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


class LocalMemoryStore:
    """Encrypted, retention-bound turns keyed by a local session id."""

    def __init__(self, db_path: str | Path, retention_days: int = 90):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.key_path = self.db_path.with_suffix(self.db_path.suffix + ".key.dpapi")
        self.retention_days = max(1, int(retention_days))
        self._key = self._load_key()
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as exc:  # pragma: no cover - installer supplies it
            raise RuntimeError("cryptography is required for local encrypted memory") from exc
        self._aes = AESGCM(self._key)
        self._init_db()
        self.purge_expired()

    def _load_key(self) -> bytes:
        if self.key_path.exists():
            return _dpapi_unprotect(self.key_path.read_bytes())
        raw = secrets.token_bytes(32)
        self.key_path.write_bytes(_dpapi_protect(raw))
        try:
            os.chmod(self.key_path, 0o600)
        except OSError:
            pass
        return raw

    def _init_db(self) -> None:
        db = sqlite3.connect(self.db_path)
        try:
            db.execute(
                "CREATE TABLE IF NOT EXISTS turns ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, "
                "role TEXT NOT NULL CHECK(role IN ('user','assistant')), "
                "ciphertext BLOB NOT NULL, created_at REAL NOT NULL)"
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, id)")
            db.commit()
        finally:
            db.close()

    def _encrypt(self, value: str) -> bytes:
        nonce = secrets.token_bytes(12)
        return nonce + self._aes.encrypt(nonce, value.encode("utf-8"), None)

    def _decrypt(self, value: bytes) -> str:
        nonce, ciphertext = value[:12], value[12:]
        return self._aes.decrypt(nonce, ciphertext, None).decode("utf-8")

    def append(self, session_id: str, role: str, content: str) -> None:
        if role not in {"user", "assistant"} or not str(content).strip():
            return
        db = sqlite3.connect(self.db_path)
        try:
            db.execute(
                "INSERT INTO turns(session_id, role, ciphertext, created_at) VALUES(?,?,?,?)",
                (session_id[:100], role, self._encrypt(str(content)[:12000]), time.time()),
            )
            db.commit()
        finally:
            db.close()

    def history(self, session_id: str, limit: int = 1000) -> list[dict[str, str]]:
        db = sqlite3.connect(self.db_path)
        try:
            rows = db.execute(
                "SELECT role, ciphertext FROM turns WHERE session_id=? ORDER BY id DESC LIMIT ?",
                (session_id[:100], max(1, min(int(limit), 2000))),
            ).fetchall()
        finally:
            db.close()
        return [{"role": role, "content": self._decrypt(bytes(cipher))} for role, cipher in reversed(rows)]

    def purge_expired(self) -> int:
        cutoff = time.time() - self.retention_days * 86400
        db = sqlite3.connect(self.db_path)
        try:
            cur = db.execute("DELETE FROM turns WHERE created_at < ?", (cutoff,))
            db.commit()
            return int(cur.rowcount or 0)
        finally:
            db.close()

    def clear(self, session_id: str | None = None) -> int:
        db = sqlite3.connect(self.db_path)
        try:
            if session_id:
                cur = db.execute("DELETE FROM turns WHERE session_id=?", (session_id[:100],))
            else:
                cur = db.execute("DELETE FROM turns")
            deleted = int(cur.rowcount or 0)
            db.commit()
        finally:
            db.close()
        if session_id:
            return deleted
        # Full wipe also removes the DPAPI-wrapped key.  Recreate a fresh
        # database/key pair so a subsequent new session remains usable.
        try:
            self.db_path.unlink(missing_ok=True)
            self.key_path.unlink(missing_ok=True)
        finally:
            self._key = self._load_key()
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM

            self._aes = AESGCM(self._key)
            self._init_db()
        return deleted
