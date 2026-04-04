"""数据库连接 - 从 MySQL 读取/管理煤样数据"""

import pymysql
import logging

logger = logging.getLogger("deepcoke.coal_db")

DB_HOST = "127.0.0.1"
DB_PORT = 3306
DB_USER = "root"
DB_PASSWORD = "123456"
DB_NAME = "coaldata"

# 配煤优化核心字段
CORE_FIELDS = [
    "id", "coal_name", "coal_type", "coal_price",
    "coal_mad", "coal_ad", "coal_vdaf", "coal_std",
    "G", "X", "Y",
    "coke_CRI", "coke_CSR", "coke_M10", "coke_M25", "coke_M40",
]

# 允许写入的字段（防注入）
WRITABLE_FIELDS = {
    "coal_name", "coal_type", "coal_price",
    "coal_mad", "coal_ad", "coal_vdaf", "coal_std",
    "G", "X", "Y",
    "coke_CRI", "coke_CSR", "coke_M10", "coke_M25", "coke_M40",
}


def _conn():
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        database=DB_NAME, charset="utf8", cursorclass=pymysql.cursors.DictCursor,
    )


def get_all_coals() -> list[dict]:
    """查询所有有效煤样（用于配煤优化）。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, coal_name, coal_type, coal_price,
                       coal_mad, coal_ad, coal_vdaf, coal_std,
                       G, X, Y,
                       coke_CRI, coke_CSR, coke_M10, coke_M25, coke_M40
                FROM coaldata_table
                WHERE coal_name IS NOT NULL
                  AND G IS NOT NULL
                  AND coke_CRI IS NOT NULL
                ORDER BY coal_name
            """)
            return cur.fetchall()
    finally:
        conn.close()


def get_coal_by_name(name: str) -> dict | None:
    """按名称查询单个煤样。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            fields = ", ".join(CORE_FIELDS)
            cur.execute(f"SELECT {fields} FROM coaldata_table WHERE coal_name = %s", (name,))
            return cur.fetchone()
    finally:
        conn.close()


def add_coal(data: dict) -> dict:
    """新增煤样，返回 {"ok": True, "id": ...} 或 {"ok": False, "error": ...}。"""
    if "coal_name" not in data or not data["coal_name"]:
        return {"ok": False, "error": "缺少煤样名称"}
    # 检查重名
    if get_coal_by_name(data["coal_name"]):
        return {"ok": False, "error": f"煤样 '{data['coal_name']}' 已存在"}
    # 过滤合法字段
    safe = {k: v for k, v in data.items() if k in WRITABLE_FIELDS and v is not None}
    if not safe:
        return {"ok": False, "error": "没有有效字段"}
    cols = ", ".join(safe.keys())
    phs = ", ".join(["%s"] * len(safe))
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"INSERT INTO coaldata_table ({cols}) VALUES ({phs})", list(safe.values()))
        conn.commit()
        return {"ok": True, "id": conn.insert_id(), "coal_name": data["coal_name"]}
    except Exception as e:
        conn.rollback()
        return {"ok": False, "error": str(e)}
    finally:
        conn.close()


def update_coal(name: str, data: dict) -> dict:
    """按名称更新煤样字段。"""
    if not get_coal_by_name(name):
        return {"ok": False, "error": f"煤样 '{name}' 不存在"}
    safe = {k: v for k, v in data.items() if k in WRITABLE_FIELDS and v is not None}
    if not safe:
        return {"ok": False, "error": "没有有效更新字段"}
    sets = ", ".join(f"{k} = %s" for k in safe.keys())
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE coaldata_table SET {sets} WHERE coal_name = %s",
                        list(safe.values()) + [name])
        conn.commit()
        return {"ok": True, "coal_name": name, "updated": list(safe.keys())}
    except Exception as e:
        conn.rollback()
        return {"ok": False, "error": str(e)}
    finally:
        conn.close()


def delete_coal(name: str) -> dict:
    """按名称删除煤样。"""
    if not get_coal_by_name(name):
        return {"ok": False, "error": f"煤样 '{name}' 不存在"}
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM coaldata_table WHERE coal_name = %s", (name,))
        conn.commit()
        return {"ok": True, "coal_name": name}
    except Exception as e:
        conn.rollback()
        return {"ok": False, "error": str(e)}
    finally:
        conn.close()


def batch_add_coals(coal_list: list[dict]) -> dict:
    """批量新增煤样。"""
    results = {"success": [], "failed": []}
    for item in coal_list:
        r = add_coal(item)
        if r["ok"]:
            results["success"].append(r["coal_name"])
        else:
            results["failed"].append({"coal_name": item.get("coal_name", "?"), "error": r["error"]})
    return results
