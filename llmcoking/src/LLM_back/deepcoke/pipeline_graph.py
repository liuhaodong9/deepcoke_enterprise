"""
DeepCoke 企业版 Pipeline — LangGraph StateGraph 实现
Phase 1: LangGraph 替换手写路由
Phase 2: Supervisor LLM 智能路由 + 多 agent 串行
Phase 3: 配煤优化反思循环（不达标自动调整重试）
"""
import logging
import json
import operator
import asyncio
from typing import Annotated, AsyncGenerator, Any
from typing_extensions import TypedDict

from langgraph.graph import StateGraph, START, END

from .supervisor import supervisor_decide, AGENT_DESCRIPTIONS
from .classifier.question_classifier import is_complex, needs_rag
from .agents import report_agent
from .skills.research_skills import translate_and_extract, search_literature, search_knowledge_graph
from .skills.reasoning_skills import deep_reasoning
from .coal_agent.agent_runner import run_agent as run_coal_agent, _generate_summary
from .coal_agent.coal_db import (
    get_all_coals, get_coal_by_name, add_coal, update_coal,
    delete_coal, batch_add_coals, CORE_FIELDS,
)
from .skills.coal_skills import get_coal_props, run_multi_strategy_blend, _coal_cache
from .coal_agent.blend_optimizer import optimize_with_feedback
from .skills.report_skills import extract_constraints
from .coal_agent import quality_agent
from .llm_client import chat_json
from . import pipeline_state as state  # 仍用于兼容旧的 agent command 检测

logger = logging.getLogger("deepcoke.pipeline")

# 反思循环最大轮次
MAX_REFLECT_ROUNDS = 3


# ══════════════════════════════════════════════════════════════════
# State 定义
# ══════════════════════════════════════════════════════════════════

class PipelineState(TypedDict):
    """企业版 LangGraph 流转状态。"""
    question: str
    session_id: str
    question_type: str
    # Supervisor 多 agent 计划（Phase 2）
    agent_plan: list[str]       # 有序 agent 列表，如 ["coal_price", "optimization"]
    agent_plan_idx: int         # 当前执行到第几个 agent（0-based）
    supervisor_reasoning: str   # supervisor 决策理由
    # 配煤优化相关
    constraints: dict
    coal_names: list[str]
    evaluated: list[dict]       # 多方案评估结果
    chosen_plan: dict
    prediction: dict
    round_num: int
    adjustment_hint: dict
    any_passed: bool            # Phase 3: 反思循环用
    # RAG 相关
    english_queries: list[str]
    key_concepts: list[str]
    chunks: list
    kg_context: str
    reasoning_trace: str
    # 交互恢复值（interrupt 返回的用户选择）
    user_action: str
    # 累计输出
    output: Annotated[list[str], operator.add]


# ══════════════════════════════════════════════════════════════════
# 从原 pipeline.py 搬来的辅助函数（完全不动）
# ══════════════════════════════════════════════════════════════════

def _agent_buttons(buttons: list[dict]) -> str:
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
    lines = [f'\n\n**{agent_name}：** {text}\n\n']
    if buttons:
        lines.append(_agent_buttons(buttons))
    return ''.join(lines)


_CONSTRAINT_LABELS = {
    "CRI_max": "CRI上限", "CRI_min": "CRI下限",
    "CSR_max": "CSR上限", "CSR_min": "CSR下限",
    "M10_max": "M10上限", "M10_min": "M10下限",
    "M25_max": "M25上限", "M25_min": "M25下限",
    "Vdaf_max": "挥发分上限", "Vdaf_min": "挥发分下限",
    "G_min": "粘结指数下限", "Ad_max": "灰分上限",
}


def _describe_constraints(constraints: dict) -> str:
    if not constraints:
        return "无"
    parts = []
    for k, v in constraints.items():
        label = _CONSTRAINT_LABELS.get(k, k)
        parts.append(f"{label}={v}")
    return "，".join(parts)


def _build_adjustment_buttons(constraints: dict) -> list[dict]:
    buttons = []
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
    if "CRI_max" in constraints:
        v = constraints["CRI_max"]
        if v > 20:
            buttons.append({"label": f"收紧 CRI 上限（{v} → {v - 2}）",
                            "action": "__AGENT:adjust:CRI_max_down2__", "style": "default"})
    if "CSR_min" in constraints:
        v = constraints["CSR_min"]
        buttons.append({"label": f"提高 CSR 要求（{v} → {v + 2}）",
                        "action": "__AGENT:adjust:CSR_min_up2__", "style": "default"})
    if "CRI_max" not in constraints:
        buttons.append({"label": "新增 CRI 上限 ≤ 38",
                        "action": "__AGENT:adjust:add_CRI_max_38__", "style": "default"})
    if "CSR_min" not in constraints:
        buttons.append({"label": "新增 CSR 下限 ≥ 43",
                        "action": "__AGENT:adjust:add_CSR_min_43__", "style": "default"})
    if "Ad_max" not in constraints:
        buttons.append({"label": "新增灰分上限 ≤ 13",
                        "action": "__AGENT:adjust:add_Ad_max_13__", "style": "default"})
    if constraints:
        buttons.append({"label": "🗑️ 移除所有约束，纯成本优化",
                        "action": "__AGENT:adjust:clear_all__", "style": "danger"})
    return buttons


def _apply_adjustment(constraints: dict, adjust_key: str) -> dict:
    c = dict(constraints)
    adjustments = {
        "CRI_max_up2":    lambda: c.update(CRI_max=c.get("CRI_max", 38) + 2),
        "CRI_max_up5":    lambda: c.update(CRI_max=c.get("CRI_max", 38) + 5),
        "CRI_max_down2":  lambda: c.update(CRI_max=c.get("CRI_max", 38) - 2),
        "CSR_min_down2":  lambda: c.update(CSR_min=c.get("CSR_min", 43) - 2),
        "CSR_min_down5":  lambda: c.update(CSR_min=c.get("CSR_min", 43) - 5),
        "CSR_min_up2":    lambda: c.update(CSR_min=c.get("CSR_min", 43) + 2),
        "M10_max_up1":    lambda: c.update(M10_max=c.get("M10_max", 8) + 1),
        "M25_min_down2":  lambda: c.update(M25_min=c.get("M25_min", 85) - 2),
        "Ad_max_up1":     lambda: c.update(Ad_max=c.get("Ad_max", 13) + 1),
        "add_CRI_max_38": lambda: c.update(CRI_max=38),
        "add_CSR_min_43": lambda: c.update(CSR_min=43),
        "add_Ad_max_13":  lambda: c.update(Ad_max=13),
        "clear_all":      lambda: c.clear(),
    }
    fn = adjustments.get(adjust_key)
    if fn:
        fn()
    return c


def _preselect_coals(coal_props: dict, constraints: dict, max_n: int = 20) -> tuple[list[str], str]:
    import numpy as np
    valid = {}
    for name, p in coal_props.items():
        price = p.get("price", 0)
        cri = p.get("coke_CRI", 0)
        csr = p.get("coke_CSR", 0)
        if price > 0 and (cri > 0 or csr > 0):
            valid[name] = p
    if not valid:
        names = list(coal_props.keys())[:max_n]
        return names, f"数据不完整，取前 {len(names)} 种"
    cri_max = constraints.get("CRI_max", 999)
    csr_min = constraints.get("CSR_min", 0)
    filtered = {}
    for name, p in valid.items():
        cri = p.get("coke_CRI", 0)
        csr = p.get("coke_CSR", 0)
        if cri <= cri_max * 1.3 and csr >= csr_min * 0.7:
            filtered[name] = p
    if len(filtered) < 5:
        filtered = valid
    filter_info_parts = [f"有完整数据 {len(valid)} 种"]
    if len(filtered) < len(valid):
        filter_info_parts.append(f"约束粗筛后 {len(filtered)} 种")
    if len(filtered) <= max_n:
        filter_info = "→".join(filter_info_parts)
        return list(filtered.keys()), filter_info
    names = list(filtered.keys())
    prices = np.array([filtered[n].get("price", 0) for n in names])
    cris = np.array([filtered[n].get("coke_CRI", 50) for n in names])
    csrs = np.array([filtered[n].get("coke_CSR", 50) for n in names])

    def _norm(arr):
        r = arr.max() - arr.min()
        return (arr - arr.min()) / r if r > 0 else np.zeros_like(arr)
    score = 0.4 * (1 - _norm(prices)) + 0.3 * (1 - _norm(cris)) + 0.3 * _norm(csrs)
    top_idx = np.argsort(score)[-max_n:][::-1]
    selected = [names[i] for i in top_idx]
    filter_info_parts.append(f"综合排序取 Top-{max_n}")
    filter_info = " → ".join(filter_info_parts)
    return selected, filter_info


