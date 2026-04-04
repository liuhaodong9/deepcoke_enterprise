"""
Pipeline 会话状态存储 — 支持 Agent 交互式暂停/恢复
"""
import time

# 内存存储：session_id → state dict
_store: dict[str, dict] = {}

# 状态过期时间（秒）
_TTL = 600


def save(session_id: str, state: dict) -> None:
    """保存 pipeline 会话状态。"""
    state["_ts"] = time.time()
    _store[session_id] = state


def load(session_id: str) -> dict | None:
    """读取 pipeline 会话状态，过期返回 None。"""
    state = _store.get(session_id)
    if state and time.time() - state.get("_ts", 0) < _TTL:
        return state
    if state:
        del _store[session_id]
    return None


def clear(session_id: str) -> None:
    """清除会话状态。"""
    _store.pop(session_id, None)


def is_agent_command(message: str) -> bool:
    """判断消息是否是 Agent 交互指令。"""
    return message.startswith("__AGENT:")
