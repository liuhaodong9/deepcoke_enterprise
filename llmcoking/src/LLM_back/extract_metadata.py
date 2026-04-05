"""
从 CrossRef API 批量提取论文元数据（journal, volume, issue, pages, doi, authors）
并更新 papers.db
"""
import sqlite3
import requests
import time
import os
import re
import json

DB_PATH = "deepcoke/data/papers.db"
PDF_ROOT = "D:/deepcoke/deepcoke_enterprise/Coal blend paper/Coal blend papper"

# CrossRef API 查询
CROSSREF_URL = "https://api.crossref.org/works"
HEADERS = {
    "User-Agent": "DeepCoke/1.0 (mailto:liuhaodong@example.com)"
}


def clean_title_from_filename(filepath: str) -> str:
    """从文件名提取可搜索的标题"""
    fname = os.path.basename(filepath).replace(".pdf", "").replace(".PDF", "")
    # 去掉常见的前缀模式
    fname = re.sub(r"^(Shi et al\. \d{4}-?)", "", fname)
    fname = re.sub(r"^\d{4}_", "", fname)
    fname = re.sub(r"_", " ", fname)
    # 去掉括号中的年份
    fname = re.sub(r"\(\d{4}\)", "", fname)
    return fname.strip()


def query_crossref(title: str, year: int = None) -> dict | None:
    """查询 CrossRef API，返回最佳匹配的元数据"""
    params = {
        "query.bibliographic": title,
        "rows": 3,
        "select": "title,author,container-title,volume,issue,page,DOI,published-print,published-online,type,score",
    }
    try:
        resp = requests.get(CROSSREF_URL, params=params, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return None
        data = resp.json()
        items = data.get("message", {}).get("items", [])
        if not items:
            return None

        # 选择最佳匹配
        best = None
        best_score = 0
        for item in items:
            score = item.get("score", 0)
            # 标题相似度检查
            cr_title = ""
            if item.get("title"):
                cr_title = item["title"][0].lower()
            query_lower = title.lower()

            # 简单相似度：双向共同词比例
            query_words = set(re.findall(r'\w{3,}', query_lower))  # 忽略短词
            cr_words = set(re.findall(r'\w{3,}', cr_title))
            if query_words and cr_words:
                overlap_q = len(query_words & cr_words) / len(query_words)
                overlap_c = len(query_words & cr_words) / len(cr_words)
                overlap = max(overlap_q, overlap_c)
            else:
                overlap = 0

            if overlap < 0.3:
                continue  # 标题匹配度太低

            # 年份匹配加分
            cr_year = None
            for date_field in ("published-print", "published-online"):
                if item.get(date_field, {}).get("date-parts"):
                    parts = item[date_field]["date-parts"][0]
                    if parts:
                        cr_year = parts[0]
                        break

            year_bonus = 1.0
            if year and cr_year and abs(year - cr_year) <= 1:
                year_bonus = 1.5
            elif year and cr_year and abs(year - cr_year) > 5:
                year_bonus = 0.5

            adjusted = score * overlap * year_bonus
            if adjusted > best_score:
                best_score = adjusted
                best = item

        if not best:
            return None

        # 提取作者
        authors = []
        for a in best.get("author", []):
            name = ""
            if a.get("family"):
                name = a["family"]
                if a.get("given"):
                    name = f"{a['given']} {name}"
            elif a.get("name"):
                name = a["name"]
            if name:
                authors.append(name)

        # 提取年份
        cr_year = None
        for date_field in ("published-print", "published-online"):
            if best.get(date_field, {}).get("date-parts"):
                parts = best[date_field]["date-parts"][0]
                if parts:
                    cr_year = parts[0]
                    break

        # 提取真正的标题
        real_title = best["title"][0] if best.get("title") else None

        return {
            "title": real_title,
            "authors": ", ".join(authors) if authors else None,
            "year": cr_year,
            "journal": best.get("container-title", [None])[0] if best.get("container-title") else None,
            "volume": best.get("volume"),
            "issue": best.get("issue"),
            "pages": best.get("page"),
            "doi": best.get("DOI"),
        }
    except Exception as e:
        print(f"  CrossRef error: {e}")
        return None


def update_paper(conn, paper_id: int, meta: dict):
    """更新数据库中的论文元数据"""
    updates = []
    values = []

    # 更新标题（如果当前标题很差）
    if meta.get("title"):
        updates.append("title = ?")
        values.append(meta["title"])

    if meta.get("authors"):
        updates.append("authors = ?")
        values.append(meta["authors"])

    if meta.get("year"):
        updates.append("year = ?")
        values.append(meta["year"])

    for field in ("journal", "volume", "issue", "pages", "doi"):
        if meta.get(field):
            updates.append(f"{field} = ?")
            values.append(meta[field])

    if updates:
        values.append(paper_id)
        sql = f"UPDATE papers SET {', '.join(updates)} WHERE id = ?"
        conn.execute(sql, values)


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    papers = conn.execute(
        "SELECT id, file_path, title, authors, year, journal, doi FROM papers"
    ).fetchall()

    total = len(papers)
    updated = 0
    skipped = 0
    failed = 0

    print(f"开始处理 {total} 篇论文...\n")

    for i, paper in enumerate(papers):
        pid = paper["id"]
        filepath = paper["file_path"]
        db_title = paper["title"] or ""
        db_year = paper["year"]

        # 已有完整元数据的跳过
        if paper["journal"] and paper["doi"]:
            skipped += 1
            continue

        # 用文件名作为搜索标题（通常比DB中提取的标题更好）
        search_title = clean_title_from_filename(filepath)

        # 如果文件名太短或太通用，试试DB标题
        if len(search_title) < 10:
            search_title = db_title if len(db_title) > len(search_title) else search_title

        # 跳过纯中文标题（CrossRef主要是英文文献）
        if search_title and all(ord(c) > 0x4e00 for c in search_title.replace(" ", "") if c.isalpha()):
            # 全中文，跳过CrossRef
            print(f"[{i+1}/{total}] 跳过中文论文: {search_title[:50]}")
            skipped += 1
            continue

        print(f"[{i+1}/{total}] 查询: {search_title[:60]}...", end=" ", flush=True)

        meta = query_crossref(search_title, db_year)

        if meta:
            update_paper(conn, pid, meta)
            conn.commit()
            updated += 1
            journal = meta.get('journal', '')[:30] if meta.get('journal') else 'N/A'
            print(f"✓ {journal}")
        else:
            failed += 1
            print("✗ 未找到")

        # 控制请求频率（CrossRef 礼貌策略）
        time.sleep(0.5)

    conn.close()
    print(f"\n完成！更新: {updated}, 跳过: {skipped}, 未找到: {failed}")


if __name__ == "__main__":
    main()
