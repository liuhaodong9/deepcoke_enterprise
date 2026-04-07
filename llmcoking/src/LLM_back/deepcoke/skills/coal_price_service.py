"""
煤炭市场价格查询服务（模拟数据）
按日期种子生成每日变化价格，同一天返回一致结果。
"""
import hashlib
from datetime import datetime


# 煤种基准数据：{煤种名: {base_price, coal_type, quality_range}}
_COAL_MARKET = {
    "澳大利亚焦煤": {
        "base_price": 3200,
        "coal_type": "主焦煤",
        "source_region": "澳大利亚",
        "quality": {
            "csr_range": [60, 65],
            "cri_range": [25, 30],
            "recommended_ratio": "50%-60%",
            "ad_range": [9, 11],
            "vdaf_range": [20, 25],
            "g_range": [85, 95],
        },
    },
    "山西主焦煤": {
        "base_price": 2800,
        "coal_type": "主焦煤",
        "source_region": "山西",
        "quality": {
            "csr_range": [58, 63],
            "cri_range": [26, 31],
            "recommended_ratio": "45%-55%",
            "ad_range": [9, 12],
            "vdaf_range": [22, 28],
            "g_range": [80, 92],
        },
    },
    "唐山肥煤": {
        "base_price": 1950,
        "coal_type": "肥煤",
        "source_region": "唐山",
        "quality": {
            "csr_range": [50, 55],
            "cri_range": [32, 38],
            "recommended_ratio": "20%-30%",
            "ad_range": [10, 13],
            "vdaf_range": [28, 35],
            "g_range": [85, 100],
        },
    },
    "淮北气煤": {
        "base_price": 1200,
        "coal_type": "气煤",
        "source_region": "淮北",
        "quality": {
            "csr_range": [35, 42],
            "cri_range": [40, 50],
            "recommended_ratio": "15%-25%",
            "ad_range": [7, 10],
            "vdaf_range": [33, 40],
            "g_range": [65, 80],
        },
    },
    "邢台瘦煤": {
        "base_price": 1650,
        "coal_type": "瘦煤",
        "source_region": "邢台",
        "quality": {
            "csr_range": [55, 60],
            "cri_range": [28, 33],
            "recommended_ratio": "5%-15%",
            "ad_range": [8, 11],
            "vdaf_range": [15, 22],
            "g_range": [40, 65],
        },
    },
    "蒙古焦煤": {
        "base_price": 2600,
        "coal_type": "主焦煤",
        "source_region": "蒙古",
        "quality": {
            "csr_range": [56, 62],
            "cri_range": [27, 32],
            "recommended_ratio": "40%-50%",
            "ad_range": [9, 12],
            "vdaf_range": [21, 26],
            "g_range": [82, 90],
        },
    },
}

# 煤种别名映射
_ALIASES = {
    "澳洲焦煤": "澳大利亚焦煤",
    "澳煤": "澳大利亚焦煤",
    "澳大利亚煤": "澳大利亚焦煤",
    "山西焦煤": "山西主焦煤",
    "唐山煤": "唐山肥煤",
    "气煤": "淮北气煤",
    "瘦煤": "邢台瘦煤",
    "蒙古煤": "蒙古焦煤",
}


def _daily_variation(coal_name: str) -> int:
    """基于日期和煤名生成每日价格波动（-100 ~ +100）"""
    today = datetime.now().strftime("%Y-%m-%d")
    seed = hashlib.md5(f"{today}_{coal_name}".encode()).hexdigest()
    return int(seed[:4], 16) % 201 - 100


def _resolve_name(name: str) -> str:
    """模糊匹配煤种名称"""
    if name in _COAL_MARKET:
        return name
    if name in _ALIASES:
        return _ALIASES[name]
    # 模糊搜索
    for key in _COAL_MARKET:
        if name in key or key in name:
            return key
    for alias, real in _ALIASES.items():
        if name in alias or alias in name:
            return real
    return ""


def get_price(coal_type: str) -> dict | None:
    """查询指定煤种的今日价格"""
    resolved = _resolve_name(coal_type)
    if not resolved:
        return None

    info = _COAL_MARKET[resolved]
    variation = _daily_variation(resolved)
    price = info["base_price"] + variation
    now = datetime.now()
    update_time = now.strftime("%Y-%m-%d") + " 07:00"

    return {
        "coal_name": resolved,
        "coal_type": info["coal_type"],
        "source_region": info["source_region"],
        "price": price,
        "unit": "元/吨",
        "source": "钢铁煤炭网",
        "update_time": update_time,
    }


def get_quality_range(coal_type: str) -> dict | None:
    """查询指定煤种作为主焦煤时的焦炭质量参数范围"""
    resolved = _resolve_name(coal_type)
    if not resolved:
        return None

    info = _COAL_MARKET[resolved]
    q = info["quality"]
    return {
        "coal_name": resolved,
        "coal_type": info["coal_type"],
        "csr_range": q["csr_range"],
        "cri_range": q["cri_range"],
        "recommended_ratio": q["recommended_ratio"],
        "ad_range": q.get("ad_range"),
        "vdaf_range": q.get("vdaf_range"),
        "g_range": q.get("g_range"),
    }


def get_all_prices() -> list[dict]:
    """返回所有煤种今日价格"""
    return [get_price(name) for name in _COAL_MARKET]
