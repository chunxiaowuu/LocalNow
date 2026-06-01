"use client";

import { ProgressEvent } from "@/lib/types";

interface Props {
  events: ProgressEvent[];
}

// 每个节点完成后，预测并立即显示下一步，避免长时间无反馈
const NEXT_STEP: Record<string, string> = {
  parse_intent:      "正在搜索附近场所和餐厅...",
  search_candidates: "AI 正在构思方案，本地模型约需 1-3 分钟，请稍候...",
  generate_plans:    "正在确认场所和餐厅的可用性...",
  check_availability:"等待您确认方案...",
  human_review:      "正在完成预订...",
  execute_bookings:  "正在发送行程通知...",
};

export function AgentProgress({ events }: Props) {
  const lastEvent = events[events.length - 1];
  const pendingMessage = lastEvent?.done
    ? NEXT_STEP[lastEvent.node]
    : undefined;

  return (
    <div className="w-full max-w-2xl mx-auto">
      <div className="rounded-xl border border-gray-100 bg-white shadow-sm p-6">
        <h2 className="text-sm font-medium text-gray-500 mb-4">Agent 正在工作...</h2>
        <div className="space-y-3">
          {events.map((event, i) => {
            const isLast = i === events.length - 1;
            return (
              <div key={i} className="flex items-start gap-3">
                <div className="mt-0.5 flex-shrink-0">
                  {event.done ? (
                    <div className="w-5 h-5 rounded-full bg-green-100 flex items-center justify-center">
                      <svg className="w-3 h-3 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                      </svg>
                    </div>
                  ) : isLast ? (
                    <div className="w-5 h-5 rounded-full border-2 border-gray-300 border-t-gray-800 animate-spin" />
                  ) : (
                    <div className="w-5 h-5 rounded-full bg-gray-100 flex items-center justify-center">
                      <div className="w-2 h-2 rounded-full bg-gray-400" />
                    </div>
                  )}
                </div>
                <span className={`text-sm ${isLast && !event.done ? "text-gray-900 font-medium" : "text-gray-500"}`}>
                  {event.message}
                </span>
              </div>
            );
          })}

          {/* 预测下一步：当前最后一个事件已完成，立即显示下一步 */}
          {pendingMessage && (
            <div className="flex items-start gap-3">
              <div className="mt-0.5 flex-shrink-0">
                <div className="w-5 h-5 rounded-full border-2 border-gray-300 border-t-gray-800 animate-spin" />
              </div>
              <span className="text-sm text-gray-900 font-medium">{pendingMessage}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
