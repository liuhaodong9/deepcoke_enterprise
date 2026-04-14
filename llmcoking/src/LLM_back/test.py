from fastapi import FastAPI, Depends, HTTPException  # 导入 FastAPI 和 Depends 依赖
from sqlalchemy import create_engine, Column, Integer, String, Text, TIMESTAMP, ForeignKey  # 导入 SQLAlchemy 组件
from sqlalchemy.ext.declarative import declarative_base  # 定义数据库模型
from sqlalchemy.orm import sessionmaker, Session, relationship  # 处理数据库会话
from uuid import uuid4  # 生成唯一 session_id（Python 内置库，无需安装）
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.sql import func  # 导入 SQL 函数
from datetime import datetime  # 导入 datetime
from openai import OpenAI  # DeepSeek 兼容 OpenAI API
from starlette.responses import StreamingResponse
import asyncio
import traceback
import logging
from pydantic import BaseModel
import hashlib

# ── DeepCoke Pipeline ──────────────────────────────────────────────
from deepcoke.pipeline_graph import process_question  # LangGraph 版 pipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("deepcoke")

from fastapi.staticfiles import StaticFiles
import os

app = FastAPI() # 创建一个 FastAPI「实例」

# 挂载静态文件目录（文献图片等）
_static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(_static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=_static_dir), name="static")

# 使用 config 中的 LLM 配置（默认 Ollama 本地 Qwen3）
from deepcoke import config as _cfg
DEEPSEEK_API_KEY = _cfg.DEEPSEEK_API_KEY
DEEPSEEK_BASE_URL = _cfg.DEEPSEEK_BASE_URL

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

# 允许前端访问后端（CORS 处理）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有前端访问
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE_URL = "mysql+pymysql://root:123456@127.0.0.1:3306/chat_db?charset=utf8mb4"
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)  # 创建数据库会话
Base = declarative_base()  # 创建数据库模型基类

# 定义用户表（存储注册用户）
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    nickname = Column(String(50), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now())

# 定义会话表（存储用户 ID 和会话 ID）
class ChatSession(Base):
    __tablename__ = "chat_sessions"  # 表名
    id = Column(Integer, primary_key=True, autoincrement=True)  # 主键，自增
    user_id = Column(String(50), nullable=False)  # 用户 ID（标识用户）
    session_id = Column(String(50), unique=True, nullable=False)  # 唯一会话 ID（用于存储对话）

# 定义消息表（存储聊天记录）
class Message(Base):
    __tablename__ = "messages"  # 表名
    id = Column(Integer, primary_key=True, autoincrement=True)  # 主键，自增
    session_id = Column(String(50), ForeignKey("chat_sessions.session_id"), nullable=False)  # 关联会话 ID
    user_message = Column(Text, nullable=False)  # 用户输入的消息
    bot_response = Column(Text(length=2**32-1), nullable=False)  # AI 生成的回复（LONGTEXT）
    timestamp = Column(TIMESTAMP, nullable=False)  # 记录时间戳

# 延迟初始化数据库（在 FastAPI 启动事件中执行，避免模块加载时 MySQL 未启动导致崩溃）
@app.on_event("startup")
def _startup_init_db():
    try:
        Base.metadata.create_all(bind=engine)
        # 创建默认管理员账号
        db = SessionLocal()
        try:
            if not db.query(User).filter(User.username == "admin").first():
                admin = User(
                    username="admin",
                    password_hash=hashlib.sha256("123456".encode('utf-8')).hexdigest(),
                    nickname="管理员"
                )
                db.add(admin)
                db.commit()
                print("已创建默认管理员账号: admin / 123456")
        finally:
            db.close()
        logger.info("MySQL 数据库初始化成功")
    except Exception as e:
        logger.warning(f"MySQL 数据库初始化失败（聊天记录功能不可用）: {e}")
        logger.warning("请确保 MySQL 服务已启动并且 chat_db 数据库已创建")

