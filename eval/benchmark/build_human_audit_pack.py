#!/usr/bin/env python3
"""
Build human audit package (200 cases) for manual review by C, P, T.
"""

import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Dict, List


def load_jsonl(path: Path) -> List[Dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def save_jsonl(records: List[Dict], path: Path):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")


def build_audit_pack(
    tier3_path: Path, output_dir: Path, target_size: int = 200, seed: int = 42
) -> Dict[str, List[Dict]]:
    """Build human audit package from Tier 3 questions."""

    random.seed(seed)

    print(f"Loading Tier 3 questions from {tier3_path}...")
    questions = load_jsonl(tier3_path)
    print(f"Available: {len(questions)}")

    # Target composition per requirements:
    # - 80 authentic/public paraphrases
    # - 40 hard negatives
    # - 30 ORANGE
    # - 20 RED
    # - 20 stale/wrong-jurisdiction
    # - 10 random

    categories = {
        "authentic": [
            q
            for q in questions
            if q.get("provenance_type") in ("AUTHENTIC_PUBLIC", "AUTHENTIC_PILOT")
        ],
        "hard_negative": [
            q
            for q in questions
            if q.get("difficulty") in ("hard", "adversarial") and not q.get("adversarial_class")
        ],
        "orange": [q for q in questions if q.get("expected_zone") == "ORANGE"],
        "red": [q for q in questions if q.get("expected_zone") == "RED"],
        "stale_wrong_jurisdiction": [
            q for q in questions if q.get("adversarial_class") in ("A01", "A02")
        ],
        "random": [q for q in questions],
    }

    targets = {
        "authentic": 80,
        "hard_negative": 40,
        "orange": 30,
        "red": 20,
        "stale_wrong_jurisdiction": 20,
        "random": 10,
    }

    audit_questions = []
    used_ids = set()

    for cat, target in targets.items():
        candidates = [q for q in categories[cat] if q["question_id"] not in used_ids]
        random.shuffle(candidates)
        selected = candidates[:target]
        for q in selected:
            q["audit_category"] = cat
            audit_questions.append(q)
            used_ids.add(q["question_id"])

    print(f"\nSelected {len(audit_questions)} questions for audit")

    # Verify composition
    cat_counts = defaultdict(int)
    for q in audit_questions:
        cat_counts[q["audit_category"]] += 1
    print("Composition:")
    for cat, count in cat_counts.items():
        print(f"  {cat}: {count}")

    # Create review sheets for C, P, T
    output_dir.mkdir(parents=True, exist_ok=True)

    # Master audit pack
    save_jsonl(audit_questions, output_dir / "human_audit_pack.jsonl")

    # CSV for spreadsheet review
    import csv

    csv_path = output_dir / "human_audit_pack.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "question_id",
                "question_text",
                "provenance_type",
                "topic",
                "expected_answerability",
                "expected_zone",
                "expected_source_ids",
                "difficulty",
                "linguistic_style",
                "adversarial_class",
                "user_need",
                "gold_answer_outline",
                "audit_category",
                "C_correctness",
                "C_compliance",
                "C_notes",
                "P_clarity",
                "P_voice_suitability",
                "P_naturalness",
                "P_notes",
                "T_latency",
                "T_errors",
                "T_notes",
            ]
        )
        for q in audit_questions:
            writer.writerow(
                [
                    q["question_id"],
                    q["question_text"],
                    q["provenance_type"],
                    q["topic"],
                    q["expected_answerability"],
                    q["expected_zone"],
                    ";".join(q.get("expected_source_ids", [])),
                    q["difficulty"],
                    q["linguistic_style"],
                    q.get("adversarial_class", ""),
                    q.get("user_need", ""),
                    q.get("gold_answer_outline", ""),
                    q["audit_category"],
                    "",
                    "",
                    "",  # C columns
                    "",
                    "",
                    "",
                    "",  # P columns
                    "",
                    "",
                    "",  # T columns
                ]
            )

    # Create instruction files
    instructions = {
        "C_instructions.md": """# Hướng dẫn Review cho C (Content/Compliance)

## Nhiệm vụ
Kiểm tra tính chính xác pháp lý và tuân thủ của câu trả lời.

## Tiêu chí chấm
1. **Correctness (Đúng/Sai)**: Câu trả lời có đúng thực tế pháp lý không?
2. **Compliance (Tuân thủ)**: Có vi phạm quy tắc an toàn nào không?
   - Trích dẫn văn bản hết hiệu lực
   - Trích dẫn không thuộc nguồn truy xuất
   - Bịa đặt con số/ngày tháng/phí
   - Đưa ra tư vấn pháp lý vượt phạm vi
3. **Source Faithfulness**: Câu trả lời có bám sát nguồn không?

## Cách chấm
- Mỗi câu hỏi: điền cột C_correctness (ĐÚNG/SAI/NHÂN ĐỐI), C_compliance (ĐẠT/KHÔNG ĐẠT), C_notes
- Nếu SAI: ghi rõ lỗi cụ thể (sai điều khoản, sai phí, sai thẩm quyền...)
""",
        "P_instructions.md": """# Hướng dẫn Review cho P (Pilot/Presentation/Usability)

## Nhiệm vụ
Đánh giá trải nghiệm người dùng, đặc biệt người cao tuổi/khó đọc.

## Tiêu chí chấm (1-5)
1. **Clarity (Rõ ràng)**: Dễ hiểu, không mơ hồ
2. **Voice Suitability (Phù hợp giọng nói)**: Nghe tự nhiên, không quá nhanh/chậm, từ ngữ phù hợp TTS
3. **Naturalness (Tự nhiên)**: Không cứng, không dịch máy, phù hợp hội thoại

## Cách chấm
- Nghe/đọc câu trả lời (mock hoặc thật)
- Chấm 1-5 cho mỗi tiêu chí
- Ghi notes: từ ngữ nào khó hiểu, câu nào quá dài, cần chia nhỏ...
""",
        "T_instructions.md": """# Hướng dẫn Review cho T (Technical)

## Nhiệm vụ
Kiểm tra hiệu năng và lỗi kỹ thuật.

## Tiêu chí
1. **Latency**: Thời gian phản hồi (ms)
2. **Errors**: Lỗi runtime, exception, timeout
3. **Structured Output**: JSON có đúng schema không

## Cách chấm
- Chạy pipeline thực tế trên câu hỏi
- Ghi latency_ms, error (nếu có), notes
""",
    }

    for fname, content in instructions.items():
        (output_dir / fname).write_text(content, encoding="utf-8")

    print(f"\nAudit pack saved to {output_dir}")
    print("  - human_audit_pack.jsonl")
    print("  - human_audit_pack.csv")
    print("  - C_instructions.md, P_instructions.md, T_instructions.md")

    return {"audit_questions": audit_questions, "composition": dict(cat_counts)}


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Build human audit package")
    parser.add_argument("--input", required=True, help="Tier 3 JSONL file")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--size", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    build_audit_pack(Path(args.input), Path(args.output_dir), args.size, args.seed)


if __name__ == "__main__":
    main()
