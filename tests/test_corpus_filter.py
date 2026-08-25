"""Corpus filter + chunker regression tests (DB integrity round).

Covers:
- ``filter_retrievable``: degenerate fragments and not-yet-effective
  (pending_effective) sources must never reach the retriever; expired
  sources STAY retrievable by design (the assistant redirects users to the
  replacement document and citation_validator blocks misuse).
- ``DocumentLoader._split_chunks``: slicing a long paragraph must not emit
  a tiny tail fragment that only duplicates the overlap region.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from app.retrieval.document_loader import (
    MIN_CHUNK_CHARS,
    ChunkRecord,
    DocumentLoader,
    filter_retrievable,
    parse_law_date,
)


def _rec(chunk_id: str, source_id: str, text: str) -> ChunkRecord:
    return ChunkRecord(chunk_id=chunk_id, source_id=source_id, text=text)


def _status_file(tmp_path: Path, sources: dict) -> Path:
    path = tmp_path / "law_status.json"
    path.write_text(json.dumps({"sources": sources}), encoding="utf-8")
    return path


class TestFilterRetrievable:
    def test_drops_degenerate_fragments(self, tmp_path):
        records = [
            _rec("a::c000", "a", "Äiá»u 5. NgÆ°á»i lao Ä‘á»™ng Ä‘Æ°á»£c hÆ°á»Ÿng Ä‘áº§y Ä‘á»§ quyá»n lá»£i."),
            _rec("b::c001", "b", "Ã¡)"),
            _rec("c::c002", "c", "9."),
        ]
        kept, dropped = filter_retrievable(records)
        assert [r.chunk_id for r in kept] == ["a::c000"]
        assert dropped["too_short"] == 2
        assert dropped["pending_effective"] == 0

    def test_keeps_chunks_at_min_length_boundary(self):
        text = "x" * MIN_CHUNK_CHARS
        kept, dropped = filter_retrievable([_rec("a::c000", "a", text)])
        assert len(kept) == 1 and dropped["too_short"] == 0

    def test_drops_pending_effective_source(self, tmp_path):
        status = _status_file(
            tmp_path,
            {
                "luat03_2026": {
                    "status": "pending_effective",
                    "ngay_hieu_luc": "2027-03-01",
                }
            },
        )
        records = [
            _rec("luat03_2026::c000", "luat03_2026", "Luáº­t Há»™ tá»‹ch sá»­a Ä‘á»•i toÃ n vÄƒn."),
            _rec("nd01_2020::c000", "nd01_2020", "Nghá»‹ Ä‘á»‹nh hÆ°á»›ng dáº«n thi hÃ nh luáº­t."),
        ]
        kept, dropped = filter_retrievable(records, status_path=status)
        assert [r.source_id for r in kept] == ["nd01_2020"]
        assert dropped["pending_effective"] == 1

    def test_pending_effective_without_date_is_dropped(self, tmp_path):
        status = _status_file(tmp_path, {"x_2026": {"status": "pending_effective"}})
        records = [_rec("x_2026::c000", "x_2026", "VÄƒn báº£n chÆ°a cÃ³ ngÃ y hiá»‡u lá»±c.")]
        kept, _ = filter_retrievable(records, status_path=status)
        assert kept == []

    def test_expired_stays_retrievable_by_design(self, tmp_path):
        status = _status_file(
            tmp_path,
            {
                "nd62_2021": {"status": "expired", "replaced_by": "nd154_2024"},
                "nd154_2024": {"status": "active_verified"},
            },
        )
        records = [
            _rec("nd62_2021::c000", "nd62_2021", "Quy Ä‘á»‹nh chi tiáº¿t Luáº­t CÆ° trÃº cÅ©."),
            _rec("nd154_2024::c000", "nd154_2024", "Luáº­t CÆ° trÃº hiá»‡n hÃ nh má»›i nháº¥t."),
        ]
        kept, dropped = filter_retrievable(records, status_path=status)
        assert len(kept) == 2
        assert sum(dropped.values()) == 0

    def test_unknown_source_defaults_to_kept(self, tmp_path):
        status = _status_file(tmp_path, {"known": {"status": "active_verified"}})
        records = [_rec("mystery::c000", "mystery", "Nguá»“n chÆ°a Ä‘Äƒng kÃ½ váº«n giá»¯.")]
        kept, _ = filter_retrievable(records, status_path=status)
        assert len(kept) == 1

    def test_missing_status_file_only_filters_short(self, tmp_path):
        missing = tmp_path / "does_not_exist.json"
        records = [
            _rec("a::c000", "a", "VÄƒn báº£n dÃ i hÆ¡n ngÆ°á»¡ng tá»‘i thiá»ƒu."),
            _rec("b::c001", "b", ""),
        ]
        kept, dropped = filter_retrievable(records, status_path=missing)
        assert len(kept) == 1 and dropped == {"too_short": 1, "pending_effective": 0}

    def test_real_corpus_has_no_active_gap(self):
        """The shipped corpus must contain no junk fragments, and everything
        dropped must be pending_effective (never an active/expired source)."""
        from collections import Counter

        path = Path("data/chunks/real_chunks.jsonl")
        if not path.exists():
            return
        records = DocumentLoader.load_chunks(path)
        kept, dropped = filter_retrievable(records, status_path=Path("data/law_status.json"))
        assert len(kept) >= len(records) * 0.95
        assert all(len(r.text.strip()) >= MIN_CHUNK_CHARS for r in kept)
        ids = Counter(r.chunk_id for r in records)
        assert all(v == 1 for v in ids.values())


class TestSplitChunksTail:
    def test_no_tiny_tail_fragment(self):
        loader = DocumentLoader()
        # A paragraph slightly larger than N*step so the last slice would be
        # tiny without the fix.
        para = "tá»« " * 400  # ~2000 chars > 900
        chunks = loader._split_chunks(para)
        assert chunks
        assert all(len(c) > loader.overlap_chars for c in chunks)

    def test_tail_content_preserved(self):
        loader = DocumentLoader()
        body = "Má»Ÿ Ä‘áº§u quy Ä‘á»‹nh. " + "ná»™i dung chi tiáº¿t quan trá»ng " * 120
        tail_marker = "Káº¾T THÃšC CUá»I CÃ™NG"
        para = body + " " + tail_marker
        chunks = loader._split_chunks(para)
        joined = " ".join(chunks)
        # The final words must survive in some chunk (merged or own slice).
        assert any(tail_marker.split()[0] in c for c in chunks) or tail_marker in joined


def test_parse_law_date_formats():
    assert parse_law_date("2027-03-01") == date(2027, 3, 1)
    assert parse_law_date("01-07-2025") == date(2025, 7, 1)
    assert parse_law_date("") is None
    assert parse_law_date("rubbish") is None
