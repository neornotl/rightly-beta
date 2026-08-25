"""Document loading and chunking for markdown sources."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Optional

from app.schemas import SourceMetadata

_DEMO_MARKER = re.compile(r"DEMO|SYNTHETIC", re.IGNORECASE)

#: Chunks shorter than this are ingest artifacts (mid-word tails such as
#: ``"á)"``, ``"9."``) — they can never answer a query and only pollute the
#: BM25/dense indexes.
MIN_CHUNK_CHARS = 15


class IngestError(ValueError):
    """Raised when a source file cannot be ingested cleanly."""


@dataclass
class ChunkRecord:
    chunk_id: str
    source_id: str
    text: str
    title: str = ""
    source_type: str = ""
    publisher: str = ""
    published_date: str = ""
    is_demo: bool = False
    url: str = ""


@dataclass
class DocumentLoader:
    sources_dir: Path = field(default=Path("data/sources"))
    chunks_dir: Path = field(default=Path("data/chunks"))
    metadata_csv: Path = field(default=Path("data/metadata.csv"))
    out_name: str = "demo_chunks.jsonl"
    chunk_chars: int = 900
    overlap_chars: int = 120

    def __post_init__(self) -> None:
        self.sources_dir = Path(self.sources_dir)
        self.chunks_dir = Path(self.chunks_dir)
        self.metadata_csv = Path(self.metadata_csv)

    def _iter_markdown(self) -> Iterable[tuple[Path, str]]:
        if not self.sources_dir.exists():
            raise IngestError(f"Sources directory not found: {self.sources_dir}")
        files = sorted(self.sources_dir.glob("*.md"))
        if not files:
            raise IngestError(f"No .md files in {self.sources_dir}")
        for path in files:
            text = path.read_text(encoding="utf-8")
            if not text.strip():
                raise IngestError(f"Source file is empty: {path.name}")
            yield path, text

    @staticmethod
    def _parse_front_matter(text: str) -> tuple[dict[str, str], str]:
        """Very small YAML-ish front matter parser (--- blocks)."""
        if not text.startswith("---"):
            return {}, text
        end = text.find("\n---", 3)
        if end == -1:
            return {}, text
        block = text[3:end].strip()
        body = text[end + 4 :].lstrip("\n")
        meta: dict[str, str] = {}
        for line in block.splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                meta[key.strip().lower()] = value.strip().strip("\"'")
        return meta, body

    def _split_chunks(self, text: str) -> list[str]:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        chunks: list[str] = []
        current = ""
        for para in paragraphs:
            if len(current) + len(para) <= self.chunk_chars:
                current = f"{current}\n\n{para}".strip()
            else:
                if current:
                    chunks.append(current)
                if len(para) > self.chunk_chars:
                    step = self.chunk_chars - self.overlap_chars
                    for i in range(0, len(para), step):
                        chunks.append(para[i : i + self.chunk_chars].strip())
                    # The final slice may be a tiny remainder that only
                    # duplicates the overlap region of the previous slice.
                    # Drop it instead of indexing a mid-word fragment.
                    while (
                        len(chunks) > 1
                        and chunks[-1]
                        and len(chunks[-1]) <= self.overlap_chars
                    ):
                        chunks.pop()
                    current = ""
                else:
                    current = para
        if current:
            chunks.append(current)
        return chunks

    def ingest(self) -> list[ChunkRecord]:
        """Ingest all markdown sources; write chunks JSONL and metadata CSV."""
        records: list[ChunkRecord] = []
        for path, raw in self._iter_markdown():
            meta, body = self._parse_front_matter(raw)
            source_id = meta.get("source_id") or path.stem
            is_demo = bool(
                _DEMO_MARKER.search(meta.get("license", "") + " " + meta.get("notes", ""))
            )
            title = meta.get("title", path.stem)
            chunks = self._split_chunks(body)
            if not chunks:
                raise IngestError(f"Source produced no chunks: {path.name}")
            for idx, chunk_text in enumerate(chunks):
                records.append(
                    ChunkRecord(
                        chunk_id=f"{source_id}::c{idx:03d}",
                        source_id=source_id,
                        text=chunk_text,
                        title=title,
                        source_type=meta.get("source_type", "unknown"),
                        publisher=meta.get("publisher", ""),
                        published_date=meta.get("published_date", ""),
                        is_demo=is_demo or bool(_DEMO_MARKER.search(chunk_text + " " + title)),
                        url=meta.get("url", ""),
                    )
                )
        self.chunks_dir.mkdir(parents=True, exist_ok=True)
        out_file = self.chunks_dir / self.out_name
        with out_file.open("w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec.__dict__, ensure_ascii=False) + "\n")
        self._write_metadata_csv(records)
        return records

    def _write_metadata_csv(self, records: list[ChunkRecord]) -> None:
        seen: dict[str, ChunkRecord] = {}
        for rec in records:
            seen.setdefault(rec.source_id, rec)
        self.metadata_csv.parent.mkdir(parents=True, exist_ok=True)
        with self.metadata_csv.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(
                [
                    "source_id",
                    "title",
                    "source_type",
                    "publisher",
                    "published_date",
                    "is_demo",
                    "url",
                ]
            )
            for rec in seen.values():
                writer.writerow(
                    [
                        rec.source_id,
                        rec.title,
                        rec.source_type,
                        rec.publisher,
                        rec.published_date,
                        rec.is_demo,
                        rec.url,
                    ]
                )

    @staticmethod
    def load_chunks(path) -> list[ChunkRecord]:
        path = Path(path)
        records: list[ChunkRecord] = []
        if not path.exists():
            return records
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                records.append(
                    ChunkRecord(**{k: data.get(k) for k in ChunkRecord.__dataclass_fields__})
                )
        return records

    @staticmethod
    def to_metadata(rec: ChunkRecord) -> SourceMetadata:
        return SourceMetadata(
            source_id=rec.source_id,
            title=rec.title,
            source_type=rec.source_type,
            publisher=rec.publisher,
            published_date=rec.published_date,
            is_demo=rec.is_demo,
            url=rec.url,
        )


def parse_law_date(value: str) -> Optional[date]:
    """Parse a registry date in ISO (``2027-03-01``) or VN (``01-03-2027``)."""
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def filter_retrievable(
    records: list[ChunkRecord],
    status_path: Optional[Path] = None,
    today: Optional[date] = None,
) -> tuple[list[ChunkRecord], dict[str, int]]:
    """Drop chunks that must never reach retrieval.

    Removed:
    - degenerate fragments shorter than :data:`MIN_CHUNK_CHARS`;
    - chunks of sources registered ``pending_effective`` — the registry says
      the document is not yet verified/in force, so citing it as current law
      would be wrong even though its text is on disk.

    Expired sources stay retrievable *by design*: the assistant uses them to
    redirect users to the replacement document, and
    :class:`~app.validation.citation_validator.CitationValidator` blocks any
    answer that cites them as current.

    Returns ``(kept_records, dropped_counts)``.
    """
    today = today or date.today()
    statuses: dict[str, str] = {}
    effective: dict[str, Optional[date]] = {}
    if status_path is not None and Path(status_path).exists():
        payload = json.loads(Path(status_path).read_text(encoding="utf-8"))
        for sid, info in (payload.get("sources") or {}).items():
            statuses[sid] = info.get("status", "")
            effective[sid] = parse_law_date(info.get("ngay_hieu_luc") or "")

    kept: list[ChunkRecord] = []
    dropped = {"too_short": 0, "pending_effective": 0}
    for rec in records:
        if len(rec.text.strip()) < MIN_CHUNK_CHARS:
            dropped["too_short"] += 1
            continue
        status = statuses.get(rec.source_id)
        eff = effective.get(rec.source_id)
        if status == "pending_effective" and (eff is None or eff > today):
            dropped["pending_effective"] += 1
            continue
        kept.append(rec)
    return kept, dropped
