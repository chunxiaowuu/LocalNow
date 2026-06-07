// 行程分享 / 导出：纯客户端，无需后端。
// 方式 1：复制带 emoji 的行程文字；导出：打印友好的独立 HTML（可另存为 PDF）。

import { Plan, TimelineItem } from "./types";

const CATEGORY_ICON: Record<string, string> = {
  activity: "🎯",
  restaurant: "🍴",
  transport: "🚕",
};

const CATEGORY_LABEL: Record<string, string> = {
  activity: "活动",
  restaurant: "餐厅",
  transport: "交通",
};

export type ItemStatus = { completed: boolean; booked: boolean };
export type StatusMap = Record<string, ItemStatus>;

/** 行程项稳定 key（用于勾选状态 / 状态导出），同 day+时间+名称唯一 */
export function itemKey(it: TimelineItem): string {
  return `${it.day ?? 1}|${it.start_time}|${it.name}`;
}

function statusTag(it: TimelineItem, status?: StatusMap): string {
  if (!status) return "";
  const s = status[itemKey(it)];
  if (!s) return "";
  return `[${s.completed ? "✅已完成" : "⬜未完成"} ${s.booked ? "✅已预订" : "⬜未预订"}] `;
}

/** 按 day 分组，保持时间顺序 */
export function groupByDay(timeline: TimelineItem[]): [number, TimelineItem[]][] {
  const map = new Map<number, TimelineItem[]>();
  for (const it of timeline) {
    const d = it.day ?? 1;
    if (!map.has(d)) map.set(d, []);
    map.get(d)!.push(it);
  }
  return [...map.entries()].sort((a, b) => a[0] - b[0]);
}

/** 方式 1：纯文字行程，适合粘贴到微信等。传入 status 则带勾选状态。 */
export function buildItineraryText(plan: Plan, status?: StatusMap): string {
  const lines: string[] = [`📍 ${plan.title}`];
  if (plan.summary) lines.push(plan.summary);

  const days = groupByDay(plan.timeline);
  const multiDay = days.length > 1;

  for (const [day, items] of days) {
    lines.push("");
    if (multiDay) lines.push(`【第 ${day} 天】`);
    for (const it of items) {
      const icon = CATEGORY_ICON[it.category] ?? "•";
      lines.push(`${icon} ${statusTag(it, status)}${it.start_time}–${it.end_time}  ${it.name}`);
      if (it.map_uri) lines.push(`   📍 ${it.map_uri}`);
      if (it.booking_uri) lines.push(`   🎫 预订：${it.booking_uri}`);
    }
  }

  lines.push("");
  lines.push(`人均约 ¥${plan.total_cost_estimate}`);
  lines.push("—— 由 LocalNow 规划");
  return lines.join("\n");
}

/** 导出：自包含、打印友好的 HTML 文档（浏览器可另存为 PDF）。传入 status 则带勾选状态。 */
export function buildItineraryHtml(plan: Plan, status?: StatusMap): string {
  const esc = (s: string) =>
    s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

  const days = groupByDay(plan.timeline);
  const multiDay = days.length > 1;

  const rows = days
    .map(([day, items]) => {
      const head = multiDay ? `<h2>第 ${day} 天</h2>` : "";
      const lis = items
        .map((it) => {
          const label = CATEGORY_LABEL[it.category] ?? "";
          const map = it.map_uri
            ? ` <a href="${esc(it.map_uri)}">地图</a>`
            : "";
          const book = it.booking_uri
            ? ` <a href="${esc(it.booking_uri)}">去预订</a>`
            : "";
          const notes = it.notes ? `<div class="notes">${esc(it.notes)}</div>` : "";
          const st = status?.[itemKey(it)];
          const mark = st
            ? `<span class="mark">${st.completed ? "✅" : "⬜"}完成 ${st.booked ? "✅" : "⬜"}预订</span> `
            : "";
          return `<li>
            ${mark}<span class="time">${esc(it.start_time)}–${esc(it.end_time)}</span>
            <span class="tag ${it.category}">${label}</span>
            <span class="name">${esc(it.name)}</span>${map}${book}
            ${notes}
          </li>`;
        })
        .join("");
      return `${head}<ul>${lis}</ul>`;
    })
    .join("");

  return `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>${esc(plan.title)} · LocalNow</title>
<style>
  body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;max-width:640px;margin:40px auto;padding:0 20px;color:#1f2937;line-height:1.6}
  h1{font-size:22px;margin:0 0 4px}
  .summary{color:#6b7280;margin:0 0 24px}
  h2{font-size:15px;color:#374151;margin:24px 0 8px;border-bottom:1px solid #eee;padding-bottom:4px}
  ul{list-style:none;padding:0;margin:0}
  li{padding:10px 0;border-bottom:1px solid #f3f4f6}
  .time{color:#9ca3af;font-variant-numeric:tabular-nums;margin-right:8px}
  .tag{font-size:12px;padding:1px 8px;border-radius:999px;margin-right:6px}
  .tag.activity{background:#eff6ff;color:#1d4ed8}
  .tag.restaurant{background:#fff7ed;color:#c2410c}
  .tag.transport{background:#f3f4f6;color:#4b5563}
  .name{font-weight:600}
  .mark{font-size:12px;margin-right:6px;color:#374151}
  a{color:#2563eb;text-decoration:none;font-size:13px;margin-left:6px}
  .notes{color:#9ca3af;font-size:12px;margin-top:2px;margin-left:2px}
  .foot{margin-top:24px;color:#6b7280;font-size:14px}
  @media print{a{color:#2563eb}body{margin:0}}
</style></head>
<body>
  <h1>${esc(plan.title)}</h1>
  ${plan.summary ? `<p class="summary">${esc(plan.summary)}</p>` : ""}
  ${rows}
  <p class="foot">人均约 ¥${plan.total_cost_estimate} · 由 LocalNow 规划</p>
</body></html>`;
}

/** 复制到剪贴板，返回是否成功 */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/** 通过邮箱分享：用 mailto 打开默认邮件客户端，预填标题和行程正文 */
export function shareViaEmail(plan: Plan, status?: StatusMap): void {
  const subject = `行程分享：${plan.title}`;
  const body = buildItineraryText(plan, status);
  window.location.href =
    `mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}

/** 打开打印窗口（用户可另存为 PDF / 打印），失败回退为下载 .html */
export function exportItinerary(plan: Plan, status?: StatusMap): void {
  const html = buildItineraryHtml(plan, status);
  const win = window.open("", "_blank");
  if (win) {
    win.document.write(html);
    win.document.close();
    win.focus();
    setTimeout(() => win.print(), 300); // 等待渲染再唤起打印
    return;
  }
  // 弹窗被拦截 → 下载 HTML 文件
  const blob = new Blob([html], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${plan.title}.html`;
  a.click();
  URL.revokeObjectURL(url);
}
