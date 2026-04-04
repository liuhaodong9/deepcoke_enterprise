"""
质量分析师 Skills — 焦炭质量预测、达标评估
"""

import logging

from ..coal_agent.quality_predictor import predictor

logger = logging.getLogger("deepcoke.skills.quality")


# ── Skill: 质量预测 ──────────────────────────────────────────────

def predict_quality(blend_ratios: dict, coal_props: dict,
                    model_name: str = "RF") -> dict:
    """
    根据配煤比例预测焦炭质量指标。

    Args:
        blend_ratios: {煤种名: 百分比}，如 {"气煤": 20, "肥煤": 30}
        coal_props: 煤样属性字典
        model_name: 预测模型名称 (RF/SVR/KNN/Linear/DecisionTree/GBR)
    Returns:
        {"CRI": float, "CSR": float, "Ad": float, "model": str}
    """
    return predictor.predict(blend_ratios, coal_props, model_name)


# ── Skill: 达标评估 ──────────────────────────────────────────────

def evaluate_quality(prediction: dict, constraints: dict) -> dict:
    """
    评估预测结果是否满足约束条件。

    Args:
        prediction: predict_quality 的返回值
        constraints: 约束条件 {CSR_min, CRI_max, ...}
    Returns:
        {"passed": bool, "feedback": str, "issues": list[str]}
    """
    if "error" in prediction:
        return {
            "passed": False,
            "feedback": f"预测失败: {prediction['error']}",
            "issues": [prediction["error"]],
        }

    passed = True
    issues = []

    cri = prediction.get("CRI")
    csr = prediction.get("CSR")

    if cri is not None:
        if "CRI_max" in constraints and cri > constraints["CRI_max"]:
            passed = False
            issues.append(f"CRI={cri:.2f}，超过上限{constraints['CRI_max']}（差{cri - constraints['CRI_max']:.2f}）")
        if "CRI_min" in constraints and cri < constraints["CRI_min"]:
            passed = False
            issues.append(f"CRI={cri:.2f}，低于下限{constraints['CRI_min']}（差{constraints['CRI_min'] - cri:.2f}）")

    if csr is not None:
        if "CSR_min" in constraints and csr < constraints["CSR_min"]:
            passed = False
            issues.append(f"CSR={csr:.2f}，低于下限{constraints['CSR_min']}（差{constraints['CSR_min'] - csr:.2f}）")
        if "CSR_max" in constraints and csr > constraints["CSR_max"]:
            passed = False
            issues.append(f"CSR={csr:.2f}，超过上限{constraints['CSR_max']}（差{csr - constraints['CSR_max']:.2f}）")

    if passed:
        feedback = "所有质量指标均满足约束要求。"
    else:
        feedback = "质量指标不达标：" + "；".join(issues) + "。请调整配煤方案。"

    return {
        "passed": passed,
        "feedback": feedback,
        "issues": issues,
    }


# ── Skill: 可用模型列表 ──────────────────────────────────────────

def available_models() -> list[str]:
    """返回可用的预测模型列表。"""
    return predictor.available_models()
