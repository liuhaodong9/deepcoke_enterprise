"""
报告撰写员 Agent — 负责汇总证据、推理结果，生成带引用的最终回答
调用 Skills: report_skills.build_evidence, report_skills.generate_answer_stream,
            report_skills.generate_followups
"""

import logging

from ..skills.report_skills import build_evidence, generate_answer_stream, generate_followups
from ..vectorstore.retriever import RetrievedChunk

logger = logging.getLogger("deepcoke.report_agent")


def run_stream(question: str, chunks: list[RetrievedChunk],
               kg_context: str = "", reasoning_trace: str = "",
               on_progress=None):
    """
    运行报告撰写员 Agent（流式输出）。

    Args:
        question: 用户原始问题
        chunks: 文献研究员检索到的文献片段
        kg_context: 知识图谱上下文
        reasoning_trace: 推理专家的推理过程
        on_progress: 可选回调 on_progress(description)
    Yields:
        回答文本片段
    """
    def _report(desc):
        if on_progress:
            on_progress(desc)

    # Skill 1: 构建证据上下文
    _report("报告撰写员：正在整理证据…")
    evidence_text, references = build_evidence(chunks)

    # Skill 2: 流式生成回答
    _report("报告撰写员：正在生成回答…")
    full_response_parts = []
    for piece in generate_answer_stream(
        question, evidence_text, references, kg_context, reasoning_trace
    ):
        full_response_parts.append(piece)
        yield piece

    _report("报告撰写员：回答生成完成")

    # Skill 3: 生成延伸问题
    _report("报告撰写员：正在生成延伸问题…")
    full_response = "".join(full_response_parts)
    followup_text = generate_followups(question, full_response)
    if followup_text:
        yield followup_text

    _report("报告撰写员：任务完成")
