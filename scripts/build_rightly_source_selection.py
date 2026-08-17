#!/usr/bin/env python3
"""Select the smallest useful verified legal corpus for Rightly.

The manifest is a curation aid, not a legal opinion. Statuses are inherited
from source_registry.csv and must be re-verified before production use.
"""
import csv
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "data" / "source_registry.csv"
OUT = ROOT / "data" / "rightly_source_selection.csv"
REPORT = ROOT / "docs" / "rightly_source_selection.md"

CORE = {
    "Bộ luật Dân sự", "Luật Hôn nhân và Gia đình", "Luật Hộ tịch", "Luật Cư trú",
    "Luật Căn cước", "Luật Quốc tịch Việt Nam", "Luật Đất đai", "Luật Nhà ở",
    "Luật Kinh doanh bất động sản", "Luật Xây dựng", "Bộ luật Lao động",
    "Luật Việc làm", "Luật Bảo hiểm xã hội", "Luật Bảo hiểm Y tế",
    "Luật Khám bệnh, chữa bệnh", "Luật Người cao tuổi", "Luật Người khuyết tật",
    "Luật Trợ giúp pháp lý", "Luật Khiếu nại", "Luật Tố cáo",
    "Luật Xử lý vi phạm hành chính", "Luật Ban hành văn bản quy phạm pháp luật",
    "Luật Phổ biến, giáo dục pháp luật", "Luật Hòa giải ở cơ sở",
    "Luật Thi hành án dân sự", "Luật Tố tụng dân sự", "Luật Tố tụng hành chính",
    "Luật Luật sư", "Luật Công chứng", "Luật Bảo vệ quyền lợi người tiêu dùng",
    "Luật Giao dịch điện tử", "Luật An toàn, vệ sinh lao động",
    "Luật Trật tự, an toàn giao thông đường bộ", "Luật Đường bộ",
}

CORE_KEYS = (
    "bo luat dan su", "hon nhan va gia dinh", "ho tich", "cu tru", "can cuoc",
    "quoc tich", "dat dai", "nha o", "kinh doanh bat dong san", "xay dung",
    "bo luat lao dong", "viec lam", "bao hiem xa hoi", "bao hiem y te",
    "kham benh chua benh", "nguoi cao tuoi", "nguoi khuyet tat", "tro giup phap ly",
    "khieu nai", "to cao", "xu ly vi pham hanh chinh", "ban hanh van ban",
    "pho bien giao duc phap luat", "hoa giai o co so", "thi hanh an dan su",
    "to tung dan su", "to tung hanh chinh", "luat su", "cong chung",
    "bao ve quyen loi nguoi tieu dung", "giao dich dien tu", "an toan ve sinh lao dong",
    "trat tu an toan giao thong", "duong bo",
)

SUPPORT = {
    "Nghị định quy định chi tiết một số điều và biện pháp thi hành Luật Hộ tịch",
    "Quy định chi tiết một số điều và biện pháp thi hành Luật Hôn nhân và gia đình",
    "Quy định chi tiết một số điều Luật Cư trú",
    "Quy định chi tiết một số điều và biện pháp thi hành Luật Cư trú",
    "Sửa đổi, bổ sung một số điều của các Nghị định trong lĩnh vực hộ tịch, quốc tịch, chứng thực",
    "Quy định chi tiết và biện pháp thi hành Luật Căn cước",
    "Nghị định quy định chi tiết và hướng dẫn thi hành một số điều của Bộ luật Lao động",
    "Nghị định quy định về tuổi nghỉ hưu",
    "Nghị định quy định về phân định thẩm quyền của chính quyền địa phương 02 cấp trong lĩnh vực quản lý nhà nước của Bộ Tư pháp",
    "Nghị định quy định về phân định thẩm quyền của chính quyền địa phương 02 cấp, phân quyền, phân cấp trong lĩnh vực đất đai",
    "Nghị định quy định chi tiết và hướng dẫn thi hành một số điều của Luật Bảo hiểm xã hội",
    "Nghị định quy định chi tiết và hướng dẫn thi hành một số điều của Luật Bảo hiểm y tế",
    "Nghị định quy định chính sách trợ giúp xã hội đối với đối tượng bảo trợ xã hội",
    "Nghị định quy định xử phạt vi phạm hành chính về trật tự, an toàn giao thông",
    "Nghị định quy định chi tiết một số điều và biện pháp thi hành Luật Công chứng",
    "Nghị định quy định chi tiết thi hành một số điều của Luật Việc làm về bảo hiểm thất nghiệp",
    "Nghị định quy định mức lương tối thiểu",
    "Nghị định quy định chuẩn nghèo đa chiều quốc gia",
}


