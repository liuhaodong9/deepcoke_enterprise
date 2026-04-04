"""配煤优化 - 差分进化 (scipy) + LP fallback"""

import warnings
import numpy as np
from scipy.optimize import differential_evolution, NonlinearConstraint, linprog

warnings.filterwarnings("ignore", module="scipy.optimize")


def optimize_blend(coal_props: dict, coal_names: list[str],
                   constraints: dict, total_weight_g: float = 1000) -> dict | None:
    """
    Args:
        coal_props: {name: {price, coke_CRI, coke_CSR, coke_M10, coke_M25, Vdaf, G, Ad, ...}}
        coal_names: 参与配煤的煤样名称列表
        constraints: {CRI_min, CRI_max, CSR_min, CSR_max, M10_min, M10_max, M25_min, M25_max, ...}
        total_weight_g: 总量(克)
    """
    n = len(coal_names)
    if n == 0:
        return None

    props = coal_props
    has_quality = any(k in constraints for k in
                      ["CRI_min", "CRI_max", "CSR_min", "CSR_max",
                       "M10_min", "M10_max", "M25_min", "M25_max"])

    if has_quality:
        plan = _de_optimize(props, coal_names, constraints, total_weight_g)
        if plan:
            return plan

    return _lp_optimize(props, coal_names, constraints, total_weight_g)


def _de_optimize(props, names, constraints, total_weight_g):
    n = len(names)
    prices = np.array([props[c]["price"] for c in names], dtype=float)
    cri = np.array([props[c]["coke_CRI"] for c in names], dtype=float)
    csr = np.array([props[c]["coke_CSR"] for c in names], dtype=float)
    m10 = np.array([props[c]["coke_M10"] for c in names], dtype=float)
    m25 = np.array([props[c]["coke_M25"] for c in names], dtype=float)

    nl = [NonlinearConstraint(lambda x: np.sum(x), 1.0, 1.0)]
    for vals, lo_key, hi_key in [
        (cri, "CRI_min", "CRI_max"), (csr, "CSR_min", "CSR_max"),
        (m10, "M10_min", "M10_max"), (m25, "M25_min", "M25_max"),
    ]:
        lo = constraints.get(lo_key, 0)
        hi = constraints.get(hi_key, 100)
        if lo_key in constraints or hi_key in constraints:
            nl.append(NonlinearConstraint(lambda x, v=vals: np.dot(v, x), lo, hi))

    try:
        result = differential_evolution(
            lambda x: np.dot(prices, x), bounds=[(0, 0.6)] * n,
            constraints=nl, maxiter=2000, popsize=100, tol=1e-8, seed=42,
        )
    except Exception:
        return None

    if not result.success:
        return None

    return _build(names, result.x, total_weight_g, float(result.fun), "scipy_DE")


def _lp_optimize(props, names, constraints, total_weight_g):
    n = len(names)
    prices = np.array([props[c]["price"] for c in names], dtype=float)
    A_ub, b_ub = [], []

    vdaf = np.array([props[c]["Vdaf"] for c in names])
    if "Vdaf_max" in constraints: A_ub.append(vdaf); b_ub.append(constraints["Vdaf_max"])
    if "Vdaf_min" in constraints: A_ub.append(-vdaf); b_ub.append(-constraints["Vdaf_min"])
    g = np.array([props[c]["G"] for c in names])
    if "G_min" in constraints: A_ub.append(-g); b_ub.append(-constraints["G_min"])
    ad = np.array([props[c]["Ad"] for c in names])
    if "Ad_max" in constraints: A_ub.append(ad); b_ub.append(constraints["Ad_max"])

    result = linprog(prices,
                     A_ub=np.array(A_ub) if A_ub else None,
                     b_ub=np.array(b_ub) if b_ub else None,
                     A_eq=np.ones((1, n)), b_eq=np.array([1.0]),
                     bounds=[(0.05, 0.60)] * n, method="highs")

    if not result.success:
        return None
    return _build(names, result.x, total_weight_g, float(result.fun), "LP")


def _build(names, ratios, total_weight_g, cost, optimizer):
    return {
        "hoppers": [
            {"coal": names[i], "ratio": round(ratios[i] * 100, 1),
             "weight_g": round(ratios[i] * total_weight_g, 1)}
            for i in range(len(names))
        ],
        "total_weight_g": total_weight_g,
        "cost_per_ton": cost,
        "optimizer": optimizer,
    }


