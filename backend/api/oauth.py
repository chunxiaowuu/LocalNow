"""
GitHub OAuth 登录（Web 流程，签发 Bearer token 给前端存 localStorage）。

流程：
  前端 → GET /auth/github/login → 302 到 GitHub 授权页
  GitHub → GET /auth/github/callback?code=&state= → 换 token、取用户 → 302 回前端，
           token 放在 URL fragment（#token=...，不进服务器日志/Referer）
  前端把 token 存 localStorage，之后请求带 Authorization: Bearer

未配置 GITHUB_CLIENT_ID/SECRET 时端点返回 503，应用其余功能（匿名限流）不受影响。
"""
from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from api.auth import current_user, make_token
from config import config

router = APIRouter(prefix="/auth", tags=["auth"])

_AUTHORIZE = "https://github.com/login/oauth/authorize"
_TOKEN = "https://github.com/login/oauth/access_token"
_USER = "https://api.github.com/user"


def _enabled() -> bool:
    return bool(config.github_client_id and config.github_client_secret)


def _sign_state() -> str:
    ts = str(int(time.time()))
    sig = hmac.new(config.session_secret.encode(), ts.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{ts}.{sig}"


def _valid_state(state: str) -> bool:
    try:
        ts, sig = state.split(".", 1)
        expected = hmac.new(config.session_secret.encode(), ts.encode(), hashlib.sha256).hexdigest()[:16]
        return hmac.compare_digest(sig, expected) and (int(time.time()) - int(ts) < 600)
    except Exception:
        return False


@router.get("/me")
async def me(request: Request):
    """前端查询登录态。"""
    user = current_user(request)
    return {"user": {"id": str(user["id"]), "login": user["login"]} if user else None}


@router.get("/github/login")
async def github_login():
    if not _enabled():
        raise HTTPException(503, "GitHub 登录未配置")
    params = {
        "client_id": config.github_client_id,
        "redirect_uri": f"{config.oauth_redirect_base}/auth/github/callback",
        "scope": "read:user",
        "state": _sign_state(),
    }
    return RedirectResponse(f"{_AUTHORIZE}?{urlencode(params)}")


@router.get("/github/callback")
async def github_callback(code: str = "", state: str = ""):
    if not _enabled():
        raise HTTPException(503, "GitHub 登录未配置")
    if not code or not _valid_state(state):
        raise HTTPException(400, "无效的回调参数")

    async with httpx.AsyncClient(timeout=10) as cli:
        tok = await cli.post(
            _TOKEN,
            headers={"Accept": "application/json"},
            data={
                "client_id": config.github_client_id,
                "client_secret": config.github_client_secret,
                "code": code,
                "redirect_uri": f"{config.oauth_redirect_base}/auth/github/callback",
            },
        )
        access = tok.json().get("access_token")
        if not access:
            raise HTTPException(400, "GitHub 授权失败")
        u = await cli.get(_USER, headers={"Authorization": f"Bearer {access}", "Accept": "application/json"})
        gh = u.json()

    token = make_token({"id": str(gh["id"]), "login": gh.get("login", "")})
    # token 放 fragment（# 后），不会被发到服务器、不进日志
    return RedirectResponse(f"{config.frontend_base}/#token={token}")


@router.get("/config")
async def auth_config():
    """前端用来判断是否显示登录按钮。"""
    return JSONResponse({"github_login": _enabled()})
