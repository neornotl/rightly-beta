"""User-supplied documents ("TaiLieuCuaToi") -> retrievable corpus.

Users drop .md/.txt/.pdf/.docx files into ``data/user_docs``; every server
start re-ingests new or changed files into ``data/chunks/user_chunks.jsonl``
and registers them in ``data/user_registry.json`` so the citation validator
accepts answers grounded in them.

Trust model: user documents are treated as authoritative for that user's
context (per product decision); they are labeled ``source_type="user_doc"``
so audits can tell them apart from verified law.
"""

from __future__ import annotations

import json
import hashlib
import logging
import re
from datetime import date
from pathlib import Path
from typing import Optional

from app.retrieval.document_loader import ChunkRecord, DocumentLoader

logger = logging.getLogger(__name__)

DOCS_DIRNAME = "TaiLieuCuaToi"
CHUNKS_NAME = "user_chunks.jsonl"
REGISTRY_NAME = "user_registry.json"
STATE_NAME = ".ingested_state.json"

SUPPORTED_EXT = {".md", ".txt", ".markdown"}
_CHUNK_CHARS = 900
_OVERLAP_CHARS = 120


def _slug(name: str) -> str:
    base = Path(name).stem
    base = re.sub(r"[^\w\s-]", "", base, flags=re.UNICODE).strip()
    slug = re.sub(r"[\s_]+", "-", base.casefold())
    return slug[:40] or "tailieu"


def _read_text(path: Path) -> Optional[str]:
    ext = path.suffix.lower()
    try:
        if ext in SUPPORTED_EXT:
            return path.read_text(encoding="utf-8", errors="replace")
        if ext == ".pdf":
            try:
                from pypdf import PdfReader  # type: ignore

                reader = PdfReader(str(path))
                return "\n\n".join(
                    (page.extract_text() or "") for page in reader.pages
                )
            except ImportError:
                logger.warning("PDF %s skipped: 'pip install pypdf' để đọc PDF", path.name)
                return None
        if ext == ".docx":
            try:
                import docx  # type: ignore

                document = docx.Document(str(path))
                return "\n\n".join(p.text for p in document.paragraphs if p.text.strip())
            except ImportError:
                logger.warning("DOCX %s skipped: 'pip install python-docx'", path.name)
                return None
    except Exception as exc:
        logger.warning("Cannot read %s: %s", path.name, exc)
        return None
    logger.info("Unsupported file type skipped: %s", path.name)
    return None


def _split(text: str, chunk_chars: int = _CHUNK_CHARS, overlap: int = _OVERLAP_CHARS) -> list[str]:
    loader = DocumentLoader(chunk_chars=chunk_chars, overlap_chars=overlap)
    return loader._split_chunks(text)


def ingest_user_docs(data_dir: Optional[Path] = None, force: bool = False) -> dict:
    """Ingest new/changed files; returns summary dict."""
    root = Path(data_dir) if data_dir else Path("data")
    docs_dir = root.parent / DOCS_DIRNAME if not (root / DOCS_DIRNAME).exists() else root / DOCS_DIRNAME
    # canonical location: project-root/TaiLieuCuaToi OR data/TaiLieuCuaToi
    candidates = [root.parent / DOCS_DIRNAME, root / DOCS_DIRNAME]
    docs_dir = next((c for c in candidates if c.exists()), candidates[0])
    docs_dir.mkdir(parents=True, exist_ok=True)

    chunks_path = root / "chunks" / CHUNKS_NAME
    registry_path = root / REGISTRY_NAME
    state_path = root / STATE_NAME

    state: dict[str, str] = {}
    if state_path.exists() and not force:
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except ValueError:
            state = {}

    # Existing records grouped by source_id (re-ingest replaces whole file).
    records_by_source: dict[str, ChunkRecord] = {}
    if chunks_path.exists():
        for rec in DocumentLoader.load_chunks(chunks_path):
            records_by_source.setdefault(rec.source_id, rec)

    registry: dict = {"sources": {}}
    if registry_path.exists():
        try:
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
        except ValueError:
            registry = {"sources": {}}

    used_slugs = {r.source_id.rsplit("::", 1)[0] for r in records_by_source.values()}
    new_records: list[ChunkRecord] = []
    processed = []

    for path in sorted(docs_dir.rglob("*")):
        if not path.is_file() or path.name.startswith("~$"):
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rel_key = str(path.relative_to(docs_dir)).replace("\\", "/")
        if not force and state.get(rel_key) == digest:
            continue
        text = _read_text(path)
        if text is None:
            continue
        if not text.strip():
            logger.info("Empty document skipped: %s", path.name)
            continue
        slug = _slug(rel_key)
        while f"{slug}_ud" in used_slugs:
            slug = f"{slug}-x"
        source_id = f"{slug}_ud"
        used_slugs.add(source_id)
        title = path.stem
        chunks = _split(text)
        for idx, chunk_text in enumerate(chunks):
            new_records.append(
                ChunkRecord(
                    chunk_id=f"{source_id}::u{idx:03d}",
                    source_id=source_id,
                    text=chunk_text,
                    title=title,
                    source_type="user_doc",
                    publisher="Người dùng cung cấp",
                    published_date=date.today().isoformat(),
                    is_demo=False,
                    url="",
                )
            )
        registry["sources"][source_id] = {
            "ky_hieu": title,
            "loai": "Tài liệu người dùng",
            "trich_yeu": title,
            "ngay_hieu_luc": date.today().isoformat(),
            "expired_on": None,
            "replaced_by": None,
            "status": "active_verified",
            "note": "Nguồn do người dùng cung cấp qua TaiLieuCuaToi",
        }
        state[rel_key] = digest
        processed.append(path.name)
        # drop stale records of replaced source (same slug re-ingest)
        records_by_source.pop(source_id, None)

    if not processed and not force:
        return {"ingested": 0, "files": [], "total_chunks": len(records_by_source)}

    # merge: keep old non-user records? user_chunks only holds user docs.
    all_records: list[ChunkRecord] = []
    seen_sources: set[str] = set()
    for rec in new_records:
        all_records.append(rec)
        seen_sources.add(rec.source_id)
    for sid, rec in records_by_source.items():
        if sid not in seen_sources and rec.source_type == "user_doc":
            all_records.append(rec)
            seen_sources.add(sid)
    all_records.sort(key=lambda r: r.chunk_id)

    chunks_path.parent.mkdir(parents=True, exist_ok=True)
    with chunks_path.open("w", encoding="utf-8") as fh:
        for rec in all_records:
            fh.write(json.dumps(rec.__dict__, ensure_ascii=False) + "\n")

    registry_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info(
        "User docs ingested: %d file(s) -> %d chunk(s) total",
        len(processed),
        len(all_records),
    )
    return {
        "ingested": len(processed),
        "files": processed,
        "total_chunks": len(all_records),
        "sources": sorted(seen_sources),
    }


def load_user_registry(data_dir: Optional[Path] = None) -> dict[str, dict]:
    """Registry entries shaped like law_status sources (validator-compatible)."""
    root = Path(data_dir) if data_dir else Path("data")
    registry_path = root / REGISTRY_NAME
    if not registry_path.exists():
        return {}
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
        return payload.get("sources", {}) or {}
    except (ValueError, OSError):
        return {}
