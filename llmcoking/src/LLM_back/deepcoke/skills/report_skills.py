"""
报告撰写员 Skills — 证据汇总、回答生成、延伸问题
"""

import logging

from ..generation.answer_generator import (
    build_evidence_context,
    build_answer_prompt,
    format_references,
)
from ..followup.followup_generator import generate_followup_questions, format_followup_block
from ..llm_client import chat
from ..vectorstore.retriever import RetrievedChunk

logger = logging.getLogger("deepcoke.skills.report")


# ── Skill: 构建证据上下文 ────────────────────────────────────────

def build_evidence(chunks: list[RetrievedChunk]) -> tuple[str, list[dict]]:
    """
    将检索到的文献片段构建为带引用编号的证据文本。

    Returns:
        (evidence_text, references_list)
    """
    return build_evidence_context(chunks)


# ── Skill: 流式生成回答 ──────────────────────────────────────────

def generate_answer_stream(question: str, evidence_text: str,
                           references: list[dict],
                           kg_context: str = "",
                           reasoning_trace: str = ""):
    """
    基于证据流式生成带引用的回答。

    Yields:
        回答文本片段
    """
    messages = build_answer_prompt(question, evidence_text, kg_context, reasoning_trace)

    stream = chat(messages, stream=True)
    for chunk in stream:
        if not getattr(chunk, "choices", None):
            continue
        delta = chunk.choices[0].delta
        piece = getattr(delta, "content", None)
        if not piece:
            continue
        yield piece

    # 附加参考文献
    if references:
        yield format_references(references)


# ── Skill: 生成延伸问题 ──────────────────────────────────────────

def generate_followups(question: str, answer_summary: str) -> str:
    """
    基于问答对生成延伸问题。

    Returns:
        格式化的延伸问题文本块（Markdown），无则返回空字符串
    """
    try:
        followups = generate_followup_questions(question, answer_summary[:500])
        return format_followup_block(followups)
    except Exception as e:
        logger.warning(f"延伸问题生成失败: {e}")
        return ""


# ── Skill: 约束条件提取 ──────────────────────────────────────────

def extract_constraints(question: str) -> dict:
    """
    从用户问题中提取质量约束条件。

    Returns:
        {CSR_min, CRI_max, ...} 约束字典
    """
    import re
    import json
    import requests

    OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
    MODEL = "qwen3:8b"

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "从用户的配煤需求中提取质量约束条件，返回 JSON 格式。\n"
                    "可能的字段：CRI_min, CRI_max, CSR_min, CSR_max, M10_min, M10_max, "
                    "M25_min, M25_max, Vdaf_max, G_min, Ad_max\n"
                    "只提取用户明确提到的约束，没提到的不要加。\n"
                    "只返回 JSON，不要其他文字。"
                ),
            },
            {"role": "user", "content": question + " /nothink"},
        ],
        "stream": False,
        "options": {"num_ctx": 2048},
    }

    try:
        resp = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=30)
        resp.raise_for_status()
        content = resp.json()["message"].get("content", "")
        match = re.search(r"\{[^}]*\}", content)
        if match:
            return json.loads(match.group(0))
    except Exception as e:
        logger.warning(f"约束提取失败: {e}")

    return {}
