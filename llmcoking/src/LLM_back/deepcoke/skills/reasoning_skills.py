"""
推理专家 Skills — ESCARGOT 深度推理
"""

import logging

from ..reasoning.escargot_runner import run_escargot_reasoning

logger = logging.getLogger("deepcoke.skills.reasoning")


# ── Skill: 深度推理 ──────────────────────────────────────────────

def deep_reasoning(question: str, timeout: int = 60,
                   num_strategies: int = 2) -> dict:
    """
    对复杂问题进行 ESCARGOT Graph of Thoughts 深度推理。

    Args:
        question: 需要推理的问题
        timeout: 超时时间（秒）
        num_strategies: 推理路径数
    Returns:
        {"reasoning_trace": str, "success": bool}
    """
    try:
        trace = run_escargot_reasoning(
            question,
            answer_type="natural",
            num_strategies=num_strategies,
            timeout=timeout,
        )
        if trace and "超时" not in trace:
            logger.info(f"深度推理完成: {len(trace)} 字符")
            return {"reasoning_trace": trace, "success": True}
        else:
            logger.info("深度推理超时或无结果")
            return {"reasoning_trace": "", "success": False}
    except Exception as e:
        logger.warning(f"深度推理异常: {e}")
        return {"reasoning_trace": "", "success": False}
