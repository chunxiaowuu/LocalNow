"use client";

import { useCallback, useState } from "react";
import { Phase, PlanRequest, ProgressEvent } from "@/lib/types";
import { createSession, openStream, confirmPlan } from "@/lib/api";
import { PlannerInput } from "@/components/planner/PlannerInput";
import { AgentProgress } from "@/components/planner/AgentProgress";
import { PlanCards } from "@/components/planner/PlanCards";
import { ExecSummary } from "@/components/planner/ExecSummary";
import { ItineraryChecklist } from "@/components/planner/ItineraryChecklist";

export default function Home() {
  const [phase, setPhase] = useState<Phase>({ kind: "input" });

  // 启动 SSE 流，处理所有事件类型
  const startStream = useCallback((sessionId: string, existingEvents: ProgressEvent[] = []) => {
    const es = openStream(sessionId);

    // heartbeat 事件仅用于保持 SSE 连接，前端直接忽略
    es.addEventListener("heartbeat", () => {});

    es.addEventListener("node_update", (e) => {
      const data = JSON.parse(e.data);
      setPhase((prev) => {
        const events = [
          ...(("events" in prev ? prev.events : existingEvents).map((ev) => ({ ...ev, done: true }))),
          { node: data.node, message: data.message, done: false },
        ];
        return { kind: "running", events };
      });
    });

    es.addEventListener("interrupt", (e) => {
      const data = JSON.parse(e.data);
      es.close();
      setPhase((prev) => ({
        kind: "interrupted",
        events: "events" in prev ? prev.events.map((ev) => ({ ...ev, done: true })) : existingEvents,
        plans: data.plans,
        sessionId,
      }));
    });

    es.addEventListener("done", (e) => {
      const data = JSON.parse(e.data);
      es.close();
      setPhase({
        kind: "done",
        summary: data.summary,
        bookingResults: data.booking_results ?? [],
        plan: data.plan ?? null,
      });
    });

    es.addEventListener("error", () => {
      es.close();
      setPhase({ kind: "error", message: "连接出错，请重试" });
    });
  }, []);

  // 用户提交输入，创建会话并开始流
  const handleSubmit = useCallback(async (req: PlanRequest) => {
    try {
      setPhase({ kind: "running", events: [] });
      const sessionId = await createSession(req);
      startStream(sessionId);
    } catch {
      setPhase({ kind: "error", message: "创建会话失败，请检查后端是否启动" });
    }
  }, [startStream]);

  // 用户确认方案
  const handleConfirm = useCallback(async (planId: string) => {
    if (phase.kind !== "interrupted") return;
    const { sessionId, events } = phase;
    try {
      setPhase({ kind: "executing", events: [...events, { node: "execute", message: "正在执行预订...", done: false }] });
      await confirmPlan(sessionId, true, planId);
      startStream(sessionId, events);
    } catch {
      setPhase({ kind: "error", message: "确认失败，请重试" });
    }
  }, [phase, startStream]);

  // 用户拒绝，重新规划
  const handleReject = useCallback(async (feedback: string, basePlanId: string) => {
    if (phase.kind !== "interrupted") return;
    const { sessionId, events } = phase;
    try {
      setPhase({ kind: "running", events });
      await confirmPlan(sessionId, false, basePlanId, feedback);
      startStream(sessionId, events);
    } catch {
      setPhase({ kind: "error", message: "操作失败，请重试" });
    }
  }, [phase, startStream]);

  return (
    <main className="min-h-screen bg-gray-50">
      <div className="max-w-5xl mx-auto px-4 py-16">
        {phase.kind === "input" && (
          <PlannerInput onSubmit={handleSubmit} loading={false} />
        )}

        {phase.kind === "running" && (
          <AgentProgress events={phase.events} />
        )}

        {phase.kind === "interrupted" && (
          <div className="space-y-6">
            <AgentProgress events={phase.events} />
            <PlanCards
              plans={phase.plans}
              onConfirm={handleConfirm}
              onReject={handleReject}
            />
          </div>
        )}

        {phase.kind === "executing" && (
          <AgentProgress events={phase.events} />
        )}

        {phase.kind === "done" && (
          phase.plan ? (
            <ItineraryChecklist
              summary={phase.summary}
              plan={phase.plan}
              bookingResults={phase.bookingResults}
              onReset={() => setPhase({ kind: "input" })}
            />
          ) : (
            <ExecSummary
              summary={phase.summary}
              bookingResults={phase.bookingResults}
              onReset={() => setPhase({ kind: "input" })}
            />
          )
        )}

        {phase.kind === "error" && (
          <div className="text-center space-y-4">
            <p className="text-red-600">{phase.message}</p>
            <button
              onClick={() => setPhase({ kind: "input" })}
              className="text-sm text-gray-500 underline"
            >
              返回重试
            </button>
          </div>
        )}
      </div>
    </main>
  );
}