def _plan_chart_tag(ep: dict, constraints: dict = None) -> str:
    plan = ep["plan"]
    strategy = plan.get("strategy", "?")
    name = plan.get("strategy_name", "方案")
    hoppers = [h for h in plan.get("hoppers", []) if h["ratio"] > 0.1]
    all_preds = ep.get("all_predictions", {})
    recommended = ep.get("recommended_model", "")
    pred = all_preds.get(recommended) or ep.get("prediction", {})
    desc = {
        "chartType": "blend_dashboard",
        "title": f"方案{strategy}: {name}",
        "pieData": [{"name": h["coal"], "value": round(h["ratio"], 1)} for h in hoppers],
        "costPerTon": round(plan.get("cost_per_ton", 0), 1),
        "predictions": {k: round(v, 2) for k, v in pred.items() if isinstance(v, (int, float))},
        "constraints": constraints or {},
        "recommended_model": recommended,
        "passed": ep.get("evaluation", {}).get("passed", False),
    }
    return f'\n\n<!--ECHART:{json.dumps(desc, ensure_ascii=False)}-->\n\n'


def _format_plan_card_v2(ep: dict) -> str:
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
        pred = ep.get("prediction", {})
        if pred.get("CRI") is not None:
            lines.append(f"\n- **预测 CRI:** {pred['CRI']:.2f}")
            lines.append(f"- **预测 CSR:** {pred.get('CSR', 0):.2f}")
    if not passed and ep["evaluation"].get("feedback"):
        lines.append(f"\n- **评估：** {ep['evaluation']['feedback']}")
    lines.append("")
    return "\n".join(lines)


def _format_coal_table(rows: list[dict]) -> str:
    cols = [
        ("coal_name", "名称"), ("coal_type", "类型"), ("coal_price", "价格"),
        ("coal_ad", "灰分Ad"), ("coal_vdaf", "Vdaf"), ("coal_std", "硫分St,d"),
        ("G", "G值"), ("coke_CRI", "CRI"), ("coke_CSR", "CSR"),
        ("coke_M10", "M10"), ("coke_M25", "M25"),
    ]
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


# ══════════════════════════════════════════════════════════════════
# 进度条辅助
# ══════════════════════════════════════════════════════════════════

class ProgressTracker:
    """进度条状态管理器（与原版一致）。"""
    def __init__(self):
        self.steps: list[dict] = []

    def add(self, text: str, pct: int = 0) -> None:
        self.steps.append({'text': text, 'done': False, 'pct': pct, 'details': []})

    def update(self, text: str = None, pct: int = None) -> None:
        if self.steps:
            if text:
                self.steps[-1]['text'] = text
            if pct is not None:
                self.steps[-1]['pct'] = pct

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
        lines.append('</div>')
        body = ''.join(lines)
        return f'\n__PG__{body}__/PG__\n'


# ══════════════════════════════════════════════════════════════════
# Node 函数
# ══════════════════════════════════════════════════════════════════

def node_supervisor(state: PipelineState) -> dict:
    """Node: Supervisor LLM 智能路由决策（Phase 2）。"""
    question = state["question"]
    p = ProgressTracker()
    p.add("Supervisor：正在分析问题并制定执行计划…", pct=5)
    p.detail(f'<span class="agent-name">Supervisor</span> 收到用户问题："{question[:60]}{"…" if len(question)>60 else ""}"')
    out = [p.html()]

    decision = supervisor_decide(question)
    agent_plan = decision["agents"]
    reasoning = decision["reasoning"]

    # 把 agent 名映射为 question_type（兼容后续节点）
    # 对 knowledge_qa 类的，映射为 factual（触发 RAG）
    agent_to_type = {
        "coal_price": "coal_price", "oven_control": "oven_control",
        "optimization": "optimization", "data_management": "data_management",
        "knowledge_qa": "knowledge_qa", "simple_chat": "general_chat",
    }
    first_agent = agent_plan[0] if agent_plan else "knowledge_qa"
    question_type = agent_to_type.get(first_agent, "knowledge_qa")

    # 展示 supervisor 决策
    agent_labels = {
        "coal_price": "煤价查询", "oven_control": "焦炉操作",
        "optimization": "配煤优化", "data_management": "数据管理",
        "knowledge_qa": "知识问答", "simple_chat": "闲聊",
    }
    plan_display = " → ".join(agent_labels.get(a, a) for a in agent_plan)
    p.detail(f'<span class="agent-name">Supervisor</span> <span class="tool-call">LLM 路由决策</span>')
    p.detail(f'<span class="agent-name">Supervisor</span> <span class="tool-result">执行计划: {plan_display}</span>')
    p.detail(f'<span class="agent-name">Supervisor</span> 理由: {reasoning}')

    if len(agent_plan) > 1:
        p.finish(f"执行计划：{plan_display}（多 Agent 串行）", pct=10)
    else:
        p.finish(f"路由到：{plan_display}", pct=10)
    out.append(p.html())

    logger.info(f"[supervisor] plan={agent_plan}, reasoning={reasoning}")

    return {
        "question_type": question_type,
        "agent_plan": agent_plan,
        "agent_plan_idx": 0,
        "supervisor_reasoning": reasoning,
        "output": out,
    }


def node_advance(state: PipelineState) -> dict:
    """Node: 推进 agent_plan_idx，准备执行下一个 agent。"""
    idx = state.get("agent_plan_idx", 0) + 1
    plan = state.get("agent_plan", [])
    if idx < len(plan):
        next_agent = plan[idx]
        agent_labels = {
            "coal_price": "煤价查询", "oven_control": "焦炉操作",
            "optimization": "配煤优化", "data_management": "数据管理",
            "knowledge_qa": "知识问答", "simple_chat": "闲聊",
        }
        out = [_agent_message("Supervisor",
            f"第一步已完成，继续执行下一步：**{agent_labels.get(next_agent, next_agent)}**")]
    else:
        out = []
    return {"agent_plan_idx": idx, "output": out}


