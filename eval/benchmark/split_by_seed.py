#!/usr/bin/env python3
"""
Split benchmark questions by leakage_group_id (seed) to prevent data leakage.
All paraphrases of the same seed must go to the same split.
"""

import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set


def load_jsonl(path: Path) -> List[Dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def save_jsonl(records: List[Dict], path: Path):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")


def split_by_seed(
    records: List[Dict],
    train_ratio: float = 0.60,
    calibration_ratio: float = 0.15,
    test_ratio: float = 0.20,
    audit_ratio: float = 0.05,
    seed: int = 42,
) -> Dict[str, List[Dict]]:
    """
    Split records by leakage_group_id to prevent leakage.
    Returns dict with splits: train_dev, calibration, test, audit
    """
    random.seed(seed)

    # Group by leakage_group_id
    groups: Dict[str, List[Dict]] = defaultdict(list)
    for rec in records:
        gid = rec.get("leakage_group_id", "NO_GROUP")
        groups[gid].append(rec)

    print(f"Total groups: {len(groups)}")
    print(f"Total records: {len(records)}")

    # Count records per group
    group_sizes = {gid: len(recs) for gid, recs in groups.items()}
    total_records = sum(group_sizes.values())

    # Target counts
    target_calibration = int(total_records * calibration_ratio)
    target_test = int(total_records * test_ratio)
    target_audit = int(total_records * audit_ratio)

    # Shuffle groups
    group_ids = list(groups.keys())
    random.shuffle(group_ids)

    splits = {"train_dev": [], "calibration": [], "test": [], "audit": []}

    current_train = 0
    current_cal = 0
    current_test = 0
    current_audit = 0

    # Priority for audit: authentic, hard-negative, RED
    def audit_priority(gid: str, recs: List[Dict]) -> int:
        """Higher = more priority for audit"""
        priority = 0
        for rec in recs:
            prov = rec.get("provenance_type", "")
            if prov in ("AUTHENTIC_PUBLIC", "AUTHENTIC_PILOT"):
                priority += 10
            if rec.get("adversarial_class"):
                priority += 5
            if rec.get("expected_zone") == "RED":
                priority += 5
            if rec.get("difficulty") in ("hard", "adversarial"):
                priority += 2
        return priority

    # Sort groups by audit priority (descending)
    group_ids.sort(key=lambda gid: audit_priority(gid, groups[gid]), reverse=True)

    # Assign groups to splits
    for gid in group_ids:
        recs = groups[gid]
        size = len(recs)

        # Try to fill audit first with high-priority groups
        if current_audit + size <= target_audit * 1.5:  # Allow 50% overshoot for priority
            splits["audit"].extend(recs)
            current_audit += size
        elif current_test + size <= target_test * 1.2:
            splits["test"].extend(recs)
            current_test += size
        elif current_cal + size <= target_calibration * 1.2:
            splits["calibration"].extend(recs)
            current_cal += size
        else:
            splits["train_dev"].extend(recs)
            current_train += size

    # Update split field in records
    for split_name, recs in splits.items():
        for rec in recs:
            rec["split"] = split_name

    return splits


def verify_no_leakage(splits: Dict[str, List[Dict]]) -> List[str]:
    """Verify no leakage_group_id appears in multiple splits."""
    errors = []
    group_splits: Dict[str, Set[str]] = defaultdict(set)

    for split_name, recs in splits.items():
        for rec in recs:
            gid = rec.get("leakage_group_id")
            if gid:
                group_splits[gid].add(split_name)

    for gid, split_set in group_splits.items():
        if len(split_set) > 1:
            errors.append(f"LEAKAGE: group {gid} appears in splits: {split_set}")

    return errors


def print_split_stats(splits: Dict[str, List[Dict]]):
    print("\nSplit Statistics:")
    print("-" * 60)
    for split_name, recs in splits.items():
        print(f"\n{split_name}: {len(recs)} records")

        # Provenance distribution
        prov = defaultdict(int)
        ans = defaultdict(int)
        diff = defaultdict(int)
        zone = defaultdict(int)

        for rec in recs:
            prov[rec.get("provenance_type", "UNKNOWN")] += 1
            ans[rec.get("expected_answerability", "UNKNOWN")] += 1
            diff[rec.get("difficulty", "UNKNOWN")] += 1
            zone[rec.get("expected_zone", "UNKNOWN")] += 1

        print(f"  Provenance: {dict(prov)}")
        print(f"  Answerability: {dict(ans)}")
        print(f"  Difficulty: {dict(diff)}")
        print(f"  Zone: {dict(zone)}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Split benchmark questions by seed")
    parser.add_argument("--input", required=True, help="Input deduplicated JSONL file")
    parser.add_argument("--output-dir", required=True, help="Output directory for splits")
    parser.add_argument("--train-ratio", type=float, default=0.60)
    parser.add_argument("--calibration-ratio", type=float, default=0.15)
    parser.add_argument("--test-ratio", type=float, default=0.20)
    parser.add_argument("--audit-ratio", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading records from {input_path}...")
    records = load_jsonl(input_path)
    print(f"Loaded {len(records)} records")

    # Check all records have leakage_group_id
    missing = [r for r in records if not r.get("leakage_group_id")]
    if missing:
        print(f"ERROR: {len(missing)} records missing leakage_group_id")
        sys.exit(1)

    print("\nSplitting by leakage_group_id...")
    splits = split_by_seed(
        records,
        train_ratio=args.train_ratio,
        calibration_ratio=args.calibration_ratio,
        test_ratio=args.test_ratio,
        audit_ratio=args.audit_ratio,
        seed=args.seed,
    )

    # Verify no leakage
    errors = verify_no_leakage(splits)
    if errors:
        print("\nLEAKAGE ERRORS:")
        for err in errors:
            print(f"  {err}")
        sys.exit(1)
    else:
        print("\nNo leakage detected ✓")

    # Print stats
    print_split_stats(splits)

    # Save splits
    for split_name, recs in splits.items():
        out_path = output_dir / f"questions_{split_name}.jsonl"
        save_jsonl(recs, out_path)
        print(f"Saved {len(recs)} records to {out_path}")

    # Save combined with split field
    all_recs = []
    for recs in splits.values():
        all_recs.extend(recs)
    combined_path = output_dir / "questions_all_with_splits.jsonl"
    save_jsonl(all_recs, combined_path)
    print(f"Saved combined to {combined_path}")


if __name__ == "__main__":
    main()
