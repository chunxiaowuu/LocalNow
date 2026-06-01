"""
内存会话存储。

每个 session 对应一次规划会话，持有 LangGraph thread_id 和当前状态。
demo 规模使用内存存储，进程重启后会话丢失，生产环境替换为 Redis 即可。
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Session:
    session_id: str
    user_message: str
    status: str = "created"          # created | running | interrupted | resuming | done | error
    resume_payload: dict = field(default_factory=dict)   # /confirm 收到的用户选择
    result: dict = field(default_factory=dict)           # 最终状态快照


# 模块级单例，进程内共享
_store: dict[str, Session] = {}


def create(session_id: str, user_message: str) -> Session:
    s = Session(session_id=session_id, user_message=user_message)
    _store[session_id] = s
    return s


def get(session_id: str) -> Session | None:
    return _store.get(session_id)


def update(session_id: str, **kwargs: Any) -> None:
    s = _store.get(session_id)
    if s:
        for k, v in kwargs.items():
            setattr(s, k, v)
