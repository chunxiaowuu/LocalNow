import { PlanRequest } from "@/lib/types";
import { authHeaders } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/** 解析后端错误体，优先返回 detail（如限流提示），否则给通用兜底文案 */
async function errorMessage(res: Response, fallback: string): Promise<string> {
  try {
    const data = await res.json();
    if (typeof data.detail === "string") return data.detail;
  } catch { /* ignore */ }
  return fallback;
}

export async function createSession(req: PlanRequest): Promise<string> {
  const res = await fetch(`${API_BASE}/session`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(req),
  });
  if (!res.ok) throw new Error(await errorMessage(res, "创建会话失败，请检查后端是否启动"));
  const data = await res.json();
  return data.session_id;
}

export function openStream(sessionId: string): EventSource {
  // EventSource 不支持自定义 header；限流校验在 POST /session 已完成，stream 无需鉴权
  return new EventSource(`${API_BASE}/session/${sessionId}/stream`);
}

export async function confirmPlan(
  sessionId: string,
  confirmed: boolean,
  selectedPlanId: string,
  feedback?: string,
): Promise<void> {
  const res = await fetch(`${API_BASE}/session/${sessionId}/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ confirmed, selected_plan_id: selectedPlanId, feedback: feedback ?? "" }),
  });
  if (!res.ok) throw new Error(await errorMessage(res, "操作失败，请重试"));
}

export interface Quota {
  authenticated: boolean;
  plans_used: number;
  plans_limit: number;
  plans_remaining: number;
  calls_per_plan: number;
}

export async function fetchQuota(): Promise<Quota | null> {
  try {
    const r = await fetch(`${API_BASE}/quota`, { headers: authHeaders() });
    return await r.json();
  } catch {
    return null;
  }
}
