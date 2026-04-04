"""
推理专家 Agent — 负责复杂问题的深度推理
调用 Skills: reasoning_skills.deep_reasoning
"""

import logging

from ..skills.reasoning_skills import deep_reasoning

logger = logging.getLogger("deepcoke.reasoning_agent")


def run(question: str, timeout: int = 60, num_strategies: int = 2,
        on_progress=None) -> dict:
    """
    运行推理专家 Agent。

    Args:
        question: 需要深度推理的问题
        timeout: 推理超时时间（秒）
        num_strategies: 探索的推理路径数
        on_progress: 可选回调 on_progress(description)
    Returns:
        {"reasoning_trace": str, "success": bool}
    """
    def _report(desc):
        if on_progress:
            on_progress(desc)

    _report("推理专家：正在进行深度推理（ESCARGOT）…")

    result = deep_reasoning(question, timeout=timeout, num_strategies=num_strategies)

    if result["success"]:
        _report("推理专家：深度推理完成")
    else:
        _report("推理专家：跳过（超时/异常）")

    return result
