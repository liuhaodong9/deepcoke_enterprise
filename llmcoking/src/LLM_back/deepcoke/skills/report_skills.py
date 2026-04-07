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

    # 附上引用论文中的原文图表
    if references:
        try:
            from ..generation.pdf_figures import get_figures_for_references
            paper_ids = [r["paper_id"] for r in references if r.get("paper_id")]
            figures = get_figures_for_references(paper_ids, max_total=4)
            if figures:
                fig_parts = ["\n\n---\n\n**文献图表：**\n\n"]
                for fig in figures:
                    ref_num = ""
                    for r in references:
                        if r.get("paper_id") == fig.get("paper_id"):
                            ref_num = f"[{r['num']}]"
                            break
                    caption = fig.get("caption", "")
                    caption_html = f'<br><span style="color:#334155;font-size:13px;">{caption}</span>' if caption else ""
                    fig_parts.append(
                        f'<div style="margin:12px 0;padding:10px;background:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;">'
                        f'<img src="{fig["url"]}" alt="文献图 {ref_num} p.{fig["page"]}" '
                        f'style="max-width:100%;border-radius:4px;">'
                        f'{caption_html}'
                        f'<br><small style="color:#94A3B8;">来源：{ref_num} 第{fig["page"]}页</small>'
                        f'</div>\n\n'
                    )
                yield "".join(fig_parts)
        except Exception as e:
            logger.warning(f"提取文献图片失败: {e}")


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

def _regex_extract_constraints(question: str) -> dict | None:
    """用正则从问题中快速提取约束，能提取到就跳过 LLM。"""
    import re
    constraints = {}

    # 匹配模式：CRI≤28, CRI<=28, CRI不超过28, CRI<28, CRI上限28 等
    patterns = [
        # CRI 上限
        (r"CRI\s*[≤<＜]\s*=?\s*(\d+\.?\d*)", "CRI_max"),
        (r"CRI\s*不[超大高]过\s*(\d+\.?\d*)", "CRI_max"),
        (r"CRI\s*上限\s*(\d+\.?\d*)", "CRI_max"),
        (r"CRI\s*最[大高]\s*(\d+\.?\d*)", "CRI_max"),
        # CRI 下限
        (r"CRI\s*[≥>＞]\s*=?\s*(\d+\.?\d*)", "CRI_min"),
        (r"CRI\s*不[低小]于\s*(\d+\.?\d*)", "CRI_min"),
        (r"CRI\s*下限\s*(\d+\.?\d*)", "CRI_min"),
        # CSR 下限
        (r"CSR\s*[≥>＞]\s*=?\s*(\d+\.?\d*)", "CSR_min"),
        (r"CSR\s*不[低小]于\s*(\d+\.?\d*)", "CSR_min"),
        (r"CSR\s*下限\s*(\d+\.?\d*)", "CSR_min"),
        (r"CSR\s*最[小低]\s*(\d+\.?\d*)", "CSR_min"),
        # CSR 上限
        (r"CSR\s*[≤<＜]\s*=?\s*(\d+\.?\d*)", "CSR_max"),
        (r"CSR\s*不[超大高]过\s*(\d+\.?\d*)", "CSR_max"),
        # M10 上限
        (r"M10\s*[≤<＜]\s*=?\s*(\d+\.?\d*)", "M10_max"),
        (r"M10\s*不[超大高]过\s*(\d+\.?\d*)", "M10_max"),
        # M25 下限
        (r"M25\s*[≥>＞]\s*=?\s*(\d+\.?\d*)", "M25_min"),
        (r"M25\s*不[低小]于\s*(\d+\.?\d*)", "M25_min"),
        # 灰分上限
        (r"(?:灰分|Ad)\s*[≤<＜]\s*=?\s*(\d+\.?\d*)", "Ad_max"),
        (r"(?:灰分|Ad)\s*不[超大高]过\s*(\d+\.?\d*)", "Ad_max"),
        # 挥发分上限
        (r"(?:挥发分|Vdaf)\s*[≤<＜]\s*=?\s*(\d+\.?\d*)", "Vdaf_max"),
        # 粘结指数下限
        (r"(?:粘结指数|G)\s*[≥>＞]\s*=?\s*(\d+\.?\d*)", "G_min"),
    ]

    for pat, key in patterns:
        m = re.search(pat, question, re.IGNORECASE)
        if m:
            constraints[key] = float(m.group(1))

    return constraints if constraints else None


def extract_constraints(question: str) -> dict:
    """
    从用户问题中提取质量约束条件。
    优先用正则快速提取，提取不到再调 LLM。

    Returns:
        {CSR_min, CRI_max, ...} 约束字典
    """
    import re
    import json
    import requests

    # 快速路径：正则提取
    fast_result = _regex_extract_constraints(question)
    if fast_result:
        logger.info(f"正则快速提取约束: {fast_result}")
        return fast_result

    # 慢路径：LLM 提取
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
