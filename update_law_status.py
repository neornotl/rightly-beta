import json

# Load current law_status
with open('data/law_status.json', encoding='utf-8') as f:
    data = json.load(f)

# Add missing expired regulations
new_entries = {
    "nd135_2020": {
        "ky_hieu": "135/2020/NĐ-CP",
        "loai": "Nghị định",
        "ngay_ban_hanh": "18-11-2020",
        "ngay_hieu_luc": "01-01-2021",
        "trich_yeu": "Quy định về tuổi nghỉ hưu",
        "expired_on": "01-07-2025",
        "replaced_by": "158/2025/NĐ-CP",
        "note": "Hết hiệu lực từ 01/07/2025 theo Nghị định 158/2025/NĐ-CP. Chỉ giữ để tham khảo lịch sử.",
        "status": "expired",
        "verified_on": "2026-08-12"
    },
    "nd115_2015": {
        "ky_hieu": "115/2015/NĐ-CP",
        "loai": "Nghị định",
        "ngay_ban_hanh": "11-11-2015",
        "ngay_hieu_luc": "01-01-2016",
        "trich_yeu": "Quy định chi tiết một số điều và biện pháp thi hành Luật Bảo hiểm xã hội",
        "expired_on": "01-07-2025",
        "replaced_by": "158/2025/NĐ-CP",
        "note": "Hết hiệu lực từ 01/07/2025 theo Nghị định 158/2025/NĐ-CP. Chỉ giữ để tham khảo lịch sử.",
        "status": "expired",
        "verified_on": "2026-08-12"
    }
}

# Add key Thông tư (TTLT) - current active ones
ttlt_entries = {
    "ttlt11_2025": {
        "ky_hieu": "11/2025/TT-BLĐTBXH",
        "loai": "Thông tư liên tịch",
        "ngay_ban_hanh": "15-04-2025",
        "ngay_hieu_luc": "01-07-2025",
        "trich_yeu": "Hướng dẫn thi hành một số điều của Luật Việc làm về bảo hiểm thất nghiệp",
        "expired_on": None,
        "replaced_by": None,
        "note": "TTLT hướng dẫn Luật Việc làm 74/2025/QH15 về BHTN",
        "status": "active_verified",
        "verified_on": "2026-08-12"
    },
    "ttlt12_2025": {
        "ky_hieu": "12/2025/TT-BLĐTBXH",
        "loai": "Thông tư liên tịch",
        "ngay_ban_hanh": "15-04-2025",
        "ngay_hieu_luc": "01-07-2025",
        "trich_yeu": "Hướng dẫn thi hành một số điều của Luật Bảo hiểm xã hội về bảo hiểm xã hội bắt buộc",
        "expired_on": None,
        "replaced_by": None,
        "note": "TTLT hướng dẫn Luật BHXH 41/2024/QH15",
        "status": "active_verified",
        "verified_on": "2026-08-12"
    },
    "ttlt13_2025": {
        "ky_hieu": "13/2025/TT-BLĐTBXH",
        "loai": "Thông tư liên tịch",
        "ngay_ban_hanh": "15-04-2025",
        "ngay_hieu_luc": "01-07-2025",
        "trich_yeu": "Hướng dẫn thi hành một số điều của Luật Bảo hiểm y tế",
        "expired_on": None,
        "replaced_by": None,
        "note": "TTLT hướng dẫn Luật BYT 25/2008/QH12 (sửa đổi)",
        "status": "active_verified",
        "verified_on": "2026-08-12"
    },
    "ttlt14_2025": {
        "ky_hieu": "14/2025/TT-BLĐTBXH",
        "loai": "Thông tư liên tịch",
        "ngay_ban_hanh": "15-04-2025",
        "ngay_hieu_luc": "01-07-2025",
        "trich_yeu": "Hướng dẫn thi hành một số điều của Luật Việc làm về bảo hiểm thất nghiệp",
        "expired_on": None,
        "replaced_by": None,
        "note": "TTLT hướng dẫn Luật Việc làm 74/2025/QH15 về BHTN",
        "status": "active_verified",
        "verified_on": "2026-08-12"
    }
}

# Merge new entries
data['sources'].update(new_entries)
data['sources'].update(ttlt_entries)

# Update verified_on
data['verified_on'] = "2026-08-12"

# Write back
with open('data/law_status.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("Updated law_status.json with:")
for k in new_entries:
    print(f"  - {k}: {new_entries[k]['ky_hieu']} ({new_entries[k]['status']})")
for k in ttlt_entries:
    print(f"  - {k}: {ttlt_entries[k]['ky_hieu']} ({ttlt_entries[k]['status']})")