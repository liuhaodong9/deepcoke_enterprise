"""
DeepCoke 多智能体 Pipeline 调度器（交互式）
Agent 在关键决策点暂停，与用户讨论后再行动。
"""
import logging
import asyncio
import json
from typing import AsyncGenerator

from .classifier.question_classifier import classify_question, is_complex, needs_rag
from .agents import research_agent, reasoning_agent, report_agent
from .coal_agent.agent_runner import run_agent as run_coal_agent
from .coal_agent.coal_db import (
    get_all_coals, get_coal_by_name, add_coal, update_coal,
    delete_coal, batch_add_coals, CORE_FIELDS,
)
from .skills.coal_skills import get_coal_props, run_multi_strategy_blend, _coal_cache
from .coal_agent.blend_optimizer import optimize_with_feedback
from .skills.report_skills import extract_constraints
from .coal_agent import quality_agent
from .llm_client import chat_json
from . import pipeline_state as state

logger = logging.getLogger("deepcoke.pipeline")


# ── Agent 交互按钮 HTML 生成 ─────────────────────────────────────

def _agent_buttons(buttons: list[dict]) -> str:
    """生成 Agent 交互按钮 HTML。
    buttons: [{"label": "确认", "action": "__AGENT:confirm__"}, ...]
    """
    lines = ['<div class="agent-actions">']
    for btn in buttons:
        action = btn["action"]
        label = btn["label"]
        style = btn.get("style", "default")
        lines.append(
            f'<button class="agent-btn agent-btn-{style}" '
            f'data-agent-action="{action}">{label}</button>'
        )
    lines.append('</div>')
    return ''.join(lines)


def _agent_message(agent_name: str, text: str, buttons: list[dict] = None) -> str:
    """生成 Agent 对话消息（带可选按钮）。"""
    lines = [f'\n\n**{agent_name}：** {text}\n\n']
    if buttons:
        lines.append(_agent_buttons(buttons))
    return ''.join(lines)


# ── 约束调整辅助 ─────────────────────────────────────────────────

# 约束项的中文描述映射
_CONSTRAINT_LABELS = {
    "CRI_max": "CRI上限", "CRI_min": "CRI下限",
    "CSR_max": "CSR上限", "CSR_min": "CSR下限",
    "M10_max": "M10上限", "M10_min": "M10下限",
    "M25_max": "M25上限", "M25_min": "M25下限",
    "Vdaf_max": "挥发分上限", "Vdaf_min": "挥发分下限",
    "G_min": "粘结指数下限", "Ad_max": "灰分上限",
}


def _describe_constraints(constraints: dict) -> str:
    """把约束字典转为可读文本。"""
    if not constraints:
        return "无"
    parts = []
    for k, v in constraints.items():
        label = _CONSTRAINT_LABELS.get(k, k)
        parts.append(f"{label}={v}")
    return "，".join(parts)


def _build_adjustment_buttons(constraints: dict) -> list[dict]:
    """根据当前约束生成预设调整选项按钮。"""
    buttons = []

    # 放宽类按钮
    if "CRI_max" in constraints:
        v = constraints["CRI_max"]
        buttons.append({"label": f"放宽 CRI 上限（{v} → {v + 2}）",
                        "action": "__AGENT:adjust:CRI_max_up2__", "style": "primary"})
        buttons.append({"label": f"大幅放宽 CRI 上限（{v} → {v + 5}）",
                        "action": "__AGENT:adjust:CRI_max_up5__", "style": "default"})
    if "CSR_min" in constraints:
        v = constraints["CSR_min"]
        buttons.append({"label": f"降低 CSR 要求（{v} → {v - 2}）",
                        "action": "__AGENT:adjust:CSR_min_down2__", "style": "primary"})
        buttons.append({"label": f"大幅降低 CSR 要求（{v} → {v - 5}）",
                        "action": "__AGENT:adjust:CSR_min_down5__", "style": "default"})
    if "M10_max" in constraints:
        v = constraints["M10_max"]
        buttons.append({"label": f"放宽 M10 上限（{v} → {v + 1}）",
                        "action": "__AGENT:adjust:M10_max_up1__", "style": "default"})
    if "M25_min" in constraints:
        v = constraints["M25_min"]
        buttons.append({"label": f"降低 M25 要求（{v} → {v - 2}）",
                        "action": "__AGENT:adjust:M25_min_down2__", "style": "default"})
    if "Ad_max" in constraints:
        v = constraints["Ad_max"]
        buttons.append({"label": f"放宽灰分上限（{v} → {v + 1}）",
                        "action": "__AGENT:adjust:Ad_max_up1__", "style": "default"})

    # 收紧类按钮（用户可能想提高质量要求）
    if "CRI_max" in constraints:
        v = constraints["CRI_max"]
        if v > 20:
            buttons.append({"label": f"收紧 CRI 上限（{v} → {v - 2}）",
                            "action": "__AGENT:adjust:CRI_max_down2__", "style": "default"})
    if "CSR_min" in constraints:
        v = constraints["CSR_min"]
        buttons.append({"label": f"提高 CSR 要求（{v} → {v + 2}）",
                        "action": "__AGENT:adjust:CSR_min_up2__", "style": "default"})

    # 新增约束按钮（当前没有的）
    if "CRI_max" not in constraints:
        buttons.append({"label": "新增 CRI 上限 ≤ 30",
                        "action": "__AGENT:adjust:add_CRI_max_30__", "style": "default"})
    if "CSR_min" not in constraints:
        buttons.append({"label": "新增 CSR 下限 ≥ 60",
                        "action": "__AGENT:adjust:add_CSR_min_60__", "style": "default"})
    if "Ad_max" not in constraints:
        buttons.append({"label": "新增灰分上限 ≤ 13",
                        "action": "__AGENT:adjust:add_Ad_max_13__", "style": "default"})

    # 移除全部约束
    if constraints:
        buttons.append({"label": "🗑️ 移除所有约束，纯成本优化",
                        "action": "__AGENT:adjust:clear_all__", "style": "danger"})

    return buttons


