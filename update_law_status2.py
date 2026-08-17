import json

with open('data/law_status.json', encoding='utf-8') as f:
    data = json.load(f)

new_entries = {
    "nd161_2026": {
        "ky_hieu": "161/2026/NĐ-CP",
        "loai": "Nghị định",
        "ngay_ban_hanh": "01-07-2026",
        "ngay_hieu_luc": "01-07-2026",
        "trich_yeu": "Quy định mức lương cơ sở 2.530.000 đồng/tháng và chế độ tiền thưởng đối với cán bộ, công chức, viên chức, lực lượng vũ trang",
        "expired_on": None,
        "replaced_by": None,
        "note": "Thay thế Nghị định 73/2024/NĐ-CP. Mức lương cơ sở mới từ 01/07/2026: 2.530.000 đồng/tháng.",
        "status": "active_verified",
        "verified_on": "2026-08-12"
    },
    "nd283_2026": {
        "ky_hieu": "283/2026/NĐ-CP",
        "loai": "Nghị định",
        "ngay_ban_hanh": "01-07-2026",
        "ngay_hieu_luc": "01-07-2026",
        "trich_yeu": "Quy định xử phạt vi phạm hành chính trong lĩnh vực lao động, bảo hiểm xã hội, người lao động Việt Nam đi làm việc ở nước ngoài theo hợp đồng",
        "expired_on": None,
        "replaced_by": None,
        "note": "Thay thế Nghị định 12/2022/NĐ-CP. Hiệu lực từ 01/07/2026.",
        "status": "active_verified",
        "verified_on": "2026-08-12"
    },
    "nd293_2025": {
        "ky_hieu": "293/2025/NĐ-CP",
        "loai": "Nghị định",
        "ngay_ban_hanh": "10-11-2025",
        "ngay_hieu_luc": "01-01-2026",
        "trich_yeu": "Quy định mức lương tối thiểu vùng đối với người lao động làm việc theo hợp đồng lao động",
        "expired_on": None,
        "replaced_by": None,
        "note": "Hiệu lực từ 01/01/2026. Thay thế ND 74/2024. Vùng I: 5.310.000đ/tháng, II: 4.730.000đ, III: 4.140.000đ, IV: 3.700.000đ. Giờ: I 25.500đ, II 22.700đ, III 20.000đ, IV 17.800đ.",
        "status": "active_verified",
        "verified_on": "2026-08-12"
    },
    "nd74_2024": {
        "ky_hieu": "74/2024/NĐ-CP",
        "loai": "Nghị định",
        "ngay_ban_hanh": "30-06-2024",
        "ngay_hieu_luc": "01-07-2024",
        "trich_yeu": "Quy định mức lương tối thiểu vùng đối với người lao động làm việc theo hợp đồng lao động",
        "expired_on": "01-01-2026",
        "replaced_by": "293/2025/NĐ-CP",
        "note": "Hết hiệu lực từ 01/01/2026 theo Nghị định 293/2025/NĐ-CP. Mức cũ: Vùng I 4.960.000đ, II 4.410.000đ, III 3.860.000đ, IV 3.450.000đ. Chỉ giữ để tham khảo lịch sử.",
        "status": "expired",
        "verified_on": "2026-08-12"
    },
    "nd73_2024": {
        "ky_hieu": "73/2024/NĐ-CP",
        "loai": "Nghị định",
        "ngay_ban_hanh": "30-06-2024",
        "ngay_hieu_luc": "01-07-2024",
        "trich_yeu": "Quy định mức lương cơ sở 2.340.000 đồng/tháng và chế độ tiền thưởng đối với cán bộ, công chức, viên chức, lực lượng vũ trang",
        "expired_on": "01-07-2026",
        "replaced_by": "161/2026/NĐ-CP",
        "note": "Hết hiệu lực từ 01/07/2026 theo Nghị định 161/2026/NĐ-CP. Mức lương cơ sở cũ: 2.340.000 đồng/tháng (07/2024 - 06/2026). Chỉ giữ để tham khảo lịch sử.",
        "status": "expired",
        "verified_on": "2026-08-12"
    }
}

data['sources'].update(new_entries)
data['verified_on'] = "2026-08-12"

with open('data/law_status.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("Updated law_status.json with 5 new entries:")
for k, v in new_entries.items():
    print(f"  - {k}: {v['ky_hieu']} ({v['status']})")
print(f"Total sources: {len(data['sources'])}")