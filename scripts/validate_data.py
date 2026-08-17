"""Validate data files (chunks JSONL, metadata, eval fixtures, schemas).

Usage:
    python scripts/validate_data.py
"""

from __future__ import annotations

import json
from pathlib import Path


def _load_jsonl(path: Path) -> list[dict]:
    records = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def main() -> int:
    errors: list[str] = []
    data = Path("data")
    source_ids: set[str] = set()

    chunks_file = data / "chunks" / "demo_chunks.jsonl"
    if chunks_file.exists():
        records = _load_jsonl(chunks_file)
        if not records:
            errors.append("demo_chunks.jsonl is empty")
        source_ids = set()
        for i, rec in enumerate(records):
            if not rec.get("chunk_id") or not rec.get("source_id") or not rec.get("text"):
                errors.append(f"chunk {i}: missing required fields")
            source_ids.add(rec.get("source_id"))
            if not rec.get("is_demo"):
                errors.append(f"chunk {i}: missing is_demo label (must be demo)")
        print(f"chunks: {len(records)} records, sources: {sorted(source_ids)}")
    else:
        errors.append("demo_chunks.jsonl missing (run scripts/ingest_documents.py)")

    for fixture in ("retrieval_dev", "retrieval_test", "routing_dev", "routing_test"):
        path = data / "eval" / f"{fixture}.jsonl"
        if not path.exists():
            errors.append(f"eval fixture missing: {path}")
            continue
        records = _load_jsonl(path)
        for i, rec in enumerate(records):
            if fixture.startswith("retrieval"):
                if not rec.get("query") or not rec.get("expected_source_id"):
                    errors.append(f"{fixture}[{i}]: missing query/expected_source_id")
                if rec.get("expected_source_id") not in source_ids:
                    errors.append(
                        f"{fixture}[{i}]: expected_source_id unknown: {rec.get('expected_source_id')}"
                    )
            else:
                zone = rec.get("expected_zone")
                action = rec.get("expected_action")
                if zone not in {"YELLOW", "ORANGE", "RED"}:
                    errors.append(f"{fixture}[{i}]: bad zone {zone!r}")
                if action not in {"ANSWER", "CLARIFY", "GUIDE", "REFUSE", "ESCALATE"}:
                    errors.append(f"{fixture}[{i}]: bad action {action!r}")

    # schema files exist and are valid JSON
    for schema in ("source.schema.json", "retrieval_case.schema.json", "routing_case.schema.json"):
        path = data / "schemas" / schema
        if not path.exists():
            errors.append(f"schema missing: {path}")
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"schema invalid JSON: {path}: {exc}")

    if errors:
        print("VALIDATION FAILED:")
        for err in errors:
            print(f"  - {err}")
        return 1
    print("VALIDATION OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