def _apply_adjustment(constraints: dict, adjust_key: str) -> dict:
    """根据调整 key 修改约束并返回新约束。"""
    c = dict(constraints)  # 浅拷贝

    adjustments = {
        "CRI_max_up2":    lambda: c.update(CRI_max=c.get("CRI_max", 30) + 2),
        "CRI_max_up5":    lambda: c.update(CRI_max=c.get("CRI_max", 30) + 5),
        "CRI_max_down2":  lambda: c.update(CRI_max=c.get("CRI_max", 30) - 2),
        "CSR_min_down2":  lambda: c.update(CSR_min=c.get("CSR_min", 60) - 2),
        "CSR_min_down5":  lambda: c.update(CSR_min=c.get("CSR_min", 60) - 5),
        "CSR_min_up2":    lambda: c.update(CSR_min=c.get("CSR_min", 60) + 2),
        "M10_max_up1":    lambda: c.update(M10_max=c.get("M10_max", 8) + 1),
        "M25_min_down2":  lambda: c.update(M25_min=c.get("M25_min", 85) - 2),
        "Ad_max_up1":     lambda: c.update(Ad_max=c.get("Ad_max", 13) + 1),
        "add_CRI_max_30": lambda: c.update(CRI_max=30),
        "add_CSR_min_60": lambda: c.update(CSR_min=60),
        "add_Ad_max_13":  lambda: c.update(Ad_max=13),
        "clear_all":      lambda: c.clear(),
    }

    fn = adjustments.get(adjust_key)
    if fn:
        fn()
    return c


# ── 进度条辅助 ───────────────────────────────────────────────────

class ProgressTracker:
    """进度条状态管理器。"""

    def __init__(self):
        self.steps: list[dict] = []

    def add(self, text: str, pct: int = 0) -> None:
        self.steps.append({'text': text, 'done': False, 'pct': pct, 'details': []})

    def detail(self, text: str) -> None:
        if self.steps:
            self.steps[-1].setdefault('details', []).append(text)

    def finish(self, text: str = None, pct: int = None) -> None:
        if self.steps:
            self.steps[-1]['done'] = True
            if text:
                self.steps[-1]['text'] = text
            if pct is not None:
                self.steps[-1]['pct'] = pct

    def html(self) -> str:
        lines = ['<div class="pipeline-progress">']
        for step in self.steps:
            icon = '✅' if step.get('done') else '⏳'
            lines.append(f'<div class="progress-step">{icon} {step["text"]}')
            details = step.get('details', [])
            if details:
                lines.append(f'<details class="agent-details">')
                lines.append(f'<summary>查看详情 ({len(details)} 条记录)</summary>')
                lines.append(f'<div class="agent-details-content">')
                for d in details:
                    lines.append(f'<div class="agent-detail-item">{d}</div>')
                lines.append(f'</div></details>')
            lines.append(f'</div>')
        pct = self.steps[-1].get('pct', 0) if self.steps else 0
        is_complete = pct >= 100
        bar_class = 'progress-bar-complete' if is_complete else ''
        lines.append(f'<div class="progress-bar-wrap">')
        lines.append(f'<div class="progress-bar-fill {bar_class}" style="width:{pct}%"></div>')
        lines.append(f'</div>')
        if is_complete:
            lines.append(f'<div class="progress-pct-done">✅ 完成</div>')
        else:
            lines.append(f'<div class="progress-pct">{pct}%</div>')
        lines.append('</div>\n\n')
        return ''.join(lines)


# ══════════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════════

async def process_question(question: str, session_id: str = "") -> AsyncGenerator[str, None]:
    """
    多智能体 Pipeline 主入口（支持交互式暂停/恢复）。
    """
    # 检查是否是 Agent 交互指令（用户点击了按钮）
    if state.is_agent_command(question):
        async for piece in _handle_agent_command(question, session_id):
            yield piece
        return

    p = ProgressTracker()

    # ── Step 1: 调度员分类 ─────────────────────────────────────
    p.add("调度员：正在分析问题类型…", pct=5)
    p.detail(f'<span class="agent-name">调度员</span> 收到用户问题："{question[:60]}{"…" if len(question)>60 else ""}"')
    p.detail(f'<span class="agent-name">调度员</span> <span class="tool-call">调用 Skill: classify_question()</span>')
    yield p.html()
    await asyncio.sleep(0)

    try:
        question_type = classify_question(question)
    except Exception as e:
        yield f"调度员分类异常: {e}"
        return

    type_labels = {
        "optimization": "配煤优化", "data_management": "数据管理",
        "factual": "事实查询", "process": "工艺流程",
        "comparison": "对比分析", "causal": "因果推理",
        "recommendation": "方案推荐",
    }
    label = type_labels.get(question_type, question_type)
    p.detail(f'<span class="agent-name">调度员</span> <span class="tool-result">分类结果: {label}</span>')
    p.finish(f"问题类型：{label}", pct=10)

    # ══ 路由 A: 配煤优化（交互式） ══════════════════════════════
    if question_type == "optimization":
        async for piece in _optimization_step1(question, session_id, p):
            yield piece
        return

    # ══ 路由 A2: 数据管理 ═══════════════════════════════════════
    if question_type == "data_management":
        async for piece in _data_management(question, session_id, p):
            yield piece
        return

    # ══ 路由 B: 闲聊 ════════════════════════════════════════════
    if not needs_rag(question_type):
        yield "\r\n"
        async for chunk in _simple_chat(question):
            yield chunk
        return

    # ══ 路由 C: 知识问答 ════════════════════════════════════════
    async for piece in _knowledge_qa(question, question_type, label, p):
        yield piece


# ══════════════════════════════════════════════════════════════════
# 配煤优化：交互式多步骤
# ══════════════════════════════════════════════════════════════════

