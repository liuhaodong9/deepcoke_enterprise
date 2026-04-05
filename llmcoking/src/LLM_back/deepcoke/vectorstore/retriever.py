"""
Semantic retrieval over the ChromaDB coking papers collection.
"""
import sqlite3
from dataclasses import dataclass

from .chromadb_store import get_collection
from .. import config


@dataclass
class RetrievedChunk:
    text: str
    paper_id: int
    title: str
    section: str
    category: str
    year: int
    authors: str
    keywords: str
    score: float  # cosine similarity (higher = more similar)
    chunk_index: int
    journal: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    doi: str = ""


def retrieve(
    query: str,
    top_k: int | None = None,
    where: dict | None = None,
) -> list[RetrievedChunk]:
    """
    Retrieve top-k most relevant chunks for a query.

    Args:
        query: English search query text.
        top_k: Number of results (default from config).
        where: Optional ChromaDB metadata filter, e.g. {"category": "CSR & CRI"}.

    Returns:
        List of RetrievedChunk sorted by relevance.
    """
    k = top_k or config.RETRIEVAL_TOP_K
    collection = get_collection()

    query_params = {
        "query_texts": [query],
        "n_results": k,
    }
    if where:
        query_params["where"] = where

    results = collection.query(**query_params)

    chunks = []
    if not results or not results["ids"] or not results["ids"][0]:
        return chunks

    for i, doc_id in enumerate(results["ids"][0]):
        meta = results["metadatas"][0][i]
        distance = results["distances"][0][i] if results.get("distances") else 0.0
        # ChromaDB returns distances; for cosine, similarity = 1 - distance
        similarity = 1.0 - distance

        chunks.append(RetrievedChunk(
            text=results["documents"][0][i],
            paper_id=meta.get("paper_id", 0),
            title=meta.get("title", ""),
            section=meta.get("section", ""),
            category=meta.get("category", ""),
            year=meta.get("year", 0),
            authors=meta.get("authors", ""),
            keywords=meta.get("keywords", ""),
            score=similarity,
            chunk_index=meta.get("chunk_index", 0),
            journal=meta.get("journal", ""),
            volume=meta.get("volume", ""),
            issue=meta.get("issue", ""),
            pages=meta.get("pages", ""),
            doi=meta.get("doi", ""),
        ))

    # 从 papers.db 补全 journal/volume/issue/pages/doi 等字段
    _enrich_from_papers_db(chunks)

    return chunks


def _enrich_from_papers_db(chunks: list[RetrievedChunk]):
    """从 papers.db 查询补全 ChromaDB 中缺失的元数据字段"""
    if not chunks:
        return

    paper_ids = list({c.paper_id for c in chunks if c.paper_id})
    if not paper_ids:
        return

    try:
        db_path = config.DATA_DIR / "papers.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        placeholders = ",".join("?" * len(paper_ids))
        rows = conn.execute(
            f"SELECT id, title, authors, year, journal, volume, issue, pages, doi "
            f"FROM papers WHERE id IN ({placeholders})",
            paper_ids,
        ).fetchall()
        conn.close()

        db_map = {r["id"]: r for r in rows}
        for chunk in chunks:
            row = db_map.get(chunk.paper_id)
            if not row:
                continue
            if not chunk.journal and row["journal"]:
                chunk.journal = row["journal"]
            if not chunk.volume and row["volume"]:
                chunk.volume = row["volume"]
            if not chunk.issue and row["issue"]:
                chunk.issue = row["issue"]
            if not chunk.pages and row["pages"]:
                chunk.pages = row["pages"]
            if not chunk.doi and row["doi"]:
                chunk.doi = row["doi"]
            if (not chunk.authors or chunk.authors == "[]") and row["authors"] and row["authors"] != "[]":
                chunk.authors = row["authors"]
            if row["title"] and len(row["title"]) > len(chunk.title or ""):
                chunk.title = row["title"]
            if not chunk.year and row["year"]:
                chunk.year = row["year"]
    except Exception:
        pass  # 数据库不可用时静默降级
