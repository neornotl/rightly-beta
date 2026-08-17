# -*- coding: utf-8 -*-
"""Convert decree txt files into sources_real markdown with front matter."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LEGAL = ROOT / "legal-sources" / "decrees-n-decisions"
DEST = ROOT / "data" / "sources_real"

jobs = [
    {
        "src": "161-2026-NĐ-CP Nghị định của Chính phủ Quy định mức lương cơ sở và chế độ tiền thưởng đối với cán bộ, công chức, viên chức và lực lượng vũ trang.txt",
        "dest": "nd161_2026.md",
        "source_id": "nd161_2026",
        "title": "Nghị định 161/2026/NĐ-CP quy định mức lương cơ sở và chế độ tiền thưởng đối với cán bộ, công chức, viên chức và lực lượng vũ trang",
        "publisher": "Chính phủ",
        "published_date": "01-07-2026",
        "url": "https://congbao.chinhphu.vn",
        "notes": "Quy định mức lương cơ sở 2.530.000 đồng/tháng từ 01/07/2026. Thay thế Nghị định 73/2024/NĐ-CP.",
    },
    {
        "src": "283-2026-NĐ-CP Nghị định Quy định xử phạt vi phạm hành chính trong lĩnh vực lao động, bảo hiểm xã hội, người lao động Việt Nam đi làm việc ở nước ngoài theo hợp đồng.txt",
        "dest": "nd283_2026.md",
        "source_id": "nd283_2026",
        "title": "Nghị định 283/2026/NĐ-CP quy định xử phạt vi phạm hành chính trong lĩnh vực lao động, bảo hiểm xã hội, người lao động Việt Nam đi làm việc ở nước ngoài theo hợp đồng",
        "publisher": "Chính phủ",
        "published_date": "01-07-2026",
        "url": "https://congbao.chinhphu.vn",
        "notes": "Thay thế Nghị định 12/2022/NĐ-CP về xử phạt vi phạm hành chính trong lĩnh vực lao động, BHXH.",
    },
]

for job in jobs:
    src = LEGAL / job["src"]
    dest = DEST / job["dest"]
    text = src.read_text(encoding="utf-8")
    # Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Clean leading/trailing whitespace
    text = text.strip()
    fm = (
        "---\n"
        f"source_id: {job['source_id']}\n"
        f'title: "{job["title"]}"\n'
        "source_type: gov_legal\n"
        f'publisher: "{job["publisher"]}"\n'
        f'published_date: "{job["published_date"]}"\n'
        f'url: "{job["url"]}"\n'
        "license: \"PUBLIC\"\n"
        f'notes: "{job["notes"]}"\n'
        "---\n\n"
    )
    dest.write_text(fm + text, encoding="utf-8")
    print(f"{job['dest']}: {len(text)} chars -> written")