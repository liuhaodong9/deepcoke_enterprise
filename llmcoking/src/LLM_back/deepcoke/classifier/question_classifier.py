"""
Question type classifier for routing to appropriate processing pipeline.
"""
import re
from ..llm_client import chat_json

# Question types and their descriptions
QUESTION_TYPES = {
    "coal_price": "asking about coal market prices, trading prices, or price quotes",
    "oven_control": "loading coal blend into coke oven, starting digital twin monitoring, or oven operations",
    "optimization": "asking to optimize coal blending ratios, predict coke quality (CRI/CSR), or find best blend",
    "data_management": "adding, updating, deleting, or querying coal sample data in the database",
    "factual": "asking for a specific fact, definition, or value",
    "comparison": "comparing two or more things (methods, materials, properties)",
    "causal": "asking why something happens, cause-effect relationships",
    "process": "asking how something works step-by-step",
    "recommendation": "asking for advice, best practices, or optimal parameters",
    "general_chat": "greeting, off-topic, meta-questions, or simple conversation",
}

# Types that require ESCARGOT reasoning (complex)
COMPLEX_TYPES = {"comparison", "causal", "recommendation"}
# Types that use simple RAG
SIMPLE_RAG_TYPES = {"factual", "process"}

# ── 关键词优先匹配（不依赖 LLM，速度快且稳定）──────────────────

# 煤价查询（必须在 optimization 之前匹配）
_COAL_PRICE_KEYWORDS = re.compile(
    r"成交价|煤价|报价|行情|市场价|今日.*价|价格查询|煤炭.*价格|焦煤.*价格",
    re.IGNORECASE,
)

# 焦炉操作 / 数字孪生监控
_OVEN_CONTROL_KEYWORDS = re.compile(
    r"填入.*焦炉|装入.*焦炉|焦炉.*装|焦炉.*填"
    r"|开启.*孪生|数字孪生.*监控|启动.*监控"
    r"|开启.*监控|关闭.*监控",
    re.IGNORECASE,
)

_DATA_MGMT_KEYWORDS = re.compile(
    r"添加.*煤|新增.*煤|录入.*煤|入库.*煤|导入.*煤"
    r"|删除.*煤|移除.*煤|去掉.*煤"
    r"|修改.*煤|更新.*煤|改一下.*煤"
    r"|煤.*添加|煤.*新增|煤.*录入|煤.*入库|煤.*导入"
    r"|煤.*删除|煤.*移除|煤.*去掉"
    r"|煤.*修改|煤.*更新|煤.*改一下"
    r"|加一个煤|加几个煤|加个煤|加条煤"
    r"|查看.*煤样|看.*煤样|所有煤样|煤样.*列表|煤样.*数据|煤样数据库|数据库.*煤样|数据库.*煤"
    r"|CNN.*预测|用CNN|用模型预测|预测.*这.*煤|这个煤.*预测"
    r"|灰分.*硫分.*粘结|Ad.*G.*CRI",
    re.IGNORECASE,
)

_OPTIMIZATION_KEYWORDS = re.compile(
    r"配煤|配比|优化配"
    r"|预测.*(?:CRI|CSR|质量)|(?:CRI|CSR|M10|M25).*(?:大于|小于|范围|要求|限制|预测)"
    r"|成本最低|最优方案|混合比例|配方|料斗|blend|opti"
    r"|哪些煤|可用.*煤|列.*煤"
    r"|多模型|模型.*对比|对比.*预测"
    r"|优化.*方案|方案.*优化",
    re.IGNORECASE,
)

_CLASSIFY_PROMPT = """You are a question classifier for a coal coking domain Q&A system.

Classify the user's question into EXACTLY ONE of these types:
- coal_price: asking about coal market prices, trading prices, or price quotes (e.g. "今天焦煤价格", "澳大利亚焦煤成交价")
- oven_control: loading coal blend into coke oven, starting/stopping digital twin monitoring, or oven operations (e.g. "填入焦炉", "开启数字孪生监控")
- data_management: adding, updating, deleting, or querying coal sample data in the database (e.g. "添加一个煤样", "录入煤数据", "删除XX煤")
- optimization: asking to optimize coal blending ratios, predict coke quality (CRI/CSR/M10/M25), find best blend, query available coals, or calculate blending costs
- factual: asking for a specific fact, definition, or value
- comparison: comparing two or more things (methods, materials, properties)
- causal: asking why something happens, cause-effect relationships
- process: asking how something works step-by-step
- recommendation: asking for advice, best practices, or optimal parameters
- general_chat: greeting, off-topic, meta-questions, or simple conversation

Return ONLY the type name, nothing else."""


def classify_question(question: str) -> str:
    """
    Classify a question into one of the predefined types.
    Uses keyword matching first (fast & reliable), falls back to LLM.
    """
    # 1) 关键词快速匹配（顺序很重要：煤价 > 焦炉 > 数据管理 > 优化）
    if _COAL_PRICE_KEYWORDS.search(question):
        return "coal_price"
    if _OVEN_CONTROL_KEYWORDS.search(question):
        return "oven_control"
    if _DATA_MGMT_KEYWORDS.search(question):
        return "data_management"
    if _OPTIMIZATION_KEYWORDS.search(question):
        return "optimization"

    # 2) LLM 分类 fallback
    try:
        result = chat_json(
            [{"role": "system", "content": _CLASSIFY_PROMPT},
             {"role": "user", "content": question}],
            temperature=0.0,
            max_tokens=20,
        )
        q_type = result.strip().lower().replace('"', "").replace("'", "")
        if q_type in QUESTION_TYPES:
            return q_type
        # Fuzzy match
        for key in QUESTION_TYPES:
            if key in q_type:
                return key
        return "factual"  # default
    except Exception:
        return "factual"


def is_complex(question_type: str) -> bool:
    """Whether this question type should use ESCARGOT reasoning."""
    return question_type in COMPLEX_TYPES


def needs_rag(question_type: str) -> bool:
    """Whether this question type needs RAG retrieval."""
    return question_type not in ("general_chat", "optimization", "data_management", "coal_price", "oven_control")
