"use client";

import { useState } from "react";
import { ActivityPreference, PlanRequest, TravelMode } from "@/lib/types";

const PREFERENCES: { id: ActivityPreference; label: string }[] = [
  { id: "museum",   label: "博物馆" },
  { id: "nature",   label: "自然公园" },
  { id: "cultural", label: "人文历史" },
  { id: "social",   label: "休闲社交" },
  { id: "family",   label: "亲子" },
  { id: "food",     label: "美食" },
];

const TRAVEL_MODES: { id: TravelMode; label: string }[] = [
  { id: "walk",  label: "步行" },
  { id: "metro", label: "地铁" },
  { id: "taxi",  label: "打车" },
  { id: "bike",  label: "骑行" },
];

const DURATIONS: { hours: number; label: string }[] = [
  { hours: 3, label: "半天" },
  { hours: 5, label: "大半天" },
  { hours: 8, label: "全天" },
];

function todayString() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

interface Props {
  onSubmit: (req: PlanRequest) => void;
  loading: boolean;
}

export function PlannerInput({ onSubmit, loading }: Props) {
  const today = todayString();
  const [startDate, setStartDate]   = useState(today);
  const [endDate,   setEndDate]     = useState(today);
  const [groupSize, setGroupSize]   = useState(2);
  const [city,      setCity]        = useState("上海");
  const [prefs,     setPrefs]       = useState<Set<ActivityPreference>>(new Set());
  const [modes,     setModes]       = useState<Set<TravelMode>>(new Set(["taxi", "metro"]));
  const [durationHours, setDurationHours] = useState(5);
  const [freeText,  setFreeText]    = useState("");

  const toggle = <T extends string>(set: Set<T>, id: T): Set<T> => {
    const next = new Set(set);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  };

  const canSubmit = startDate && endDate && city.trim() && !loading;

  const handleSubmit = () => {
    if (!canSubmit) return;
    onSubmit({
      start_date:      startDate,
      end_date:        endDate,
      preferences:     [...prefs],
      max_distance_km: 8,
      group_size:      groupSize,
      duration_hours:  durationHours,
      travel_modes:    modes.size > 0 ? [...modes] : ["taxi", "metro"],
      city:            city.trim(),
      free_text:       freeText.trim(),
    });
  };

  return (
    <div className="w-full max-w-lg mx-auto">
      {/* Brand */}
      <div className="text-center mb-10">
        <h1 className="text-4xl font-bold tracking-tight text-gray-900">LocalNow</h1>
        <p className="mt-2 text-gray-500">帮你把今天安排得刚刚好</p>
      </div>

      {/* Form card */}
      <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6 space-y-6">

        {/* Date range */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">出行日期</label>
          <div className="flex items-center gap-2">
            <input
              type="date" value={startDate} min={today}
              onChange={e => {
                setStartDate(e.target.value);
                if (e.target.value > endDate) setEndDate(e.target.value);
              }}
              className="flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-gray-900"
            />
            <span className="text-gray-300 text-sm">—</span>
            <input
              type="date" value={endDate} min={startDate}
              onChange={e => setEndDate(e.target.value)}
              className="flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-gray-900"
            />
          </div>
        </div>

        {/* Per-day duration */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">每天时长</label>
          <div className="flex gap-2">
            {DURATIONS.map(({ hours, label }) => {
              const active = durationHours === hours;
              return (
                <button
                  key={hours} onClick={() => setDurationHours(hours)}
                  className={`px-4 py-1.5 rounded-full text-sm border transition-all duration-150 ${
                    active
                      ? "bg-gray-900 text-white border-gray-900"
                      : "text-gray-600 border-gray-200 hover:border-gray-400 hover:text-gray-900"
                  }`}
                >
                  {label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Group size + City */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">人数</label>
            <div className="flex items-center rounded-lg border border-gray-200 overflow-hidden">
              <button
                onClick={() => setGroupSize(n => Math.max(1, n - 1))}
                className="px-3 py-2 text-gray-400 hover:text-gray-700 hover:bg-gray-50 transition-colors select-none"
              >−</button>
              <span className="flex-1 text-center text-sm font-medium">{groupSize} 人</span>
              <button
                onClick={() => setGroupSize(n => Math.min(20, n + 1))}
                className="px-3 py-2 text-gray-400 hover:text-gray-700 hover:bg-gray-50 transition-colors select-none"
              >+</button>
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">城市</label>
            <input
              type="text" value={city} onChange={e => setCity(e.target.value)}
              placeholder="上海"
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-gray-900"
            />
          </div>
        </div>

        {/* Preferences */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            偏好
            <span className="font-normal text-gray-400 ml-1">可多选</span>
          </label>
          <div className="flex flex-wrap gap-2">
            {PREFERENCES.map(({ id, label }) => {
              const active = prefs.has(id);
              return (
                <button
                  key={id} onClick={() => setPrefs(toggle(prefs, id))}
                  className={`px-4 py-1.5 rounded-full text-sm border transition-all duration-150 ${
                    active
                      ? "bg-gray-900 text-white border-gray-900"
                      : "text-gray-600 border-gray-200 hover:border-gray-400 hover:text-gray-900"
                  }`}
                >
                  {label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Travel modes */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">出行方式</label>
          <div className="flex gap-2">
            {TRAVEL_MODES.map(({ id, label }) => {
              const active = modes.has(id);
              return (
                <button
                  key={id} onClick={() => setModes(toggle(modes, id))}
                  className={`px-4 py-1.5 rounded-full text-sm border transition-all duration-150 ${
                    active
                      ? "bg-gray-900 text-white border-gray-900"
                      : "text-gray-600 border-gray-200 hover:border-gray-400 hover:text-gray-900"
                  }`}
                >
                  {label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Free text */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            补充说明
            <span className="font-normal text-gray-400 ml-1">选填</span>
          </label>
          <textarea
            value={freeText} onChange={e => setFreeText(e.target.value)}
            placeholder="例如：不要太远，带5岁小孩，老婆要减肥..."
            rows={2}
            className="w-full resize-none rounded-lg border border-gray-200 px-3 py-2 text-sm placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-gray-900"
          />
        </div>

        {/* Submit */}
        <button
          onClick={handleSubmit}
          disabled={!canSubmit}
          className="w-full bg-gray-900 text-white rounded-xl py-3 text-sm font-medium
                     hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed
                     transition-colors duration-150"
        >
          {loading ? "规划中..." : "开始规划"}
        </button>
      </div>
    </div>
  );
}