def fold(text):
    text = unicodedata.normalize("NFD", text or "")
    return "".join(c for c in text if unicodedata.category(c) != "Mn").lower()


def bucket(row):
    status = row.get("status", "").strip()
    title = row.get("trich_yeu", "").strip()
    folded = fold(title)
    if status == "expired":
        return "EXCLUDE_EXPIRED", "Không đưa văn bản hết hiệu lực vào corpus hiện hành"
    if status == "pending_effective":
        return "HOLD_PENDING", "Chưa có hiệu lực tại thời điểm xác minh"
    if any(key in folded for key in CORE_KEYS):
        return "CORE", "Nền tảng cho câu hỏi dân sự, quyền lợi và thủ tục phổ biến"
    if any(fold(fragment) in folded for fragment in SUPPORT):
        return "SUPPORT", "Văn bản hướng dẫn trực tiếp cho nguồn CORE"
    return "OPTIONAL_REVIEW", "Nguồn trung ương hợp lệ nhưng chưa đủ cần thiết cho MVP Rightly"


def main():
    with REGISTRY.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    selected = []
    counts = {}
    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        fields = ["selection", "reason", *rows[0].keys()]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            selection, reason = bucket(row)
            counts[selection] = counts.get(selection, 0) + 1
            item = {"selection": selection, "reason": reason, **row}
            writer.writerow(item)
            if selection in {"CORE", "SUPPORT"}:
                selected.append(item)

    report = [
        "# Rightly source selection",
        "",
        "Phạm vi: corpus production cho Rightly, dựa trên `README.md`: thủ tục hành chính, quyền lợi công và pháp luật dân sự bằng tiếng Việt.",
        "",
        "## Kết quả",
        "",
        f"- Registry đã rà soát: **{len(rows)}** nguồn trung ương.",
        f"- CORE: **{counts.get('CORE', 0)}** nguồn.",
        f"- SUPPORT: **{counts.get('SUPPORT', 0)}** nguồn.",
        f"- Bộ tối thiểu đề xuất: **{len(selected)}** nguồn.",
        f"- Loại do hết hiệu lực: **{counts.get('EXCLUDE_EXPIRED', 0)}** nguồn.",
        f"- Tạm giữ do chưa có hiệu lực: **{counts.get('HOLD_PENDING', 0)}** nguồn.",
        f"- Để ngoài MVP, chỉ bổ sung theo nhu cầu: **{counts.get('OPTIONAL_REVIEW', 0)}** nguồn.",
        "",
        "## Quy tắc sử dụng",
        "",
        "- Chỉ ingest file được chỉ ra bởi `pdf_local` hoặc `notes` và có checksum/metadata nguồn.",
        "- `active_verified` là trạng thái xác minh trong repo, không thay thế việc kiểm tra lại trên nguồn chính thức trước khi trả lời người dùng.",
        "- Văn bản hợp nhất (`VBHN`) ưu tiên cho retrieval; giữ metadata quan hệ với luật sửa đổi để trích dẫn đúng.",
        "- Văn bản địa phương, nghị quyết kế hoạch, tài liệu demo, eval, log và output model không thuộc corpus pháp luật production.",
        "- Không fine-tune trực tiếp trên toàn văn nếu mục tiêu là cập nhật hiệu lực; dùng RAG với ngày hiệu lực, nguồn và điều khoản trích dẫn.",
        "",
        "## Cảnh báo dữ liệu",
        "",
        "Registry ghi `verified_on` trong `data/law_status.json` đến 2026-08-12. Cần chạy lại kiểm tra hiệu lực và download/checksum trước pilot hoặc triển khai thật.",
        "",
        "Manifest chi tiết: `data/rightly_source_selection.csv`.",
    ]
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"registry={len(rows)} core={counts.get('CORE', 0)} support={counts.get('SUPPORT', 0)} selected={len(selected)}")


if __name__ == "__main__":
    main()
