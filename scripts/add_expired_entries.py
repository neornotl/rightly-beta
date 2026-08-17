"""Add 3 expired Round-19 decrees (stubs already in sources_real) to the DB,
and copy the Luat Ho tich 03/2026 text from legal-sources into sources_real."""

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "legal_database.json"
STATUS_PATH = ROOT / "data" / "law_status.json"
REGISTRY_PATH = ROOT / "data" / "source_registry.csv"
SOURCES = ROOT / "data" / "sources_real"

db = json.loads(DB_PATH.read_text(encoding="utf-8"))
status_db = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
sources = db["sources"]

ENTRIES = {
    "nd73_2024": {
        "docid": None,
        "ky_hieu": "73/2024/NĐ-CP",
        "ngay_ban_hanh": "2024-06-30",
        "ngay_hieu_luc": "2024-07-01",
        "expired_on": "2026-07-01",
        "replaced_by": "nd161_2026",
        "loai": "Nghị định",
        "co_quan": "Chính phủ",
        "linh_vuc": "Lao động",
        "nguoi_ky": "Phạm Minh Chính",
        "trich_yeu": "Nghị định quy định mức lương cơ sở và chế độ tiền thưởng đối với cán bộ, công chức, viên chức và lực lượng vũ trang",
        "status": "expired",
    },
    "nd74_2024": {
        "docid": None,
        "ky_hieu": "74/2024/NĐ-CP",
        "ngay_ban_hanh": "2024-06-30",
        "ngay_hieu_luc": "2024-07-01",
        "expired_on": "2026-01-01",
        "replaced_by": "nd293_2025",
        "loai": "Nghị định",
        "co_quan": "Chính phủ",
        "linh_vuc": "Lao động",
        "nguoi_ky": "Phạm Minh Chính",
        "trich_yeu": "Nghị định quy định mức lương tối thiểu đối với người lao động làm việc theo hợp đồng lao động",
        "status": "expired",
    },
    "nd115_2015": {
        "docid": 178129,
        "ky_hieu": "115/2015/NĐ-CP",
        "ngay_ban_hanh": "2015-11-11",
        "ngay_hieu_luc": "2016-01-01",
        "expired_on": "2025-07-01",
        "replaced_by": "nd158_2025",
        "loai": "Nghị định",
        "co_quan": "Chính phủ",
        "linh_vuc": "Bảo hiểm xã hội",
        "nguoi_ky": "Nguyễn Tấn Dũng",
        "trich_yeu": "Nghị định quy định chi tiết một số điều và biện pháp thi hành Luật Bảo hiểm xã hội về bảo hiểm xã hội bắt buộc",
        "status": "expired",
    },
}

for sid, e in ENTRIES.items():
    md = SOURCES / f"{sid}.md"
    text = md.read_text(encoding="utf-8")
    has_fm = text.startswith("---")
    body = text
    chars = 0
    if has_fm:
        end = text.index("---", 3)
        body = text[end + 3 :].strip()
    chars = len(body)
    source = {
        "source_id": sid,
        "docid": e["docid"],
        "ky_hieu": e["ky_hieu"],
        "loai": e["loai"],
        "co_quan": e["co_quan"],
        "ngay_ban_hanh": e["ngay_ban_hanh"],
        "ngay_hieu_luc": e["ngay_hieu_luc"],
        "trich_yeu": e["trich_yeu"],
        "url": "https://vanban.chinhphu.vn",
        "pdf_local": None,
        "chars": chars,
        "status": "expired",
        "linh_vuc": e["linh_vuc"],
        "tags": [e["linh_vuc"]],
        "replaced_by": e["replaced_by"],
        "expired_on": e["expired_on"],
        "effective_date": e["ngay_hieu_luc"],
        "source_type": e["loai"],
        "issuing_authority": e["co_quan"],
        "document_number": e["ky_hieu"],
        "gazette_number": "",
        "pages": 0,
        "source_file": "legacy stub (round19)",
        "nguoi_ky": e["nguoi_ky"],
        "note": f"HẾT HIỆU LỰC từ {e['expired_on']} theo {db['sources'].get(e['replaced_by'], {}).get('ky_hieu', e['replaced_by'])}. Giữ stub để tham khảo lịch sử.",
    }
    sources[sid] = source
    status_db["sources"][sid] = {
        "ky_hieu": e["ky_hieu"],
        "loai": e["loai"],
        "ngay_ban_hanh": e["ngay_ban_hanh"],
        "ngay_hieu_luc": e["ngay_hieu_luc"],
        "trich_yeu": e["trich_yeu"],
        "expired_on": e["expired_on"],
        "replaced_by": e["replaced_by"],
        "note": "Expired stub giữ tham khảo lịch sử (Round 19).",
        "status": "expired",
        "verified_on": "2026-08-15",
    }
    print(f"[OK] {sid}: status=expired, expired_on={e['expired_on']}, replaced_by={e['replaced_by']}, chars(body)={chars}")

src_text = ROOT / "legal-sources" / "laws-n-codes" / "03-2026-QH16 Luật Hộ tịch.txt"
if src_text.exists():
    target = SOURCES / "luat03_2026.md"
    content = src_text.read_text(encoding="utf-8", errors="replace").strip() + "\n"
    target.write_text(content, encoding="utf-8")
    chars = len(content.strip())
    if "luat03_2026" in sources:
        sources["luat03_2026"]["chars"] = chars
        sources["luat03_2026"]["source_file"] = "legal-sources/laws-n-codes"
    print(f"[OK] luat03_2026.md copied: {chars} chars (DB chars updated to {chars})")
else:
    print("[WARN] luat03_2026 source file not found")

DB_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
STATUS_PATH.write_text(json.dumps(status_db, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"sources total: {len(sources)}")
print("Next: rebuild chunks + embeddings (embed ~38 min, then build).")