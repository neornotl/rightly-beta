#!/usr/bin/env python3
"""
Check for data leakage across splits.
Verifies that no leakage_group_id appears in more than one split.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set


def load_jsonl(path: Path) -> List[Dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def check_leakage(split_files: Dict[str, Path]) -> List[str]:
    """Check leakage across multiple split files."""
    errors = []
    group_splits: Dict[str, Set[str]] = defaultdict(set)

    for split_name, file_path in split_files.items():
        if not file_path.exists():
            continue
        records = load_jsonl(file_path)
        for rec in records:
            gid = rec.get("leakage_group_id")
            if gid:
                group_splits[gid].add(split_name)

    for gid, splits in group_splits.items():
        if len(splits) > 1:
            errors.append(f"LEAKAGE: group '{gid}' appears in splits: {sorted(splits)}")

    return errors


def check_test_calibration_overlap(test_path: Path, calibration_path: Path) -> List[str]:
    """Specifically check test and calibration don't share authentic question sources."""
    errors = []

    test_records = load_jsonl(test_path) if test_path.exists() else []
    cal_records = load_jsonl(calibration_path) if calibration_path.exists() else []

    # Get source_record_ids from authentic questions in each split
    test_sources = set()
    cal_sources = set()

    for rec in test_records:
        if rec.get("provenance_type") in ("AUTHENTIC_PUBLIC", "AUTHENTIC_PILOT"):
            src_id = rec.get("source_record_id")
            if src_id:
                test_sources.add(src_id)

    for rec in cal_records:
        if rec.get("provenance_type") in ("AUTHENTIC_PUBLIC", "AUTHENTIC_PILOT"):
            src_id = rec.get("source_record_id")
            if src_id:
                cal_sources.add(src_id)

    overlap = test_sources & cal_sources
    if overlap:
        errors.append(f"TEST/CALIBRATION OVERLAP: shared source_record_ids: {overlap}")

    return errors


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Check data leakage across splits")
    parser.add_argument("--train", help="Train split file")
    parser.add_argument("--calibration", help="Calibration split file")
    parser.add_argument("--test", help="Test split file")
    parser.add_argument("--audit", help="Audit split file")
    parser.add_argument("--all-splits", help="Directory containing all split files")
    args = parser.parse_args()

    split_files = {}
    if args.train:
        split_files["train_dev"] = Path(args.train)
    if args.calibration:
        split_files["calibration"] = Path(args.calibration)
    if args.test:
        split_files["test"] = Path(args.test)
    if args.audit:
        split_files["audit"] = Path(args.audit)

    if args.all_splits:
        split_dir = Path(args.all_splits)
        for split_name in ["train_dev", "calibration", "test", "audit"]:
            f = split_dir / f"questions_{split_name}.jsonl"
            if f.exists():
                split_files[split_name] = f

    if not split_files:
        print("ERROR: No split files specified")
        sys.exit(1)

    print("Checking leakage...")
    for name, path in split_files.items():
        print(f"  {name}: {path}")

    all_errors = []

    # General leakage check
    errors = check_leakage(split_files)
    all_errors.extend(errors)

    # Specific test/calibration overlap check
    if "test" in split_files and "calibration" in split_files:
        errors = check_test_calibration_overlap(split_files["test"], split_files["calibration"])
        all_errors.extend(errors)

    if all_errors:
        print(f"\nLEAKAGE DETECTED: {len(all_errors)} issues")
        for err in all_errors:
            print(f"  - {err}")
        sys.exit(1)
    else:
        print("\nNo leakage detected ✓")
        sys.exit(0)


if __name__ == "__main__":
    main()
