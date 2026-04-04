"""
配煤工程师 Skills — 查询煤种、优化配煤方案
"""

import json
import logging

from ..coal_agent.coal_db import get_all_coals
from ..coal_agent.blend_optimizer import optimize_blend, optimize_multi_strategy

logger = logging.getLogger("deepcoke.skills.coal")

# ── 煤样数据缓存 ──────────────────────────────────────────────────
_coal_cache: dict | None = None


def _get_coal_data() -> tuple[list[dict], dict]:
    """返回 (raw_rows, props_dict)，带缓存。"""
    global _coal_cache
    if _coal_cache is not None:
        return _coal_cache
    try:
        rows = get_all_coals()
    except Exception as e:
        logger.warning(f"数据库读取失败: {e}")
        rows = []

    props = {}
    for r in rows:
        name = r["coal_name"]
        props[name] = {
            "price": float(r.get("coal_price") or 0),
            "coal_mad": float(r.get("coal_mad") or 0),
            "Ad": float(r.get("coal_ad") or 0),
            "Vdaf": float(r.get("coal_vdaf") or 0),
            "coal_std": float(r.get("coal_std") or 0),
            "G": float(r.get("G") or 0),
            "X": float(r.get("X") or 0),
            "Y": float(r.get("Y") or 0),
            "coke_CRI": float(r.get("coke_CRI") or 0),
            "coke_CSR": float(r.get("coke_CSR") or 0),
            "coke_M10": float(r.get("coke_M10") or 0),
            "coke_M25": float(r.get("coke_M25") or 0),
        }
    _coal_cache = (rows, props)
    return rows, props


def get_coal_props() -> dict:
    """获取煤样属性字典。"""
    _, props = _get_coal_data()
    return props


# ── Skill: 列出煤种 ──────────────────────────────────────────────

def list_coals() -> str:
    """列出数据库中所有可用煤种及其属性。"""
    rows, _ = _get_coal_data()
    if not rows:
        return json.dumps({"error": "数据库中没有煤样数据"}, ensure_ascii=False)
    summary = []
    for r in rows:
        summary.append({
            "煤种": r["coal_name"],
            "类型": r.get("coal_type", ""),
            "价格": r.get("coal_price"),
            "Vdaf": r.get("coal_vdaf"),
            "G": r.get("G"),
            "Ad": r.get("coal_ad"),
            "CRI": r.get("coke_CRI"),
            "CSR": r.get("coke_CSR"),
        })
    return json.dumps({"coals": summary, "count": len(summary)}, ensure_ascii=False)


# ── Skill: 优化配煤 ──────────────────────────────────────────────

def run_optimize_blend(coal_names: list[str] = None,
                       constraints: dict = None,
                       total_weight_g: float = 1000) -> str:
    """根据约束条件优化配煤方案，返回 JSON 字符串。"""
    _, props = _get_coal_data()
    if not coal_names:
        coal_names = list(props.keys())
    constraints = constraints or {}
    result = optimize_blend(props, coal_names, constraints, total_weight_g)
    if result is None:
        return json.dumps({"error": "无法找到满足约束的配煤方案，请放宽约束条件或更换煤种"}, ensure_ascii=False)
    return json.dumps(result, ensure_ascii=False)


# ── Skill: 多策略配煤（生成多个方案供选择） ──────────────────────

def run_multi_strategy_blend(coal_names: list[str] = None,
                             constraints: dict = None,
                             total_weight_g: float = 1000) -> list[dict]:
    """
    生成多个配煤方案供用户选择。
    返回方案列表，每个方案带 strategy(A/B/C) 和 strategy_name。
    """
    _, props = _get_coal_data()
    if not coal_names:
        coal_names = list(props.keys())
    constraints = constraints or {}
    return optimize_multi_strategy(props, coal_names, constraints, total_weight_g)


# ── 工具定义（供 LLM tool-calling 使用） ─────────────────────────

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "list_coals",
            "description": "列出数据库中所有可用煤种及其属性（价格、挥发分、粘结指数、灰分、CRI、CSR等）",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "optimize_blend",
            "description": "根据约束条件（CRI/CSR/M10/M25范围、Vdaf/G/Ad限制）优化配煤方案，最小化成本",
            "parameters": {
                "type": "object",
                "properties": {
                    "coal_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "参与配煤的煤种名称列表",
                    },
                    "CRI_min": {"type": "number", "description": "CRI下限"},
                    "CRI_max": {"type": "number", "description": "CRI上限"},
                    "CSR_min": {"type": "number", "description": "CSR下限"},
                    "CSR_max": {"type": "number", "description": "CSR上限"},
                    "M10_min": {"type": "number", "description": "M10下限"},
                    "M10_max": {"type": "number", "description": "M10上限"},
                    "M25_min": {"type": "number", "description": "M25下限"},
                    "M25_max": {"type": "number", "description": "M25上限"},
                    "Vdaf_max": {"type": "number", "description": "挥发分上限"},
                    "G_min": {"type": "number", "description": "粘结指数下限"},
                    "Ad_max": {"type": "number", "description": "灰分上限"},
                    "total_weight_g": {"type": "number", "description": "总重量(克)，默认1000"},
                },
                "required": ["coal_names"],
            },
        },
    },
]


def exec_tool(name: str, args: dict) -> str:
    """执行工具调用，供 Agent 的 LLM tool-calling 使用。"""
    _, props = _get_coal_data()

    if name == "list_coals":
        return list_coals()

    elif name == "optimize_blend":
        coal_names = args.get("coal_names", [])
        if not coal_names:
            coal_names = list(props.keys())
        constraints = {}
        for key in ["CRI_min", "CRI_max", "CSR_min", "CSR_max",
                     "M10_min", "M10_max", "M25_min", "M25_max",
                     "Vdaf_max", "G_min", "Ad_max"]:
            if key in args and args[key] is not None:
                constraints[key] = float(args[key])
        total_w = float(args.get("total_weight_g", 1000))
        result = optimize_blend(props, coal_names, constraints, total_w)
        if result is None:
            return json.dumps({"error": "无法找到满足约束的配煤方案"}, ensure_ascii=False)
        return json.dumps(result, ensure_ascii=False)

    return json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)
