"""
从 PDF 中提取图表（单独图片 + 对应标题描述）。
策略：
  1. 提取嵌入的大图（>=200x200），匹配最近的 Figure/Table 标题
  2. 扫描版 PDF（整页大图）→ 裁切包含图表的区域
"""
import io
import os
import re
import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger("deepcoke.pdf_figures")

# 图片缓存目录
FIGURE_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "figures"
FIGURE_DIR.mkdir(parents=True, exist_ok=True)

# PDF 搜索根目录
PDF_ROOT = Path("D:/deepcoke/deepcoke_enterprise/Coal blend paper/Coal blend papper")

# papers.db 路径
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "papers.db"

# Figure/Table 标题正则
_CAPTION_RE = re.compile(
    r'((?:Fig(?:ure|\.)?|Table)\s*\.?\s*\d+[\.\:：]?\s*[^\n]{0,300})',
    re.IGNORECASE,
)


def _find_pdf(paper_id: int) -> Path | None:
    """根据 paper_id 从 papers.db 获取文件名，在 PDF_ROOT 下查找"""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        row = conn.execute(
            "SELECT file_path FROM papers WHERE id=?", (paper_id,)
        ).fetchone()
        conn.close()
        if not row:
            return None

        fname = os.path.basename(row[0])
        for dirpath, _, files in os.walk(PDF_ROOT):
            if fname in files:
                return Path(dirpath) / fname
    except Exception as e:
        logger.warning(f"查找 PDF 失败: {e}")
    return None


def _is_fullpage_scan(doc) -> bool:
    """判断 PDF 是否为扫描版（每页只有一个接近页面尺寸的大图）"""
    if len(doc) < 2:
        return False
    # 检查前3页
    scan_pages = 0
    for pn in range(min(3, len(doc))):
        page = doc[pn]
        images = page.get_images(full=True)
        if len(images) == 1:
            try:
                import fitz
                pix = fitz.Pixmap(doc, images[0][0])
                # 图片尺寸接近页面（宽高都>1500）→ 扫描版
                if pix.width >= 1500 and pix.height >= 1500:
                    scan_pages += 1
            except Exception:
                pass
    return scan_pages >= 2


def _extract_captions(page) -> list[dict]:
    """提取页面中所有 Figure/Table 标题及其在页面上的 Y 位置"""
    text_dict = page.get_text("dict")
    captions = []
    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:  # 文本块
            continue
        block_text = ""
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                block_text += span.get("text", "")
            block_text += " "

        for m in _CAPTION_RE.finditer(block_text):
            caption_text = m.group(1).strip()
            # 过滤掉引用性质的（如 "Fig. 1)." 太短的）
            if len(caption_text) < 20:
                continue
            # 标题的 Y 位置（取 block 的 bbox 中心）
            bbox = block["bbox"]
            y_center = (bbox[1] + bbox[3]) / 2
            captions.append({
                "text": caption_text,
                "y": y_center,
                "bbox": bbox,
            })
    return captions


def _extract_individual_figures(doc, cache_dir: Path, max_figures: int) -> list[dict]:
    """从非扫描版 PDF 提取独立嵌入图片 + 匹配标题"""
    import fitz

    figures = []
    seen_xrefs = set()

    for pn in range(1, len(doc)):  # 跳过首页
        page = doc[pn]
        images = page.get_images(full=True)
        captions = _extract_captions(page)

        for img_info in images:
            xref = img_info[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)

            try:
                pix = fitz.Pixmap(doc, xref)
                # 跳过小图（logo、图标等）
                if pix.width < 200 or pix.height < 200:
                    continue
                # 跳过全页扫描图
                if pix.width >= 1500 and pix.height >= 1500:
                    continue

                # 转换为 RGB（如果是 CMYK 等）
                if pix.n > 4:
                    pix = fitz.Pixmap(fitz.csRGB, pix)

                # 获取图片在页面上的位置
                img_rects = page.get_image_rects(img_info)
                img_y = img_rects[0].y1 if img_rects else 0  # 图片底部 Y

                # 匹配最近的 caption（图片下方最近的标题）
                caption = ""
                if captions:
                    # 找图片下方最近的标题
                    below_caps = [c for c in captions if c["y"] > img_y - 20]
                    if below_caps:
                        below_caps.sort(key=lambda c: abs(c["y"] - img_y))
                        caption = below_caps[0]["text"]
                    else:
                        # 没有下方标题，取最近的
                        captions.sort(key=lambda c: abs(c["y"] - img_y))
                        caption = captions[0]["text"]

                # 保存图片
                img_name = f"fig_p{pn+1}_x{xref}.png"
                img_path = cache_dir / img_name
                pix.save(str(img_path))

                figures.append({
                    "url": f"/static/figures/{cache_dir.name}/{img_name}",
                    "page": pn + 1,
                    "caption": caption,
                    "width": pix.width,
                    "height": pix.height,
                })

                if len(figures) >= max_figures:
                    return figures

            except Exception as e:
                logger.debug(f"提取图片失败 xref={xref}: {e}")
                continue

    return figures