# 依赖项：获取数据库会话
def get_db():
    db = SessionLocal()  # 获取数据库会话
    try:
        yield db  # 提供数据库连接
    finally:
        db.close()  # 关闭数据库连接

def hash_password(password: str) -> str:
    """对密码进行 SHA-256 哈希"""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

class LoginForm(BaseModel):
    username: str
    password: str

class RegisterForm(BaseModel):
    username: str
    password: str
    nickname: str = ""

@app.post("/login")
def login(form: LoginForm, db: Session = Depends(get_db)):
    """
    数据库验证登录：
    - 成功返回: {"status":"ok","token":"...","username":"...","nickname":"..."}
    - 失败返回: "fail"
    """
    user = db.query(User).filter(User.username == form.username).first()
    if user and user.password_hash == hash_password(form.password):
        return {
            "status": "ok",
            "token": "I have login",
            "username": user.username,
            "nickname": user.nickname or user.username
        }
    return "fail"

@app.post("/register")
def register(form: RegisterForm, db: Session = Depends(get_db)):
    """
    用户注册：
    - 成功返回: {"status":"ok","message":"注册成功"}
    - 用户名已存在: {"status":"fail","message":"用户名已存在"}
    """
    existing = db.query(User).filter(User.username == form.username).first()
    if existing:
        return {"status": "fail", "message": "用户名已存在"}

    new_user = User(
        username=form.username,
        password_hash=hash_password(form.password),
        nickname=form.nickname if form.nickname else form.username
    )
    db.add(new_user)
    db.commit()
    return {"status": "ok", "message": "注册成功"}

# 1️⃣ **创建新会话**
@app.post("/new_session/")
async def create_session(user_id: str, db: Session = Depends(get_db)):
    """
    - 生成一个新的 session_id
    - 存储到 chat_sessions 表
    - 返回给用户 session_id
    """
    session_id = str(uuid4())  # 生成唯一 session_id
    new_session = ChatSession(user_id=user_id, session_id=session_id)  # 创建会话对象
    db.add(new_session)  # 添加到数据库
    db.commit()  # 提交事务

    # ✅ 直接存储 bot 欢迎消息
    welcome_message = Message(
        session_id=session_id,
        user_message="",  # 空用户消息
        bot_response="您好！我是焦化大语言智能问答与分析系统DeepCoke，有什么可以帮助你的？",  # ✅ 直接存入 bot 消息
        timestamp=datetime.utcnow()
    )
    db.add(welcome_message)
    db.commit()

    return {"session_id": session_id}  # 返回 session_id

# ✅ **DeepCoke 知识增强问答端点（RAG + ESCARGOT推理 + 知识图谱）**
@app.post("/chat/")
async def chat(session_id: str, user_message: str, db: Session = Depends(get_db)):
    async def generate():
        bot_response_parts = []

        try:
            # 使用 DeepCoke 知识增强管线处理问题
            # 管线内部完成：问题分类 → 中英翻译 → 向量检索 + KG检索 →
            # ESCARGOT推理(复杂问题) → 证据驱动回答生成 → 延伸问题生成
            async for piece in process_question(user_message, session_id=session_id):
                bot_response_parts.append(piece)
                yield piece
                await asyncio.sleep(0)

        except Exception as e:
            logger.error(f"Pipeline error: {repr(e)}")
            traceback.print_exc()
            # 管线失败时回退到简单 DeepSeek 调用
            try:
                fallback_stream = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": "你是焦化大语言智能问答与分析系统DeepCoke，由苏州龙泰氢一能源科技有限公司研发。"},
                        {"role": "user", "content": user_message},
                    ],
                    stream=True,
                )
                for chunk in fallback_stream:
                    if not getattr(chunk, "choices", None):
                        continue
                    delta = chunk.choices[0].delta
                    piece = getattr(delta, "content", None)
                    if not piece:
                        continue
                    bot_response_parts.append(piece)
                    yield piece
                    await asyncio.sleep(0)
            except Exception as e2:
                logger.error(f"Fallback error: {repr(e2)}")
        finally:
            # 流结束或异常都尽量把已有内容落库
            full_reply = "".join(bot_response_parts).strip()
            try:
                new_message = Message(
                    session_id=session_id,
                    user_message=user_message,
                    bot_response=full_reply if full_reply else "（空响应或被中断）",
                    timestamp=datetime.utcnow()
                )
                db.add(new_message)
                db.commit()
            except Exception as e2:
                db.rollback()
                logger.error(f"db commit error: {repr(e2)}")

    # 保持与前端相同的流式响应格式
    return StreamingResponse(
        generate(),
        media_type="text/plain; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # 避免某些反向代理缓冲
        }
    )

