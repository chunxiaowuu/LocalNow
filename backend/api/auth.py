"""
轻量鉴权与身份识别。

- 登录态用 HMAC 签名的 cookie（stdlib，无额外依赖）承载用户身份；GitHub OAuth 回调签发。
- 未登录用客户端 IP 作为限流身份。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from fastapi import Request

from config import config

_COOKIE_NAME = "ln_session"
_MAX_AGE = 7 * 24 * 3600  # 7 天


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_session_cookie(user: dict) -> str:
    """user: {'id': ..., 'login': ...} → 签名 token。"""
    payload = {**user, "iat": int(time.time())}
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64e(hmac.new(config.session_secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def _verify(token: str) -> dict | None:
    try:
        body, sig = token.split(".", 1)
        expected = _b64e(hmac.new(config.session_secret.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(_b64d(body))
        if int(time.time()) - int(data.get("iat", 0)) > _MAX_AGE:
            return None
        return data
    except Exception:
        return None


def current_user(request: Request) -> dict | None:
    """
    返回登录用户 {'id','login'}，未登录返回 None。
    优先读 Authorization: Bearer（跨站部署用，避免第三方 cookie 被拦截），
    回退到 cookie（同源部署用）。
    """
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        user = _verify(auth[7:].strip())
        if user:
            return user
    token = request.cookies.get(_COOKIE_NAME)
    return _verify(token) if token else None


def make_token(user: dict) -> str:
    """签发会话 token（与 cookie 同格式；前端存 localStorage 走 Bearer）。"""
    return make_session_cookie(user)


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def identity(request: Request) -> tuple[str, bool]:
    """返回 (限流身份键, 是否登录)。"""
    user = current_user(request)
    if user:
        return f"user:{user['id']}", True
    return f"ip:{client_ip(request)}", False


COOKIE_NAME = _COOKIE_NAME
COOKIE_MAX_AGE = _MAX_AGE