async def _optimization_step1(question: str, session_id: str, p: ProgressTracker):
    """Step 1: 提取约束 → 展示给用户确认。"""
    p.add("调度员：正在分析配煤需求…", pct=15)
    p.detail(f'<span class="agent-name">调度员</span> <span class="tool-call">调用 Skill: extract_constraints()</span> 提取约束条件')
    yield p.html()
    await asyncio.sleep(0)

    constraints = await asyncio.to_thread(extract_constraints, question)
    coal_props = await asyncio.to_thread(get_coal_props)
    coal_names = list(coal_props.keys())

    p.detail(f'<span class="agent-name">调度员</span> <span class="tool-result">约束条件: {json.dumps(constraints, ensure_ascii=False)}</span>')
    p.detail(f'<span class="agent-name">调度员</span> <span class="tool-result">可用煤种: {len(coal_names)} 种</span>')
    p.finish("调度员：需求分析完成", pct=20)
    yield p.html()

    # 格式化约束条件展示
    constraint_display = []
    label_map = {
        "CRI_min": "CRI 下限", "CRI_max": "CRI 上限",
        "CSR_min": "CSR 下限", "CSR_max": "CSR 上限",
        "M10_min": "M10 下限", "M10_max": "M10 上限",
        "M25_min": "M25 下限", "M25_max": "M25 上限",
        "Vdaf_max": "挥发分上限", "G_min": "粘结指数下限", "Ad_max": "灰分上限",
    }
    for k, v in constraints.items():
        name = label_map.get(k, k)
        constraint_display.append(f"- **{name}：** {v}")
    if not constraint_display:
        constraint_display.append("- （未检测到明确约束，将使用默认参数优化）")

    # 生成煤样数据可视化
    p.add("调度员：正在生成煤样数据报表…", pct=25)
    yield p.html()
    await asyncio.sleep(0)

    from .skills.coal_charts import generate_overview_chart_data
    rows = await asyncio.to_thread(get_all_coals)
    chart_descriptors = generate_overview_chart_data(rows)

    p.finish("调度员：数据报表生成完成", pct=30)
    yield p.html()

    # 煤样统计摘要
    import numpy as np
    cri_vals = [float(r.get("coke_CRI") or 0) for r in rows if r.get("coke_CRI")]
    csr_vals = [float(r.get("coke_CSR") or 0) for r in rows if r.get("coke_CSR")]
    ad_vals = [float(r.get("coal_ad") or 0) for r in rows if r.get("coal_ad")]

    msg = (
        f"我分析了你的需求，以下是我理解到的信息：\n\n"
        f"**约束条件：**\n"
        f"{''.join(c + chr(10) for c in constraint_display)}\n"
        f"**煤样数据库概况：** 共 {len(rows)} 条煤样\n"
        f"- CRI 范围：{min(cri_vals):.1f} ~ {max(cri_vals):.1f}，均值 {np.mean(cri_vals):.1f}\n"
        f"- CSR 范围：{min(csr_vals):.1f} ~ {max(csr_vals):.1f}，均值 {np.mean(csr_vals):.1f}\n"
        f"- 灰分 Ad 范围：{min(ad_vals):.1f} ~ {max(ad_vals):.1f}，均值 {np.mean(ad_vals):.1f}\n\n"
    )

    yield _agent_message("调度员", msg)

    # 输出图表（ECharts 前端渲染）
    for cd in chart_descriptors:
        yield f'\n\n<!--ECHART:{json.dumps(cd, ensure_ascii=False)}-->\n\n'

    # 下载链接
    yield '\n\n<a href="http://127.0.0.1:8000/download_coals/" target="_blank" '
    yield 'style="display:inline-block;padding:8px 16px;background:#1F2937;color:#38BDF8;'
    yield 'border-radius:8px;text-decoration:none;font-size:13px;border:1px solid #334155;">'
    yield '📥 下载完整煤样数据 (Excel)</a>\n\n'

    confirm_msg = (
        f"确认后，**配煤工程师** 将生成 3 个方案（成本最优 / 质量最优 / 均衡），"
        f"**质量分析师** 使用 RF + CNN 双模型预测各方案炼焦后的焦炭质量。\n\n"
        f"确认开始，还是需要补充条件？"
    )

    # 保存状态
    state.save(session_id, {
        "stage": "confirm_constraints",
        "question": question,
        "constraints": constraints,
        "coal_names": coal_names,
    })

    yield _agent_message("调度员", confirm_msg, [
        {"label": "确认，开始优化", "action": "__AGENT:confirm_blend__", "style": "primary"},
        {"label": "我要补充条件", "action": "__AGENT:add_constraints__", "style": "default"},
    ])


async def _optimization_step2_generate(session_id: str, p: ProgressTracker,
                                       is_retry: bool = False, adjustment_hint: dict = None):
    """Step 2: 配煤工程师生成方案 → 质量分析师多模型评估 → 暂停让用户决定。"""
    s = state.load(session_id)
    if not s:
        yield "会话状态过期，请重新提问。"
        return

    constraints = s["constraints"]
    coal_names = s["coal_names"]
    question = s["question"]
    round_num = s.get("round_num", 0) + 1
    coal_props = await asyncio.to_thread(get_coal_props)

    # ── 配煤工程师生成方案 ──
    if not is_retry:
        p.add("配煤工程师：正在生成配煤方案…", pct=25)
        p.detail(f'<span class="agent-name">配煤工程师</span> <span class="tool-call">调用 Skill: run_multi_strategy_blend()</span>')
    else:
        p.add(f"配煤工程师：根据质量分析师反馈调整方案（第 {round_num} 轮）…", pct=30)
        p.detail(f'<span class="agent-name">配煤工程师</span> <span class="tool-call">第 {round_num} 轮：根据反馈调整配煤比例</span>')
    yield p.html()
    await asyncio.sleep(0)

    if not is_retry or adjustment_hint is None:
        plans = await asyncio.to_thread(run_multi_strategy_blend, coal_names, constraints)
    else:
        plans = await asyncio.to_thread(
            optimize_with_feedback, coal_props, coal_names, constraints, adjustment_hint
        )

    if not plans:
        p.finish("配煤工程师：未找到可行方案", pct=50)
        yield p.html()
        yield _agent_message("配煤工程师", "抱歉，当前约束条件下未找到可行的配煤方案。建议放宽约束或更换煤种。", [
            {"label": "放宽约束重试", "action": "__AGENT:add_constraints__", "style": "primary"},
        ])
        return

    p.detail(f'<span class="agent-name">配煤工程师</span> <span class="tool-result">生成了 {len(plans)} 个方案</span>')
    p.finish(f"配煤工程师：生成了 {len(plans)} 个方案", pct=45)
    yield p.html()
    await asyncio.sleep(0)

    # ── 质量分析师多模型评估 ──
    models_list = quality_agent.available_models()
    models_str = ", ".join(models_list)
    p.add(f"质量分析师：多模型竞赛评估中…", pct=55)
    p.detail(f'<span class="agent-name">质量分析师</span> <span class="tool-call">启动多模型竞赛: {models_str}</span>')
    yield p.html()
    await asyncio.sleep(0)

    evaluated = []
    any_passed = False
    worst_hint = None

    for plan in plans:
        result = await asyncio.to_thread(
            quality_agent.run_multi_model,
            blend_result=plan, coal_props=coal_props, constraints=constraints,
        )
        evaluated.append({
            "plan": plan,
            "multi_model": result,
            "prediction": result["prediction"],
            "evaluation": {"passed": result["passed"], "feedback": result["feedback"]},
            "all_predictions": result["all_predictions"],
            "recommended_model": result["recommended_model"],
            "model_comparison": result["model_comparison"],
        })
        if result["passed"]:
            any_passed = True
        elif result.get("adjustment_hint"):
            worst_hint = result["adjustment_hint"]

    passed_count = sum(1 for e in evaluated if e["evaluation"]["passed"])
    p.detail(f'<span class="agent-name">质量分析师</span> <span class="tool-result">多模型评估完成: {passed_count}/{len(evaluated)} 达标</span>')
    p.finish(f"质量分析师：焦炭质量评估完成，{passed_count}/{len(evaluated)} 达标", pct=75)
    yield p.html()

    # ── 展示方案卡片 ──
    yield "\n---\n\n## 配煤方案对比\n\n"
    for ep in evaluated:
        yield _format_plan_card_v2(ep)

    # ── 保存状态 + 生成按钮 ──
    state.save(session_id, {
        "stage": "pick_plan",
        "question": question,
        "constraints": constraints,
        "coal_names": coal_names,
        "evaluated": evaluated,
        "round_num": round_num,
        "adjustment_hint": worst_hint,  # 存起来供"自动调整"使用
    })

    buttons = []
    for ep in evaluated:
        plan = ep["plan"]
        tag = plan.get("strategy", "?")
        name = plan.get("strategy_name", "方案")
        status = "✅" if ep["evaluation"]["passed"] else "⚠️"
        buttons.append({
            "label": f"{status} 选择 {tag}: {name}",
            "action": f"__AGENT:pick_plan:{tag}__",
            "style": "primary" if ep["evaluation"]["passed"] else "default",
        })

    # 不达标时提供两种调整方式
    if not any_passed and worst_hint and round_num < 3:
        # 生成反馈摘要
        hint_parts = []
        if worst_hint.get("cri_gap"):
            hint_parts.append(f"CRI 超标 {worst_hint['cri_gap']:.1f}")
        if worst_hint.get("csr_gap"):
            hint_parts.append(f"CSR 不足 {worst_hint['csr_gap']:.1f}")
        hint_summary = "；".join(hint_parts) if hint_parts else "质量指标不达标"

        buttons.append({
            "label": f"🔄 让质量分析师自动调整再试（{hint_summary}）",
            "action": "__AGENT:auto_retry__",
            "style": "primary",
        })

    buttons.append({"label": "我自己调整条件", "action": "__AGENT:add_constraints__", "style": "default"})

    round_info = f"（第 {round_num} 轮）" if round_num > 1 else ""
    yield _agent_message("调度员",
        f"质量分析师已完成多模型竞赛评估{round_info}。"
        f"每个方案使用 {len(models_list)} 个模型（{models_str}）预测并选出推荐模型。"
        f"\n\n请选择方案，或选择调整方式。",
        buttons)


