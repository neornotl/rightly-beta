"""R1 - Word Error Rate evaluation (WER, substitutions, deletions, insertions).

Pure-Python Levenshtein (Wagner-Fischer) on token sequences; no heavy deps.
Input: JSONL with reference, hypothesis, accent_group (optional).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from eval.common import (
    load_jsonl,
    median,
    percentile,
    save_csv,
    save_json,
    tokenize,
    watermark_summary,
)

PACKAGE_VERSION = "4.0.0"


def levenshtein_tokens(a: list[str], b: list[str]):
    """Return (distance, sub, ins, del) for token sequences."""
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            dp[i][j] = min(
                dp[i - 1][j] + 1,  # deletion
                dp[i][j - 1] + 1,  # insertion
                dp[i - 1][j - 1] + cost,  # substitution/match
            )
    # Backtrace to count operations.
    sub = ins = dele = 0
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + (0 if a[i - 1] == b[j - 1] else 1):
            if a[i - 1] != b[j - 1]:
                sub += 1
            i -= 1
            j -= 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            dele += 1
            i -= 1
        else:
            ins += 1
            j -= 1
    return dp[n][m], sub, ins, dele


def evaluate_wer(records: list[dict]) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    total_s = total_i = total_d = total_ref = 0
    for idx, rec in enumerate(records):
        ref_toks = tokenize(rec.get("reference", ""))
        hyp_toks = tokenize(rec.get("hypothesis", ""))
        dist, sub, ins, dele = levenshtein_tokens(ref_toks, hyp_toks)
        ref_len = len(ref_toks)
        total_s += sub
        total_i += ins
        total_d += dele
        total_ref += ref_len
        rows.append(
            {
                "case_id": rec.get("case_id", idx),
                "accent_group": rec.get("accent_group", "unknown"),
                "reference": rec.get("reference", ""),
                "hypothesis": rec.get("hypothesis", ""),
                "ref_tokens": ref_len,
                "substitutions": sub,
                "insertions": ins,
                "deletions": dele,
                "wer": round(dist / ref_len, 4) if ref_len else 0.0,
            }
        )
    wer_total = round(total_s + total_i + total_d / 1.0, 4)
    if total_ref:
        wer_total = round((total_s + total_i + total_d) / total_ref, 4)
    else:
        wer_total = 0.0
    wer_values = [r["wer"] for r in rows]
    groups: dict[str, dict] = {}
    for r in rows:
        g = groups.setdefault(
            r["accent_group"],
            {"count": 0, "substitutions": 0, "insertions": 0, "deletions": 0, "ref_tokens": 0},
        )
        g["count"] += 1
        g["substitutions"] += r["substitutions"]
        g["insertions"] += r["insertions"]
        g["deletions"] += r["deletions"]
        g["ref_tokens"] += r["ref_tokens"]
    for g in groups.values():
        g["wer"] = (
            round((g["substitutions"] + g["insertions"] + g["deletions"]) / g["ref_tokens"], 4)
            if g["ref_tokens"]
            else 0.0
        )
    summary = watermark_summary(
        {
            "cases": len(rows),
            "wer": wer_total,
            "substitutions": total_s,
            "insertions": total_i,
            "deletions": total_d,
            "ref_tokens": total_ref,
            "median_wer": round(median(wer_values), 4) if wer_values else 0.0,
            "p90_wer": round(percentile(wer_values, 90), 4) if wer_values else 0.0,
            "by_accent_group": groups,
        },
        "R1_WER",
        PACKAGE_VERSION,
    )
    return rows, summary


def main() -> None:
    parser = argparse.ArgumentParser(description="R1 WER evaluation")
    parser.add_argument("--input", type=Path, required=True, help="JSONL of cases")
    parser.add_argument("--output-csv", type=Path, default=Path("results/wer_results.csv"))
    parser.add_argument("--output-json", type=Path, default=Path("results/wer_summary.json"))
    args = parser.parse_args()
    rows, summary = evaluate_wer(load_jsonl(args.input))
    save_csv(args.output_csv, rows)
    save_json(args.output_json, summary)
    print(f"WER total: {summary['wer']:.4f} over {summary['cases']} cases")


if __name__ == "__main__":
    main()