def node_coal_price(state: PipelineState) -> dict:
    """Node: 煤价查询。"""
    import re as _re
    from .skills.coal_price_service import get_price, get_quality_range, get_all_prices

    question = state["question"]
    out = []

    # 提取煤种名
    coal_name = ""
    known = ["澳大利亚焦煤", "澳洲焦煤", "澳煤", "山西主焦煤", "山西焦煤",
             "唐山肥煤", "气煤", "瘦煤", "蒙古焦煤", "蒙古煤"]
    for name in known:
        if name in question:
            coal_name = name
            break
    if not coal_name:
        m = _re.search(r"([\u4e00-\u9fa5]+(?:焦煤|肥煤|气煤|瘦煤|煤))", question)
        if m:
            coal_name = m.group(1)

    if not coal_name:
        all_prices = get_all_prices()
        lines = ["## 今日煤炭市场行情\n\n"]
        lines.append(f"数据来源：{all_prices[0]['source']}　更新时间：{all_prices[0]['update_time']}\n\n")
        lines.append("| 煤种 | 类型 | 产地 | 价格(元/吨) |\n|---|---|---|---|\n")
        for p_info in all_prices:
            lines.append(f"| {p_info['coal_name']} | {p_info['coal_type']} | {p_info['source_region']} | {p_info['price']} |\n")
        out.append("".join(lines))
        out.append(_agent_message("市场分析员", "是否需要根据当前煤仓储备情况制定配煤方案？", [
            {"label": "根据煤仓制定配煤方案", "action": "__AGENT:price_to_blend__", "style": "primary"},
        ]))
        # 保存旧式状态以兼容 agent command
        state_module = state  # 避免与参数名冲突——不，这里 state 是函数参数
        # 注意：这里仍用旧 pipeline_state 模块保存按钮交互所需的状态
        from . import pipeline_state as ps
        ps.save(state["session_id"], {"stage": "price_queried", "coal_info": {}, "quality_info": None})
        return {"output": out}

    price_info = get_price(coal_name)
    quality_info = get_quality_range(coal_name)
    if not price_info:
        out.append(f"抱歉，未找到「{coal_name}」的市场数据。")
        return {"output": out}

    lines = [
        f"\n\n根据{price_info['source']}今日 {price_info['update_time']} 更新数据：\n\n",
        f"煤种：{price_info['coal_name']}（{price_info['source_region']}）\n",
        f"今日成交价：{price_info['price']} {price_info['unit']}\n",
        f"煤种类型：{price_info['coal_type']}\n\n",
    ]
    if quality_info:
        q = quality_info
        lines.append("焦炭质量参数（作为主焦煤）\n\n")
        lines.append(f"根据国内外科研报告及工业报告分析记录，该煤种作为{q['coal_type']}，")
        lines.append(f"配入量在 {q['recommended_ratio']} 时：\n\n")
        lines.append(f"CSR（热态强度）：稳定在 {q['csr_range'][0]}-{q['csr_range'][1]}\n")
        lines.append(f"CRI（热态反应性）：稳定在 {q['cri_range'][0]}-{q['cri_range'][1]}\n")
        if q.get("ad_range"):
            lines.append(f"Ad（灰分）：{q['ad_range'][0]}-{q['ad_range'][1]}%\n")
        if q.get("g_range"):
            lines.append(f"G（粘结指数）：{q['g_range'][0]}-{q['g_range'][1]}\n")
    out.append("".join(lines))

    from . import pipeline_state as ps
    ps.save(state["session_id"], {
        "stage": "price_queried", "coal_info": price_info, "quality_info": quality_info,
    })
    out.append(_agent_message("市场分析员", "是否需要根据当前煤仓储备情况制定配煤方案？", [
        {"label": "根据煤仓制定配煤方案", "action": "__AGENT:price_to_blend__", "style": "primary"},
    ]))
    return {"output": out}


def node_oven_control(state: PipelineState) -> dict:
    """Node: 焦炉操作 / 数字孪生。"""
    import re as _re
    question = state["question"]
    session_id = state["session_id"]
    out = []

    if _re.search(r"开启.*(?:孪生|监控)|启动.*监控|数字孪生", question):
        from . import pipeline_state as ps
        s = ps.load(session_id) or {}
        oven_id = s.get("oven_id", "1")
        out.append(f"__MONITORING:start:{oven_id}__")
        out.append(_agent_message(
            "数字孪生控制系统",
            f"{oven_id}号焦炉数字孪生监控已启动。\n\n"
            f"后台实时监测焦化温度与压力\n监控画面已在右侧面板开启\n系统将自动预警异常波动",
            [{"label": "关闭监控", "action": "__AGENT:stop_monitoring__", "style": "default"}],
        ))
        return {"output": out}

    # 装填焦炉
    m = _re.search(r"(\d+)\s*号?\s*(?:焦炉|炉)", question)
    oven_id = m.group(1) if m else "1"
    from . import pipeline_state as ps
    s = ps.load(session_id) or {}
    plan = s.get("chosen_plan")
    if not plan:
        out.append(_agent_message("调度员", "当前没有待装填的配煤方案。请先制定一个配煤方案。"))
        return {"output": out}

    out.append("__VIDEO:blend__")
    hoppers = plan.get("hoppers", [])
    lines = [f"\n\n装填完成\n\n", f"已将配煤方案成功填入 {oven_id}号焦炉。\n\n"]
    if hoppers:
        lines.append("煤种 / 配比(%)：\n")
        for h in hoppers:
            lines.append(f"  {h['coal']}：{h['ratio']:.1f}%\n")
    cost = plan.get("cost_per_ton")
    if cost:
        lines.append(f"\n吨焦成本：{cost:.1f} 元/吨\n")
    lines.append(f"建议结焦时间：12小时后进行推焦\n")
    out.append("".join(lines))
    ps.save(session_id, {"stage": "oven_loaded", "oven_id": oven_id, "chosen_plan": plan})
    out.append(_agent_message("调度员", "是否需要开启数字孪生监控？", [
        {"label": "开启数字孪生监控", "action": "__AGENT:start_monitoring__", "style": "primary"},
        {"label": "查看配煤详情", "action": "__AGENT:add_constraints__", "style": "default"},
    ]))
    return {"output": out}