# 3️⃣ **查询用户的所有会话**
@app.get("/user_sessions/")
async def get_user_sessions(user_id: str, db: Session = Depends(get_db)):
    """
    - 查询某个用户的所有会话
    - 返回按照最后的消息时间排序（最新的在上面）
    - 使用该会话的第一条用户输入作为名称
    """
    sessions = db.query(ChatSession).filter(ChatSession.user_id == user_id).all()

    session_list = []
    for session in sessions:
        # 获取该会话的第一条用户消息
        first_message = db.query(Message).filter(
            Message.session_id == session.session_id,
            Message.user_message != ""
        ).order_by(Message.timestamp).first()

        # 默认标题（如果没有用户输入，则显示 session_id 前 6 位）
        session_title = first_message.user_message[:10] if first_message else f"新对话"

        # 获取该会话最后的消息时间（用于排序）
        last_message_time = db.query(func.max(Message.timestamp)).filter(Message.session_id == session.session_id).scalar()

        session_list.append({
            "session_id": session.session_id,
            "title": session_title,
            "last_message_time": last_message_time or datetime.utcnow()
        })

    # **按最后消息时间排序（最近的会话在上面）**
    session_list = sorted(session_list, key=lambda x: x["last_message_time"], reverse=True)

    return session_list


# 4️⃣ **查询某个会话的所有聊天记录**
@app.get("/messages/")
async def get_messages(session_id: str, db: Session = Depends(get_db)):
    """
    - 查询某个 session_id 下的所有聊天记录
    - 交替返回 user 和 bot 的消息
    """
    messages = db.query(Message).filter(Message.session_id == session_id).order_by(Message.timestamp.asc()).all()

    chat_history = []
    for msg in messages:
        if msg.user_message.strip():  # 过滤掉空的 user_message
            chat_history.append({"text": msg.user_message, "type": "user"})
        if msg.bot_response.strip():  # 过滤掉空的 bot_response
            chat_history.append({"text": msg.bot_response, "type": "bot"})

    return chat_history  # ✅ user 和 bot 按顺序交替返回


# 5️⃣-a **煤样数据分页查询**
@app.get("/all_coals_page/")
async def all_coals_page(page: int = 1, page_size: int = 10):
    """分页查询所有煤样数据，供前端表格展示。"""
    from deepcoke.coal_agent.coal_db import get_all_coals
    rows = get_all_coals()
    total = len(rows)
    start = (page - 1) * page_size
    end = start + page_size
    return {"total": total, "page": page, "page_size": page_size, "data": rows[start:end]}


# 5️⃣-b **煤样数据下载（Excel）**
@app.get("/download_coals/")
async def download_coals():
    """导出所有煤样数据为 Excel 文件下载。"""
    import io
    import pandas as pd
    from starlette.responses import Response
    from deepcoke.coal_agent.coal_db import get_all_coals

    rows = get_all_coals()
    df = pd.DataFrame(rows)
    # 重命名列
    col_map = {
        "coal_name": "煤样名称", "coal_type": "煤种类型", "coal_price": "价格(元/吨)",
        "coal_mad": "水分Mad(%)", "coal_ad": "灰分Ad(%)", "coal_vdaf": "挥发分Vdaf(%)",
        "coal_std": "硫分St,d(%)", "G": "粘结指数G", "X": "胶质层X(mm)", "Y": "胶质层Y(mm)",
        "coke_CRI": "CRI(%)", "coke_CSR": "CSR(%)", "coke_M10": "M10(%)",
        "coke_M25": "M25(%)", "coke_M40": "M40(%)",
    }
    df = df.rename(columns=col_map)

    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    buf.seek(0)

    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=coal_data.xlsx"},
    )


