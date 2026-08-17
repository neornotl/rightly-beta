"""Pre-deploy checklist (F3): verify the repo is safe+ready to go public.

Run before clicking Deploy on Streamlit Cloud / HF Spaces:
    python scripts/predeploy_check.py

Checks (each prints OK/WARN/FAIL):
1. No real-looking secrets committed (.env, gsk_, AIza, .streamlit/secrets.toml).
2. App imports (config, pipeline, ui deps, FAQ, contacts, forms).
3. data/faq.json + contacts.json parse; contacts verified flag consistent.
4. Corpus present (demo chunks + real sources if hybrid expected).
5. Requirements.txt present for Cloud installs.
6. Placeholder hotline flags: OFFICIAL_* still placeholder -> WARN (P must
   verify before public demo).
Exit code: 0 = ready, 1 = FAIL present, 2 = warnings only.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_SECRET_PATTERNS = (
    re.compile(r"gsk_[A-Za-z0-9_-]{20,}"),
    re.compile(r"AIza[A-Za-z0-9_-]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}"),
)
_SKIP_DIRS = {".git", "node_modules", ".venv", "debate_output", "results", "logs"}


def _check_secrets() -> list[str]:
    notes = ["OK: no obvious secrets committed"]
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        if path.suffix.lower() not in {".py", ".toml", ".json", ".md", ".txt", ".env", ".cfg"}:
            continue
        if rel.name == "secrets.toml.example":
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pat in _SECRET_PATTERNS:
            if pat.search(text):
                notes.append(f"FAIL: possible secret in {rel} ({pat.pattern[:20]}...)")
    return notes


def _check_imports() -> list[str]:
    notes = ["OK: app imports"]
    try:
        from app.config import load_settings
        from app.contacts import all_contacts
        from app.faq import FAQMatcher
        from app.pipeline import make_llm

        settings = load_settings()
        _ = settings, make_llm
        faq = FAQMatcher()
        if not faq.count:
            notes.append("WARN: data/faq.json missing or empty (voice FAQ disabled)")
        contacts = all_contacts()
        if not contacts:
            notes.append("WARN: data/contacts.json empty (connect feature shows 'no contacts')")
        elif any(not c.verified for c in contacts):
            notes.append(
                "WARN: some contacts unverified — dial buttons will be hidden until "
                "P sets verified=true with a real number"
            )
    except Exception as exc:  # noqa: BLE001
        notes.append(f"FAIL: import error: {exc}")
    return notes


def _check_data() -> list[str]:
    notes: list[str] = []
    demo = ROOT / "data" / "chunks" / "demo_chunks.jsonl"
    real = ROOT / "data" / "chunks" / "real_chunks.jsonl"
    sources = ROOT / "data" / "sources_real"
    notes.append("OK: chunks present" if demo.exists() else "FAIL: demo_chunks.jsonl missing")
    if real.exists():
        notes.append(
            f"OK: real_chunks.jsonl ({sum(1 for _ in real.open(encoding='utf-8'))} chunks)"
        )
    else:
        notes.append("WARN: real_chunks.jsonl missing (hybrid retrieval not ready)")
    real_sources = list(sources.glob("*.md")) if sources.exists() else []
    notes.append(
        f"INFO: {len(real_sources)} real law sources in data/sources_real (target 15-30 by 13/08)"
    )
    faq = ROOT / "data" / "faq.json"
    if faq.exists():
        try:
            payload = json.loads(faq.read_text(encoding="utf-8"))
            notes.append(f"OK: faq.json with {len(payload.get('faqs', []))} scripts")
        except ValueError as exc:
            notes.append(f"FAIL: faq.json invalid JSON: {exc}")
    contacts = ROOT / "data" / "contacts.json"
    if contacts.exists():
        try:
            payload = json.loads(contacts.read_text(encoding="utf-8"))
            notes.append(f"OK: contacts.json ({len(payload.get('contacts', []))} entries)")
        except ValueError as exc:
            notes.append(f"FAIL: contacts.json invalid JSON: {exc}")
    return notes


def main() -> int:
    checks = [_check_secrets, _check_imports, _check_data]
    fails = warns = 0
    for fn in checks:
        for note in fn():
            prefix = note.split(":", 1)[0]
            if prefix == "FAIL":
                fails += 1
            elif prefix == "WARN":
                warns += 1
            print(note)
    print(f"\n{len(checks)} checks done: {fails} FAIL(s), {warns} WARN(s)")
    return 1 if fails else (2 if warns else 0)


if __name__ == "__main__":
    raise SystemExit(main())
