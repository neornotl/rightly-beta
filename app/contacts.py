"""Danh bạ đầu mối chuyển tuyến (đọc từ data/contacts.json).

Quy tắc triển khai (khớp ghi chú trong contacts.json):
- Chỉ hiển thị số điện thoại khi ``verified=true`` (P phải xác minh bằng cuộc
  gọi thử trước khi đưa vào demo public).
- Số chưa xác minh -> không render tel: link, chỉ hiển thị nhãn + ghi chú.
- Không bao giờ ghi nội dung danh bạ vào log.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

_CONTACTS_FILE = Path("data") / "contacts.json"


@dataclass(frozen=True)
class Contact:
    id: str
    label: str
    category: str
    phone: str = ""
    verified: bool = False
    note: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def callable(self) -> bool:
        """True when a real phone number is verified and safe to dial."""
        digits = "".join(ch for ch in self.phone if ch.isdigit())
        return self.verified and len(digits) >= 8

    @property
    def tel_link(self) -> str:
        """tel: URI for the dialer; empty when not callable."""
        if not self.callable:
            return ""
        return "tel:" + "".join(ch for ch in self.phone if ch.isdigit())


def _parse(raw: dict[str, Any]) -> Contact:
    return Contact(
        id=str(raw.get("id", "")),
        label=str(raw.get("label", "")),
        category=str(raw.get("category", "")),
        phone=str(raw.get("phone", "")),
        verified=bool(raw.get("verified", False)),
        note=str(raw.get("note", "")),
        extra={
            k: v
            for k, v in raw.items()
            if k not in {"id", "label", "category", "phone", "verified", "note"}
        },
    )


@lru_cache(maxsize=1)
def _load_contacts(path: Optional[Path] = None) -> tuple[Contact, ...]:
    file = path or _CONTACTS_FILE
    if not file.exists():
        return ()
    try:
        payload = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    contacts = payload.get("contacts", []) if isinstance(payload, dict) else []
    return tuple(_parse(c) for c in contacts if isinstance(c, dict) and c.get("id"))


def all_contacts() -> tuple[Contact, ...]:
    """All contacts from data/contacts.json (cached)."""
    return _load_contacts()


def find_contact(contact_id: str) -> Optional[Contact]:
    """Find a contact by id; None when missing."""
    for c in _load_contacts():
        if c.id == contact_id:
            return c
    return None


def find_by_category(category: str) -> tuple[Contact, ...]:
    """Contacts in a category, verified first."""
    hits = [c for c in _load_contacts() if c.category == category]
    return tuple(sorted(hits, key=lambda c: (not c.verified, c.id)))


def default_contact() -> Optional[Contact]:
    """Best-effort default (bộ phận một cửa trước, công an thứ hai)."""
    for category in ("bo_phan_mot_cua", "cong_an"):
        hits = find_by_category(category)
        if hits:
            return hits[0]
    return None
