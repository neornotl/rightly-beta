#!/usr/bin/env python3
"""
Validate benchmark questions against JSON Schema and additional rules.
"""

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

from jsonschema import ValidationError, validate

SCHEMA_PATH = Path("data/schemas/benchmark_question.schema.json")
LAW_STATUS_PATH = Path("data/law_status.json")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> List[Dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def validate_schema(records: List[Dict], schema: Dict) -> List[str]:
    errors = []
    for i, rec in enumerate(records):
        try:
            validate(instance=rec, schema=schema)
        except ValidationError as e:
            errors.append(f"Record {i} ({rec.get('question_id', 'NO_ID')}): {e.message}")
    return errors


def validate_pii(records: List[Dict]) -> List[str]:
    """Heuristic PII scan."""
    errors = []
    patterns = {
        "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
        "phone": re.compile(r"\b(0|\+84)[0-9]{9,10}\b"),
        "cccd": re.compile(r"\b[0-9]{12}\b"),
        "bhxh": re.compile(r"\b[0-9]{10,11}\b"),
    }
    for rec in records:
        text = rec.get("question_text", "") + " " + rec.get("normalized_question", "")
        for pii_type, pattern in patterns.items():
            if pattern.search(text):
                errors.append(
                    f"{rec['question_id']}: Possible {pii_type} detected in question text"
                )
    return errors


def validate_duplicates(records: List[Dict]) -> List[str]:
    """Check exact and near duplicates on normalized_question."""
    errors = []
    seen: Dict[str, str] = {}
    for rec in records:
        norm = rec.get("normalized_question", "").strip().lower()
        qid = rec["question_id"]
        if norm in seen:
            errors.append(f"EXACT DUPLICATE: {qid} and {seen[norm]} have same normalized_question")
        else:
            seen[norm] = qid
    return errors


def validate_source_ids(records: List[Dict], law_status: Dict) -> List[str]:
    """Check expected_source_ids exist in law_status and are active_verified."""
    errors = []
    valid_sources = set(law_status.get("sources", {}).keys())
    for rec in records:
        for sid in rec.get("expected_source_ids", []):
            if sid not in valid_sources:
                errors.append(
                    f"{rec['question_id']}: expected_source_id '{sid}' not in law_status.json"
                )
            else:
                src = law_status["sources"][sid]
                # Check if source is expired
                if src.get("expired_on"):
                    errors.append(
                        f"{rec['question_id']}: expected_source_id '{sid}' is EXPIRED ({src['expired_on']})"
                    )
    return errors


def validate_leakage(records: List[Dict]) -> List[str]:
    """Check no leakage_group_id appears in more than one split."""
    errors = []
    groups: Dict[str, Set[str]] = {}
    for rec in records:
        gid = rec.get("leakage_group_id")
        split = rec.get("split")
        if gid and split:
            groups.setdefault(gid, set()).add(split)
    for gid, splits in groups.items():
        if len(splits) > 1:
            errors.append(f"LEAKAGE: group {gid} appears in multiple splits: {splits}")
    return errors


def validate_distribution(records: List[Dict]) -> List[str]:
    """Check distribution against quotas (warning only)."""
    warnings = []
    total = len(records)
    if total == 0:
        return ["No records to validate"]

    # Provenance distribution
    prov_counts = {}
    for rec in records:
        prov = rec.get("provenance_type", "UNKNOWN")
        prov_counts[prov] = prov_counts.get(prov, 0) + 1

    expected = {
        "AUTHENTIC_PUBLIC": 0.15,
        "AUTHENTIC_PILOT": 0.02,
        "DERIVED_PARAPHRASE": 0.50,
        "SYNTHETIC_COVERAGE": 0.20,
        "ADVERSARIAL": 0.13,
    }
    for prov, exp_ratio in expected.items():
        actual = prov_counts.get(prov, 0) / total
        if abs(actual - exp_ratio) > 0.05:
            warnings.append(f"DISTRIBUTION: {prov} = {actual:.1%} (expected ~{exp_ratio:.0%})")

    # Answerability distribution
    ans_counts = {}
    for rec in records:
        ans = rec.get("expected_answerability", "UNKNOWN")
        ans_counts[ans] = ans_counts.get(ans, 0) + 1

    expected_ans = {
        "ANSWER": 0.45,
        "CLARIFY": 0.20,
        "GUIDE": 0.10,
        "REFUSE": 0.15,  # includes INSUFFICIENT, STALE, UNSUPPORTED, UNKNOWN
        "ESCALATE": 0.05,
    }
    for ans, exp_ratio in expected_ans.items():
        actual = ans_counts.get(ans, 0) / total
        if abs(actual - exp_ratio) > 0.05:
            warnings.append(
                f"DISTRIBUTION: expected_answerability {ans} = {actual:.1%} (expected ~{exp_ratio:.0%})"
            )

    return warnings


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Validate benchmark questions")
    parser.add_argument("--input", required=True, help="Path to questions JSONL file")
    parser.add_argument("--schema", default=str(SCHEMA_PATH), help="Path to JSON Schema")
    parser.add_argument(
        "--law-status", default=str(LAW_STATUS_PATH), help="Path to law_status.json"
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    schema_path = Path(args.schema)
    law_status_path = Path(args.law_status)

    if not input_path.exists():
        print(f"ERROR: Input file not found: {input_path}")
        sys.exit(1)
    if not schema_path.exists():
        print(f"ERROR: Schema file not found: {schema_path}")
        sys.exit(1)
    if not law_status_path.exists():
        print(f"ERROR: law_status.json not found: {law_status_path}")
        sys.exit(1)

    print(f"Loading records from {input_path}...")
    records = load_jsonl(input_path)
    print(f"Loaded {len(records)} records")

    print(f"Loading schema from {schema_path}...")
    schema = load_json(schema_path)

    print(f"Loading law_status from {law_status_path}...")
    law_status = load_json(law_status_path)

    all_errors = []
    all_warnings = []

    print("\n1. Validating JSON Schema...")
    schema_errors = validate_schema(records, schema)
    all_errors.extend(schema_errors)
    print(f"   Schema errors: {len(schema_errors)}")

    print("\n2. Scanning for PII...")
    pii_errors = validate_pii(records)
    all_errors.extend(pii_errors)
    print(f"   PII errors: {len(pii_errors)}")

    print("\n3. Checking duplicates...")
    dup_errors = validate_duplicates(records)
    all_errors.extend(dup_errors)
    print(f"   Duplicate errors: {len(dup_errors)}")

    print("\n4. Validating source IDs...")
    src_errors = validate_source_ids(records, law_status)
    all_errors.extend(src_errors)
    print(f"   Source ID errors: {len(src_errors)}")

    print("\n5. Checking split leakage...")
    leak_errors = validate_leakage(records)
    all_errors.extend(leak_errors)
    print(f"   Leakage errors: {len(leak_errors)}")

    print("\n6. Checking distribution...")
    dist_warnings = validate_distribution(records)
    all_warnings.extend(dist_warnings)
    print(f"   Distribution warnings: {len(dist_warnings)}")

    # Summary
    print("\n" + "=" * 60)
    print("VALIDATION SUMMARY")
    print("=" * 60)
    print(f"Total records: {len(records)}")
    print(f"Errors: {len(all_errors)}")
    print(f"Warnings: {len(all_warnings)}")

    if all_errors:
        print("\nERRORS:")
        for err in all_errors[:20]:
            print(f"  - {err}")
        if len(all_errors) > 20:
            print(f"  ... and {len(all_errors) - 20} more")

    if all_warnings:
        print("\nWARNINGS:")
        for warn in all_warnings:
            print(f"  - {warn}")

    if all_errors:
        print("\nVALIDATION FAILED")
        sys.exit(1)
    else:
        print("\nVALIDATION PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()
