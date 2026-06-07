"use client";

import { useEffect, useState } from "react";
import { BookingResult, Plan } from "@/lib/types";
import {
  StatusMap, itemKey, groupByDay,
  buildItineraryText, copyText, exportItinerary, shareViaEmail,
} from "@/lib/share";

interface Props {
  summary: string;
  plan: Plan;
  bookingResults: BookingResult[];
  onReset: () => void;
}

const CATEGORY_LABEL: Record<string, string> = {
  activity: "活动",
  restaurant: "餐厅",
  transport: "交通",
};
const CATEGORY_COLOR: Record<string, string> = {
  activity: "bg-blue-50 text-blue-700",
  restaurant: "bg-orange-50 text-orange-700",
};

export function ItineraryChecklist({ summary, plan, bookingResults, onReset }: Props) {
  const storageKey = `localnow:checklist:${plan.id}`;

  // 只对活动/餐厅做清单（交通是连接环节，不计入勾选）
  const items = plan.timeline.filter((it) => it.category !== "transport");
  const bookable = plan.timeline.filter((it) => it.booking_uri?.startsWith("http"));

  // 初始状态：已成功预订的项目默认勾「已预订」；其余未勾。（SSR 安全，仅依赖 props）
  const initStatus = (): StatusMap => {
    const bookedNames = new Set(
      bookingResults.filter((r) => r.status === "success").map((r) => r.target_name),
    );
    const m: StatusMap = {};
    for (const it of items) {
      m[itemKey(it)] = { completed: false, booked: bookedNames.has(it.name) };
    }
    return m;
  };
  const [status, setStatus] = useState<StatusMap>(initStatus);
  const [copied, setCopied] = useState(false);

  // 客户端挂载后叠加 localStorage 中保存的勾选（避免 SSR/hydration 不一致）
  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || "{}");
      if (Object.keys(saved).length) {
        // 持久化勾选必须在挂载后叠加（lazy initializer 读 localStorage 会致 SSR/hydration 不一致）
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setStatus((s) => {
          const n = { ...s };
          for (const k in saved) n[k] = { ...n[k], ...saved[k] };
          return n;
        });
      }
    } catch { /* localStorage 不可用则忽略 */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const persist = (next: StatusMap) => {
    setStatus(next);
    try { localStorage.setItem(storageKey, JSON.stringify(next)); } catch { /* ignore */ }
  };
  const toggle = (key: string, field: "completed" | "booked") => {
    const cur = status[key] ?? { completed: false, booked: false };
    persist({ ...status, [key]: { ...cur, [field]: !cur[field] } });
  };

  const doneCount = items.filter((it) => status[itemKey(it)]?.completed).length;
  const bookedCount = items.filter((it) => status[itemKey(it)]?.booked).length;

  const openAllBookings = () => {
    for (const it of bookable) window.open(it.booking_uri, "_blank", "noopener");
    // 打开即视为「已预订」
    const next = { ...status };
    for (const it of bookable) {
      const k = itemKey(it);
      next[k] = { ...(next[k] ?? { completed: false, booked: false }), booked: true };
    }
    persist(next);
  };

  const handleCopy = async () => {
    if (await copyText(buildItineraryText(plan, status))) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const days = groupByDay(items);
  const multiDay = days.length > 1;

  return (
    <div className="w-full max-w-2xl mx-auto space-y-5">
      {/* 成功横幅 */}
      <div className="rounded-xl border border-green-100 bg-green-50 p-5">
        <p className="text-sm font-medium text-green-800 mb-1">行程已生成！</p>
        {summary && <p className="text-sm text-green-700 whitespace-pre-wrap">{summary}</p>}
      </div>

      {/* 标题 + 进度 + 一键预订 */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">{plan.title}</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            已完成 {doneCount}/{items.length} · 已预订 {bookedCount}/{items.length}
          </p>
        </div>
        {bookable.length > 0 && (
          <button
            onClick={openAllBookings}
            className="bg-gray-900 text-white rounded-lg px-4 py-2 text-sm font-medium hover:bg-gray-700 transition-colors"
            title="在新标签依次打开所有需预订项目的高德搜索页"
          >
            打开全部预订（{bookable.length}）
          </button>
        )}
      </div>

      {/* 清单 */}
      <div className="rounded-xl border border-gray-100 bg-white shadow-sm divide-y divide-gray-50">
        {days.map(([day, dayItems]) => (
          <div key={day}>
            {multiDay && (
              <div className="px-4 py-2 bg-gray-50 text-xs font-semibold text-gray-600">第 {day} 天</div>
            )}
            {dayItems.map((it) => {
              const k = itemKey(it);
              const st = status[k] ?? { completed: false, booked: false };
              return (
                <div key={k} className="flex items-start gap-3 px-4 py-3">
                  <span className="text-xs text-gray-400 w-10 flex-shrink-0 pt-1 tabular-nums">{it.start_time}</span>
                  <span className={`text-xs px-2 py-0.5 rounded-full flex-shrink-0 mt-0.5 ${CATEGORY_COLOR[it.category] ?? "bg-gray-50 text-gray-600"}`}>
                    {CATEGORY_LABEL[it.category]}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      {it.map_uri?.startsWith("http") ? (
                        <a href={it.map_uri} target="_blank" rel="noopener noreferrer"
                           className={`text-sm font-medium hover:underline truncate ${st.completed ? "text-gray-400 line-through" : "text-gray-800"}`}>
                          {it.name}
                        </a>
                      ) : (
                        <span className={`text-sm font-medium truncate ${st.completed ? "text-gray-400 line-through" : "text-gray-800"}`}>{it.name}</span>
                      )}
                      {it.estimated_cost > 0 && <span className="text-xs text-gray-400 flex-shrink-0">¥{it.estimated_cost}</span>}
                    </div>
                    {it.notes && <p className="text-xs text-gray-400 truncate mt-0.5">{it.notes}</p>}
                    {it.booking_uri?.startsWith("http") && (
                      <a href={it.booking_uri} target="_blank" rel="noopener noreferrer"
                         className="text-xs text-orange-600 hover:underline">去预订 →</a>
                    )}
                  </div>
                  {/* 勾选 */}
                  <div className="flex flex-col items-end gap-1 flex-shrink-0 text-xs">
                    <label className="flex items-center gap-1 text-gray-600 cursor-pointer select-none">
                      <input type="checkbox" checked={st.completed} onChange={() => toggle(k, "completed")} />
                      完成
                    </label>
                    <label className="flex items-center gap-1 text-gray-600 cursor-pointer select-none">
                      <input type="checkbox" checked={st.booked} onChange={() => toggle(k, "booked")} />
                      预订
                    </label>
                  </div>
                </div>
              );
            })}
          </div>
        ))}
      </div>

      {/* 分享 / 导出 / 重新规划 */}
      <div className="flex items-center justify-between">
        <div className="flex gap-3 text-gray-400">
          <button onClick={handleCopy} className="p-1.5 rounded-md hover:bg-gray-100 hover:text-gray-900 transition-colors" title={copied ? "已复制" : "复制行程"}>
            {copied ? (
              <svg className="w-4 h-4 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" /></svg>
            ) : (
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" /></svg>
            )}
          </button>
          <button onClick={() => shareViaEmail(plan, status)} className="p-1.5 rounded-md hover:bg-gray-100 hover:text-gray-900 transition-colors" title="邮箱分享">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" /></svg>
          </button>
          <button onClick={() => exportItinerary(plan, status)} className="p-1.5 rounded-md hover:bg-gray-100 hover:text-gray-900 transition-colors" title="导出 PDF">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" /></svg>
          </button>
        </div>
        <button onClick={onReset} className="text-sm text-gray-500 hover:text-gray-900 underline">重新规划一次</button>
      </div>
    </div>
  );
}