async def _optimization_step3_finalize(session_id: str, chosen_strategy: str, p: ProgressTracker):
    """Step 3: 用户选定方案 → 生成最终报告。"""
    s = state.load(session_id)
    if not s:
        yield "会话状态过期，请重新提问。"
        return

    evaluated = s.get("evaluated", [])
    question = s["question"]

    chosen = None
    for ep in evaluated:
        if ep["plan"].get("strategy") == chosen_strategy:
            chosen = ep
            break

    if not chosen:
        yield f"未找到方案 {chosen_strategy}，请重新选择。"
        return

    plan = chosen["plan"]
    prediction = chosen["prediction"]
    evaluation = chosen["evaluation"]

    p.add("报告撰写员：正在生成最终报告…", pct=85)
    p.detail(f'<span class="agent-name">报告撰写员</span> 用户选择了方案 {chosen_strategy}: {plan.get("strategy_name", "?")}')
    yield p.html()
    await asyncio.sleep(0)

    # 生成详细报告
    from .coal_agent.agent_runner import _generate_summary
    card_text = _format_plan_card_v2(chosen) if "all_predictions" in chosen else _format_plan_card(plan, prediction, evaluation)
    summary = await asyncio.to_thread(_generate_summary, question, card_text)

    p.finish("报告撰写员：最终报告生成完成", pct=100)
    yield p.html()

    yield "\n---\n\n## 最终推荐方案\n\n"
    yield card_text
    if summary:
        yield "\n---\n\n## 智能分析\n\n"
        yield summary

    yield _agent_message("调度员", "方案已生成。你可以继续提问，或基于此方案进一步调整。", [
        {"label": "基于此方案微调", "action": "__AGENT:add_constraints__", "style": "default"},
    ])

    state.clear(session_id)


# ── Agent 指令处理 ────────────────────────────────────────────────

