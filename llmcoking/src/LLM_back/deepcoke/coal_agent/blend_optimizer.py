"""配煤优化 - 差分进化 (scipy) + LP fallback"""

import warnings
import numpy as np
from scipy.optimize import differential_evolution, linprog

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


def _ml_predict_cri_csr(props, names, x, _cache={}):
    """用 ML 模型（RF）预测配比 x 对应的焦炭 CRI/CSR，带缓存。"""
    if "predictor" not in _cache:
        from .quality_predictor import predictor as _p
        _cache["predictor"] = _p

    # 缓存 key
    key = tuple(round(v, 6) for v in x)
    if key in _cache.get("results", {}):
        return _cache["results"][key]

    pred = _cache["predictor"]
    blend_ratios = {names[i]: x[i] * 100 for i in range(len(names))}
    result = pred.predict(blend_ratios, props, model_name="RF")
    cri_csr = (result.get("CRI", 50.0), result.get("CSR", 30.0))

    if "results" not in _cache:
        _cache["results"] = {}
    if len(_cache["results"]) > 10000:
        _cache["results"].clear()
    _cache["results"][key] = cri_csr
    return cri_csr


def _z_to_ratios(z, lo_bounds, hi_bounds):
    """
    将 z ∈ [0,1]^n 映射到满足 sum=1 且 lo <= x <= hi 的配比。
    先将 z 映射到 [lo, hi] 范围，再通过迭代投影保证 sum=1。
    """
    n = len(z)
    # z ∈ [0,1] → x ∈ [lo, hi]
    x = lo_bounds + z * (hi_bounds - lo_bounds)
    # 迭代投影到 simplex（sum=1）同时保持 bounds
    for _ in range(50):
        s = x.sum()
        if abs(s - 1.0) < 1e-8:
            break
        if s > 1.0:
            excess = s - 1.0
            reducible = x - lo_bounds
            r_sum = reducible.sum()
            if r_sum > 1e-10:
                x = x - excess * (reducible / r_sum)
        else:
            deficit = 1.0 - s
            expandable = hi_bounds - x
            e_sum = expandable.sum()
            if e_sum > 1e-10:
                x = x + deficit * (expandable / e_sum)
        x = np.clip(x, lo_bounds, hi_bounds)
    return x


