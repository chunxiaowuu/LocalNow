// 与后端 Pydantic schema 对应的 TypeScript 类型

export type TravelMode = "walk" | "taxi" | "metro" | "bike";
export type ActivityPreference = "nature" | "cultural" | "museum" | "social" | "food" | "family";

export interface PlanRequest {
  start_date: string;          // YYYY-MM-DD
  end_date: string;
  preferences: ActivityPreference[];
  max_distance_km: number;
  group_size: number;
  duration_hours: number;      // 每天活动时长（含餐饮）
  travel_modes: TravelMode[];
  city: string;
  free_text: string;
}

export interface TimelineItem {
  name: string;
  address: string;
  start_time: string;
  end_time: string;
  category: "activity" | "restaurant" | "transport";
  booking_required: boolean;
  estimated_cost: number;
  notes: string;
  map_uri: string;            // 高德地图跳转链接，空串表示无
}

export interface Plan {
  id: string;
  title: string;
  summary: string;
  timeline: TimelineItem[];
  total_duration_minutes: number;
  total_cost_estimate: number;
  constraint_coverage: Record<string, boolean>;
  score: number;
}

export interface BookingResult {
  action: string;
  target_name: string;
  status: "success" | "failed" | "skipped";
  detail: string;
  cost: number;
  fallback_applied: boolean;
}

// SSE 事件类型
export type SseEvent =
  | { type: "node_update"; node: string; message: string }
  | { type: "interrupt"; plans: Plan[] }
  | { type: "done"; summary: string; booking_results: BookingResult[]; error?: string }
  | { type: "error"; message: string };

// 应用阶段状态机
export type Phase =
  | { kind: "input" }
  | { kind: "running"; events: ProgressEvent[] }
  | { kind: "interrupted"; events: ProgressEvent[]; plans: Plan[]; sessionId: string }
  | { kind: "executing"; events: ProgressEvent[] }
  | { kind: "done"; summary: string; bookingResults: BookingResult[] }
  | { kind: "error"; message: string };

export interface ProgressEvent {
  node: string;
  message: string;
  done: boolean;
}