def node_optimization_step1(state: PipelineState) -> dict:
    """Node: 配煤优化 Step1 — 提取约束 → 筛选煤种 → interrupt 等用户确认。"""
    import numpy as np
    question = state["question"]
    session_id = state["session_id"]
    out = []
    p = ProgressTracker()

    p.add("调度员：正在分析配煤需求…", pct=15)
    out.append(p.html())

    constraints = extract_constraints(question)
    coal_props = get_coal_props()
    all_coal_names = list(coal_props.keys())

    p.finish("调度员：需求分析完成", pct=20)
    out.append(p.html())

    selected_names, filter_info = _preselect_coals(coal_props, constraints, max_n=12)

    # 格式化约束条件展示
    label_map = {
        "CRI_min": "CRI 下限", "CRI_max": "CRI 上限",
        "CSR_min": "CSR 下限", "CSR_max": "CSR 上限",
        "M10_min": "M10 下限", "M10_max": "M10 上限",
        "M25_min": "M25 下限", "M25_max": "M25 上限",
        "Vdaf_max": "挥发分上限", "G_min": "粘结指数下限", "Ad_max": "灰分上限",
    }
    constraint_display = []
    for k, v in constraints.items():
        name = label_map.get(k, k)
        constraint_display.append(f"- **{name}：** {v}")
    if not constraint_display:
        constraint_display.append("- （未检测到明确约束，将使用默认参数优化）")

    p.add("调度员：正在生成数据报表…", pct=25)
    out.append(p.html())

    from .skills.coal_charts import generate_overview_chart_data
    rows = get_all_coals()
    chart_descriptors = generate_overview_chart_data(rows)

    p.finish("调度员：数据报表生成完成", pct=30)
    out.append(p.html())

    sel_props = {n: coal_props[n] for n in selected_names}
    cri_vals = [pp["coke_CRI"] for pp in sel_props.values() if pp.get("coke_CRI")]
    csr_vals = [pp["coke_CSR"] for pp in sel_props.values() if pp.get("coke_CSR")]

    coal_table_lines = []
    for name in selected_names:
        cp = coal_props[name]
        coal_table_lines.append(
            f"| {name} | {cp.get('price', 0):.0f} | {cp.get('coke_CRI', 0):.1f} | "
            f"{cp.get('coke_CSR', 0):.1f} | {cp.get('Ad', 0):.1f} | {cp.get('G', 0):.0f} |"
        )
    coal_table = (
        "| 煤种 | 价格(元/吨) | CRI | CSR | 灰分Ad | 粘结指数G |\n"
        "|------|-----------|-----|-----|--------|----------|\n"
        + "\n".join(coal_table_lines)
    )

    msg = (
        f"我分析了你的需求，以下是我理解到的信息：\n\n"
        f"**约束条件：**\n"
        f"{''.join(c + chr(10) for c in constraint_display)}\n"
        f"**煤种筛选：** 从 {len(all_coal_names)} 种煤中筛选出 **{len(selected_names)}** 种候选煤\n"
        f"- 筛选依据：{filter_info}\n"
        f"- CRI 范围：{min(cri_vals):.1f} ~ {max(cri_vals):.1f}，均值 {np.mean(cri_vals):.1f}\n"
        f"- CSR 范围：{min(csr_vals):.1f} ~ {max(csr_vals):.1f}，均值 {np.mean(csr_vals):.1f}\n\n"
        f"**候选煤种详情：**\n\n{coal_table}\n\n"
    )
    out.append(_agent_message("调度员", msg))

    for cd in chart_descriptors:
        out.append(f'\n\n<!--ECHART:{json.dumps(cd, ensure_ascii=False)}-->\n\n')

    out.append(
        '\n\n<a href="http://127.0.0.1:8000/download_coals/" target="_blank" '
        'style="display:inline-block;padding:8px 16px;background:#F1F5F9;color:#2563EB;'
        'border-radius:8px;text-decoration:none;font-size:13px;border:1px solid #CBD5E1;">'
        '📥 下载完整煤样数据 (Excel)</a>\n\n'
    )

    confirm_msg = (
        f"以上 **{len(selected_names)} 种煤**将参与配煤优化。"
        f"确认后，**配煤工程师** 将生成 3 个方案（成本最优 / 质量最优 / 均衡），"
        f"**质量分析师** 使用多模型预测各方案焦炭质量。\n\n请确认，或补充条件 / 指定煤种。"
    )
    out.append(_agent_message("调度员", confirm_msg, [
        {"label": "确认，开始优化", "action": "__AGENT:confirm_blend__", "style": "primary"},
        {"label": "我要补充条件", "action": "__AGENT:add_constraints__", "style": "default"},
        {"label": "用全部煤种优化（慢）", "action": "__AGENT:use_all_coals__", "style": "default"},
    ]))

    # 保存旧式 pipeline_state（兼容 agent command 处理）
    from . import pipeline_state as ps
    ps.save(session_id, {
        "stage": "confirm_constraints",
        "question": question,
        "constraints": constraints,
        "coal_names": selected_names,
    })

    return {
        "constraints": constraints,
        "coal_names": selected_names,
        "output": out,
    }


def node_optimize(state: PipelineState) -> dict:
    """Node: 配煤工程师生成方案（Phase 3 反思循环的一环）。"""
    from . import pipeline_state as ps
    session_id = state["session_id"]
    s = ps.load(session_id)
    if not s:
        return {"output": ["会话状态过期，请重新提问。"]}

    constraints = s["constraints"]
    coal_names = s["coal_names"]
    round_num = s.get("round_num", 0) + 1
    coal_props = get_coal_props()
    is_retry = round_num > 1
    adjustment_hint = s.get("adjustment_hint")

    out = []
    p = ProgressTracker()

    blend_label = f"配煤工程师：正在生成配煤方案（第 {round_num} 轮）…" if is_retry else "配煤工程师：正在生成配煤方案…"
    p.add(blend_label, pct=25)
    out.append(p.html())

    if not is_retry or adjustment_hint is None:
        plans = run_multi_strategy_blend(coal_names, constraints)
    else:
        plans = optimize_with_feedback(coal_props, coal_names, constraints, adjustment_hint)

    if not plans:
        p.finish("配煤工程师：未找到可行方案", pct=50)
        out.append(p.html())
        out.append(_agent_message("配煤工程师", "抱歉，当前约束条件下未找到可行的配煤方案。建议放宽约束或更换煤种。", [
            {"label": "放宽约束重试", "action": "__AGENT:add_constraints__", "style": "primary"},
        ]))
        # 标记为已通过以跳出循环（无方案也不再重试）
        return {"evaluated": [], "any_passed": True, "round_num": round_num, "output": out}

    p.finish(f"配煤工程师：生成了 {len(plans)} 个方案", pct=45)
    out.append(p.html())

    # 保存 plans 到 pipeline_state 供 evaluate 读取
    s["plans"] = plans
    s["round_num"] = round_num
    ps.save(session_id, s)

    return {"round_num": round_num, "output": out}