async def _handle_agent_command(command: str, session_id: str):
    """处理用户点击 Agent 按钮发来的指令。"""
    p = ProgressTracker()

    if command == "__AGENT:confirm_blend__":
        async for piece in _optimization_step2_generate(session_id, p):
            yield piece

    elif command.startswith("__AGENT:pick_plan:"):
        strategy = command.replace("__AGENT:pick_plan:", "").replace("__", "")
        async for piece in _optimization_step3_finalize(session_id, strategy, p):
            yield piece

    elif command == "__AGENT:add_constraints__":
        state_data = state.load(session_id)
        old_constraints = state_data.get("constraints", {}) if state_data else {}
        # 根据当前约束生成可点击的调整选项
        buttons = _build_adjustment_buttons(old_constraints)
        buttons.append({"label": "✏️ 我自己输入条件", "action": "__AGENT:free_input__", "style": "default"})
        current_desc = _describe_constraints(old_constraints)
        yield _agent_message(
            "调度员",
            f"当前约束：{current_desc}\n\n请选择调整方向：",
            buttons,
        )

    elif command == "__AGENT:free_input__":
        # 自由输入模式
        state_data = state.load(session_id)
        old_constraints = state_data.get("constraints", {}) if state_data else {}
        current_desc = _describe_constraints(old_constraints)
        yield _agent_message(
            "调度员",
            f"当前约束：{current_desc}\n\n"
            f"请直接输入你想要的调整，例如：\n"
            f"- \"CRI不超过25\"\n"
            f"- \"灰分控制在12以内\"\n\n"
            f"输入后我会重新分析并优化。"
        )
        state.clear(session_id)

    elif command.startswith("__AGENT:adjust:"):
        # 点击预设调整按钮 → 修改约束 → 重新优化
        adjust_key = command.replace("__AGENT:adjust:", "").replace("__", "")
        state_data = state.load(session_id)
        if not state_data:
            yield "操作已过期，请重新提问。"
            return
        old_constraints = state_data.get("constraints", {})
        new_constraints = _apply_adjustment(old_constraints, adjust_key)
        state_data["constraints"] = new_constraints
        state_data["round_num"] = 0  # 重新开始计数
        state.save(session_id, state_data)
        new_desc = _describe_constraints(new_constraints)
        yield _agent_message("调度员", f"已调整约束为：{new_desc}，正在重新优化…")
        async for piece in _optimization_step2_generate(session_id, p):
            yield piece

    elif command == "__AGENT:auto_retry__":
        # 质量分析师自动调整再试
        state_data = state.load(session_id)
        if not state_data or state_data.get("stage") != "pick_plan":
            yield "操作已过期，请重新提问。"
            return
        hint = state_data.get("adjustment_hint")
        round_num = state_data.get("round_num", 1)
        if not hint:
            yield _agent_message("调度员", "没有可用的调整建议，请手动调整条件。")
            return
        if round_num >= 3:
            yield _agent_message("调度员", "已达到最大调整轮次（3轮），请手动调整条件或选择当前方案。")
            return
        async for piece in _optimization_step2_generate(
            session_id, p, is_retry=True, adjustment_hint=hint
        ):
            yield piece

    # ── 数据管理确认 ──
    elif command == "__AGENT:confirm_add_coal__":
        state_data = state.load(session_id)
        if not state_data or state_data.get("stage") != "confirm_add_coal":
            yield "操作已过期，请重新输入。"
            return
        coals = state_data.get("coals", [])
        result = await asyncio.to_thread(batch_add_coals, coals)
        state.clear(session_id)
        # 清除煤样缓存
        import deepcoke.skills.coal_skills as cs
        cs._coal_cache = None
        ok = result["success"]
        fail = result["failed"]
        msg = f"**录入完成！**\n\n"
        if ok:
            msg += f"✅ 成功录入 {len(ok)} 条：{', '.join(ok)}\n\n"
        if fail:
            msg += f"⚠️ 失败 {len(fail)} 条：\n"
            for f_item in fail:
                msg += f"- {f_item['coal_name']}：{f_item['error']}\n"

        # CNN 自动预测（对有完整特征的煤样）
        try:
            from .skills.cnn_predict import predict_batch, FEATURE_NAMES
            predictable = [c for c in coals
                           if c.get("coal_name") in ok
                           and all(c.get(f) for f in FEATURE_NAMES)]
            if predictable:
                preds = await asyncio.to_thread(predict_batch, predictable)
                msg += f"\n**CNN 焦炭质量预测：**\n\n"
                msg += "| 煤样 | 预测CRI | 预测CSR |\n|------|---------|--------|\n"
                for pr in preds:
                    if "error" not in pr:
                        msg += f"| {pr['coal_name']} | {pr['CRI']} | {pr['CSR']} |\n"
                    else:
                        msg += f"| {pr['coal_name']} | {pr['error']} | - |\n"
        except Exception as e:
            logger.warning(f"CNN 预测跳过: {e}")

        # 显示最新煤样列表
        rows = await asyncio.to_thread(get_all_coals)
        msg += f"\n当前数据库共 **{len(rows)}** 条煤样。"
        yield _agent_message("数据管理员", msg)

    elif command == "__AGENT:confirm_delete_coal__":
        state_data = state.load(session_id)
        if not state_data or state_data.get("stage") != "confirm_delete_coal":
            yield "操作已过期，请重新输入。"
            return
        names = state_data.get("names", [])
        state.clear(session_id)
        import deepcoke.skills.coal_skills as cs
        cs._coal_cache = None
        ok_list, fail_list = [], []
        for name in names:
            r = await asyncio.to_thread(delete_coal, name)
            if r["ok"]:
                ok_list.append(name)
            else:
                fail_list.append(f"{name}（{r['error']}）")
        msg = "**删除完成！**\n\n"
        if ok_list:
            msg += f"✅ 已删除：{', '.join(ok_list)}\n"
        if fail_list:
            msg += f"⚠️ 失败：{', '.join(fail_list)}\n"
        rows = await asyncio.to_thread(get_all_coals)
        msg += f"\n当前数据库共 **{len(rows)}** 条煤样。"
        yield _agent_message("数据管理员", msg)

    elif command == "__AGENT:confirm_update_coal__":
        state_data = state.load(session_id)
        if not state_data or state_data.get("stage") != "confirm_update_coal":
            yield "操作已过期，请重新输入。"
            return
        name = state_data.get("name", "")
        fields = state_data.get("fields", {})
        state.clear(session_id)
        import deepcoke.skills.coal_skills as cs
        cs._coal_cache = None
        r = await asyncio.to_thread(update_coal, name, fields)
        if r["ok"]:
            msg = f"✅ 煤样「{name}」更新成功！更新字段：{', '.join(r['updated'])}"
        else:
            msg = f"⚠️ 更新失败：{r['error']}"
        yield _agent_message("数据管理员", msg)

    elif command == "__AGENT:cancel_data__":
        state.clear(session_id)
        yield _agent_message("数据管理员", "已取消操作。")

    else:
        yield "未知的操作指令，请重新提问。"
        state.clear(session_id)


# ── 格式化工具 ───────────────────────────────────────────────────

def _format_plan_card(plan: dict, prediction: dict, evaluation: dict,
                      cnn_prediction: dict = None) -> str:
    """将单个方案格式化为 Markdown 卡片（含 RF + CNN 双模型预测）。"""
    strategy = plan.get("strategy", "?")
    name = plan.get("strategy_name", "未知策略")
    passed = evaluation.get("passed", False)
    status = "✅ 达标" if passed else "⚠️ 不达标"

    hoppers = [h for h in plan.get("hoppers", []) if h["ratio"] > 0.1]
    cost = plan.get("cost_per_ton", 0)

    lines = [f"### 方案 {strategy}: {name} {status}\n"]
    lines.append("| 煤种 | 配比(%) | 重量(g) |")
    lines.append("|------|---------|---------|")
    for h in hoppers:
        lines.append(f"| {h['coal']} | {h['ratio']} | {h['weight_g']} |")
    lines.append("")

    if cost > 0:
        lines.append(f"- **吨煤成本：** {cost:.1f} 元")

    # 双模型预测结果
    rf_cri = prediction.get("CRI")
    rf_csr = prediction.get("CSR")
    cnn_cri = cnn_prediction.get("CRI") if cnn_prediction else None
    cnn_csr = cnn_prediction.get("CSR") if cnn_prediction else None

    lines.append("")
    lines.append("| 预测模型 | CRI | CSR |")
    lines.append("|----------|-----|-----|")
    if rf_cri is not None and rf_csr is not None:
        lines.append(f"| RF（随机森林） | {rf_cri:.2f} | {rf_csr:.2f} |")
    if cnn_cri is not None and cnn_csr is not None:
        lines.append(f"| CNN（卷积神经网络） | {cnn_cri:.2f} | {cnn_csr:.2f} |")

    if not passed and evaluation.get("feedback"):
        lines.append(f"\n- **评估：** {evaluation['feedback']}")
    lines.append("")
    return "\n".join(lines)


