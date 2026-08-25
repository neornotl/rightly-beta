"""Database integrity gate: tracked data files must stay mutually consistent.

These are fast structural checks over the small registries plus one linear
scan of real_chunks.jsonl (~1-2s). They guard against regressions like:
mojibake/corrupt JSON, duplicate IDs, sources present in the retrievable
corpus but missing from source_registry.csv / law_status.json.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

DATA = Path("data")
CHUNKS_FILE = DATA / "chunks" / "real_chunks.jsonl"
VALID_STATUSES = {"active_verified", "expired", "pending_effective"}


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _corpus_source_ids() -> set[str]:
    if not CHUNKS_FILE.exists():
        return set()
    sids = set()
    with CHUNKS_FILE.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                sids.add(json.loads(line)["source_id"])
    return sids


class TestFaqRegistry:
    def test_faq_json_valid_and_complete(self):
        payload = _load_json(DATA / "faq.json")
        assert isinstance(payload, dict)
        faqs = payload.get("faqs")
        assert isinstance(faqs, list) and len(faqs) >= 50
        ids = [f.get("id") for f in faqs]
        assert all(ids), "every FAQ needs an id"
        dupes = [k for k, v in Counter(ids).items() if v > 1]
        assert not dupes, f"duplicate FAQ ids: {dupes}"
        for f in faqs:
            assert f.get("question"), f["id"]
            assert f.get("answer_text"), f["id"]
            assert f.get("keywords"), f"{f['id']} has no keywords"
            assert isinstance(f.get("exclude_keywords", []), list)

    def test_faq_batch_files_are_not_corrupt(self):
        """faq_batch2.json was removed after being merged into faq.json; if a
        new batch file appears it must use the {"faqs": [...]} envelope."""
        legacy = DATA / "faq_batch2.json"
        assert not legacy.exists(), (
            "data/faq_batch2.json was corrupt and superseded by data/faq.json; "
            "do not reintroduce it without merging first"
        )

    def test_curated_faqs_survived_merge(self):
        payload = _load_json(DATA / "faq.json")
        ids = {f["id"] for f in payload["faqs"]}
        assert {"nguoc-dai-gd", "dieu-kien-bhtn"} <= ids


class TestLawStatusRegistry:
    def test_valid_statuses(self):
        sources = _load_json(DATA / "law_status.json").get("sources", {})
        assert len(sources) >= 190
        bad = {
            sid: info.get("status")
            for sid, info in sources.items()
            if info.get("status") not in VALID_STATUSES
        }
        assert not bad, f"invalid status values: {bad}"

    def test_expired_entries_name_replacement(self):
        sources = _load_json(DATA / "law_status.json").get("sources", {})
        for sid, info in sources.items():
            if info.get("status") == "expired":
                repl = info.get("replaced_by")
                assert repl, f"expired source {sid} lacks replaced_by"
                assert repl in sources, f"{sid} replaced_by {repl} not registered"


class TestCorpusConsistency:
    def test_corpus_sources_registered_everywhere(self):
        """Every chunked source must exist in source_registry.csv,
        legal_database.json and law_status.json."""
        sids = _corpus_source_ids()
        assert sids, "real_chunks.jsonl missing or empty"

        reg_ids = set()
        with (DATA / "source_registry.csv").open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                reg_ids.add(row["source_id"])
        assert not (sids - reg_ids), f"chunked sources missing from registry: {sorted(sids - reg_ids)}"

        ldb = _load_json(DATA / "legal_database.json").get("sources", {})
        assert not (sids - set(ldb)), f"chunked sources missing from legal_database: {sorted(sids - set(ldb))}"

        status = _load_json(DATA / "law_status.json").get("sources", {})
        assert not (sids - set(status)), f"chunked sources missing from law_status: {sorted(sids - set(status))}"

    def test_no_duplicate_chunk_ids(self):
        ids = Counter()
        with CHUNKS_FILE.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    ids[json.loads(line)["chunk_id"]] += 1
        dupes = [k for k, v in ids.items() if v > 1]
        assert not dupes, f"duplicate chunk ids: {dupes[:5]}"

    def test_registry_has_no_duplicate_ids(self):
        rows = list(
            csv.DictReader((DATA / "source_registry.csv").open(encoding="utf-8-sig", newline=""))
        )
        seen = Counter(r["source_id"] for r in rows)
        dupes = [k for k, v in seen.items() if v > 1]
        assert not dupes, f"duplicate registry ids: {dupes}"