def node_evaluate(state: PipelineState) -> dict:
    """Node: 质量分析师多模型评估（Phase 3 反思循环的一环）。"""
    from . import pipeline_state as ps
    session_id = state["session_id"]
    s = ps.load(session_id)
    if not s:
        return {"output": ["会话状态过期，请重新提问。"]}

    plans = s.get("plans", [])
    if not plans:
        return {"evaluated": [], "any_passed": True, "output": []}

    constraints = s["constraints"]
    coal_props = get_coal_props()

    out = []
    p = ProgressTracker()
    models_list = quality_agent.available_models()
    models_str = ", ".join(models_list)
    evaluated = []
    any_passed = False
    worst_hint = None

    for i, plan in enumerate(plans):
        strategy_name = plan.get("strategy_name", f"方案{i+1}")
        pct_base = 45 + int(i * 30 / len(plans))
        pct_next = 45 + int((i + 1) * 30 / len(plans))
        p.add(f"质量分析师：评估 {strategy_name}（{models_str}）…", pct=pct_base)
        out.append(p.html())

        result = quality_agent.run_multi_model(
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
        p.finish(f"质量分析师：{strategy_name} 评估完成", pct=pct_next)
        out.append(p.html())

    passed_count = sum(1 for e in evaluated if e["evaluation"]["passed"])
    round_num = state.get("round_num", 1)
    p.finish(f"质量分析师：全部评估完成，{passed_count}/{len(evaluated)} 达标（第 {round_num} 轮）", pct=75)
    out.append(p.html())

    # 保存评估结果到 pipeline_state
    s["evaluated"] = evaluated
    s["adjustment_hint"] = worst_hint
    s["stage"] = "evaluated"
    ps.save(session_id, s)

    return {
        "evaluated": evaluated,
        "any_passed": any_passed,
        "adjustment_hint": worst_hint or {},
        "output": out,
    }


def node_reflect(state: PipelineState) -> dict:
    """
    Node: 反思决策（Phase 3 核心）。
    如果不达标且轮次 < MAX_REFLECT_ROUNDS → 自动调整约束并触发重试。
    如果达标或超限 → 进入展示结果。
    """
    from . import pipeline_state as ps
    session_id = state["session_id"]
    any_passed = state.get("any_passed", False)
    round_num = state.get("round_num", 1)
    adjustment_hint = state.get("adjustment_hint", {})
    out = []

    if any_passed or round_num >= MAX_REFLECT_ROUNDS or not adjustment_hint:
        # 达标 / 超限 / 无调整建议 → 进入展示（不再循环）
        return {"output": out}

    # ── 自动调整约束并重试 ──
    s = ps.load(session_id)
    if not s:
        return {"output": ["会话状态过期。"]}

    constraints = s.get("constraints", {})

    # 根据 adjustment_hint 自动放宽约束
    hint_parts = []
    if adjustment_hint.get("cri_gap"):
        gap = adjustment_hint["cri_gap"]
        old_cri = constraints.get("CRI_max", 38)
        new_cri = round(old_cri + gap + 1, 1)  # 超标值 + 1 的余量
        constraints["CRI_max"] = new_cri
        hint_parts.append(f"CRI 上限 {old_cri} → {new_cri}")
    if adjustment_hint.get("csr_gap"):
        gap = adjustment_hint["csr_gap"]
        old_csr = constraints.get("CSR_min", 43)
        new_csr = round(old_csr - gap - 1, 1)  # 不足值 - 1 的余量
        constraints["CSR_min"] = new_csr
        hint_parts.append(f"CSR 下限 {old_csr} → {new_csr}")

    adjustment_desc = "，".join(hint_parts) if hint_parts else "微调约束"
    out.append(_agent_message("质量分析师",
        f"第 {round_num} 轮方案不达标，自动调整约束：{adjustment_desc}，启动第 {round_num + 1} 轮优化…"))

    # 更新 pipeline_state
    s["constraints"] = constraints
    s["adjustment_hint"] = adjustment_hint
    ps.save(session_id, s)

    logger.info(f"[reflect] round {round_num} → auto adjust: {adjustment_desc}")
    return {"constraints": constraints, "output": out}


def node_show_results(state: PipelineState) -> dict:
    """Node: 展示评估结果 + 交互按钮（反思循环结束后调用）。"""
    from . import pipeline_state as ps
    session_id = state["session_id"]
    s = ps.load(session_id)
    if not s:
        return {"output": ["会话状态过期。"]}

    evaluated = s.get("evaluated", [])
    constraints = s.get("constraints", {})
    question = s.get("question", "")
    coal_names = s.get("coal_names", [])
    round_num = state.get("round_num", 1)
    adjustment_hint = state.get("adjustment_hint", {})
    any_passed = state.get("any_passed", False)

    out = []
    # 展示方案卡片
    out.append("\n---\n\n## 配煤方案对比\n\n")
    for ep in evaluated:
        out.append(_format_plan_card_v2(ep))
        out.append(_plan_chart_tag(ep, constraints))

    # 保存状态
    ps.save(session_id, {
        "stage": "pick_plan",
        "question": question,
        "constraints": constraints,
        "coal_names": coal_names,
        "evaluated": evaluated,
        "round_num": round_num,
        "adjustment_hint": adjustment_hint,
    })

    # 生成按钮
    models_list = quality_agent.available_models()
    models_str = ", ".join(models_list)
    buttons = []
    for ep in evaluated:
        plan = ep["plan"]
        tag = plan.get("strategy", "?")
        name = plan.get("strategy_name", "方案")
        status_icon = "✅" if ep["evaluation"]["passed"] else "⚠️"
        buttons.append({
            "label": f"{status_icon} 选择 {tag}: {name}",
            "action": f"__AGENT:pick_plan:{tag}__",
            "style": "primary" if ep["evaluation"]["passed"] else "default",
        })
    if not any_passed and adjustment_hint and round_num < 3:
        hint_parts = []
        if adjustment_hint.get("cri_gap"):
            hint_parts.append(f"CRI 超标 {adjustment_hint['cri_gap']:.1f}")
        if adjustment_hint.get("csr_gap"):
            hint_parts.append(f"CSR 不足 {adjustment_hint['csr_gap']:.1f}")
        hint_summary = "；".join(hint_parts) if hint_parts else "质量指标不达标"
        buttons.append({
            "label": f"🔄 让质量分析师自动调整再试（{hint_summary}）",
            "action": "__AGENT:auto_retry__", "style": "primary",
        })
    buttons.append({"label": "我自己调整条件", "action": "__AGENT:add_constraints__", "style": "default"})

    reflect_info = f"（经 {round_num} 轮自动优化）" if round_num > 1 else ""
    round_info = f"（第 {round_num} 轮）" if round_num > 1 else ""
    out.append(_agent_message("调度员",
        f"质量分析师已完成多模型竞赛评估{round_info}{reflect_info}。"
        f"每个方案使用 {len(models_list)} 个模型（{models_str}）预测并选出推荐模型。"
        f"\n\n请选择方案，或选择调整方式。",
        buttons))

    return {"output": out}


def node_optimization_step3(state: PipelineState) -> dict:
    """Node: 用户选定方案 → 生成最终报告。"""
    from . import pipeline_state as ps
    session_id = state["session_id"]
    s = ps.load(session_id)
    if not s:
        return {"output": ["会话状态过期，请重新提问。"]}

    user_action = state.get("user_action", "")
    chosen_strategy = user_action.replace("__AGENT:pick_plan:", "").replace("__", "")

    evaluated = s.get("evaluated", [])
    question = s["question"]
    chosen = None
    for ep in evaluated:
        if ep["plan"].get("strategy") == chosen_strategy:
            chosen = ep
            break
    if not chosen:
        return {"output": [f"未找到方案 {chosen_strategy}，请重新选择。"]}

    plan = chosen["plan"]
    prediction = chosen["prediction"]
    out = []
    p = ProgressTracker()

    p.add("报告撰写员：正在生成最终报告…", pct=85)
    out.append(p.html())

    card_text = _format_plan_card_v2(chosen)
    summary = _generate_summary(question, card_text)

    p.finish("报告撰写员：最终报告生成完成", pct=100)
    out.append(p.html())

    out.append("\n\n最终推荐方案\n\n")
    out.append(card_text)
    out.append(_plan_chart_tag(chosen, s.get("constraints", {})))
    if summary:
        out.append("\n\n智能分析\n\n")
        out.append(summary)

    out.append(_agent_message("调度员", "方案已生成。你可以将此方案填入焦炉，或进一步调整。", [
        {"label": "填入焦炉", "action": "__AGENT:load_oven__", "style": "primary"},
        {"label": "基于此方案微调", "action": "__AGENT:add_constraints__", "style": "default"},
    ]))

    ps.save(session_id, {
        "stage": "plan_finalized",
        "chosen_plan": plan,
        "prediction": prediction,
        "question": question,
    })

    return {"chosen_plan": plan, "prediction": prediction, "output": out}


def node_data_management(state: PipelineState) -> dict:
    """Node: 自然语言管理煤样数据库。"""
    question = state["question"]
    session_id = state["session_id"]
    out = []

    _DATA_EXTRACT_PROMPT = """你是煤样数据提取助手。从用户的自然语言中提取煤样数据操作。

支持的操作：
- add: 添加煤样（可批量）
- update: 更新煤样
- delete: 删除煤样
- query: 查询煤样
- predict: 用CNN预测煤样的焦炭质量（CRI/CSR）

支持的字段：
- coal_name, coal_type, coal_price, coal_mad, coal_ad, coal_vdaf, coal_std, G, X, Y
- coke_CRI, coke_CSR, coke_M10, coke_M25, coke_M40

返回严格 JSON 格式（不要 markdown 包裹）：
{"action": "add/update/delete/query", "coals": [{"coal_name": "...", ...}]}"""

    try:
        raw = chat_json(
            [{"role": "system", "content": _DATA_EXTRACT_PROMPT},
             {"role": "user", "content": question}],
            temperature=0.0,
        )
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
        parsed = json.loads(raw)
    except Exception as e:
        logger.error(f"数据提取失败: {e}")
        out.append("\n\n抱歉，无法解析您的数据操作指令。请用更明确的表述。\n")
        return {"output": out}

    action = parsed.get("action", "query")
    coals = parsed.get("coals", [])

    if action == "query":
        from .skills.coal_charts import generate_overview_chart_data, generate_single_coal_chart_data
        if coals and isinstance(coals[0], dict) and coals[0].get("coal_name"):
            name = coals[0]["coal_name"]
            row = get_coal_by_name(name)
            if row:
                out.append(f"\n\n**煤样「{name}」详情：**\n\n")
                out.append(_format_coal_table([row]))
                cd = generate_single_coal_chart_data(row)
                if cd:
                    out.append(f'\n\n<!--ECHART:{json.dumps(cd, ensure_ascii=False)}-->\n\n')
            else:
                rows = get_all_coals()
                names = [r["coal_name"] for r in rows]
                out.append(f"\n\n未找到煤样「{name}」。当前数据库有 {len(names)} 条煤样。\n")
        else:
            rows = get_all_coals()
            out.append(f"\n\n**当前数据库共 {len(rows)} 条煤样：**\n\n")
            out.append(_format_coal_table(rows[:30]))
            if len(rows) > 30:
                out.append(f"\n> 表格仅显示前 30 条，共 {len(rows)} 条\n\n")
            chart_list = generate_overview_chart_data(rows)
            for cd in chart_list:
                out.append(f'\n\n<!--ECHART:{json.dumps(cd, ensure_ascii=False)}-->\n\n')
            out.append(
                '\n\n<a href="http://127.0.0.1:8000/download_coals/" target="_blank" '
                'style="display:inline-block;padding:8px 16px;background:#F1F5F9;color:#2563EB;'
                'border-radius:8px;text-decoration:none;font-size:13px;border:1px solid #CBD5E1;">'
                '📥 下载完整煤样数据 (Excel)</a>\n\n'
            )
        return {"output": out}

    if action == "predict":
        from .skills.cnn_predict import predict_batch, FEATURE_LABELS
        if not coals:
            coals = get_all_coals()
        preds = predict_batch(coals)
        out.append(f"\n\n**CNN 焦炭质量预测结果：**\n\n")
        out.append("| 煤样 | 预测CRI | 预测CSR | 状态 |\n|------|---------|--------|------|\n")
        for pr in preds:
            name = pr.get("coal_name", "?")
            if "error" in pr:
                out.append(f"| {name} | - | - | ⚠️ {pr['error']} |\n")
            else:
                out.append(f"| {name} | {pr['CRI']} | {pr['CSR']} | ✅ |\n")
        out.append(f"\n> 模型：CNN，输入特征：{', '.join(FEATURE_LABELS)}\n")
        return {"output": out}

    if action == "add":
        if not coals:
            out.append("\n\n没有检测到要添加的煤样数据。\n")
            return {"output": out}
        out.append(_agent_message("数据管理员", "我解析到以下煤样数据，请确认是否录入：\n\n"))
        out.append(_format_coal_table(coals))
        from . import pipeline_state as ps
        ps.save(session_id, {"stage": "confirm_add_coal", "coals": coals})
        out.append(_agent_buttons([
            {"label": f"确认录入 {len(coals)} 条", "action": "__AGENT:confirm_add_coal__", "style": "primary"},
            {"label": "取消", "action": "__AGENT:cancel_data__", "style": "default"},
        ]))
        return {"output": out}

    if action == "delete":
        if not coals:
            out.append("\n\n没有检测到要删除的煤样名称。\n")
            return {"output": out}
        names = [c.get("coal_name", "?") for c in coals]
        from . import pipeline_state as ps
        ps.save(session_id, {"stage": "confirm_delete_coal", "names": names})
        out.append(_agent_message(
            "数据管理员",
            f"确认删除以下煤样？\n\n**{', '.join(names)}**\n\n⚠️ 删除操作不可恢复。",
            [
                {"label": "确认删除", "action": "__AGENT:confirm_delete_coal__", "style": "primary"},
                {"label": "取消", "action": "__AGENT:cancel_data__", "style": "default"},
            ],
        ))
        return {"output": out}

    if action == "update":
        if not coals:
            out.append("\n\n没有检测到要更新的煤样数据。\n")
            return {"output": out}
        coal = coals[0]
        name = coal.get("coal_name", "")
        fields = {k: v for k, v in coal.items() if k != "coal_name" and v is not None}
        if not name or not fields:
            out.append("\n\n请提供要更新的煤样名称和具体字段。\n")
            return {"output": out}
        from . import pipeline_state as ps
        ps.save(session_id, {"stage": "confirm_update_coal", "name": name, "fields": fields})
        field_text = "\n".join(f"- **{k}**: {v}" for k, v in fields.items())
        out.append(_agent_message(
            "数据管理员",
            f"确认更新煤样「{name}」的以下字段？\n\n{field_text}",
            [
                {"label": "确认更新", "action": "__AGENT:confirm_update_coal__", "style": "primary"},
                {"label": "取消", "action": "__AGENT:cancel_data__", "style": "default"},
            ],
        ))
        return {"output": out}

    out.append(f"\n\n不支持的操作类型：{action}\n")
    return {"output": out}


def node_knowledge_qa(state: PipelineState) -> dict:
    """Node: 知识问答 — 文献研究员 + 推理专家 + 报告撰写员。"""
    question = state["question"]
    question_type = state["question_type"]
    out = []
    p = ProgressTracker()

    # 文献研究员：关键词提取
    p.add("文献研究员：正在提取关键词并翻译…", pct=10)
    out.append(p.html())
    translated = translate_and_extract(question)
    english_queries = translated["english_queries"]
    key_concepts = translated["key_concepts"]
    p.finish("文献研究员：关键词提取完成", pct=20)
    out.append(p.html())

    # 文献研究员：检索
    p.add("文献研究员：正在检索文献库…", pct=25)
    out.append(p.html())
    chunks = search_literature(english_queries)
    p.finish(f"文献研究员：检索到 {len(chunks)} 条文献", pct=35)
    out.append(p.html())

    # 文献研究员：知识图谱
    p.add("文献研究员：正在查询知识图谱…", pct=38)
    out.append(p.html())
    kg_context = search_knowledge_graph(key_concepts)
    p.finish("文献研究员：检索完成", pct=45)
    out.append(p.html())

    # 推理专家
    reasoning_trace = ""
    if is_complex(question_type) and chunks:
        p.add("推理专家：正在深度推理…", pct=50)
        out.append(p.html())
        reasoning_result = deep_reasoning(question, timeout=60, num_strategies=2)
        reasoning_trace = reasoning_result["reasoning_trace"]
        if reasoning_result["success"]:
            p.finish("推理专家：深度推理完成", pct=80)
        else:
            p.finish("推理专家：跳过（超时）", pct=80)
        out.append(p.html())

    # 推理过程展示块
    thinking = _build_thinking_block(question_type, chunks, kg_context, reasoning_trace)
    if thinking:
        out.append(thinking)

    # 报告撰写员：流式生成
    p.add("报告撰写员：正在生成回答…", pct=85)
    out.append(p.html())
    try:
        for piece in report_agent.run_stream(
            question=question, chunks=chunks,
            kg_context=kg_context, reasoning_trace=reasoning_trace,
        ):
            out.append(piece)
    except Exception as e:
        out.append(f"\n\n报告生成异常: {e}")

    p.finish("报告撰写员：回答生成完成", pct=100)
    return {"chunks": chunks, "kg_context": kg_context, "reasoning_trace": reasoning_trace, "output": out}


def node_simple_chat(state: PipelineState) -> dict:
    """Node: 闲聊。"""
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
        {"role": "user", "content": state["question"]},
    ]
    out = ["\r\n"]
    stream = chat(messages, stream=True)
    for chunk in stream:
        if not getattr(chunk, "choices", None):
            continue
        delta = chunk.choices[0].delta
        piece = getattr(delta, "content", None)
        if piece:
            out.append(piece)
    return {"output": out}


