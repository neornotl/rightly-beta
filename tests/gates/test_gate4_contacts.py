"""GATE 4 — Escalation / contacts (Luna gate #4).

`data/contacts.json` must be schema-valid AND carry a minimum number of
verified contacts for the pilot flows. A verified contact has
`verified: true` plus a verification date and a purpose.

BLOCKER: the file is empty today (0 contacts), so this gate FAILS. It must
be populated and verified before opening the pilot — the app must never
invent hotline numbers.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

CONTACTS = Path("data/contacts.json")

REQUIRED_FIELDS = {"id", "name", "phone", "verified", "verified_on", "purpose"}


def _load() -> dict:
    return json.loads(CONTACTS.read_text(encoding="utf-8"))


def test_gate4_schema_valid():
    data = _load()
    assert data.get("schema") == 1, "contacts.json schema must be 1"
    assert isinstance(data.get("contacts"), list), "contacts must be a list"


def test_gate4_each_contact_is_complete():
    data = _load()
    for contact in data.get("contacts", []):
        missing = REQUIRED_FIELDS - set(contact)
        assert not missing, f"contact {contact.get('id')} missing fields: {missing}"
        assert isinstance(contact["verified"], bool)
        assert contact["phone"], f"contact {contact.get('id')} has empty phone"


def test_gate4_min_verified_contacts_for_pilot():
    """Gate bar: at least GATE4_MIN_CONTACTS verified contacts (default 5)."""
    minimum = int(os.environ.get("GATE4_MIN_CONTACTS", "5"))
    data = _load()
    verified = [c for c in data["contacts"] if c.get("verified")]
    assert len(verified) >= minimum, (
        f"contacts.json has {len(verified)} verified contacts, need >= {minimum}. "
        "BLOCKER: populate + verify real hotlines/one-stop contacts before pilot."
    )
    for contact in verified:
        assert contact.get("verified_on"), f"verified contact {contact['id']} needs verified_on"
        assert contact.get("purpose"), f"verified contact {contact['id']} needs a purpose"
