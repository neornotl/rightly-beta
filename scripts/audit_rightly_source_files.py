#!/usr/bin/env python3
"""Audit selected Rightly sources against files actually present on disk."""
import csv
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "rightly_source_selection.csv"
OUT = ROOT / "data" / "rightly_source_file_audit.csv"
REPORT = ROOT / "docs" / "rightly_source_file_audit.md"


def fold(value):
    value = unicodedata.normalize("NFD", value or "")
    return "".join(c for c in value if unicodedata.category(c) != "Mn").lower()


def normalized_filename(path):
    return fold(path.stem.replace("_", " ").replace("-", " "))


def all_files():
    excluded = {".venv", ".git", "__pycache__", ".pytest_cache", ".ruff_cache"}
    files = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in excluded for part in path.parts):
            continue
        if path.name in {"rightly_source_file_audit.csv", "rightly_source_selection.csv"}:
            continue
        files.append(path)
    return files


def find_matches(row, files):
    source_id = row["source_id"]
    exact = []
    for path in files:
        text = fold(str(path))
        if source_id in text:
            exact.append(path)
    if exact:
        return exact

    number = fold(row["ky_hieu"]).replace("/", " ")
    title = fold(row["trich_yeu"])
    tokens = [token for token in re.findall(r"[a-z0-9]+", title) if len(token) >= 5]
    candidates = []
    for path in files:
        text = normalized_filename(path)
        score = 0
        if number and all(token in text for token in number.split()[:2]):
            score += 4
        score += sum(token in text for token in tokens[:5])
        if score >= 4:
            candidates.append((score, path))
    return [path for _, path in sorted(candidates, key=lambda item: (-item[0], str(item[1])))]


def main():
    with MANIFEST.open(encoding="utf-8-sig", newline="") as f:
        selected = [row for row in csv.DictReader(f) if row["selection"] in {"CORE", "SUPPORT"}]
    files = all_files()
    rows = []
    for source in selected:
        matches = find_matches(source, files)
        direct = []
        for value in (source.get("pdf_local", ""), source.get("notes", "")):
            if value and (ROOT / value).is_file():
                direct.append(ROOT / value)
        matches = list(dict.fromkeys(direct + matches))
        text_matches = [p for p in matches if p.suffix.lower() in {".txt", ".md", ".pdf", ".docx"}]
        text_paths = [p for p in text_matches if p.suffix.lower() in {".txt", ".md"}]
        text_chars = 0
        mojibake = 0
        for path in text_paths:
            content = path.read_text(encoding="utf-8", errors="replace")
            text_chars = max(text_chars, len(content))
            mojibake += content.count("�") + content.count("?")
        if not text_matches:
            state = "MISSING_TEXT"
            reason = "Không tìm thấy file toàn văn khớp source_id/số hiệu/tên"
        elif any(p.suffix.lower() in {".txt", ".md"} for p in text_matches):
            state = "TEXT_PRESENT"
            reason = "Có file text/markdown để ingest"
        else:
            state = "BINARY_PRESENT"
            reason = "Có PDF/DOCX; cần extract và kiểm tra checksum"
        if text_paths and (text_chars < 10000 or mojibake > 20):
            state = "TEXT_PRESENT_BUT_QUALITY_REVIEW"
            reason = f"Có text nhưng cần kiểm tra chất lượng: chars={text_chars}, mojibake_markers={mojibake}"
        rows.append({**source, "file_state": state, "match_count": str(len(text_matches)), "text_chars": str(text_chars), "mojibake_markers": str(mojibake), "matched_files": " | ".join(str(p.relative_to(ROOT)) for p in text_matches[:5]), "audit_reason": reason})

    fields = [*selected[0].keys(), "file_state", "match_count", "text_chars", "mojibake_markers", "matched_files", "audit_reason"]
    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    counts = {}
    for row in rows:
        counts[row["file_state"]] = counts.get(row["file_state"], 0) + 1
    report = [
        "# Rightly source file audit",
        "",
        "Đối chiếu 46 nguồn CORE/SUPPORT với file thực tế trong repo, loại trừ `.venv`, cache và output audit.",
        "",
        f"- Sources audited: **{len(rows)}**",
        f"- Text/Markdown present and not flagged: **{counts.get('TEXT_PRESENT', 0)}**",
        f"- Text present but quality review needed: **{counts.get('TEXT_PRESENT_BUT_QUALITY_REVIEW', 0)}**",
        f"- PDF/DOCX only: **{counts.get('BINARY_PRESENT', 0)}**",
        f"- Missing text: **{counts.get('MISSING_TEXT', 0)}**",
        "",
        "## Missing or incomplete",
        "",
    ]
    for row in rows:
        if row["file_state"] != "TEXT_PRESENT":
            report.append(f"- `{row['source_id']}` `{row['ky_hieu']}`: **{row['file_state']}**; {row['trich_yeu'] or '(không có tiêu đề)'}; matches: {row['matched_files'] or 'none'}")
    report += ["", "Full machine-readable result: `data/rightly_source_file_audit.csv`."]
    REPORT.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"audited={len(rows)} text={counts.get('TEXT_PRESENT', 0)} binary={counts.get('BINARY_PRESENT', 0)} missing={counts.get('MISSING_TEXT', 0)}")


if __name__ == "__main__":
    main()
