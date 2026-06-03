import { PlanRequest } from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function createSession(req: PlanRequest): Promise<string> {
  const res = await fetch(`${API_BASE}/session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) throw new Error("Failed to create session");
  const data = await res.json();
  return data.session_id;
}

export function openStream(sessionId: string): EventSource {
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
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirmed, selected_plan_id: selectedPlanId, feedback: feedback ?? "" }),
  });
  if (!res.ok) throw new Error("Failed to confirm plan");
}
