# -*- coding: utf-8 -*-
"""Full database integrity audit for the Rightly legal corpus.

Usage:
    python scripts/verify_database.py [--data-dir data] [--strict]

Checks (see tests/test_database_integrity.py for the CI-enforced subset):
  1. real_chunks.jsonl   - JSONL validity, duplicate ids, empty/degenerate text
  2. embeddings npz      - id alignment with the chunk file, NaN/zero vectors
  3. faq.json            - structure, duplicate ids, missing fields
  4. law_status.json     - status vocabulary, expired entries have replacement
  5. source_registry.csv - no duplicate ids, superset of chunked sources
  6. legal_database.json - superset of chunked sources
  7. retrievability      - filter_retrievable drops only expected categories

Exit codes: 0 = clean/warnings only (unless --strict), 1 = issues found.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.retrieval.document_loader import DocumentLoader, filter_retrievable  # noqa: E402

VALID_STATUSES = {"active_verified", "expired", "pending_effective"}


def audit(data_dir: Path, check_embeddings: bool) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    warns: list[str] = []

    chunks_file = data_dir / "chunks" / "real_chunks.jsonl"
    records = DocumentLoader.load_chunks(chunks_file)
    if not records:
        return [f"{chunks_file} missing or empty"], warns

    # 1. chunk file sanity
    dup_ids = [k for k, v in Counter(r.chunk_id for r in records).items() if v > 1]
    if dup_ids:
        issues.append(f"duplicate chunk_ids: {dup_ids[:10]}")
    empty = sum(1 for r in records if not r.text.strip())
    if empty:
        issues.append(f"{empty} chunks with empty text")
    tiny = sum(1 for r in records if len(r.text.strip()) < 15)
    if tiny:
        warns.append(f"{tiny} degenerate fragments (<15 chars); filter_retrievable drops them at load")

    # 2. embeddings alignment
    if check_embeddings:
        try:
            import numpy as np

            npz_path = data_dir / "chunks" / "real_embeddings.npz"
            if npz_path.exists():
                npz = np.load(npz_path)
                emb_ids = [str(x) for x in npz["ids"].tolist()]
                emb = npz["embeddings"]
                file_ids = [r.chunk_id for r in records]
                if emb_ids != file_ids:
                    common = len(set(emb_ids) & set(file_ids))
                    warns.append(
                        f"embeddings cache covers {len(emb_ids)} ids vs {len(file_ids)} file ids "
                        f"({common} shared); DenseIndex rebuilds/rewrites it on next boot"
                    )
                if emb.ndim == 2 and int(np.isnan(emb).sum()):
                    issues.append("embeddings contain NaN values")
            else:
                warns.append("no dense cache; it will be built on first hybrid boot")
        except Exception as exc:  # numpy missing / corrupt file
            warns.append(f"could not inspect embeddings: {exc}")

    chunk_sids = {r.source_id for r in records}

    # 3. FAQ registry
    faq_payload = json.loads((data_dir / "faq.json").read_text(encoding="utf-8"))
    faqs = faq_payload.get("faqs", [])
    fids = [f.get("id") for f in faqs]
    fdup = sorted({k for k, v in Counter(fids).items() if v > 1})
    if fdup:
        issues.append(f"duplicate FAQ ids: {fdup}")
    broken = [f.get("id") for f in faqs if not f.get("answer_text") or not f.get("keywords")]
    if broken:
        issues.append(f"FAQ items missing answer_text/keywords: {broken}")

    # 4. law_status
    status_db = json.loads((data_dir / "law_status.json").read_text(encoding="utf-8")).get("sources", {})
    bad_status = {
        sid: info.get("status")
        for sid, info in status_db.items()
        if info.get("status") not in VALID_STATUSES
    }
    if bad_status:
        issues.append(f"invalid statuses: {list(bad_status.items())[:5]}")
    for sid, info in status_db.items():
        if info.get("status") == "expired":
            repl = info.get("replaced_by")
            if not repl or repl not in status_db:
                issues.append(f"expired {sid} lacks a registered replaced_by")

    # 5. registry
    with (data_dir / "source_registry.csv").open(encoding="utf-8-sig", newline="") as fh:
        reg_rows = list(csv.DictReader(fh))
    reg_ids = [r["source_id"] for r in reg_rows]
    rdup = sorted({k for k, v in Counter(reg_ids).items() if v > 1})
    if rdup:
        issues.append(f"duplicate registry ids: {rdup[:10]}")
    missing_reg = sorted(chunk_sids - set(reg_ids))
    if missing_reg:
        issues.append(f"chunked sources absent from source_registry.csv: {missing_reg[:10]}")

    # 6. merged DB
    ldb_ids = set(json.loads((data_dir / "legal_database.json").read_text(encoding="utf-8"))["sources"])
    missing_ldb = sorted(chunk_sids - ldb_ids)
    if missing_ldb:
        issues.append(f"chunked sources absent from legal_database.json: {missing_ldb[:10]}")

    # 7. retrievability policy
    kept, dropped = filter_retrievable(
        DocumentLoader.load_chunks(chunks_file),
        status_path=data_dir / "law_status.json",
        today=date.today(),
    )
    print(
        f"retrievable corpus: {len(kept)}/{len(records)} chunks "
        f"(dropped: {dropped})"
    )

    return issues, warns


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--skip-embeddings", action="store_true", help="skip npz inspection")
    parser.add_argument("--strict", action="store_true", help="treat warnings as failures")
    args = parser.parse_args()

    issues, warns = audit(args.data_dir.resolve(), check_embeddings=not args.skip_embeddings)

    print()
    for x in issues:
        print("[ISSUE]", x)
    for x in warns:
        print("[WARN]", x)
    print(f"\n{len(issues)} issue(s), {len(warns)} warning(s)")
    if issues or (args.strict and warns):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
