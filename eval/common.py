"""Shared helpers for evaluation scripts."""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from pathlib import Path

WATERMARK = "SYNTHETIC DEMO - NOT PILOT RESULTS"

_WS_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Normalize for WER: lowercase, NFC, collapse whitespace, strip punctuation."""
    text = unicodedata.normalize("NFC", text)
    text = _WS_RE.sub(" ", text.strip().casefold())
    return text


def tokenize(text: str) -> list[str]:
    return normalize_text(text).split()


def load_jsonl(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Evaluation file not found: {p}")
    records: list[dict] = []
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def save_csv(path: str | Path, rows: list[dict]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        p.write_text("", encoding="utf-8")
        return
    with p.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def save_json(path: str | Path, obj: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def watermark_summary(base: dict, name: str, tool_version: str) -> dict:
    return {
        "metric": name,
        "note": WATERMARK,
        "tool_version": tool_version,
        **base,
    }


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return float(s[mid])
    return (s[mid - 1] + s[mid]) / 2.0


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    if p == 100.0:
        return float(s[-1])
    idx = (len(s) - 1) * p / 100.0
    lo = int(idx)
    hi = min(lo + 1, len(s) - 1)
    frac = idx - lo
    return s[lo] * (1 - frac) + s[hi] * frac
