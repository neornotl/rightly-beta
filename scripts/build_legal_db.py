#!/usr/bin/env python3
"""
Build vector database from legal documents for retrieval.
Uses the legal_database.json as source of truth.
"""

import json
import sys
from pathlib import Path
from typing import List, Dict
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.retrieval.document_loader import DocumentLoader, ChunkRecord
from app.retrieval.bm25_retriever import BM25Retriever
from app.retrieval.hybrid_retriever import HybridRetriever, DenseIndex
from app.config import Settings
import numpy as np


@dataclass
class LegalChunk:
    chunk_id: str
    source_id: str
    text: str
    title: str
    source_type: str
    publisher: str
    published_date: str
    is_demo: bool
    url: str
    linh_vuc: str = ""
    tags: List[str] = None
    document_number: str = ""
    effective_date: str = ""
    gazette_number: str = ""
    pages: int = 0

    def __post_init__(self):
        if self.tags is None:
            self.tags = []


def load_legal_database() -> Dict:
    with open("data/legal_database.json", "r", encoding="utf-8") as f:
        return json.load(f)


def load_source_texts() -> Dict[str, str]:
    """Load full text content from markdown files."""
    texts = {}
    sources_dir = Path("data/sources_real")
    for md_file in sources_dir.glob("*.md"):
        content = md_file.read_text(encoding="utf-8")
        source_id = md_file.stem
        texts[source_id] = content
    return texts


def create_chunks_from_legal_db(db: Dict, source_texts: Dict[str, str]) -> List[ChunkRecord]:
    """Create ChunkRecords from legal database with accurate metadata."""
    records = []
    chunk_chars = 900
    overlap_chars = 120
    
    # Combine current sources with missing critical (when available)
    all_sources = {**db['sources']}
    
    for source_id, meta in all_sources.items():
        if source_id not in source_texts:
            print(f"WARNING: No text content for {source_id}")
            continue
        
        text = source_texts[source_id]
        
        # Split into chunks
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        chunks = []
        current = ""
        
        for para in paragraphs:
            if len(current) + len(para) <= chunk_chars:
                current = f"{current}\n\n{para}".strip() if current else para
            else:
                if current:
                    chunks.append(current)
                if len(para) > chunk_chars:
                    for i in range(0, len(para), chunk_chars - overlap_chars):
                        chunks.append(para[i:i + chunk_chars].strip())
                    current = ""
                else:
                    current = para
        if current:
            chunks.append(current)
        
        if not chunks:
            continue
        
        # Create records with full metadata
        for idx, chunk_text in enumerate(chunks):
            chunk_id = f"{source_id}::c{idx:03d}"
            record = ChunkRecord(
                chunk_id=chunk_id,
                source_id=source_id,
                text=chunk_text,
                title=meta.get('trich_yeu', source_id),
                source_type=meta.get('source_type', meta.get('loai', 'unknown')),
                publisher=meta.get('issuing_authority', meta.get('co_quan', '')),
                published_date=meta.get('effective_date', meta.get('ngay_hieu_luc', '')),
                is_demo=False,
                url=meta.get('url', ''),
            )
            # Add custom metadata
            record.metadata = {
                'linh_vuc': meta.get('linh_vuc', ''),
                'tags': meta.get('tags', []),
                'document_number': meta.get('document_number', meta.get('ky_hieu', '')),
                'gazette_number': meta.get('gazette_number', ''),
                'pages': meta.get('pages', 0),
                'expired_on': meta.get('expired_on'),
                'replaced_by': meta.get('replaced_by'),
                'status': meta.get('status', 'active_verified'),
            }
            records.append(record)
    
    return records


def build_bm25_index(records: List[ChunkRecord]) -> BM25Retriever:
    """Build BM25 index from chunks."""
    bm25 = BM25Retriever.from_chunks(records)
    return bm25


def build_dense_index(records: List[ChunkRecord]) -> DenseIndex:
    """Build dense vector index from chunks."""
    dense = DenseIndex.from_chunks(records, cache_path=Path("data/chunks/real_embeddings.npz"))
    return dense


