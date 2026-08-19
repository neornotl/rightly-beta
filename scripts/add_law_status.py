#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATUS = ROOT / "data" / "law_status.json"
DB = ROOT / "data" / "legal_database.json"

NEW_IDS = [
    "nd401_2026", "tt11_2025_bhxh", "tt12_2025_bhxh", "nd144_2017",
    "nd69_2024", "nd118_2025", "nd45_2022", "nd282_2025", "nd91_2020",
    "nq110_2025", "tt04_2026_bgddt", "tt02_2025_bgddt", "tt15_2026_bgddt",
    "tt53_2026_bgddt", "tt15_2019_bgddt",
]

status = json.loads(STATUS.read_text(encoding="utf-8"))
db = json.loads(DB.read_text(encoding="utf-8"))
sources = status["sources"]
db_sources = db["sources"]

added = 0
for sid in NEW_IDS:
    if sid in sources:
        print(f"skip (exists): {sid}")
        continue
    info = db_sources.get(sid)
    if not info:
        print(f"MISSING in legal_database.json: {sid}")
        continue
    sources[sid] = {
        "ky_hieu": info.get("ky_hieu", ""),
        "loai": info.get("loai", ""),
        "ngay_ban_hanh": info.get("ngay_ban_hanh", ""),
        "ngay_hieu_luc": info.get("ngay_hieu_luc", ""),
        "trich_yeu": info.get("trich_yeu", ""),
        "expired_on": None,
        "replaced_by": None,
        "note": "",
        "status": "active_verified",
        "verified_on": "2026-08-19",
    }
    added += 1
    print(f"added: {sid}")

status["verified_on"] = "2026-08-19"
STATUS.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"law_status.json now has {len(sources)} sources (+{added})")