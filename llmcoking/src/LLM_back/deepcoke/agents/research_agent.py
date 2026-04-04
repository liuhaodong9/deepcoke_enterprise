"""
文献研究员 Agent — 负责检索文献、查询知识图谱，为回答提供证据支撑
调用 Skills: research_skills.translate_and_extract, research_skills.search_literature,
            research_skills.search_knowledge_graph
"""

import logging

from ..skills.research_skills import (
    translate_and_extract,
    search_literature,
    search_knowledge_graph,
)

logger = logging.getLogger("deepcoke.research_agent")


def run(question: str, top_k: int = 5, on_progress=None) -> dict:
    """
    运行文献研究员 Agent。

    Args:
        question: 用户问题（中文）
        top_k: 每个查询检索的文献数量
        on_progress: 可选回调 on_progress(description)
    Returns:
        {
            "chunks": list[RetrievedChunk],
            "kg_context": str,
            "key_concepts": list[str],
            "english_queries": list[str],
        }
    """
    def _report(desc):
        if on_progress:
            on_progress(desc)

    # Skill 1: 查询翻译与关键词提取
    _report("文献研究员：正在提取关键词并翻译检索语句…")
    translated = translate_and_extract(question)
    english_queries = translated["english_queries"]
    key_concepts = translated["key_concepts"]
    logger.info(f"检索语句: {english_queries}, 关键概念: {key_concepts}")

    # Skill 2: 向量数据库检索
    _report("文献研究员：正在检索文献数据库…")
    chunks = search_literature(english_queries, top_k=top_k)
    logger.info(f"检索到 {len(chunks)} 条文献片段")

    # Skill 3: 知识图谱查询
    _report("文献研究员：正在查询知识图谱…")
    kg_context = search_knowledge_graph(key_concepts)

    _report(f"文献研究员：检索到 {len(chunks)} 条文献，{len(kg_context.splitlines()) if kg_context else 0} 条图谱关联")

    return {
        "chunks": chunks,
        "kg_context": kg_context,
        "key_concepts": key_concepts,
        "english_queries": english_queries,
    }