# ══════════════════════════════════════════════════════════════════
# 路由函数
# ══════════════════════════════════════════════════════════════════

def route_dispatch(state: PipelineState) -> str:
    """根据 agent_plan 中当前位置分派到对应 agent 节点。"""
    plan = state.get("agent_plan", [])
    idx = state.get("agent_plan_idx", 0)
    if idx >= len(plan):
        return END
    agent = plan[idx]
    dispatch_map = {
        "coal_price": "coal_price",
        "oven_control": "oven_control",
        "optimization": "optimization_step1",
        "data_management": "data_management",
        "knowledge_qa": "knowledge_qa",
        "simple_chat": "simple_chat",
    }
    return dispatch_map.get(agent, "knowledge_qa")


def route_after_agent(state: PipelineState) -> str:
    """agent 执行完后，检查 plan 中是否还有下一个 agent。"""
    plan = state.get("agent_plan", [])
    idx = state.get("agent_plan_idx", 0)
    if idx + 1 < len(plan):
        return "advance"   # 推进到下一个 agent
    return END


def route_after_reflect(state: PipelineState) -> str:
    """Phase 3: 反思后决定是继续循环还是展示结果。"""
    any_passed = state.get("any_passed", False)
    round_num = state.get("round_num", 1)
    adjustment_hint = state.get("adjustment_hint", {})
    if any_passed or round_num >= MAX_REFLECT_ROUNDS or not adjustment_hint:
        return "show_results"
    return "optimize"  # 循环回去重新优化


