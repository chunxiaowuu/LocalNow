"""
每日限流计数（SQLite 持久化，进程重启不丢、按自然日重置）。

- 「plan 生成」按身份（登录用户 id 或匿名 IP）按天计数，达上限拒绝。
- 「修改 plan（replan）」次数按单个 session 计数，存在 session 上（见 session_store）。
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import date

from config import config

_LOCK = threading.Lock()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(config.ratelimit_db_path)
    c.execute(
        "CREATE TABLE IF NOT EXISTS daily_plans "
        "(identity TEXT, day TEXT, count INTEGER, PRIMARY KEY (identity, day))"
    )
    return c


def plans_used_today(identity: str) -> int:
    today = str(date.today())
    with _LOCK, _conn() as c:
        row = c.execute(
            "SELECT count FROM daily_plans WHERE identity=? AND day=?", (identity, today)
        ).fetchone()
        return row[0] if row else 0


def try_consume_plan(identity: str, limit: int) -> bool:
    """
    原子地：若该身份今日已用 < limit，则计数 +1 并返回 True；否则返回 False（不计数）。
    """
    today = str(date.today())
    with _LOCK, _conn() as c:
        row = c.execute(
            "SELECT count FROM daily_plans WHERE identity=? AND day=?", (identity, today)
        ).fetchone()
        if (row[0] if row else 0) >= limit:
            return False
        c.execute(
            "INSERT INTO daily_plans (identity, day, count) VALUES (?, ?, 1) "
            "ON CONFLICT(identity, day) DO UPDATE SET count = count + 1",
            (identity, today),
        )
        c.commit()
        return True