def _format_plan_card_v2(ep: dict) -> str:
    """将方案格式化为 Markdown 卡片（含多模型竞赛结果）。"""
    plan = ep["plan"]
    strategy = plan.get("strategy", "?")
    name = plan.get("strategy_name", "未知策略")
    passed = ep["evaluation"].get("passed", False)
    status = "✅ 达标" if passed else "⚠️ 不达标"

    hoppers = [h for h in plan.get("hoppers", []) if h["ratio"] > 0.1]
    cost = plan.get("cost_per_ton", 0)

    lines = [f"### 方案 {strategy}: {name} {status}\n"]
    lines.append("| 煤种 | 配比(%) | 重量(g) |")
    lines.append("|------|---------|---------|")
    for h in hoppers:
        lines.append(f"| {h['coal']} | {h['ratio']} | {h['weight_g']} |")
    lines.append("")

    if cost > 0:
        lines.append(f"- **吨煤成本：** {cost:.1f} 元")

    # 多模型预测对比表
    all_preds = ep.get("all_predictions", {})
    recommended = ep.get("recommended_model", "")

    if all_preds:
        lines.append("")
        lines.append("**多模型焦炭质量预测：**\n")
        lines.append("| 预测模型 | CRI | CSR | 推荐 |")
        lines.append("|----------|-----|-----|------|")
        for m, pred in all_preds.items():
            cri = pred.get("CRI")
            csr = pred.get("CSR")
            if cri is not None and csr is not None:
                mark = "⭐" if m == recommended else ""
                lines.append(f"| {m} | {cri:.2f} | {csr:.2f} | {mark} |")
        if recommended:
            lines.append(f"\n> 推荐模型：**{recommended}**（保守估计策略）")
    else:
        # fallback 到旧格式
        pred = ep.get("prediction", {})
        if pred.get("CRI") is not None:
            lines.append(f"\n- **预测 CRI:** {pred['CRI']:.2f}")
            lines.append(f"- **预测 CSR:** {pred.get('CSR', 0):.2f}")

    if not passed and ep["evaluation"].get("feedback"):
        lines.append(f"\n- **评估：** {ep['evaluation']['feedback']}")
    lines.append("")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# 知识问答路线（保持原逻辑）
# ══════════════════════════════════════════════════════════════════

async def _knowledge_qa(question: str, question_type: str, label: str, p: ProgressTracker):
    """知识问答：文献研究员 + 推理专家 + 报告撰写员。"""
    p.detail(f'<span class="agent-name">调度员</span> <span class="agent-decision">路由到知识问答链: 文献研究员 → 推理专家 → 报告撰写员</span>')

    # ── 文献研究员 ─────────────────────────────────────────────
    p.add("文献研究员：正在检索…", pct=15)
    p.detail(f'<span class="agent-name">文献研究员</span> <span class="tool-call">调用 Skill: translate_and_extract()</span> 提取关键词')
    p.detail(f'<span class="agent-name">文献研究员</span> <span class="tool-call">调用 Skill: search_literature()</span> 检索 ChromaDB 文献库')
    p.detail(f'<span class="agent-name">文献研究员</span> <span class="tool-call">调用 Skill: search_knowledge_graph()</span> 查询 Neo4j 知识图谱')
    yield p.html()
    await asyncio.sleep(0)

    research_result = await asyncio.to_thread(
        research_agent.run, question=question, on_progress=lambda desc: None,
    )

    chunks = research_result["chunks"]
    kg_context = research_result["kg_context"]
    key_concepts = research_result["key_concepts"]

    p.detail(f'<span class="agent-name">文献研究员</span> <span class="tool-result">关键词: {", ".join(key_concepts[:5])}</span>')
    p.detail(f'<span class="agent-name">文献研究员</span> <span class="tool-result">命中 {len(chunks)} 条文献</span>')
    if chunks:
        top = chunks[0]
        score_pct = f"{top.score:.0%}" if top.score <= 1 else f"{top.score:.2f}"
        p.detail(f'<span class="agent-name">文献研究员</span> <span class="tool-result">最佳匹配: 「{top.title[:40]}」相关度 {score_pct}</span>')
    if kg_context:
        kg_lines = kg_context.strip().split("\n")
        p.detail(f'<span class="agent-name">文献研究员</span> <span class="tool-result">知识图谱: {len(kg_lines)} 条关联</span>')

    p.finish(f"文献研究员：检索到 {len(chunks)} 条文献", pct=45)
    yield p.html()
    await asyncio.sleep(0)

    # ── 推理专家 ───────────────────────────────────────────────
    reasoning_trace = ""
    if is_complex(question_type) and chunks:
        p.add("推理专家：正在深度推理…", pct=50)
        p.detail(f'<span class="agent-name">推理专家</span> <span class="agent-decision">启动 ESCARGOT 深度推理</span>')
        yield p.html()
        await asyncio.sleep(0)

        reasoning_result = await asyncio.to_thread(
            reasoning_agent.run, question=question, timeout=60, on_progress=lambda desc: None,
        )
        reasoning_trace = reasoning_result["reasoning_trace"]
        if reasoning_result["success"]:
            p.finish("推理专家：深度推理完成", pct=80)
        else:
            p.finish("推理专家：跳过（超时）", pct=80)
        yield p.html()
        await asyncio.sleep(0)

    # ── 推理过程展示块 ─────────────────────────────────────────
    thinking_block = _build_thinking_block(question_type, chunks, kg_context, reasoning_trace)
    if thinking_block:
        yield thinking_block
        await asyncio.sleep(0)

    # ── 报告撰写员 ─────────────────────────────────────────────
    p.add("报告撰写员：正在生成回答…", pct=85)
    yield p.html()
    await asyncio.sleep(0)

    try:
        for piece in report_agent.run_stream(
            question=question, chunks=chunks,
            kg_context=kg_context, reasoning_trace=reasoning_trace,
        ):
            yield piece
            await asyncio.sleep(0)
    except Exception as e:
        yield f"\n\n报告生成异常: {e}"
        return

    p.finish("报告撰写员：回答生成完成", pct=100)


