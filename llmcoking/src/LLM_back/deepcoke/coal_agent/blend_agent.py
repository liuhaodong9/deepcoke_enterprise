"""
配煤工程师 Agent — 负责查询煤种、设计配煤方案
调用 Skills: coal_skills.list_coals, coal_skills.optimize_blend
"""

import json
import requests
import logging

from ..skills.coal_skills import TOOL_DEFINITIONS, exec_tool

logger = logging.getLogger("deepcoke.blend_agent")

OLLAMA_BASE = "http://localhost:11434"
OLLAMA_CHAT_URL = f"{OLLAMA_BASE}/api/chat"
MODEL = "qwen3:8b"

SYSTEM_PROMPT = """你是 DeepCoke 配煤工程师 Agent。你的职责是设计配煤方案。

你可以：
1. **查询煤种** — 用 list_coals 查看数据库中所有可用煤种及化验指标
2. **优化配煤** — 用 optimize_blend 根据约束条件找到成本最低的配煤方案

工作流程：
- 先用 list_coals 查看可用煤种
- 根据需求选择合适的煤种，调用 optimize_blend
- 返回完整的配煤方案（包含每种煤的配比和重量）

注意：
- 配比之和应为100%，每种煤的配比范围为0-60%
- 回答使用中文
- 只负责出配煤方案，不做质量预测（质量评估由质量分析师负责）"""


def _ollama_chat(messages: list[dict], tools: list | None = None) -> dict:
    """调用 Ollama /api/chat，返回 message 对象。"""
    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "options": {"num_ctx": 4096},
    }
    if tools:
        payload["tools"] = tools
    resp = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()["message"]


def run(instruction: str, max_turns: int = 4, on_progress=None) -> dict | None:
    """
    运行配煤工程师 Agent。

    Args:
        instruction: 配煤需求描述
        max_turns: 最大工具调用轮次
        on_progress: 可选回调 on_progress(description)
    Returns:
        配煤方案 dict（含 hoppers, cost_per_ton 等），或 None
    """
    def _report(desc):
        if on_progress:
            on_progress(desc)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": instruction + " /nothink"},
    ]

    _report("配煤工程师：正在分析需求…")
    last_blend_result = None

    for turn in range(max_turns):
        try:
            reply = _ollama_chat(messages, tools=TOOL_DEFINITIONS)
        except Exception as e:
            logger.error(f"配煤工程师 LLM 调用失败: {e}")
            return None

        tool_calls = reply.get("tool_calls")
        if not tool_calls:
            break

        messages.append(reply)

        for tc in tool_calls:
            fn = tc["function"]
            tool_name = fn["name"]
            tool_args = fn.get("arguments", {})
            if isinstance(tool_args, str):
                try:
                    tool_args = json.loads(tool_args)
                except json.JSONDecodeError:
                    tool_args = {}

            label = {"list_coals": "查询可用煤种", "optimize_blend": "优化配煤方案"}.get(tool_name, tool_name)
            _report(f"配煤工程师：正在{label}…")

            logger.info(f"配煤工程师 Tool call: {tool_name}({tool_args})")
            result_str = exec_tool(tool_name, tool_args)

            if tool_name == "optimize_blend":
                try:
                    parsed = json.loads(result_str)
                    if "error" not in parsed:
                        last_blend_result = parsed
                except (json.JSONDecodeError, TypeError):
                    pass

            messages.append({"role": "tool", "content": result_str})

    _report("配煤工程师：方案设计完成")
    return last_blend_result
