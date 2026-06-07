// 登录态：后端 OAuth 回调把 token 放进 URL fragment（#token=...），
// 前端存 localStorage，之后所有写请求带 Authorization: Bearer（跨站稳，避开第三方 cookie）。

const TOKEN_KEY = "localnow:token";
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(t: string) {
  localStorage.setItem(TOKEN_KEY, t);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

/** 写请求统一带上的 header（登录则带 Bearer） */
export function authHeaders(): Record<string, string> {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

/** 页面加载时调用：若 URL fragment 带 #token=... 则存下并清掉地址栏 */
export function captureTokenFromHash(): boolean {
  if (typeof window === "undefined") return false;
  const m = window.location.hash.match(/[#&]token=([^&]+)/);
  if (m) {
    setToken(decodeURIComponent(m[1]));
    history.replaceState(null, "", window.location.pathname + window.location.search);
    return true;
  }
  return false;
}

/** 跳转到后端 GitHub 登录（OAuth 需顶层导航） */
export function loginWithGitHub() {
  window.location.href = `${API_BASE}/auth/github/login`;
}

export async function fetchMe(): Promise<{ id: string; login: string } | null> {
  try {
    const r = await fetch(`${API_BASE}/auth/me`, { headers: authHeaders() });
    return (await r.json()).user ?? null;
  } catch {
    return null;
  }
}

export async function githubLoginEnabled(): Promise<boolean> {
  try {
    const r = await fetch(`${API_BASE}/auth/config`);
    return (await r.json()).github_login === true;
  } catch {
    return false;
  }
}