def build_hybrid_retriever(records: List[ChunkRecord]) -> HybridRetriever:
    """Build hybrid retriever (BM25 + Dense + RRF)."""
    bm25 = BM25Retriever.from_chunks(records)
    dense = DenseIndex.from_chunks(records, cache_path=Path("data/chunks/real_embeddings.npz"))
    
    hybrid = HybridRetriever(
        bm25=bm25,
        dense=dense,
        exclude_demo=False,
        rerank=False,
        gate="bm25_dense",
        bm25_gate=12.2,
        dense_gate=0.88,
    )
    return hybrid


def save_chunks(records: List[ChunkRecord], output_path: Path):
    """Save chunks to JSONL."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for rec in records:
            # Convert to dict with metadata
            data = {
                'chunk_id': rec.chunk_id,
                'source_id': rec.source_id,
                'text': rec.text,
                'title': rec.title,
                'source_type': rec.source_type,
                'publisher': rec.publisher,
                'published_date': rec.published_date,
                'is_demo': rec.is_demo,
                'url': rec.url,
            }
            # Add custom metadata
            if hasattr(rec, 'metadata'):
                data.update(rec.metadata)
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
    print(f"Saved {len(records)} chunks to {output_path}")


def save_metadata_csv(records: List[ChunkRecord], output_path: Path):
    """Save source metadata CSV."""
    import csv
    seen = {}
    for rec in records:
        if rec.source_id not in seen:
            seen[rec.source_id] = rec
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "source_id", "title", "source_type", "publisher", 
            "published_date", "is_demo", "url",
            "linh_vuc", "tags", "document_number", 
            "gazette_number", "pages", "status"
        ])
        for rec in seen.values():
            meta = getattr(rec, 'metadata', {})
            writer.writerow([
                rec.source_id,
                rec.title,
                rec.source_type,
                rec.publisher,
                rec.published_date,
                rec.is_demo,
                rec.url,
                meta.get('linh_vuc', ''),
                ";".join(meta.get('tags', [])),
                meta.get('document_number', ''),
                meta.get('gazette_number', ''),
                meta.get('pages', 0),
                meta.get('status', 'active_verified'),
            ])
    print(f"Saved metadata for {len(seen)} sources to {output_path}")


def main():
    print("Loading legal database...")
    db = load_legal_database()
    
    print("Loading source texts...")
    source_texts = load_source_texts()
    print(f"Found {len(source_texts)} source text files")
    
    print("Creating chunks with accurate metadata...")
    records = create_chunks_from_legal_db(db, source_texts)
    print(f"Created {len(records)} chunks")
    
    print("Saving chunks...")
    save_chunks(records, Path("data/chunks/real_chunks.jsonl"))
    save_metadata_csv(records, Path("data/metadata.csv"))
    
    print("Building BM25 index...")
    bm25 = build_bm25_index(records)
    print("BM25 index built")
    
    print("Building dense index...")
    dense = build_dense_index(records)
    print("Dense index built")
    
    print("Building hybrid retriever...")
    hybrid = build_hybrid_retriever(records)
    print("Hybrid retriever built")
    
    # Test retrieval
    print("\nTesting retrieval...")
    test_queries = [
        "Thủ tục đăng ký khai sinh cần giấy tờ gì?",
        "Hồ sơ đăng ký kết hôn gồm những gì?",
        "Đăng ký tạm trú cần bao nhiêu ngày?",
        "Phí cấp lại giấy khai sinh là bao nhiêu?",
        "Thẻ BHXH cấp như thế nào?",
        "Luật lao động quy định gì về giờ làm việc?",
    ]
    
    for query in test_queries:
        print(f"\nQuery: {query}")
        results = hybrid.search(query, top_k=3)
        for i, r in enumerate(results, 1):
            print(f"  {i}. {r.source_id} (score: {r.score:.4f}) - {r.text[:80]}...")
    
    print("\n✅ Legal database build complete!")


if __name__ == "__main__":
    main()