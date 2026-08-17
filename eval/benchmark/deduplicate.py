#!/usr/bin/env python3
"""
Deduplicate benchmark questions using multiple layers:
1. Exact normalized hash
2. Token Jaccard similarity
3. MinHash (if datasketch available)
4. Same seed/intent constraints
"""

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple

try:
    from datasketch import MinHash, MinHashLSH

    HAS_MINHASH = True
except ImportError:
    HAS_MINHASH = False
    print(
        "WARNING: datasketch not installed; MinHash deduplication skipped. Install with: pip install datasketch"
    )


def load_jsonl(path: Path) -> List[Dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def save_jsonl(records: List[Dict], path: Path):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")


def normalize_for_dedup(text: str) -> str:
    """Normalize for deduplication comparison."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def tokenize(text: str) -> Set[str]:
    return set(normalize_for_dedup(text).split())


def jaccard_similarity(a: Set[str], b: Set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def exact_dedupe(records: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """Remove exact duplicates by normalized_question."""
    seen: Dict[str, Dict] = {}
    duplicates = []
    unique = []

    for rec in records:
        norm = rec.get("normalized_question", "").strip().lower()
        if norm in seen:
            duplicates.append(
                {
                    "removed": rec["question_id"],
                    "kept": seen[norm]["question_id"],
                    "reason": "exact_normalized_match",
                }
            )
        else:
            seen[norm] = rec
            unique.append(rec)

    return unique, duplicates


def jaccard_dedupe(records: List[Dict], threshold: float = 0.85) -> Tuple[List[Dict], List[Dict]]:
    """Remove near-duplicates using token Jaccard similarity."""
    # Group by leakage_group_id first - don't dedupe within same seed
    by_group: Dict[str, List[Dict]] = defaultdict(list)
    for rec in records:
        gid = rec.get("leakage_group_id", "NO_GROUP")
        by_group[gid].append(rec)

    unique = []
    duplicates = []

    for gid, group in by_group.items():
        if len(group) <= 1:
            unique.extend(group)
            continue

        # Within same leakage group, we expect paraphrases - keep all
        # Only dedupe ACROSS different groups
        unique.extend(group)

    # Now cross-group deduplication
    # Compare each record against all previous unique records from different groups
    final_unique = []
    tokens_cache = {}

    for rec in unique:
        gid = rec.get("leakage_group_id", "NO_GROUP")
        norm = rec.get("normalized_question", "")
        tokens = tokenize(norm)
        tokens_cache[rec["question_id"]] = tokens

        is_dup = False
        for kept in final_unique:
            kept_gid = kept.get("leakage_group_id", "NO_GROUP")
            if kept_gid == gid:
                continue  # Same seed group - expected to be similar

            kept_tokens = tokens_cache[kept["question_id"]]
            sim = jaccard_similarity(tokens, kept_tokens)
            if sim >= threshold:
                duplicates.append(
                    {
                        "removed": rec["question_id"],
                        "kept": kept["question_id"],
                        "reason": f"jaccard_{sim:.3f}",
                        "similarity": sim,
                    }
                )
                is_dup = True
                break

        if not is_dup:
            final_unique.append(rec)

    return final_unique, duplicates


def minhash_dedupe(
    records: List[Dict], threshold: float = 0.85, num_perm: int = 128
) -> Tuple[List[Dict], List[Dict]]:
    """Remove near-duplicates using MinHash LSH."""
    if not HAS_MINHASH:
        return records, []

    lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
    minhashes = {}
    duplicates = []
    unique = []

    for rec in records:
        tokens = tokenize(rec.get("normalized_question", ""))
        m = MinHash(num_perm=num_perm)
        for token in tokens:
            m.update(token.encode("utf-8"))
        minhashes[rec["question_id"]] = m

        # Query LSH for similar items
        similar = lsh.query(m)
        # Filter out same leakage group
        similar = [qid for qid in similar if qid != rec["question_id"]]
        same_group_similar = [
            qid
            for qid in similar
            if records_by_id.get(qid, {}).get("leakage_group_id") == rec.get("leakage_group_id")
        ]
        cross_group_similar = [qid for qid in similar if qid not in same_group_similar]

        if cross_group_similar:
            kept = cross_group_similar[0]
            duplicates.append(
                {"removed": rec["question_id"], "kept": kept, "reason": f"minhash_{threshold}"}
            )
        else:
            lsh.insert(rec["question_id"], m)
            unique.append(rec)

    return unique, duplicates


def deduplicate(
    input_path: Path,
    output_path: Path,
    report_path: Path,
    jaccard_threshold: float = 0.85,
    use_minhash: bool = True,
):
    print(f"Loading records from {input_path}...")
    records = load_jsonl(input_path)
    print(f"Initial count: {len(records)}")

    # Build ID lookup for minhash
    global records_by_id
    records_by_id = {r["question_id"]: r for r in records}

    all_removed = []

    # Layer 1: Exact deduplication
    print("\n1. Exact deduplication...")
    records, exact_dups = exact_dedupe(records)
    all_removed.extend(exact_dups)
    print(f"  Removed {len(exact_dups)} exact duplicates")
    print(f"  Remaining: {len(records)}")

    # Layer 2: Jaccard deduplication
    print(f"\n2. Jaccard deduplication (threshold={jaccard_threshold})...")
    records, jaccard_dups = jaccard_dedupe(records, jaccard_threshold)
    all_removed.extend(jaccard_dups)
    print(f"  Removed {len(jaccard_dups)} near-duplicates")
    print(f"  Remaining: {len(records)}")

    # Layer 3: MinHash (optional, more accurate)
    if use_minhash and HAS_MINHASH:
        print(f"\n3. MinHash LSH deduplication (threshold={jaccard_threshold})...")
        records, minhash_dups = minhash_dedupe(records, jaccard_threshold)
        all_removed.extend(minhash_dups)
        print(f"  Removed {len(minhash_dups)} near-duplicates")
        print(f"  Remaining: {len(records)}")
    elif use_minhash and not HAS_MINHASH:
        print("\n3. MinHash skipped (datasketch not installed)")

    # Save deduplicated records
    print(f"\nSaving {len(records)} deduplicated records to {output_path}...")
    save_jsonl(records, output_path)

    # Save report
    report = {
        "input_count": len(records) + len(all_removed),
        "output_count": len(records),
        "removed_count": len(all_removed),
        "removed_details": all_removed,
        "layers": {
            "exact": len(exact_dups),
            "jaccard": len(jaccard_dups),
            "minhash": len([d for d in all_removed if d["reason"].startswith("minhash")]),
        },
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report saved to {report_path}")

    return report


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Deduplicate benchmark questions")
    parser.add_argument("--input", required=True, help="Input JSONL file")
    parser.add_argument("--output", required=True, help="Output deduplicated JSONL file")
    parser.add_argument("--report", required=True, help="Deduplication report JSON")
    parser.add_argument(
        "--jaccard-threshold", type=float, default=0.85, help="Jaccard similarity threshold"
    )
    parser.add_argument("--no-minhash", action="store_true", help="Skip MinHash deduplication")
    args = parser.parse_args()

    deduplicate(
        Path(args.input),
        Path(args.output),
        Path(args.report),
        jaccard_threshold=args.jaccard_threshold,
        use_minhash=not args.no_minhash,
    )


if __name__ == "__main__":
    main()
