"""
文献研究员 Skills — 查询翻译、文献检索、知识图谱查询
"""

import logging

from ..classifier.query_translator import translate_query
from ..vectorstore.retriever import retrieve, RetrievedChunk
from ..knowledge_graph.neo4j_client import find_related_papers, query_kg_with_llm

logger = logging.getLogger("deepcoke.skills.research")


# ── Skill: 查询翻译与关键词提取 ──────────────────────────────────

def translate_and_extract(question: str) -> dict:
    """
    将中文问题翻译为英文检索语句，并提取关键概念。

    Returns:
        {
            "english_queries": list[str],
            "key_concepts": list[str],
            "key_methods": list[str],
            "key_materials": list[str],
        }
    """
    try:
        return translate_query(question)
    except Exception as e:
        logger.error(f"查询翻译失败: {e}")
        return {
            "english_queries": [question],
            "key_concepts": [],
            "key_methods": [],
            "key_materials": [],
        }


# ── Skill: 向量数据库检索 ────────────────────────────────────────

def search_literature(queries: list[str], top_k: int = 5) -> list[RetrievedChunk]:
    """
    用英文检索语句在向量数据库中检索文献片段。

    Args:
        queries: 英文检索语句列表
        top_k: 每个查询返回的结果数
    Returns:
        去重后的文献片段列表，按相关度排序
    """
    all_chunks: list[RetrievedChunk] = []
    try:
        for eq in queries:
            chunks = retrieve(eq, top_k=top_k)
            all_chunks.extend(chunks)
    except Exception as e:
        logger.error(f"文献检索失败: {e}")
        return []

    # 去重，按 (paper_id, chunk_index) 保留最高分
    seen = {}
    for c in all_chunks:
        key = (c.paper_id, c.chunk_index)
        if key not in seen or c.score > seen[key].score:
            seen[key] = c

    return sorted(seen.values(), key=lambda x: x.score, reverse=True)[:10]


# ── Skill: 知识图谱查询 ──────────────────────────────────────────

def search_knowledge_graph(concepts: list[str], limit: int = 3) -> str:
    """
    根据关键概念查询知识图谱，返回格式化的上下文文本。

    Args:
        concepts: 关键概念列表
        limit: 每个概念返回的论文数
    Returns:
        知识图谱上下文文本
    """
    try:
        kg_results = []
        for concept in concepts[:3]:
            papers = find_related_papers(concept, limit=limit)
            if papers:
                kg_results.extend(papers)

        if not kg_results:
            return ""

        kg_lines = []
        for r in kg_results[:5]:
            kg_lines.append(
                f"- {r.get('title', 'Unknown')} ({r.get('year', '?')}): "
                f"studies {r.get('concept', '')}"
            )
        return "\n".join(kg_lines)

    except Exception as e:
        logger.warning(f"知识图谱查询异常: {e}")
        return ""


# ── Skill: 自然语言知识图谱查询 ──────────────────────────────────

def query_kg_natural(question: str) -> list[dict]:
    """
    用自然语言查询知识图谱（LLM 生成 Cypher 语句）。

    Args:
        question: 自然语言问题
    Returns:
        查询结果列表
    """
    try:
        return query_kg_with_llm(question)
    except Exception as e:
        logger.warning(f"自然语言 KG 查询失败: {e}")
        return []