# ══════════════════════════════════════════════════════════════════
# 辅助
# ══════════════════════════════════════════════════════════════════

def _build_thinking_block(question_type, chunks, kg_context, reasoning_trace):
    lines = ["> **推理过程**", ">"]
    type_labels = {"factual": "事实查询", "process": "工艺流程", "comparison": "对比分析",
                   "causal": "因果推理", "recommendation": "方案推荐"}
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
# 构建 Graph
# ══════════════════════════════════════════════════════════════════

def build_graph():
    """
    构建企业版 LangGraph Pipeline。
    Phase 2: supervisor → dispatch → agent → advance → dispatch (多 agent 串行)
    Phase 3: optimize → evaluate → reflect → (循环 or show_results)
    """
    g = StateGraph(PipelineState)

    # ── 节点 ──
    g.add_node("supervisor", node_supervisor)
    g.add_node("advance", node_advance)
    # Agent 节点
    g.add_node("coal_price", node_coal_price)
    g.add_node("oven_control", node_oven_control)
    g.add_node("optimization_step1", node_optimization_step1)
    g.add_node("data_management", node_data_management)
    g.add_node("knowledge_qa", node_knowledge_qa)
    g.add_node("simple_chat", node_simple_chat)
    # 配煤优化反思循环节点（Phase 3）
    g.add_node("optimize", node_optimize)
    g.add_node("evaluate", node_evaluate)
    g.add_node("reflect", node_reflect)
    g.add_node("show_results", node_show_results)
    g.add_node("optimization_step3", node_optimization_step3)

    # ── 边：Supervisor 多 agent 串行循环 ──
    g.add_edge(START, "supervisor")
    # supervisor → dispatch（根据 agent_plan[idx] 路由）
    g.add_conditional_edges("supervisor", route_dispatch, {
        "coal_price": "coal_price",
        "oven_control": "oven_control",
        "optimization_step1": "optimization_step1",
        "data_management": "data_management",
        "knowledge_qa": "knowledge_qa",
        "simple_chat": "simple_chat",
        END: END,
    })

    # 每个 agent 节点执行完后 → 检查是否还有下一个 agent
    for agent_node in ["coal_price", "oven_control", "data_management", "knowledge_qa", "simple_chat"]:
        g.add_conditional_edges(agent_node, route_after_agent, {
            "advance": "advance",
            END: END,
        })
    # optimization_step1 总是 END（等用户按钮）
    g.add_edge("optimization_step1", END)
    # optimization_step3 总是 END
    g.add_edge("optimization_step3", END)

    # advance → 重新 dispatch
    g.add_conditional_edges("advance", route_dispatch, {
        "coal_price": "coal_price",
        "oven_control": "oven_control",
        "optimization_step1": "optimization_step1",
        "data_management": "data_management",
        "knowledge_qa": "knowledge_qa",
        "simple_chat": "simple_chat",
        END: END,
    })

    # ── 边：配煤优化反思循环（Phase 3）──
    # optimize → evaluate → reflect → (optimize 循环 | show_results)
    g.add_edge("optimize", "evaluate")
    g.add_edge("evaluate", "reflect")
    g.add_conditional_edges("reflect", route_after_reflect, {
        "optimize": "optimize",     # 不达标 → 循环回去
        "show_results": "show_results",  # 达标或超限 → 展示
    })
    g.add_edge("show_results", END)

    return g.compile()


# 全局编译一次
_graph = build_graph()


def _build_reflect_graph():
    """构建反思循环子图（用于 agent command 触发优化）。"""
    g = StateGraph(PipelineState)
    g.add_node("optimize", node_optimize)
    g.add_node("evaluate", node_evaluate)
    g.add_node("reflect", node_reflect)
    g.add_node("show_results", node_show_results)
    g.add_edge(START, "optimize")
    g.add_edge("optimize", "evaluate")
    g.add_edge("evaluate", "reflect")
    g.add_conditional_edges("reflect", route_after_reflect, {
        "optimize": "optimize",
        "show_results": "show_results",
    })
    g.add_edge("show_results", END)
    return g.compile()

_reflect_graph = _build_reflect_graph()


# ══════════════════════════════════════════════════════════════════
# Agent Command 处理（与旧版兼容）
# ══════════════════════════════════════════════════════════════════

def _make_empty_state(session_id: str, user_action: str = "") -> PipelineState:
    """创建空状态（用于 agent command 直接调用节点）。"""
    return {
        "question": "", "session_id": session_id, "question_type": "optimization",
        "agent_plan": [], "agent_plan_idx": 0, "supervisor_reasoning": "",
        "user_action": user_action,
        "constraints": {}, "coal_names": [], "evaluated": [],
        "chosen_plan": {}, "prediction": {}, "round_num": 0, "adjustment_hint": {},
        "any_passed": False,
        "english_queries": [], "key_concepts": [], "chunks": [],
        "kg_context": "", "reasoning_trace": "", "output": [],
    }


async def _run_reflect_loop(session_id: str) -> AsyncGenerator[str, None]:
    """运行 optimize → evaluate → reflect 反思循环（Phase 3），逐步 yield 输出。"""
    s = _make_empty_state(session_id)
    # 用反思子图运行
    async for event in _reflect_graph.astream(s, stream_mode="updates"):
        for node_name, updates in event.items():
            for piece in updates.get("output", []):
                yield piece
                await asyncio.sleep(0)


