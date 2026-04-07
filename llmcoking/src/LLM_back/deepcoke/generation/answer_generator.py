"""
Evidence-driven answer generation module.
Generates answers grounded in retrieved literature evidence with inline citations.
"""
from ..llm_client import chat
from ..vectorstore.retriever import RetrievedChunk


def build_evidence_context(chunks: list[RetrievedChunk]) -> tuple[str, list[dict]]:
    """
    Build a formatted evidence context string and reference list from retrieved chunks.

    Returns:
        (evidence_text, references_list)
    """
    if not chunks:
        return "", []

    # Deduplicate by paper_id, keeping highest score per paper
    seen_papers = {}
    for chunk in chunks:
        pid = chunk.paper_id
        if pid not in seen_papers or chunk.score > seen_papers[pid]["score"]:
            seen_papers[pid] = {
                "chunk": chunk,
                "score": chunk.score,
            }

    # Also include unique chunks from same paper if they cover different sections
    unique_chunks = []
    paper_sections = set()
    for chunk in chunks:
        key = (chunk.paper_id, chunk.section)
        if key not in paper_sections:
            paper_sections.add(key)
            unique_chunks.append(chunk)

    # Build evidence text with citation numbers
    evidence_parts = []
    references = []
    ref_map = {}  # paper_id -> reference number

    for i, chunk in enumerate(unique_chunks[:10], 1):
        pid = chunk.paper_id
        if pid not in ref_map:
            ref_map[pid] = len(references) + 1
            # 提取原文摘录（用于悬浮提示）和搜索词
            excerpt = ""
            search_hint = ""
            if hasattr(chunk, "text") and chunk.text:
                excerpt = chunk.text.strip()[:200]
                words = chunk.text.strip().split()[:6]
                search_hint = " ".join(words)[:40]
            references.append({
                "num": ref_map[pid],
                "paper_id": pid,
                "title": chunk.title,
                "year": chunk.year,
                "authors": chunk.authors,
                "category": chunk.category,
                "journal": chunk.journal,
                "volume": chunk.volume,
                "issue": chunk.issue,
                "pages": chunk.pages,
                "doi": chunk.doi,
                "search_hint": search_hint,
                "excerpt": excerpt,
            })

        ref_num = ref_map[pid]
        evidence_parts.append(
            f"[{ref_num}] ({chunk.section}) {chunk.text[:600]}"
        )

    evidence_text = "\n\n".join(evidence_parts)
    return evidence_text, references


def format_references(references: list[dict], api_base: str = "") -> str:
    """Format the reference list with clickable PDF links.

    每条参考文献可点击查看原文 PDF。
    """
    if not references:
        return ""

    lines = ["\n\n---\n\n**参考文献：**\n\n"]
    for ref in references:
        # 清理作者字段（数据库可能存的是 "[]" 空列表）
        authors = ref.get("authors", "") or ""
        if authors in ("[]", "['']", ""):
            authors = ""
        if len(authors) > 60:
            authors = authors[:60] + ", et al."

        import html as html_mod
        title = html_mod.unescape(ref.get("title", "") or "")
        year = ref.get("year", "") or ""
        journal = html_mod.unescape(ref.get("journal", "") or "")
        volume = ref.get("volume", "") or ""
        issue = ref.get("issue", "") or ""
        pages = ref.get("pages", "") or ""
        doi = ref.get("doi", "") or ""
        category = ref.get("category", "") or ""
        paper_id = ref.get("paper_id", "")

        # 构建引用文本（GB/T 7714—2015 格式）
        # 完整格式：作者. 题名[J]. 刊名, 年, 卷(期): 页码.
        # 缺少期刊信息时：作者. 题名[R/OL]. 年. 分类.
        parts = []
        if authors:
            parts.append(f"{authors}.")
        parts.append(f" {title}")

        if journal:
            # 期刊论文
            parts.append("[J].")
            parts.append(f" {journal}")
            if year:
                parts.append(f", {year}")
            if volume:
                vol = f", {volume}"
                if issue:
                    vol += f"({issue})"
                parts.append(vol)
            if pages:
                parts.append(f": {pages}")
            parts.append(".")
        else:
            # 报告/会议/其他（无期刊信息）
            parts.append("[R].")
            if year:
                parts.append(f" {year}.")
            if category:
                parts.append(f" ({category})")

        if doi:
            parts.append(f" DOI: {doi}.")
        cite_text = "".join(parts)

        # 生成可点击链接（点击查看原文 PDF，带搜索高亮参数）
        if paper_id:
            import urllib.parse
            import html as html_mod
            search = ref.get("search_hint", "")
            search_param = f"&search={urllib.parse.quote(search)}" if search else ""
            excerpt_attr = html_mod.escape(ref.get("excerpt", ""), quote=True)
            line = (
                f'<a href="/pdf_viewer/{paper_id}?ref={ref["num"]}{search_param}" target="_blank" '
                f'class="ref-link" data-ref="{ref["num"]}" '
                f'data-excerpt="{excerpt_attr}"'
                f'>[{ref["num"]}] {cite_text}</a>'
            )
        else:
            line = f"[{ref['num']}] {cite_text}"

        lines.append(line + "<br>")

    return "\n".join(lines)