# ── 辅助函数 ─────────────────────────────────────────────────────

def _build_thinking_block(question_type, chunks, kg_context, reasoning_trace):
    lines = ["> **推理过程**", ">"]
    type_labels = {"factual": "事实查询", "process": "工艺流程", "comparison": "对比分析", "causal": "因果推理", "recommendation": "方案推荐"}
    lines.append(f"> **问题类型：** {type_labels.get(question_type, question_type)}")
    lines.append(">")
    if chunks:
        lines.append(f"> **检索到 {len(chunks)} 条相关文献片段：**")
        for i, c in enumerate(chunks[:5], 1):
            score_pct = f"{c.score:.0%}" if c.score <= 1 else f"{c.score:.2f}"
            lines.append(f"> - [{i}] {c.title[:60]} ({c.year or '?'}) -- 相关度 {score_pct}")
        if len(chunks) > 5:
            lines.append(f"> - ... 及其他 {len(chunks) - 5} 条")
        lines.append(">")
    if kg_context:
        lines.append("> **知识图谱关联：**")
        for kg_line in kg_context.split("\n"):
            lines.append(f"> {kg_line}")
        lines.append(">")
    if reasoning_trace:
        lines.append("> **深度推理 (ESCARGOT)：**")
        for rt_line in reasoning_trace.split("\n"):
            lines.append(f"> {rt_line}")
        lines.append(">")
    lines.append("\n---\n\n")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# 数据管理：自然语言增删改查煤样
# ══════════════════════════════════════════════════════════════════

_DATA_EXTRACT_PROMPT = """你是煤样数据提取助手。从用户的自然语言中提取煤样数据操作。

支持的操作：
- add: 添加煤样（可批量）
- update: 更新煤样
- delete: 删除煤样
- query: 查询煤样
- predict: 用CNN预测煤样的焦炭质量（CRI/CSR），需要提供 coal_mad, coal_ad, coal_vdaf, coal_std, G, Y 六个特征

支持的字段：
- coal_name: 煤样名称（必须）
- coal_type: 煤种类型（如：气煤、肥煤、焦煤、瘦煤、1/3焦煤等）
- coal_price: 价格（元/吨）
- coal_mad: 水分 Mad (%)
- coal_ad: 灰分 Ad (%)
- coal_vdaf: 挥发分 Vdaf (%)
- coal_std: 全硫 St,d (%)
- G: 粘结指数
- X: 胶质层X值 (mm)
- Y: 胶质层Y值 (mm)
- coke_CRI: 焦炭反应性 CRI (%)
- coke_CSR: 焦炭反应后强度 CSR (%)
- coke_M10: 焦炭耐磨强度 M10 (%)
- coke_M25: 焦炭抗碎强度 M25 (%)
- coke_M40: 焦炭抗碎强度 M40 (%)

返回严格 JSON 格式（不要 markdown 包裹）：
{"action": "add/update/delete/query", "coals": [{"coal_name": "...", ...}]}

批量添加时 coals 数组包含多条。删除/查询时只需 coal_name。
如果用户没说具体操作，默认 "query"。"""