async def _handle_agent_command(command: str, session_id: str) -> AsyncGenerator[str, None]:
    """处理用户按钮指令。"""
    from . import pipeline_state as ps

    if command == "__AGENT:confirm_blend__":
        # 触发反思循环（Phase 3: optimize → evaluate → reflect → ...）
        async for piece in _run_reflect_loop(session_id):
            yield piece

    elif command.startswith("__AGENT:pick_plan:"):
        out = node_optimization_step3(_make_empty_state(session_id, command))
        for piece in out.get("output", []):
            yield piece
            await asyncio.sleep(0)

    elif command == "__AGENT:add_constraints__":
        state_data = ps.load(session_id)
        old_constraints = state_data.get("constraints", {}) if state_data else {}
        buttons = _build_adjustment_buttons(old_constraints)
        buttons.append({"label": "✏️ 我自己输入条件", "action": "__AGENT:free_input__", "style": "default"})
        current_desc = _describe_constraints(old_constraints)
        yield _agent_message("调度员", f"当前约束：{current_desc}\n\n请选择调整方向：", buttons)

    elif command == "__AGENT:free_input__":
        state_data = ps.load(session_id)
        old_constraints = state_data.get("constraints", {}) if state_data else {}
        current_desc = _describe_constraints(old_constraints)
        yield _agent_message("调度员",
            f"当前约束：{current_desc}\n\n请直接输入你想要的调整，例如：\n"
            f"- \"CRI不超过25\"\n- \"灰分控制在12以内\"\n\n输入后我会重新分析并优化。")
        ps.clear(session_id)

    elif command.startswith("__AGENT:adjust:"):
        adjust_key = command.replace("__AGENT:adjust:", "").replace("__", "")
        state_data = ps.load(session_id)
        if not state_data:
            yield "操作已过期，请重新提问。"
            return
        old_constraints = state_data.get("constraints", {})
        new_constraints = _apply_adjustment(old_constraints, adjust_key)
        state_data["constraints"] = new_constraints
        state_data["round_num"] = 0
        ps.save(session_id, state_data)
        new_desc = _describe_constraints(new_constraints)
        yield _agent_message("调度员", f"已调整约束为：{new_desc}，正在重新优化…")
        async for piece in _run_reflect_loop(session_id):
            yield piece

    elif command == "__AGENT:use_all_coals__":
        state_data = ps.load(session_id)
        if not state_data:
            yield "操作已过期，请重新提问。"
            return
        coal_props = get_coal_props()
        all_names = list(coal_props.keys())
        state_data["coal_names"] = all_names
        ps.save(session_id, state_data)
        yield _agent_message("调度员",
            f"已切换为全部 {len(all_names)} 种煤参与优化。\n\n"
            f"⚠️ **注意：** 煤种数量较大，优化可能需要较长时间。",
            [{"label": "确认，开始优化", "action": "__AGENT:confirm_blend__", "style": "primary"}])

    elif command == "__AGENT:auto_retry__":
        # 手动触发重试也走反思循环
        state_data = ps.load(session_id)
        if not state_data or state_data.get("stage") != "pick_plan":
            yield "操作已过期，请重新提问。"
            return
        hint = state_data.get("adjustment_hint")
        round_num = state_data.get("round_num", 1)
        if not hint:
            yield _agent_message("调度员", "没有可用的调整建议，请手动调整条件。")
            return
        if round_num >= MAX_REFLECT_ROUNDS:
            yield _agent_message("调度员", f"已达到最大调整轮次（{MAX_REFLECT_ROUNDS}轮），请手动调整条件或选择当前方案。")
            return
        async for piece in _run_reflect_loop(session_id):
            yield piece

    elif command == "__AGENT:confirm_add_coal__":
        state_data = ps.load(session_id)
        if not state_data or state_data.get("stage") != "confirm_add_coal":
            yield "操作已过期，请重新输入。"
            return
        coals = state_data.get("coals", [])
        result = batch_add_coals(coals)
        ps.clear(session_id)
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
        rows = get_all_coals()
        msg += f"\n当前数据库共 **{len(rows)}** 条煤样。"
        yield _agent_message("数据管理员", msg)

    elif command == "__AGENT:confirm_delete_coal__":
        state_data = ps.load(session_id)
        if not state_data or state_data.get("stage") != "confirm_delete_coal":
            yield "操作已过期，请重新输入。"
            return
        names = state_data.get("names", [])
        ps.clear(session_id)
        import deepcoke.skills.coal_skills as cs
        cs._coal_cache = None
        ok_list, fail_list = [], []
        for name in names:
            r = delete_coal(name)
            if r["ok"]:
                ok_list.append(name)
            else:
                fail_list.append(f"{name}（{r['error']}）")
        msg = "**删除完成！**\n\n"
        if ok_list:
            msg += f"✅ 已删除：{', '.join(ok_list)}\n"
        if fail_list:
            msg += f"⚠️ 失败：{', '.join(fail_list)}\n"
        rows = get_all_coals()
        msg += f"\n当前数据库共 **{len(rows)}** 条煤样。"
        yield _agent_message("数据管理员", msg)

    elif command == "__AGENT:confirm_update_coal__":
        state_data = ps.load(session_id)
        if not state_data or state_data.get("stage") != "confirm_update_coal":
            yield "操作已过期，请重新输入。"
            return
        name = state_data.get("name", "")
        fields = state_data.get("fields", {})
        ps.clear(session_id)
        import deepcoke.skills.coal_skills as cs
        cs._coal_cache = None
        r = update_coal(name, fields)
        if r["ok"]:
            msg = f"✅ 煤样「{name}」更新成功！更新字段：{', '.join(r['updated'])}"
        else:
            msg = f"⚠️ 更新失败：{r['error']}"
        yield _agent_message("数据管理员", msg)

    elif command == "__AGENT:cancel_data__":
        ps.clear(session_id)
        yield _agent_message("数据管理员", "已取消操作。")

    elif command == "__AGENT:price_to_blend__":
        s = ps.load(session_id) or {}
        coal_info = s.get("coal_info", {})
        coal_name = coal_info.get("coal_name", "")
        ps.clear(session_id)
        opt_question = f"根据今天煤仓的煤种储备情况，以{coal_name}为主焦煤，制定一个配煤优化方案"
        async for piece in process_question(opt_question, session_id=session_id):
            yield piece

    elif command == "__AGENT:load_oven__":
        s = ps.load(session_id) or {}
        if s.get("stage") != "plan_finalized":
            yield _agent_message("调度员", "当前没有待装填的配煤方案。")
            return
        buttons = [
            {"label": f"{i}号焦炉", "action": f"__AGENT:load_oven_{i}__", "style": "default"}
            for i in range(1, 13)
        ]
        yield _agent_message("调度员", "请选择要装填的焦炉：", buttons)

    elif command.startswith("__AGENT:load_oven_") and command.endswith("__"):
        import re as _re
        m = _re.search(r"load_oven_(\d+)", command)
        oven_id = m.group(1) if m else "1"
        async for piece in process_question(f"填入{oven_id}号焦炉", session_id=session_id):
            yield piece

    elif command == "__AGENT:start_monitoring__":
        s = ps.load(session_id) or {}
        oven_id = s.get("oven_id", "1")
        yield f"__MONITORING:start:{oven_id}__"
        yield _agent_message("数字孪生控制系统",
            f"{oven_id}号焦炉数字孪生监控已启动。后台实时监测焦化温度与压力，监控画面已在右侧面板开启。",
            [{"label": "关闭监控", "action": "__AGENT:stop_monitoring__", "style": "default"}])

    elif command == "__AGENT:stop_monitoring__":
        yield "__MONITORING:stop__"
        yield _agent_message("数字孪生控制系统", "监控已关闭。")
        ps.clear(session_id)

    else:
        yield "未知的操作指令，请重新提问。"
        ps.clear(session_id)


# ══════════════════════════════════════════════════════════════════
# 对外接口（保持与旧版完全相同的签名）
# ══════════════════════════════════════════════════════════════════

async def process_question(question: str, session_id: str = "") -> AsyncGenerator[str, None]:
    """
    LangGraph 版 pipeline 入口。
    签名与旧版 pipeline.process_question 完全一致。
    """
    from . import pipeline_state as ps

    # Agent 交互指令走旧逻辑
    if ps.is_agent_command(question):
        async for piece in _handle_agent_command(question, session_id):
            yield piece
        return

    initial_state: PipelineState = {
        "question": question,
        "session_id": session_id,
        "question_type": "",
        "agent_plan": [],
        "agent_plan_idx": 0,
        "supervisor_reasoning": "",
        "constraints": {},
        "coal_names": [],
        "evaluated": [],
        "chosen_plan": {},
        "prediction": {},
        "round_num": 0,
        "adjustment_hint": {},
        "any_passed": False,
        "english_queries": [],
        "key_concepts": [],
        "chunks": [],
        "kg_context": "",
        "reasoning_trace": "",
        "user_action": "",
        "output": [],
    }

    # astream(mode="updates") 逐节点返回状态增量
    async for event in _graph.astream(initial_state, stream_mode="updates"):
        for node_name, updates in event.items():
            new_output = updates.get("output", [])
            for piece in new_output:
                yield piece
                await asyncio.sleep(0)

    logger.info("[pipeline] === COMPLETE ===")
