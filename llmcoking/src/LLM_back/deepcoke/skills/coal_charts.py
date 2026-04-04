"""
煤样��据可视化 — 生成 ECharts 前端图表描述符（JSON）
"""
import logging

logger = logging.getLogger("deepcoke.skills.coal_charts")


def generate_overview_chart_data(rows: list[dict]) -> list[dict]:
    """生成煤样总览图表描述符列表，供前端 ECharts 渲染。"""
    charts = []

    # ── 图1: CRI vs CSR 散点图 ──
    try:
        valid = [
            {"name": r.get("coal_name", "?"),
             "cri": round(float(r.get("coke_CRI") or 0), 1),
             "csr": round(float(r.get("coke_CSR") or 0), 1)}
            for r in rows
            if float(r.get("coke_CRI") or 0) > 0 and float(r.get("coke_CSR") or 0) > 0
        ]
        if valid:
            charts.append({
                "chartType": "scatter",
                "title": f"煤样 CRI-CSR 分布（{len(valid)} 条）",
                "xLabel": "CRI（反应性）",
                "yLabel": "CSR（反应后强度）",
                "data": valid,
            })
    except Exception as e:
        logger.warning(f"散点图数据生成失败: {e}")

    # ── 图2: 关键指标分布直方图 ──
    try:
        metrics = [
            ("coal_ad", "灰分 Ad (%)"),
            ("coal_vdaf", "挥发分 Vdaf (%)"),
            ("G", "粘结指数 G"),
            ("coke_CRI", "CRI (%)"),
            ("coke_CSR", "CSR (%)"),
        ]
        hist_data = {}
        for key, label in metrics:
            vals = [round(float(r.get(key) or 0), 2) for r in rows if r.get(key)]
            if vals:
                hist_data[label] = vals
        if hist_data:
            charts.append({
                "chartType": "histogram",
                "title": "煤样关键指标分布",
                "metrics": hist_data,
            })
    except Exception as e:
        logger.warning(f"直方图数据生成失败: {e}")

    # ── 图3: 煤种类型饼图 ──
    try:
        from collections import Counter
        types = [str(r.get("coal_type") or "未知").strip() for r in rows]
        top = Counter(types).most_common(10)
        if top:
            charts.append({
                "chartType": "pie",
                "title": "煤种类型分布",
                "data": [{"name": n, "value": c} for n, c in top],
            })
    except Exception as e:
        logger.warning(f"饼图数据生成失败: {e}")

    return charts


def generate_single_coal_chart_data(coal: dict) -> dict | None:
    """生成单个煤样的雷达图描述符。"""
    metrics = [
        ("coal_ad", "灰分Ad", 25),
        ("coal_vdaf", "Vdaf", 45),
        ("coal_std", "硫分", 5),
        ("G", "G值", 110),
        ("Y", "Y值", 35),
        ("coke_CRI", "CRI", 60),
        ("coke_CSR", "CSR", 80),
    ]

    indicators = []
    values = []
    for key, name, max_val in metrics:
        v = coal.get(key)
        if v is not None and float(v) > 0:
            indicators.append({"name": name, "max": max_val})
            values.append(round(float(v), 2))

    if len(indicators) < 3:
        return None

    return {
        "chartType": "radar",
        "title": f"煤样「{coal.get('coal_name', '未知')}」指标雷达图",
        "indicators": indicators,
        "values": values,
    }