async def _data_management(question: str, session_id: str, p: ProgressTracker):
    """自然语言管理煤样数据库。"""
    import deepcoke.skills.coal_skills as cs

    p.add("数据管理员：正在解析指令…", pct=20)
    p.detail(f'<span class="agent-name">数据管理员</span> <span class="tool-call">调用 LLM 提取数据操作</span>')
    yield p.html()
    await asyncio.sleep(0)

    # 用 LLM 从自然语言提取结构化数据
    try:
        raw = await asyncio.to_thread(
            chat_json,
            [{"role": "system", "content": _DATA_EXTRACT_PROMPT},
             {"role": "user", "content": question}],
            temperature=0.0,
        )
        # 清理可能的 markdown 包裹
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
        parsed = json.loads(raw)
    except Exception as e:
        logger.error(f"数据提取失败: {e}")
        yield f"\n\n抱歉，无法解析您的数据操作指令。请用更明确的表述，例如：\n\n"
        yield f"- 「添加一个煤样：名称=测试煤A，灰分=10，硫分=0.6，G=80，CRI=30，CSR=60」\n"
        yield f"- 「删除煤样 测试煤A」\n"
        yield f"- 「查看所有煤样」\n"
        return

    action = parsed.get("action", "query")
    coals = parsed.get("coals", [])

    p.detail(f'<span class="agent-name">数据管理员</span> <span class="tool-result">操作: {action}，涉及 {len(coals)} 条煤样</span>')
    p.finish("数据管理员：指令解析完成", pct=40)
    yield p.html()
    await asyncio.sleep(0)

    # ── 查询 ──
    if action == "query":
        from .skills.coal_charts import generate_overview_chart_data, generate_single_coal_chart_data

        if coals and isinstance(coals[0], dict) and coals[0].get("coal_name"):
            name = coals[0]["coal_name"]
            row = await asyncio.to_thread(get_coal_by_name, name)
            if row:
                yield f"\n\n**煤样「{name}」详情：**\n\n"
                yield _format_coal_table([row])
                # 生成雷达图（ECharts 前端渲染）
                cd = generate_single_coal_chart_data(row)
                if cd:
                    yield f'\n\n<!--ECHART:{json.dumps(cd, ensure_ascii=False)}-->\n\n'
            else:
                yield f"\n\n未找到煤样「{name}」。"
                rows = await asyncio.to_thread(get_all_coals)
                names = [r["coal_name"] for r in rows]
                yield f"当前数据库有 {len(names)} 条煤样：{', '.join(names)}\n"
        else:
            rows = await asyncio.to_thread(get_all_coals)
            yield f"\n\n**当前数据库共 {len(rows)} 条煤样：**\n\n"
            # 表格只显示前 30 条，避免太长
            yield _format_coal_table(rows[:30])
            if len(rows) > 30:
                yield f"\n> 表格仅显示前 30 条，共 {len(rows)} 条\n\n"
            # 生成总览图表（ECharts 前端渲染）
            chart_list = generate_overview_chart_data(rows)
            for cd in chart_list:
                yield f'\n\n<!--ECHART:{json.dumps(cd, ensure_ascii=False)}-->\n\n'
            p.finish("数据管理员：报表生成完成", pct=100)
            yield p.html()
            await asyncio.sleep(0)

            # 下载链接
            download_html = (
                '\n\n<a href="http://127.0.0.1:8000/download_coals/" target="_blank" '
                'style="display:inline-block;padding:8px 16px;background:#1F2937;color:#38BDF8;'
                'border-radius:8px;text-decoration:none;font-size:13px;border:1px solid #334155;">'
                '📥 下载完整煤样数据 (Excel)</a>\n\n'
            )
            logger.info(f"输出下载链接，长度: {len(download_html)}")
            yield download_html
        return

    # ── CNN 预测 ──
    if action == "predict":
        from .skills.cnn_predict import predict_batch, predict_from_coal_dict, FEATURE_NAMES, FEATURE_LABELS
        p.add("CNN预测员：正在运行模型…", pct=60)
        p.detail(f'<span class="agent-name">CNN预测员</span> <span class="tool-call">调用 CNN 模型预测 CRI/CSR</span>')
        yield p.html()
        await asyncio.sleep(0)

        if not coals:
            # 预测数据库中所有煤样
            rows = await asyncio.to_thread(get_all_coals)
            coals = rows

        preds = await asyncio.to_thread(predict_batch, coals)
        p.finish("CNN预测员：预测完成", pct=100)
        yield p.html()

        yield f"\n\n**CNN 焦炭质量预测结果：**\n\n"
        yield "| 煤样 | 预测CRI | 预测CSR | 状态 |\n|------|---------|--------|------|\n"
        for pr in preds:
            name = pr.get("coal_name", "?")
            if "error" in pr:
                yield f"| {name} | - | - | ⚠️ {pr['error']} |\n"
            else:
                yield f"| {name} | {pr['CRI']} | {pr['CSR']} | ✅ |\n"

        yield f"\n> 模型：CNN (2026.3.15)，输入特征：{', '.join(FEATURE_LABELS)}\n"
        return

    # ── 添加 ──
    if action == "add":
        if not coals:
            yield "\n\n没有检测到要添加的煤样数据，请提供煤样名称和指标。"
            return

        # 展示待添加数据，让用户确认
        yield _agent_message("数据管理员", "我解析到以下煤样数据，请确认是否录入：\n\n")
        yield _format_coal_table(coals)

        state.save(session_id, {
            "stage": "confirm_add_coal",
            "coals": coals,
        })

        yield _agent_buttons([
            {"label": f"确认录入 {len(coals)} 条", "action": "__AGENT:confirm_add_coal__", "style": "primary"},
            {"label": "取消", "action": "__AGENT:cancel_data__", "style": "default"},
        ])
        return

    # ── 删除 ──
    if action == "delete":
        if not coals:
            yield "\n\n没有检测到要删除的煤样名称。"
            return
        names = [c.get("coal_name", "?") for c in coals]
        state.save(session_id, {
            "stage": "confirm_delete_coal",
            "names": names,
        })
        yield _agent_message(
            "数据管理员",
            f"确认删除以下煤样？\n\n**{', '.join(names)}**\n\n⚠️ 删除操作不可恢复。",
            [
                {"label": f"确认删除", "action": "__AGENT:confirm_delete_coal__", "style": "primary"},
                {"label": "取消", "action": "__AGENT:cancel_data__", "style": "default"},
            ],
        )
        return

    # ── 更新 ──
    if action == "update":
        if not coals:
            yield "\n\n没有检测到要更新的煤样数据。"
            return
        coal = coals[0]
        name = coal.get("coal_name", "")
        fields = {k: v for k, v in coal.items() if k != "coal_name" and v is not None}
        if not name or not fields:
            yield "\n\n请提供要更新的煤样名称和具体字段。"
            return
        state.save(session_id, {
            "stage": "confirm_update_coal",
            "name": name,
            "fields": fields,
        })
        field_text = "\n".join(f"- **{k}**: {v}" for k, v in fields.items())
        yield _agent_message(
            "数据管理员",
            f"确认更新煤样「{name}」的以下字段？\n\n{field_text}",
            [
                {"label": "确认更新", "action": "__AGENT:confirm_update_coal__", "style": "primary"},
                {"label": "取消", "action": "__AGENT:cancel_data__", "style": "default"},
            ],
        )
        return

    yield f"\n\n不支持的操作类型：{action}"


def _format_coal_table(rows: list[dict]) -> str:
    """格式化煤样数据为 Markdown 表格。"""
    # 核心展示字段
    cols = [
        ("coal_name", "名称"), ("coal_type", "类型"), ("coal_price", "价格"),
        ("coal_ad", "灰分Ad"), ("coal_vdaf", "Vdaf"), ("coal_std", "硫分St,d"),
        ("G", "G值"), ("coke_CRI", "CRI"), ("coke_CSR", "CSR"),
        ("coke_M10", "M10"), ("coke_M25", "M25"),
    ]
    # 只显示有数据的列
    active_cols = []
    for key, label in cols:
        if any(r.get(key) is not None for r in rows):
            active_cols.append((key, label))

    header = "| " + " | ".join(l for _, l in active_cols) + " |"
    sep = "| " + " | ".join("---" for _ in active_cols) + " |"
    lines = [header, sep]
    for r in rows:
        vals = []
        for key, _ in active_cols:
            v = r.get(key, "")
            vals.append(str(v) if v is not None else "-")
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines) + "\n"


async def _simple_chat(question: str) -> AsyncGenerator[str, None]:
    from .llm_client import chat
    system_prompt = (
        "你是焦化大语言智能问答与分析系统DeepCoke，由苏州龙泰氢一能源科技有限公司研发。"
        "以下是对你输出的强制格式要求："
        "1. 任何数学公式一定要使用 $$ 公式 $$ 包裹\n"
        "2. 多行代码一定使用三重反引号 ``` 语言 来包裹\n"
        "3. 务必使用标准 Markdown 语法。\n"
        "4. 不要提供mermaid图"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]
    stream = chat(messages, stream=True)
    for chunk in stream:
        if not getattr(chunk, "choices", None):
            continue
        delta = chunk.choices[0].delta
        piece = getattr(delta, "content", None)
        if not piece:
            continue
        yield piece
        await asyncio.sleep(0)
