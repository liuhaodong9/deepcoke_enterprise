"""
质量分析师 Agent — 多模型竞赛评估 + 模型推荐 + 反馈驱动优化
调用 Skills: quality_skills.predict_quality, quality_skills.evaluate_quality
"""

import logging
import numpy as np

from ..skills.quality_skills import predict_quality, evaluate_quality, available_models

logger = logging.getLogger("deepcoke.quality_agent")


def run(blend_result: dict, coal_props: dict, constraints: dict = None,
        model_name: str = "RF", on_progress=None) -> dict:
    """单模型预测（向后兼容）。"""
    constraints = constraints or {}
    blend_ratios = _extract_ratios(blend_result)
    if not blend_ratios:
        return {"prediction": {}, "passed": False, "feedback": "配煤方案为空，无法预测"}

    prediction = predict_quality(blend_ratios, coal_props, model_name)
    if "error" in prediction:
        return {"prediction": prediction, "passed": False, "feedback": f"预测失败: {prediction['error']}"}

    evaluation = evaluate_quality(prediction, constraints)
    return {"prediction": prediction, "passed": evaluation["passed"], "feedback": evaluation["feedback"]}


def run_multi_model(blend_result: dict, coal_props: dict,
                    constraints: dict = None, on_progress=None) -> dict:
    """
    多模型竞赛评估：对同一方案跑所有可用模型，选出推荐模型，生成调整建议。

    Returns:
        {
            "all_predictions": {model_name: {CRI, CSR, ...}},
            "recommended_model": str,
            "prediction": dict,         # 推荐模型的预测值
            "passed": bool,
            "feedback": str,
            "adjustment_hint": dict,    # 给配煤工程师的调整方向
            "model_comparison": str,    # 模型对比摘要文本
        }
    """
    constraints = constraints or {}
    blend_ratios = _extract_ratios(blend_result)
    if not blend_ratios:
        return {
            "all_predictions": {}, "recommended_model": "N/A",
            "prediction": {}, "passed": False,
            "feedback": "配煤方案为空", "adjustment_hint": {}, "model_comparison": "",
        }

    # ── 跑所有模型 ──
    models = available_models()
    all_preds = {}
    for m in models:
        try:
            pred = predict_quality(blend_ratios, coal_props, m)
            if "error" not in pred:
                all_preds[m] = pred
        except Exception as e:
            logger.warning(f"模型 {m} 预测失败: {e}")

    if not all_preds:
        return {
            "all_predictions": {}, "recommended_model": "N/A",
            "prediction": {}, "passed": False,
            "feedback": "所有模型均预测失败", "adjustment_hint": {}, "model_comparison": "",
        }

    # ── 模型选择：保守策略 ──
    recommended, comparison = _select_model(all_preds, constraints)
    best_pred = all_preds[recommended]
    evaluation = evaluate_quality(best_pred, constraints)

    # ── 生成调整建议（仅不达标时） ──
    hint = {}
    if not evaluation["passed"]:
        hint = _generate_adjustment_hint(all_preds, constraints, blend_result, coal_props)

    return {
        "all_predictions": all_preds,
        "recommended_model": recommended,
        "prediction": best_pred,
        "passed": evaluation["passed"],
        "feedback": evaluation["feedback"],
        "adjustment_hint": hint,
        "model_comparison": comparison,
    }


def _extract_ratios(blend_result: dict) -> dict:
    """从配煤方案中提取有效配比。"""
    hoppers = blend_result.get("hoppers", [])
    return {h["coal"]: h["ratio"] for h in hoppers if h["ratio"] > 0.1}


def _select_model(all_preds: dict, constraints: dict) -> tuple[str, str]:
    """
    保守选择策略：
    1. 有约束时：选预测结果最接近约束边界（最不乐观）的模型
    2. 无约束时：选模型间中位数最近的模型
    返回 (推荐模型名, 对比摘要文本)
    """
    models = list(all_preds.keys())
    cri_values = {m: all_preds[m].get("CRI", 0) for m in models}
    csr_values = {m: all_preds[m].get("CSR", 0) for m in models}

    # 对比文本
    lines = []
    for m in models:
        lines.append(f"  {m}: CRI={cri_values[m]:.2f}, CSR={csr_values[m]:.2f}")
    comparison = "\n".join(lines)

    # 保守策略：取 CRI 最高的（最差情况）
    if "CRI_max" in constraints or "CSR_min" in constraints:
        # 有约束：选最保守的预测（CRI 最高 or CSR 最低）
        conservative_score = {}
        for m in models:
            score = 0
            if "CRI_max" in constraints:
                score += cri_values[m]  # CRI 越高越保守
            if "CSR_min" in constraints:
                score -= csr_values[m]  # CSR 越低越保守
            conservative_score[m] = score
        recommended = max(conservative_score, key=conservative_score.get)
    else:
        # 无约束：选中位数模型
        cri_median = float(np.median(list(cri_values.values())))
        recommended = min(models, key=lambda m: abs(cri_values[m] - cri_median))

    return recommended, comparison


def _generate_adjustment_hint(all_preds: dict, constraints: dict,
                              blend_result: dict, coal_props: dict) -> dict:
    """
    根据不达标原因生成给配煤工程师的调整方向。

    Returns:
        {
            "direction": str,           # "lower_cri" / "raise_csr" / "both"
            "cri_gap": float,           # CRI 超标多少
            "csr_gap": float,           # CSR 缺多少
            "high_cri_coals": [str],    # 建议减少的高 CRI 煤种
            "low_cri_coals": [str],     # 建议增加的低 CRI 煤种
            "weight_shift": float,      # 建议目标函数中质量权重提高多少
        }
    """
    # 取所有模型的平均预测
    cri_avg = np.mean([p.get("CRI", 0) for p in all_preds.values()])
    csr_avg = np.mean([p.get("CSR", 0) for p in all_preds.values()])

    cri_gap = 0.0
    csr_gap = 0.0
    direction = ""

    if "CRI_max" in constraints and cri_avg > constraints["CRI_max"]:
        cri_gap = cri_avg - constraints["CRI_max"]
        direction = "lower_cri"
    if "CSR_min" in constraints and csr_avg < constraints["CSR_min"]:
        csr_gap = constraints["CSR_min"] - csr_avg
        direction = "raise_csr" if not direction else "both"

    if not direction:
        return {}

    # 分析各煤种的 CRI/CSR 贡献
    hoppers = blend_result.get("hoppers", [])
    high_cri_coals = []
    low_cri_coals = []

    for h in hoppers:
        if h["ratio"] < 0.1:
            continue
        name = h["coal"]
        props = coal_props.get(name, {})
        coal_cri = float(props.get("coke_CRI") or 0)
        coal_csr = float(props.get("coke_CSR") or 0)
        if coal_cri > cri_avg + 5:
            high_cri_coals.append(name)
        if coal_cri < cri_avg - 5 and coal_csr > csr_avg:
            low_cri_coals.append(name)

    # 调整幅度建议
    weight_shift = min(0.3, (cri_gap + csr_gap) / 20)

    return {
        "direction": direction,
        "cri_gap": round(cri_gap, 2),
        "csr_gap": round(csr_gap, 2),
        "high_cri_coals": high_cri_coals,
        "low_cri_coals": low_cri_coals,
        "weight_shift": round(weight_shift, 3),
    }
