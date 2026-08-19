#!/usr/bin/env python3
"""Convert selected legal txt files into data/sources_real/*.md and register
them in data/legal_database.json, then rebuild real_chunks.jsonl.

Selected files are the ~15 high-value legal documents among the ones the
friend sent that are NOT yet indexed.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEGAL = ROOT / "legal-sources"
DEST = ROOT / "data" / "sources_real"
DB = ROOT / "data" / "legal_database.json"

# (txt_relpath, source_id, ky_hieu, loai, co_quan, ngay_ban_hanh, ngay_hieu_luc, trich_yeu, linh_vuc, tags)
JOBS = [
    (
        "decrees-n-decisions/401-VBHN-BTP 2026 Nghị định Quy định chi tiết một số điều và biện pháp thi hành Luật Hộ tịch.txt",
        "nd401_2026", "401/VBHN-BTP 2026", "Nghị định", "Chính phủ", "15-11-2015", "01-01-2016",
        "Nghị định quy định chi tiết một số điều và biện pháp thi hành Luật Hộ tịch (hợp nhất)",
        "Hộ tịch", ["hộ tịch", "khai sinh", "kết hôn", "đăng ký hộ tịch"],
    ),
    (
        "circular/11-2025-TT-BNV Thông tư Quy định chi tiết một số điều của Luật Bảo hiểm xã hội về bảo hiểm xã hội tự nguyện.txt",
        "tt11_2025_bhxh", "11/2025/TT-BNV", "Thông tư", "Bộ Nội vụ", "2025", "2025",
        "Thông tư quy định chi tiết một số điều của Luật Bảo hiểm xã hội về bảo hiểm xã hội tự nguyện",
        "Bảo hiểm xã hội", ["bhxh", "bảo hiểm tự nguyện", "lương hưu"],
    ),
    (
        "circular/12-2025-TT-BNV Thông tư Quy định chi tiết một số điều của Luật Bảo hiểm xã hội về bảo hiểm xã hội bắt buộc.txt",
        "tt12_2025_bhxh", "12/2025/TT-BNV", "Thông tư", "Bộ Nội vụ", "2025", "2025",
        "Thông tư quy định chi tiết một số điều của Luật Bảo hiểm xã hội về bảo hiểm xã hội bắt buộc",
        "Bảo hiểm xã hội", ["bhxh", "bảo hiểm bắt buộc", "lương hưu"],
    ),
    (
        "decrees-n-decisions/144-2017-NĐ-CP Nghị định Quy định chi tiết một số điều của Luật Trợ giúp pháp lý.txt",
        "nd144_2017", "144/2017/NĐ-CP", "Nghị định", "Chính phủ", "2017", "2017",
        "Nghị định quy định chi tiết một số điều của Luật Trợ giúp pháp lý",
        "Trợ giúp pháp lý", ["trợ giúp pháp lý", "trợ giúp"],
    ),
    (
        "decrees-n-decisions/69-2024-NĐ-CP Nghị định Quy định về định danh và xác thực điện tử.txt",
        "nd69_2024", "69/2024/NĐ-CP", "Nghị định", "Chính phủ", "2024", "2024",
        "Nghị định quy định về định danh và xác thực điện tử",
        "Định danh điện tử", ["định danh", "xác thực điện tử", "tài khoản định danh"],
    ),
    (
        "decrees-n-decisions/118-2025-NĐ-CP Nghị định Về thực hiện thủ tục hành chính theo cơ chế một cửa, một cửa liên thông tại Bộ phận Một cửa và Cổng Dịch vụ công quốc gia.txt",
        "nd118_2025", "118/2025/NĐ-CP", "Nghị định", "Chính phủ", "2025", "2025",
        "Nghị định về thực hiện thủ tục hành chính theo cơ chế một cửa, một cửa liên thông",
        "Thủ tục hành chính", ["một cửa", "thủ tục hành chính", "dịch vụ công"],
    ),
    (
        "decrees-n-decisions/45-2022-NĐ-CP Nghị định Quy định về xử phạt vi phạm hành chính trong lĩnh vực bảo vệ môi trường.txt",
        "nd45_2022", "45/2022/NĐ-CP", "Nghị định", "Chính phủ", "2022", "2022",
        "Nghị định quy định về xử phạt vi phạm hành chính trong lĩnh vực bảo vệ môi trường",
        "Môi trường", ["xử phạt", "môi trường", "vi phạm hành chính"],
    ),
    (
        "decrees-n-decisions/282-2025-NĐ-CP Nghị định Quy định xử phạt vi phạm hành chính trong lĩnh vực an ninh, trật tự, an toàn xã hội; phòng, chống tệ nạn xã hội; phòng, chống bạo lực gia đình.txt",
        "nd282_2025", "282/2025/NĐ-CP", "Nghị định", "Chính phủ", "2025", "2025",
        "Nghị định quy định xử phạt vi phạm hành chính trong lĩnh vực an ninh, trật tự, an toàn xã hội; phòng, chống tệ nạn xã hội; phòng, chống bạo lực gia đình",
        "An ninh trật tự", ["xử phạt", "bạo lực gia đình", "an ninh trật tự"],
    ),
    (
        "decrees-n-decisions/91-2020-NĐ-CP Nghị định Chống tin nhắn rác, thư điện tử rác, cuộc gọi rác.txt",
        "nd91_2020", "91/2020/NĐ-CP", "Nghị định", "Chính phủ", "2020", "2020",
        "Nghị định chống tin nhắn rác, thư điện tử rác, cuộc gọi rác",
        "An ninh mạng", ["tin nhắn rác", "spam", "cuộc gọi rác"],
    ),
    (
        "ordinances-n-resolutions/110-2025-UBTVQH15 Nghị quyết về điều chỉnh mức giảm trừ gia cảnh của thuế thu nhập cá nhân.txt",
        "nq110_2025", "110/2025/UBTVQH15", "Nghị quyết", "Ủy ban Thường vụ Quốc hội", "2025", "2025",
        "Nghị quyết về điều chỉnh mức giảm trừ gia cảnh của thuế thu nhập cá nhân",
        "Thuế", ["giảm trừ gia cảnh", "thuế thu nhập cá nhân", "thuế"],
    ),
    (
        "circular/04-VBHN-BGDĐT 2026 Thông tư Quy định về dạy thêm, học thêm.txt",
        "tt04_2026_bgddt", "04/VBHN-BGDĐT 2026", "Thông tư", "Bộ Giáo dục và Đào tạo", "2026", "2026",
        "Thông tư quy định về dạy thêm, học thêm",
        "Giáo dục", ["dạy thêm", "học thêm"],
    ),
    (
        "circular/02-2025-TT-BGDĐT Thông tư Quy định về Khung năng lực số cho người học trong hệ thống giáo dục quốc dân.txt",
        "tt02_2025_bgddt", "02/2025/TT-BGDĐT", "Thông tư", "Bộ Giáo dục và Đào tạo", "2025", "2025",
        "Thông tư quy định về Khung năng lực số cho người học trong hệ thống giáo dục quốc dân",
        "Giáo dục", ["năng lực số", "giáo dục"],
    ),
    (
        "circular/15-2026-TT-BGDĐT Thông tư Ban hành Điều lệ trường tiểu học, trường trung học cơ sở, trường trung học phổ thông và trường phổ thông có nhiều cấp học.txt",
        "tt15_2026_bgddt", "15/2026/TT-BGDĐT", "Thông tư", "Bộ Giáo dục và Đào tạo", "2026", "2026",
        "Thông tư ban hành Điều lệ trường tiểu học, trung học cơ sở, trung học phổ thông",
        "Giáo dục", ["điều lệ trường học", "giáo dục"],
    ),
    (
        "circular/53-2026-TT-BGDĐT Thông tư Ban hành Quy chế tuyển sinh và đào tạo sau đại học.txt",
        "tt53_2026_bgddt", "53/2026/TT-BGDĐT", "Thông tư", "Bộ Giáo dục và Đào tạo", "2026", "2026",
        "Thông tư ban hành Quy chế tuyển sinh và đào tạo sau đại học",
        "Giáo dục", ["tuyển sinh", "sau đại học", "giáo dục"],
    ),
    (
        "circular/15-2019-TT-BGDĐT Thông tư Ban hành quy định Chuẩn quốc gia về chữ nổi Braille cho người khuyết tật.txt",
        "tt15_2019_bgddt", "15/2019/TT-BGDĐT", "Thông tư", "Bộ Giáo dục và Đào tạo", "2019", "2019",
        "Thông tư ban hành quy định Chuẩn quốc gia về chữ nổi Braille cho người khuyết tật",
        "Người khuyết tật", ["braille", "người khuyết tật", "giáo dục"],
    ),
]


def main() -> None:
    db = json.loads(DB.read_text(encoding="utf-8"))
    sources = db["sources"]

    for rel, sid, ky_hieu, loai, co_quan, ban_hanh, hieu_luc, trich_yeu, linh_vuc, tags in JOBS:
        src = LEGAL / rel
        if not src.exists():
            print(f"MISSING TXT: {rel}")
            continue
        text = src.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
        dest = DEST / f"{sid}.md"
        front = (
            "---\n"
            f"source_id: {sid}\n"
            f'title: "{trich_yeu}"\n'
            "source_type: gov_legal\n"
            f'publisher: "{co_quan}"\n'
            f'published_date: "{ban_hanh}"\n'
            'url: "https://vanban.chinhphu.vn"\n'
            'notes: "Consolidated text sent by collaborator"\n'
            "---\n\n"
        )
        dest.write_text(front + text, encoding="utf-8")
        sources[sid] = {
            "source_id": sid,
            "docid": "",
            "ky_hieu": ky_hieu,
            "loai": loai,
            "co_quan": co_quan,
            "ngay_ban_hanh": ban_hanh,
            "ngay_hieu_luc": hieu_luc,
            "trich_yeu": trich_yeu,
            "url": "https://vanban.chinhphu.vn",
            "pdf_local": "",
            "chars": len(text),
            "status": "active_verified",
            "linh_vuc": linh_vuc,
            "tags": tags,
        }
        print(f"converted {sid}: {len(text)} chars")

    DB.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"legal_database.json now has {len(sources)} sources")


if __name__ == "__main__":
    main()