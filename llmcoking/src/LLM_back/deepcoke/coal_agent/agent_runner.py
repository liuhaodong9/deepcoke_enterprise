"""
配煤优化调度员 — 协调配煤工程师 Agent 和质量分析师 Agent
生成多个方案供用户选择，支持闭环迭代优化
"""

import json
import logging
import requests

from . import blend_agent, quality_agent
from ..skills.coal_skills import get_coal_props, run_multi_strategy_blend
from ..skills.report_skills import extract_constraints

logger = logging.getLogger("deepcoke.coal_agent")

OLLAMA_BASE = "http://localhost:11434"
OLLAMA_CHAT_URL = f"{OLLAMA_BASE}/api/chat"
MODEL = "qwen3:8b"


# ── 格式化工具 ───────────────────────────────────────────────────

def _format_plan_card(plan: dict, prediction: dict, evaluation: dict) -> str:
    """将单个方案格式化为 Markdown 卡片。"""
    strategy = plan.get("strategy", "?")
    name = plan.get("strategy_name", "未知策略")
    passed = evaluation.get("passed", False)
    status = "✅ 达标" if passed else "⚠️ 不达标"

    hoppers = [h for h in plan.get("hoppers", []) if h["ratio"] > 0.1]
    cost = plan.get("cost_per_ton", 0)

    lines = []
    lines.append(f"### 方案 {strategy}: {name} {status}\n")

    lines.append("| 煤种 | 配比(%) | 重量(g) |")
    lines.append("|------|---------|---------|")
    for h in hoppers:
        lines.append(f"| {h['coal']} | {h['ratio']} | {h['weight_g']} |")
    lines.append("")

    if cost > 0:
        lines.append(f"- **吨煤成本：** {cost:.1f} 元")

    cri = prediction.get("CRI")
    csr = prediction.get("CSR")
    if cri is not None and csr is not None:
        lines.append(f"- **预测质量：** CRI = {cri:.2f}，CSR = {csr:.2f}")

    if not passed and evaluation.get("feedback"):
        lines.append(f"- **评估：** {evaluation['feedback']}")

    lines.append("")
    return "\n".join(lines)


def _generate_summary(question: str, plans_report: str) -> str:
    """让 LLM 生成总结和推荐。"""
    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是 DeepCoke 配煤优化报告撰写员。\n"
                    "根据多个配煤方案及其质量预测结果，撰写简洁的总结报告。\n"
                    "报告要包含：\n"
                    "1. 对每个方案的简要点评（一两句话）\n"
                    "2. 你的推荐意见（推荐哪个方案，为什么）\n"
                    "3. 如果没有完全达标的方案，说明原因和建议\n"
                    "使用中文，直接用 Markdown 格式输出。简洁有力。\n"
                    "重要：直接输出内容，不要用 ```markdown``` 代码块包裹。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"用户需求：{question}\n\n"
                    f"方案详情：\n{plans_report}\n\n"
                    f"请给出总结和推荐。 /nothink"
                ),
            },
        ],
        "stream": False,
        "options": {"num_ctx": 4096},
    }

    try:
        resp = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=60)
        resp.raise_for_status()
        content = resp.json()["message"].get("content", "")
        # 清理 LLM 可能包裹的代码块
        import re
        content = re.sub(r'^```\s*(?:markdown|md)?\s*\n', '', content.strip())
        content = re.sub(r'\n```\s*$', '', content.strip())
        return content
    except Exception as e:
        logger.error(f"总结报告生成失败: {e}")
        return ""


# ── 调度主入口 ───────────────────────────────────────────────────

def run_agent(question: str, max_turns: int = 6, on_progress=None) -> str:
    """
    运行多智能体协作的配煤优化流程。

    流程：
    1. 提取约束条件
    2. 生成多个配煤方案（成本最优 / 质量最优 / 均衡）
    3. 质量分析师逐一评估
    4. 汇总输出方案卡片 + 推荐意见

    Args:
        question: 用户原始问题
        max_turns: 兼容旧接口
        on_progress: 可选回调 on_progress(step, total, description)
    Returns:
        最终回答文本（Markdown）
    """
    total_steps = 6
    current_step = 0

    def _report(step, total, desc):
        if on_progress:
            on_progress(step, total, desc)

    # ── Step 1: 提取约束条件 ─────────────────────────────────────
    current_step += 1
    _report(current_step, total_steps, "调度员：正在分析配煤需求…")

    constraints = extract_constraints(question)
    coal_props = get_coal_props()
    logger.info(f"提取到约束条件: {constraints}")

    # ── Step 2: 配煤工程师生成多方案 ─────────────────────────────
    current_step += 1
    _report(current_step, total_steps, "配煤工程师：正在生成多个配煤方案…")

    plans = run_multi_strategy_blend(
        coal_names=list(coal_props.keys()),
        constraints=constraints,
    )

    if not plans:
        # 多策略失败，回退到单方案模式
        logger.info("多策略优化无结果，回退到 blend_agent 单方案模式")
        _report(current_step, total_steps, "配煤工程师：正在设计方案（单方案模式）…")
        blend_result = blend_agent.run(instruction=question)
        if blend_result is None:
            return "配煤工程师未能找到满足条件的方案，请尝试放宽约束条件或更换煤种。"
        blend_result["strategy"] = "A"
        blend_result["strategy_name"] = "最优方案"
        plans = [blend_result]

    logger.info(f"生成了 {len(plans)} 个方案")

    # ── Step 3: 质量分析师逐一评估 ───────────────────────────────
    current_step += 1
    _report(current_step, total_steps, f"质量分析师：正在评估 {len(plans)} 个方案…")

    evaluated_plans = []
    for plan in plans:
        eval_result = quality_agent.run(
            blend_result=plan,
            coal_props=coal_props,
            constraints=constraints,
        )
        evaluated_plans.append({
            "plan": plan,
            "prediction": eval_result["prediction"],
            "evaluation": {
                "passed": eval_result["passed"],
                "feedback": eval_result["feedback"],
            },
        })

    logger.info(f"评估完成: {sum(1 for e in evaluated_plans if e['evaluation']['passed'])}/{len(evaluated_plans)} 达标")

    # ── Step 4: 生成方案卡片 ─────────────────────────────────────
    current_step += 1
    _report(current_step, total_steps, "报告撰写员：正在生成方案报告…")

    plans_report = "## 配煤方案对比\n\n"
    for ep in evaluated_plans:
        plans_report += _format_plan_card(
            ep["plan"], ep["prediction"], ep["evaluation"]
        )

    # ── Step 5: 生成总结和推荐 ───────────────────────────────────
    current_step += 1
    _report(current_step, total_steps, "报告撰写员：正在生成推荐意见…")

    summary = _generate_summary(question, plans_report)

    # ── Step 6: 组装最终输出 ─────────────────────────────────────
    current_step = total_steps
    _report(current_step, total_steps, "任务完成")

    output_parts = [plans_report]
    if summary:
        output_parts.append("---\n\n## 智能推荐\n\n")
        output_parts.append(summary)

    return "\n".join(output_parts)