# 6️⃣ **PDF 文献查看**
@app.get("/pdf/{paper_id}")
async def view_pdf(paper_id: int):
    """通过 paper_id 返回原始 PDF 文件，供前端在新窗口查看。"""
    import sqlite3
    from pathlib import Path
    from starlette.responses import Response

    # 从 SQLite 查找文件路径
    db_path = Path(__file__).parent / "deepcoke" / "data" / "papers.db"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("SELECT file_path, title FROM papers WHERE id = ?", (paper_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")

    db_file_path, title = row

    # 路径映射：DB 里可能是旧机器的绝对路径，需要映射到本机
    pdf_path = Path(db_file_path)
    if not pdf_path.exists():
        # 尝试从文件名在本机 PDF 目录中查找
        pdf_name = pdf_path.name
        papers_base = Path("D:/deepcoke/deepcoke_enterprise/Coal blend paper")
        # 递归搜索
        found = list(papers_base.rglob(pdf_name))
        if found:
            pdf_path = found[0]
        else:
            raise HTTPException(status_code=404, detail=f"PDF file not found: {pdf_name}")

    # 如果有 search 参数，返回带高亮查看器的 HTML 页面
    from fastapi import Query
    search = None
    from starlette.requests import Request
    # 手动从 query string 获取 search 参数
    import urllib.parse
    # 直接返回 PDF，前端通过 pdf_viewer 端点查看
    return Response(
        content=pdf_path.read_bytes(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename=\"{pdf_path.name}\"",
        },
    )


@app.get("/pdf_viewer/{paper_id}")
async def pdf_viewer(paper_id: int, search: str = "", ref: str = ""):
    """返回基于 PDF.js 的查看器页面，支持文本搜索高亮。"""
    import sqlite3
    from pathlib import Path
    from starlette.responses import HTMLResponse
    import html as html_mod

    db_path = Path(__file__).parent / "deepcoke" / "data" / "papers.db"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("SELECT title FROM papers WHERE id = ?", (paper_id,))
    row = cur.fetchone()
    conn.close()
    title = html_mod.escape(row[0] if row else f"Paper {paper_id}")
    search_escaped = html_mod.escape(search)

    page = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>[{ref}] {title}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#111827; color:#e5e7eb; font-family:system-ui,sans-serif; }}

/* 顶部工具栏 */
.toolbar {{
  position:fixed; top:0; left:0; right:0; z-index:100; height:52px;
  background:#1f2937; border-bottom:1px solid #374151;
  display:flex; align-items:center; padding:0 16px; gap:10px;
}}
.toolbar .title {{
  flex:1; font-size:14px; color:#93c5fd; overflow:hidden;
  text-overflow:ellipsis; white-space:nowrap;
}}
.toolbar input {{
  background:#374151; border:1px solid #4b5563; color:#e5e7eb;
  padding:6px 12px; border-radius:6px; font-size:13px; width:280px;
}}
.toolbar input:focus {{ outline:none; border-color:#60a5fa; }}
.toolbar button {{
  background:#3b82f6; color:#fff; border:none; padding:6px 16px;
  border-radius:6px; cursor:pointer; font-size:13px;
}}
.toolbar button:hover {{ background:#2563eb; }}
.toolbar .info {{
  font-size:12px; color:#fbbf24; padding:4px 8px; background:#78350f;
  border-radius:4px;
}}
.toolbar .nav-btn {{
  background:#4b5563; padding:6px 10px; border-radius:4px; border:none;
  color:#e5e7eb; cursor:pointer; font-size:13px;
}}
.toolbar .nav-btn:hover {{ background:#6b7280; }}

/* PDF 页面容器 */
#viewer {{
  margin-top:52px; display:flex; flex-direction:column; align-items:center;
  padding:20px 0; gap:16px;
}}
.page-wrapper {{
  position:relative; background:#fff; box-shadow:0 2px 12px rgba(0,0,0,0.5);
  border-radius:4px; overflow:hidden;
}}
.page-wrapper canvas {{ display:block; }}

/* 文本层（透明覆盖，用于选择和高亮） */
.text-layer {{
  position:absolute; top:0; left:0; right:0; bottom:0;
  overflow:hidden; opacity:0.3; line-height:1;
}}
.text-layer span {{
  position:absolute; white-space:pre; color:transparent;
  cursor:text;
}}

/* 高亮匹配 */
.text-layer span.highlight {{
  background:#fbbf24; color:transparent; border-radius:2px;
  opacity:1;
}}
.text-layer span.highlight-active {{
  background:#f87171; opacity:1;
}}

/* 加载提示 */
.loading {{
  position:fixed; top:50%; left:50%; transform:translate(-50%,-50%);
  font-size:16px; color:#9ca3af;
}}
</style>
</head>
<body>
<div class="toolbar">
  <div class="title">📄 [{ref}] {title}</div>
  <input id="searchInput" type="text" placeholder="搜索原文…"
         value="{search_escaped}" />
  <button onclick="doSearch()">搜索</button>
  <button class="nav-btn" onclick="prevMatch()">▲ 上一个</button>
  <button class="nav-btn" onclick="nextMatch()">▼ 下一个</button>
  <span id="matchInfo" class="info" style="display:none"></span>
</div>

<div id="loading" class="loading">加载 PDF 中…</div>
<div id="viewer"></div>

<script>
  pdfjsLib.GlobalWorkerOptions.workerSrc =
    'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';

  const PDF_URL = '/pdf/{paper_id}';
  const SCALE = 1.5;
  let pdfDoc = null;
  let textContents = [];   // 每页的文本内容
  let allSpans = [];        // 所有渲染的文本 span
  let matchSpans = [];      // 匹配的 span
  let currentMatch = -1;

  async function loadPDF() {{
    pdfDoc = await pdfjsLib.getDocument(PDF_URL).promise;
    document.getElementById('loading').style.display = 'none';
    const viewer = document.getElementById('viewer');

    for (let i = 1; i <= pdfDoc.numPages; i++) {{
      const page = await pdfDoc.getPage(i);
      const viewport = page.getViewport({{ scale: SCALE }});

      // 页面容器
      const wrapper = document.createElement('div');
      wrapper.className = 'page-wrapper';
      wrapper.style.width = viewport.width + 'px';
      wrapper.style.height = viewport.height + 'px';

      // Canvas 渲染
      const canvas = document.createElement('canvas');
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      wrapper.appendChild(canvas);
      await page.render({{ canvasContext: canvas.getContext('2d'), viewport }}).promise;

      // 文本层
      const textLayer = document.createElement('div');
      textLayer.className = 'text-layer';
      wrapper.appendChild(textLayer);

      const textContent = await page.getTextContent();
      textContents.push(textContent);

      textContent.items.forEach(item => {{
        if (!item.str.trim()) return;
        const tx = pdfjsLib.Util.transform(viewport.transform, item.transform);
        const span = document.createElement('span');
        span.textContent = item.str;
        const fontSize = Math.sqrt(tx[0]*tx[0] + tx[1]*tx[1]);
        span.style.left = tx[4] + 'px';
        span.style.top = (tx[5] - fontSize) + 'px';
        span.style.fontSize = fontSize + 'px';
        span.style.fontFamily = item.fontName || 'sans-serif';
        span.dataset.page = i;
        textLayer.appendChild(span);
        allSpans.push(span);
      }});

      viewer.appendChild(wrapper);
    }}

    // 自动搜索
    const q = document.getElementById('searchInput').value.trim();
    if (q) doSearch();
  }}

  function doSearch() {{
    const rawQ = document.getElementById('searchInput').value.trim();
    if (!rawQ) return;

    // 清除旧高亮
    matchSpans.forEach(s => s.classList.remove('highlight', 'highlight-active'));
    matchSpans = [];
    currentMatch = -1;

    // 将搜索词拆分为多个关键词（任一匹配即高亮）
    const keywords = rawQ.toLowerCase().split(/\\s+/).filter(w => w.length >= 2);
    if (keywords.length === 0) return;

    // 策略1: 逐 span 匹配单个关键词
    allSpans.forEach(span => {{
      const text = span.textContent.toLowerCase();
      for (const kw of keywords) {{
        if (text.includes(kw)) {{
          span.classList.add('highlight');
          if (!matchSpans.includes(span)) matchSpans.push(span);
          break;
        }}
      }}
    }});

    // 策略2: 按页拼接文本，搜索完整短语，高亮对应区间的 span
    const fullQ = rawQ.toLowerCase();
    // 按页分组 span
    const pageGroups = {{}};
    allSpans.forEach((span, idx) => {{
      const pg = span.dataset.page;
      if (!pageGroups[pg]) pageGroups[pg] = [];
      pageGroups[pg].push({{ span, idx }});
    }});
    Object.values(pageGroups).forEach(group => {{
      // 拼接本页所有 span 文本
      let concat = '';
      const ranges = []; // [{{start, end, span}}]
      group.forEach(item => {{
        const start = concat.length;
        concat += item.span.textContent;
        ranges.push({{ start, end: concat.length, span: item.span }});
        concat += ' '; // span 之间加空格
      }});
      const concatLower = concat.toLowerCase();
      let pos = 0;
      while ((pos = concatLower.indexOf(fullQ, pos)) !== -1) {{
        const matchEnd = pos + fullQ.length;
        ranges.forEach(r => {{
          if (r.end > pos && r.start < matchEnd) {{
            r.span.classList.add('highlight');
            if (!matchSpans.includes(r.span)) matchSpans.push(r.span);
          }}
        }});
        pos += 1;
      }}
    }});

    // 按页码+位置排序
    matchSpans.sort((a, b) => {{
      const pa = parseInt(a.dataset.page), pb = parseInt(b.dataset.page);
      if (pa !== pb) return pa - pb;
      return parseFloat(a.style.top) - parseFloat(b.style.top);
    }});

    const info = document.getElementById('matchInfo');
    if (matchSpans.length > 0) {{
      currentMatch = 0;
      highlightCurrent();
      info.textContent = '1 / ' + matchSpans.length + ' 处匹配';
      info.style.display = 'inline-block';
      matchSpans[0].scrollIntoView({{ behavior: 'smooth', block: 'center' }});
    }} else {{
      info.textContent = '未找到匹配';
      info.style.display = 'inline-block';
    }}
  }}

  function highlightCurrent() {{
    matchSpans.forEach((s, i) => {{
      s.classList.toggle('highlight-active', i === currentMatch);
    }});
    document.getElementById('matchInfo').textContent =
      (currentMatch + 1) + ' / ' + matchSpans.length + ' 处匹配';
  }}

  function nextMatch() {{
    if (matchSpans.length === 0) return;
    currentMatch = (currentMatch + 1) % matchSpans.length;
    highlightCurrent();
    matchSpans[currentMatch].scrollIntoView({{ behavior: 'smooth', block: 'center' }});
  }}

  function prevMatch() {{
    if (matchSpans.length === 0) return;
    currentMatch = (currentMatch - 1 + matchSpans.length) % matchSpans.length;
    highlightCurrent();
    matchSpans[currentMatch].scrollIntoView({{ behavior: 'smooth', block: 'center' }});
  }}

  // 回车搜索
  document.getElementById('searchInput').addEventListener('keydown', e => {{
    if (e.key === 'Enter') doSearch();
  }});

  loadPDF();
</script>
</body>
</html>"""

    return HTMLResponse(content=page)