def _extract_scan_figures(doc, cache_dir: Path, max_figures: int) -> list[dict]:
    """从扫描版 PDF 提取：找到有 Figure/Table 标题的页面，裁切图表区域"""
    import fitz

    figures = []

    for pn in range(1, len(doc)):  # 跳过首页
        page = doc[pn]
        captions = _extract_captions(page)
        if not captions:
            continue

        page_rect = page.rect
        page_height = page_rect.height

        for cap in captions:
            # 裁切图表区域：标题上方是图表主体
            # 取标题位置上方 40% 页高 到标题下方一点的区域
            cap_y = cap["y"]
            clip_top = max(0, cap_y - page_height * 0.4)
            clip_bottom = min(page_height, cap_y + 30)

            clip_rect = fitz.Rect(0, clip_top, page_rect.width, clip_bottom)

            # 渲染裁切区域（2倍缩放）
            mat = fitz.Matrix(2.0, 2.0)
            pix = page.get_pixmap(matrix=mat, clip=clip_rect)

            # 跳过太小的裁切
            if pix.height < 100:
                continue

            img_name = f"fig_p{pn+1}_y{int(cap_y)}.png"
            img_path = cache_dir / img_name
            pix.save(str(img_path))

            figures.append({
                "url": f"/static/figures/{cache_dir.name}/{img_name}",
                "page": pn + 1,
                "caption": cap["text"],
                "width": pix.width,
                "height": pix.height,
            })

            if len(figures) >= max_figures:
                return figures

    return figures


def extract_figures(paper_id: int, max_figures: int = 4) -> list[dict]:
    """
    从论文 PDF 中提取图表（图片 + 标题描述）。

    返回: [{"url": "/static/figures/xx/fig_p3_x45.png", "page": 3, "caption": "Fig. 3. ..."}, ...]
    """
    # 检查缓存
    cache_dir = FIGURE_DIR / str(paper_id)
    if cache_dir.exists() and list(cache_dir.glob("fig_*.png")):
        figures = []
        for img_file in sorted(cache_dir.glob("fig_*.png"))[:max_figures]:
            page_num = int(re.search(r'_p(\d+)_', img_file.name).group(1))
            figures.append({
                "url": f"/static/figures/{paper_id}/{img_file.name}",
                "page": page_num,
                "caption": "",  # 缓存读取不含 caption，但已够用
            })
        return figures

    # 查找 PDF 文件
    pdf_path = _find_pdf(paper_id)
    if not pdf_path:
        return []

    try:
        import fitz

        doc = fitz.open(str(pdf_path))
        cache_dir.mkdir(parents=True, exist_ok=True)

        # 清理旧缓存（page_*.png 是旧格式）
        for old in cache_dir.glob("page_*.png"):
            old.unlink()

        if _is_fullpage_scan(doc):
            figures = _extract_scan_figures(doc, cache_dir, max_figures)
        else:
            figures = _extract_individual_figures(doc, cache_dir, max_figures)

        doc.close()
        return figures

    except Exception as e:
        logger.warning(f"提取图表失败 paper_id={paper_id}: {e}")
        return []


def get_figures_for_references(paper_ids: list[int], max_total: int = 4) -> list[dict]:
    """
    为多篇引用论文提取图表，总数不超过 max_total。
    返回: [{"url": ..., "page": ..., "caption": ..., "paper_id": ...}, ...]
    """
    all_figures = []
    per_paper = max(1, max_total // len(paper_ids)) if paper_ids else 0

    for pid in paper_ids:
        figs = extract_figures(pid, max_figures=per_paper)
        for f in figs:
            f["paper_id"] = pid
            all_figures.append(f)
        if len(all_figures) >= max_total:
            break

    return all_figures[:max_total]