def _de_optimize(props, names, constraints, total_weight_g,
                 bounds_override=None):
    """用 DE + ML 预测做配煤优化。用 softmax 参数化消除 sum=1 等式约束。"""
    n = len(names)
    prices = np.array([props[c]["price"] for c in names], dtype=float)

    # 各煤种的配比上下限（每种煤至少5%，最多60%）
    if bounds_override:
        lo_bounds = np.array([b[0] for b in bounds_override])
        hi_bounds = np.array([b[1] for b in bounds_override])
    else:
        lo_bounds = np.full(n, 0.05)
        hi_bounds = np.full(n, 0.50)

    def z_to_x(z):
        return _z_to_ratios(z, lo_bounds, hi_bounds)

    # 构建惩罚函数（将约束违反作为惩罚项加到目标函数）
    def penalty(x):
        pen = 0.0
        # CRI 约束
        if "CRI_min" in constraints or "CRI_max" in constraints:
            cri, csr = _ml_predict_cri_csr(props, names, x)
            if "CRI_max" in constraints and cri > constraints["CRI_max"]:
                pen += (cri - constraints["CRI_max"]) ** 2 * 100
            if "CRI_min" in constraints and cri < constraints["CRI_min"]:
                pen += (constraints["CRI_min"] - cri) ** 2 * 100
        # CSR 约束
        if "CSR_min" in constraints or "CSR_max" in constraints:
            _, csr = _ml_predict_cri_csr(props, names, x)
            if "CSR_max" in constraints and csr > constraints["CSR_max"]:
                pen += (csr - constraints["CSR_max"]) ** 2 * 100
            if "CSR_min" in constraints and csr < constraints["CSR_min"]:
                pen += (constraints["CSR_min"] - csr) ** 2 * 100
        # M10/M25 约束（线性加权）
        m10 = np.array([props[c]["coke_M10"] for c in names], dtype=float)
        m25 = np.array([props[c]["coke_M25"] for c in names], dtype=float)
        for vals, lo_key, hi_key in [
            (m10, "M10_min", "M10_max"), (m25, "M25_min", "M25_max"),
        ]:
            val = np.dot(vals, x)
            if lo_key in constraints and val < constraints[lo_key]:
                pen += (constraints[lo_key] - val) ** 2 * 100
            if hi_key in constraints and val > constraints[hi_key]:
                pen += (val - constraints[hi_key]) ** 2 * 100
        return pen

    def objective(z):
        x = z_to_x(z)
        return np.dot(prices, x) + penalty(x)

    # DE 参数（softmax 参数化后不需要等式约束，收敛更快）
    maxiter = min(150, max(50, 300 // max(n, 1)))
    popsize = min(25, max(10, 80 // max(n, 1)))

    try:
        result = differential_evolution(
            objective, bounds=[(0, 1)] * n,
            maxiter=maxiter, popsize=popsize, tol=1e-5, seed=42,
        )
    except Exception:
        return None

    x = z_to_x(result.x)
    # 验证约束是否满足
    if penalty(x) > 0.01:
        return None

    return _build(names, x, total_weight_g, float(np.dot(prices, x)), "DE_ML")


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
    """
    n = len(coal_names)
    if n == 0:
        return []

    props = coal_props
    prices = np.array([props[c]["price"] for c in coal_names], dtype=float)
    lo_bounds = np.full(n, 0.05)
    hi_bounds = np.full(n, 0.50)

    def z_to_x(z):
        return _z_to_ratios(z, lo_bounds, hi_bounds)

    maxiter = min(150, max(50, 300 // max(n, 1)))
    popsize = min(25, max(10, 80 // max(n, 1)))

    plans = []

    # 方案 A: 成本最优
    plan_a = optimize_blend(props, coal_names, constraints, total_weight_g)
    if plan_a:
        plan_a["strategy"] = "A"
        plan_a["strategy_name"] = "成本最优"
        plans.append(plan_a)

    # 方案 B: 质量最优（最小化 ML 预测 CRI）
    try:
        result = differential_evolution(
            lambda z: _ml_predict_cri_csr(props, coal_names, z_to_x(z))[0],
            bounds=[(0, 1)] * n,
            maxiter=maxiter, popsize=popsize, tol=1e-5, seed=42,
        )
        x = z_to_x(result.x)
        plan_b = _build(coal_names, x, total_weight_g,
                       float(np.dot(prices, x)), "DE_quality")
        plan_b["strategy"] = "B"
        plan_b["strategy_name"] = "质量最优"
        plans.append(plan_b)
    except Exception:
        pass

    # 方案 C: 均衡方案（归一化后 0.5*成本 + 0.5*ML预测CRI）
    try:
        p_norm = prices / (prices.max() or 1)
        result = differential_evolution(
            lambda z: (lambda x: 0.5 * np.dot(p_norm, x) + 0.5 * _ml_predict_cri_csr(props, coal_names, x)[0] / 50)(z_to_x(z)),
            bounds=[(0, 1)] * n,
            maxiter=maxiter, popsize=popsize, tol=1e-5, seed=42,
        )
        x = z_to_x(result.x)
        plan_c = _build(coal_names, x, total_weight_g,
                       float(np.dot(prices, x)), "DE_balanced")
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

    # 根据反馈调整各煤种的比例上下限
    bounds_list = []
    for i, name in enumerate(coal_names):
        lo, hi = 0.0, 0.6
        if name in high_cri:
            hi = 0.25
        if name in low_cri:
            lo = 0.05
        bounds_list.append((lo, hi))

    lo_bounds = np.array([b[0] for b in bounds_list])
    hi_bounds = np.array([b[1] for b in bounds_list])

    def z_to_x(z):
        return _z_to_ratios(z, lo_bounds, hi_bounds)

    # 自适应 DE 参数
    maxiter = min(150, max(50, 300 // max(n, 1)))
    popsize = min(25, max(10, 80 // max(n, 1)))

    plans = []

    # 调整后的质量权重
    quality_weight = min(0.9, 0.5 + weight_shift)
    cost_weight = 1.0 - quality_weight

    # 方案 A': 偏质量的成本优化
    try:
        p_norm = prices / (prices.max() or 1)

        def obj_a(z):
            x = z_to_x(z)
            cri, _ = _ml_predict_cri_csr(props, coal_names, x)
            return cost_weight * np.dot(p_norm, x) + quality_weight * cri / 50

        result = differential_evolution(
            obj_a, bounds=[(0, 1)] * n,
            maxiter=maxiter, popsize=popsize, tol=1e-5, seed=123,
        )
        x = z_to_x(result.x)
        plan = _build(coal_names, x, total_weight_g,
                      float(np.dot(prices, x)), "DE_feedback_balanced")
        plan["strategy"] = "A"
        plan["strategy_name"] = f"调整后成本优化 (质量权重{quality_weight:.0%})"
        plans.append(plan)
    except Exception:
        pass

    # 方案 B': 强质量优化（最小化 ML 预测 CRI）
    try:
        result = differential_evolution(
            lambda z: _ml_predict_cri_csr(props, coal_names, z_to_x(z))[0],
            bounds=[(0, 1)] * n,
            maxiter=maxiter, popsize=popsize, tol=1e-5, seed=456,
        )
        x = z_to_x(result.x)
        plan = _build(coal_names, x, total_weight_g,
                      float(np.dot(prices, x)), "DE_feedback_quality")
        plan["strategy"] = "B"
        plan["strategy_name"] = "调整后质量优先"
        plans.append(plan)
    except Exception:
        pass

    # 方案 C': 最大化 ML 预测 CSR
    if direction in ("raise_csr", "both"):
        try:
            result = differential_evolution(
                lambda z: -_ml_predict_cri_csr(props, coal_names, z_to_x(z))[1],
                bounds=[(0, 1)] * n,
                maxiter=maxiter, popsize=popsize, tol=1e-5, seed=789,
            )
            x = z_to_x(result.x)
            plan = _build(coal_names, x, total_weight_g,
                          float(np.dot(prices, x)), "DE_feedback_csr")
            plan["strategy"] = "C"
            plan["strategy_name"] = "调整后 CSR 优先"
            plans.append(plan)
        except Exception:
            pass

    return plans
