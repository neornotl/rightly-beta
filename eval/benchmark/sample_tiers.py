#!/usr/bin/env python3"
"""
Sample benchmark questions into tiers for evaluation.

Tier 1: 10,000 local tests (retrieval/routing/citation - no LLM cloud)
Tier 2: 1,000 generation cases (stratified sample for LLM benchmark)
Tier 3: 200 difficult cases (judge ensemble + human audit)
Tier 4: 50 usability cases (P/C manual review)
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


def stratified_sample(
    records: List[Dict], n: int, strata_keys: List[str], random_state: int = 42
) -> List[Dict]:
    """Stratified sampling across multiple keys."""
    random.seed(random_state)

    # Group by strata combination
    groups: Dict[tuple, List[Dict]] = defaultdict(list)
    for rec in records:
        key = tuple(rec.get(k, "UNKNOWN") for k in strata_keys)
        groups[key].append(rec)

    # Calculate target per group (proportional)
    total = len(records)
    targets = {}
    for key, group_recs in groups.items():
        targets[key] = max(1, round(len(group_recs) / total * n))

    # Adjust to match exact n
    current_sum = sum(targets.values())
    if current_sum != n:
        # Adjust largest groups first
        sorted_keys = sorted(targets.keys(), key=lambda k: -targets[k])
        diff = n - current_sum
        for key in sorted_keys:
            if diff == 0:
                break
            if diff > 0:
                targets[key] += 1
                diff -= 1
            elif targets[key] > 1:
                targets[key] -= 1
                diff += 1

    # Sample from each group
    sampled = []
    for key, target in targets.items():
        group_recs = groups[key]
        if target >= len(group_recs):
            sampled.extend(group_recs)
        else:
            sampled.extend(random.sample(group_recs, target))

    return sampled


def sample_tiers(
    input_path: Path,
    output_dir: Path,
    tier1_size: int = 10000,
    tier2_size: int = 1000,
    tier3_size: int = 200,
    tier4_size: int = 50,
    seed: int = 42,
):
    """Sample questions into evaluation tiers."""

    print(f"Loading records from {input_path}...")
    records = load_jsonl(input_path)
    print(f"Total records: {len(records)}")

    # Only use test + audit splits for benchmarking (not train/calibration)
    test_records = [r for r in records if r.get("split") in ("test", "audit")]
    print(f"Test + Audit records: {len(test_records)}")

    if len(test_records) < tier1_size:
        print(
            f"WARNING: Only {len(test_records)} test+audit records, less than tier1 target {tier1_size}"
        )
        tier1_size = len(test_records)

    output_dir.mkdir(parents=True, exist_ok=True)

    # TIER 1: All test+audit records (up to tier1_size) for local tests
    # These run retrieval/routing/citation locally - no LLM cloud calls
    tier1_records = test_records[:tier1_size]
    save_jsonl(tier1_records, output_dir / "tier1_local_10k.jsonl")
    print(f"\nTIER 1 (Local 10k): {len(tier1_records)} records")
    print(f"  Saved to {output_dir / 'tier1_local_10k.jsonl'}")

    # TIER 2: Stratified sample for generation benchmark
    # Stratify by: provenance_type, topic, expected_zone, difficulty
    tier2_records = stratified_sample(
        test_records,
        min(tier2_size, len(test_records)),
        strata_keys=["provenance_type", "topic", "expected_zone", "difficulty"],
        random_state=seed,
    )
    save_jsonl(tier2_records, output_dir / "tier2_generation_1k.jsonl")
    print(f"\nTIER 2 (Generation 1k): {len(tier2_records)} records")
    print(f"  Saved to {output_dir / 'tier2_generation_1k.jsonl'}")

    # TIER 3: Difficult cases for judge ensemble + human audit
    # Priority: hard/ adversarial, RED zone, adversarial_class, authentic
    difficult_candidates = [
        r
        for r in test_records
        if r.get("difficulty") in ("hard", "adversarial")
        or r.get("expected_zone") == "RED"
        or r.get("adversarial_class")
        or r.get("provenance_type") in ("AUTHENTIC_PUBLIC", "AUTHENTIC_PILOT")
    ]

    print(f"Difficult candidates: {len(difficult_candidates)}")

    # Stratify difficult cases
    tier3_records = stratified_sample(
        difficult_candidates,
        min(tier3_size, len(difficult_candidates)),
        strata_keys=["provenance_type", "expected_zone", "adversarial_class", "difficulty"],
        random_state=seed + 1,
    )
    save_jsonl(tier3_records, output_dir / "tier3_judge_200.jsonl")
    print(f"\nTIER 3 (Judge 200): {len(tier3_records)} records")
    print(f"  Saved to {output_dir / 'tier3_judge_200.jsonl'}")

    # TIER 4: Usability cases for P/C manual review
    # Focus on accessibility styles, conversational naturalness
    usability_candidates = [
        r
        for r in test_records
        if r.get("linguistic_style")
        in ("colloquial", "narrative", "incomplete", "accessibility_cmd", "proxy_question")
        or r.get("user_need", "").startswith("U0")
    ]  # Elderly, visually impaired, etc.

    print(f"Usability candidates: {len(usability_candidates)}")

    tier4_records = stratified_sample(
        usability_candidates,
        min(tier4_size, len(usability_candidates)),
        strata_keys=["linguistic_style", "user_need", "difficulty"],
        random_state=seed + 2,
    )
    save_jsonl(tier4_records, output_dir / "tier4_usability_50.jsonl")
    print(f"\nTIER 4 (Usability 50): {len(tier4_records)} records")
    print(f"  Saved to {output_dir / 'tier4_usability_50.jsonl'}")

    # Print tier compositions
    for tier_name, tier_recs in [
        ("TIER 1", tier1_records),
        ("TIER 2", tier2_records),
        ("TIER 3", tier3_records),
        ("TIER 4", tier4_records),
    ]:
        print(f"\n{tier_name} Composition:")
        for key in ["provenance_type", "topic", "expected_zone", "difficulty", "linguistic_style"]:
            dist = defaultdict(int)
            for r in tier_recs:
                dist[r.get(key, "UNKNOWN")] += 1
            print(f"  {key}: {dict(dist)}")

    # Save manifest
    manifest = {
        "tier1_local_10k": {
            "file": "tier1_local_10k.jsonl",
            "count": len(tier1_records),
            "description": "All test+audit records for local retrieval/routing/citation tests",
        },
        "tier2_generation_1k": {
            "file": "tier2_generation_1k.jsonl",
            "count": len(tier2_records),
            "description": "Stratified sample for LLM generation benchmark (requires cloud API)",
        },
        "tier3_judge_200": {
            "file": "tier3_judge_200.jsonl",
            "count": len(tier3_records),
            "description": "Difficult cases for judge ensemble + human audit",
        },
        "tier4_usability_50": {
            "file": "tier4_usability_50.jsonl",
            "count": len(tier4_records),
            "description": "Accessibility/conversational cases for P/C manual review",
        },
    }
    manifest_path = output_dir / "tier_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nManifest saved to {manifest_path}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Sample benchmark questions into tiers")
    parser.add_argument("--input", required=True, help="Input JSONL file with splits")
    parser.add_argument("--output-dir", required=True, help="Output directory for tier files")
    parser.add_argument("--tier1-size", type=int, default=10000)
    parser.add_argument("--tier2-size", type=int, default=1000)
    parser.add_argument("--tier3-size", type=int, default=200)
    parser.add_argument("--tier4-size", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    sample_tiers(
        Path(args.input),
        Path(args.output_dir),
        tier1_size=args.tier1_size,
        tier2_size=args.tier2_size,
        tier3_size=args.tier3_size,
        tier4_size=args.tier4_size,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