def optimize_multi_strategy(coal_props: dict, coal_names: list[str],
                            constraints: dict, total_weight_g: float = 1000) -> list[dict]:
    """
    生成多个配煤方案供用户选择：
    - 方案 A: 成本最优
    - 方案 B: 质量最优（最小化 CRI）
    - 方案 C: 均衡方案（成本 + 质量加权）
    返回方案列表，每个方案带 strategy 标签。
    """
    n = len(coal_names)
    if n == 0:
        return []

    props = coal_props
    prices = np.array([props[c]["price"] for c in coal_names], dtype=float)
    cri = np.array([props[c]["coke_CRI"] for c in coal_names], dtype=float)
    csr = np.array([props[c]["coke_CSR"] for c in coal_names], dtype=float)

    # 通用约束：配比之和 = 1
    nl_base = [NonlinearConstraint(lambda x: np.sum(x), 1.0, 1.0)]

    plans = []

    # 方案 A: 成本最优
    plan_a = optimize_blend(props, coal_names, constraints, total_weight_g)
    if plan_a:
        plan_a["strategy"] = "A"
        plan_a["strategy_name"] = "成本最优"
        plans.append(plan_a)

    # 方案 B: 质量最优（最小化 CRI，等价于最大化 CSR）
    try:
        result = differential_evolution(
            lambda x: np.dot(cri, x),  # 最小化 CRI
            bounds=[(0, 0.6)] * n,
            constraints=nl_base,
            maxiter=2000, popsize=100, tol=1e-8, seed=42,
        )
        if result.success:
            plan_b = _build(coal_names, result.x, total_weight_g,
                           float(np.dot(prices, result.x)), "DE_quality")
            plan_b["strategy"] = "B"
            plan_b["strategy_name"] = "质量最优"
            plans.append(plan_b)
    except Exception:
        pass

    # 方案 C: 均衡方案（归一化后 0.5*成本 + 0.5*CRI）
    try:
        p_norm = prices / (prices.max() or 1)
        c_norm = cri / (cri.max() or 1)
        result = differential_evolution(
            lambda x: 0.5 * np.dot(p_norm, x) + 0.5 * np.dot(c_norm, x),
            bounds=[(0, 0.6)] * n,
            constraints=nl_base,
            maxiter=2000, popsize=100, tol=1e-8, seed=42,
        )
        if result.success:
            plan_c = _build(coal_names, result.x, total_weight_g,
                           float(np.dot(prices, result.x)), "DE_balanced")
            plan_c["strategy"] = "C"
            plan_c["strategy_name"] = "均衡方案"
            plans.append(plan_c)
    except Exception:
        pass

    return plans


def optimize_with_feedback(coal_props: dict, coal_names: list[str],
                           constraints: dict, adjustment_hint: dict,
                           total_weight_g: float = 1000) -> list[dict]:
    """
    根据质量分析师的反馈调整优化策略，重新生成方案。

    adjustment_hint 来自质量分析师：
      - direction: "lower_cri" / "raise_csr" / "both"
      - high_cri_coals: 建议减少的高 CRI 煤种
      - low_cri_coals: 建议增加的低 CRI 煤种
      - weight_shift: 质量权重提高幅度
    """
    direction = adjustment_hint.get("direction", "")
    high_cri = set(adjustment_hint.get("high_cri_coals", []))
    low_cri = set(adjustment_hint.get("low_cri_coals", []))
    weight_shift = adjustment_hint.get("weight_shift", 0.1)

    n = len(coal_names)
    if n == 0:
        return []

    props = coal_props
    prices = np.array([props[c]["price"] for c in coal_names], dtype=float)
    cri = np.array([props[c]["coke_CRI"] for c in coal_names], dtype=float)
    csr = np.array([props[c]["coke_CSR"] for c in coal_names], dtype=float)

    # 根据反馈调整各煤种的比例上下限
    bounds = []
    for i, name in enumerate(coal_names):
        lo, hi = 0.0, 0.6
        if name in high_cri:
            hi = 0.25  # 限制高 CRI 煤种的上限
        if name in low_cri:
            lo = 0.05  # 确保低 CRI 煤种有最低用量
        bounds.append((lo, hi))

    nl_base = [NonlinearConstraint(lambda x: np.sum(x), 1.0, 1.0)]

    # 添加质量约束
    for vals, lo_key, hi_key in [
        (cri, "CRI_min", "CRI_max"), (csr, "CSR_min", "CSR_max"),
    ]:
        lo = constraints.get(lo_key, 0)
        hi = constraints.get(hi_key, 100)
        if lo_key in constraints or hi_key in constraints:
            nl_base.append(NonlinearConstraint(lambda x, v=vals: np.dot(v, x), lo, hi))

    plans = []

    # 调整后的质量权重（比首轮更偏向质量）
    quality_weight = min(0.9, 0.5 + weight_shift)
    cost_weight = 1.0 - quality_weight

    # 方案 A': 偏质量的成本优化
    try:
        p_norm = prices / (prices.max() or 1)
        c_norm = cri / (cri.max() or 1)
        result = differential_evolution(
            lambda x: cost_weight * np.dot(p_norm, x) + quality_weight * np.dot(c_norm, x),
            bounds=bounds, constraints=nl_base,
            maxiter=3000, popsize=120, tol=1e-9, seed=123,
        )
        if result.success:
            plan = _build(coal_names, result.x, total_weight_g,
                          float(np.dot(prices, result.x)), "DE_feedback_balanced")
            plan["strategy"] = "A"
            plan["strategy_name"] = f"调整后成本优化 (质量权重{quality_weight:.0%})"
            plans.append(plan)
    except Exception:
        pass

    # 方案 B': 强质量优化（最小化 CRI）
    try:
        result = differential_evolution(
            lambda x: np.dot(cri, x),
            bounds=bounds, constraints=nl_base,
            maxiter=3000, popsize=120, tol=1e-9, seed=456,
        )
        if result.success:
            plan = _build(coal_names, result.x, total_weight_g,
                          float(np.dot(prices, result.x)), "DE_feedback_quality")
            plan["strategy"] = "B"
            plan["strategy_name"] = "调整后质量优先"
            plans.append(plan)
    except Exception:
        pass

    # 方案 C': 最大化 CSR
    if direction in ("raise_csr", "both"):
        try:
            result = differential_evolution(
                lambda x: -np.dot(csr, x),  # 最大化 CSR
                bounds=bounds, constraints=nl_base,
                maxiter=3000, popsize=120, tol=1e-9, seed=789,
            )
            if result.success:
                plan = _build(coal_names, result.x, total_weight_g,
                              float(np.dot(prices, result.x)), "DE_feedback_csr")
                plan["strategy"] = "C"
                plan["strategy_name"] = "调整后 CSR 优先"
                plans.append(plan)
        except Exception:
            pass

    return plans
