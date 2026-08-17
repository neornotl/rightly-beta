"""Document loading and chunking for markdown sources."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from app.schemas import SourceMetadata

_DEMO_MARKER = re.compile(r"DEMO|SYNTHETIC", re.IGNORECASE)


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
                    for i in range(0, len(para), self.chunk_chars - self.overlap_chars):
                        chunks.append(para[i : i + self.chunk_chars].strip())
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