def build_answer_prompt(
    question: str,
    evidence_text: str,
    kg_context: str = "",
    reasoning_trace: str = "",
) -> list[dict]:
    """Build the prompt messages for answer generation."""
    system_prompt = (
        "你是焦化大语言智能问答与分析系统DeepCoke，由苏州龙泰氢一能源科技有限公司研发。"
        "请基于提供的文献证据回答用户问题。\n\n"
        "要求：\n"
        "1. 用中文回答，专业术语可保留英文\n"
        "2. 引用证据时使用 [1][2] 等标注\n"
        "3. 如果证据不足以完全回答问题，明确说明哪些方面需要进一步研究\n"
        "4. 使用标准 Markdown 格式，标题用 ## 或 ###（不要用 #），标题前后各空一行\n"
        "5. 数学公式使用 $$ 包裹\n"
        "6. 不要提供 mermaid 图\n"
        "7. 回答要有逻辑结构，先概述再详述\n"
        "8. 当文献证据中包含可量化数据（如温度、百分比、性能指标对比等）时，"
        "请在回答中插入 ECharts 图表标记来可视化这些数据。格式为：\n"
        '<!--ECHART:{"chartType":"bar","title":"图表标题","xLabel":"X轴","yLabel":"Y轴",'
        '"categories":["A","B","C"],"series":[{"name":"系列1","data":[1,2,3]}]}-->\n'
        "支持的 chartType: bar(柱状图)、line(折线图)、scatter(散点图)、pie(饼图)。\n"
        "scatter 的 data 格式: [{\"name\":\"点名\",\"x\":1,\"y\":2},...]\n"
        "pie 的 data 格式: [{\"name\":\"类别\",\"value\":10},...]\n"
        "数据必须来自文献证据中的真实数据，不要编造数值。每个回答最多插入2个图表。"
    )

    user_parts = [f"**用户问题：** {question}\n"]

    if evidence_text:
        user_parts.append(f"**相关文献证据：**\n{evidence_text}\n")

    if kg_context:
        user_parts.append(f"**知识图谱信息：**\n{kg_context}\n")

    if reasoning_trace:
        user_parts.append(f"**推理分析：**\n{reasoning_trace}\n")

    if not evidence_text and not kg_context:
        user_parts.append(
            "（未检索到直接相关的文献证据，请基于你的专业知识回答，并说明需要进一步查阅文献。）"
        )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def generate_answer_stream(
    question: str,
    chunks: list[RetrievedChunk],
    kg_context: str = "",
    reasoning_trace: str = "",
):
    """
    Generate a streaming answer with citations.

    Yields text chunks that can be streamed to the frontend.
    Also yields the reference section at the end.
    """
    evidence_text, references = build_evidence_context(chunks)
    messages = build_answer_prompt(question, evidence_text, kg_context, reasoning_trace)

    # Stream the main answer
    stream = chat(messages, stream=True)
    full_response_parts = []

    for chunk in stream:
        if not getattr(chunk, "choices", None):
            continue
        delta = chunk.choices[0].delta
        piece = getattr(delta, "content", None)
        if not piece:
            continue
        full_response_parts.append(piece)
        yield piece

    # Append references
    if references:
        ref_text = format_references(references)
        yield ref_text
        full_response_parts.append(ref_text)

    # 附上引用论文中的图片
    if references:
        try:
            from .pdf_figures import get_figures_for_references
            paper_ids = [r["paper_id"] for r in references if r.get("paper_id")]
            figures = get_figures_for_references(paper_ids, max_total=4)
            if figures:
                fig_parts = ["\n\n---\n\n**文献图表：**\n\n"]
                for fig in figures:
                    ref_num = ""
                    for r in references:
                        if r.get("paper_id") == fig.get("paper_id"):
                            ref_num = f"[{r['num']}]"
                            break
                    caption = fig.get("caption", "")
                    caption_html = f'<br><span style="color:#334155;font-size:13px;">{caption}</span>' if caption else ""
                    fig_parts.append(
                        f'<div style="margin:12px 0;padding:10px;background:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;">'
                        f'<img src="{fig["url"]}" alt="文献图 {ref_num} p.{fig["page"]}" '
                        f'style="max-width:100%;border-radius:4px;">'
                        f'{caption_html}'
                        f'<br><small style="color:#94A3B8;">来源：{ref_num} 第{fig["page"]}页</small>'
                        f'</div>\n\n'
                    )
                fig_html = "".join(fig_parts)
                yield fig_html
        except Exception as e:
            import logging
            logging.getLogger("deepcoke").warning(f"提取文献图片失败: {e}")
