"use client";

import { useState } from "react";
import { Plan } from "@/lib/types";
import { buildItineraryText, copyText, exportItinerary, shareViaEmail } from "@/lib/share";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

interface Props {
  plans: Plan[];
  onConfirm: (planId: string) => void;
  onReject: (feedback: string, basePlanId: string) => void;
}

const CATEGORY_LABEL: Record<string, string> = {
  activity: "活动",
  restaurant: "餐厅",
  transport: "交通",
};

const CATEGORY_COLOR: Record<string, string> = {
  activity: "bg-blue-50 text-blue-700",
  restaurant: "bg-orange-50 text-orange-700",
  transport: "bg-gray-50 text-gray-600",
};

type RejectMode = "adjust" | "full";

export function PlanCards({ plans, onConfirm, onReject }: Props) {
  const [selected,    setSelected]    = useState<string | null>(null);
  const [rejecting,   setRejecting]   = useState(false);
  const [rejectMode,  setRejectMode]  = useState<RejectMode>("full");
  const [feedback,    setFeedback]    = useState("");
  const [copiedId,    setCopiedId]    = useState<string | null>(null);

  const selectedPlan = plans.find(p => p.id === selected);

  const handleCopy = async (plan: Plan) => {
    const ok = await copyText(buildItineraryText(plan));
    if (ok) {
      setCopiedId(plan.id);
      setTimeout(() => setCopiedId(null), 2000);
    }
  };

  const openReject = (mode: RejectMode) => {
    setRejectMode(mode);
    setRejecting(true);
  };

  const submitReject = () => {
    const basePlanId = rejectMode === "adjust" ? (selected ?? "") : "";
    onReject(feedback, basePlanId);
  };

  return (
    <div className="w-full max-w-4xl mx-auto">
      <div className="text-center mb-6">
        <h2 className="text-xl font-semibold text-gray-900">为您准备了 {plans.length} 个方案</h2>
        <p className="text-sm text-gray-500 mt-1">选择一个方案，我将为您完成所有预订</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        {plans.map((plan) => (
          <Card
            key={plan.id}
            onClick={() => setSelected(plan.id)}
            className={`cursor-pointer transition-all ${
              selected === plan.id
                ? "ring-2 ring-gray-900 shadow-md"
                : "hover:shadow-md hover:border-gray-300"
            }`}
          >
            <CardHeader className="pb-3">
              <div className="flex items-start justify-between">
                <CardTitle className="text-base">{plan.title}</CardTitle>
                {selected === plan.id && (
                  <div className="w-5 h-5 rounded-full bg-gray-900 flex items-center justify-center flex-shrink-0 ml-2">
                    <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                  </div>
                )}
              </div>
              <p className="text-sm text-gray-500">{plan.summary}</p>
            </CardHeader>

            <CardContent className="space-y-3">
              <Separator />

              {/* Timeline */}
              <div className="space-y-2">
                {plan.timeline.map((item, i) => (
                  <div key={i} className="flex items-start gap-3">
                    <span className="text-xs text-gray-400 w-10 flex-shrink-0 pt-0.5">
                      {item.start_time}
                    </span>
                    <span className={`text-xs px-2 py-0.5 rounded-full flex-shrink-0 ${CATEGORY_COLOR[item.category]}`}>
                      {CATEGORY_LABEL[item.category]}
                    </span>
                    <div className="min-w-0">
                      {item.map_uri ? (
                        <a
                          href={item.map_uri}
                          target="_blank"
                          rel="noopener noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          className="text-sm font-medium text-gray-800 hover:text-blue-600 hover:underline inline-flex items-center gap-1 max-w-full"
                          title="在高德地图中查看"
                        >
                          <span className="truncate">{item.name}</span>
                          <svg className="w-3 h-3 flex-shrink-0 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
                          </svg>
                        </a>
                      ) : (
                        <p className="text-sm font-medium text-gray-800 truncate">{item.name}</p>
                      )}
                      {item.notes && (
                        <p className="text-xs text-gray-400 truncate">{item.notes}</p>
                      )}
                      {item.booking_uri && (
                        <a
                          href={item.booking_uri}
                          target="_blank"
                          rel="noopener noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          className="text-xs text-orange-600 hover:text-orange-700 hover:underline inline-flex items-center gap-0.5 mt-0.5"
                          title="在高德搜索中预订"
                        >
                          去预订
                          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
                          </svg>
                        </a>
                      )}
                    </div>
                  </div>
                ))}
              </div>

              <Separator />

              {/* 费用与约束 */}
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-gray-900">
                  人均约 ¥{plan.total_cost_estimate}
                </span>
                <div className="flex gap-1 flex-wrap justify-end">
                  {Object.entries(plan.constraint_coverage)
                    .filter(([, v]) => v)
                    .map(([k]) => (
                      <Badge key={k} variant="secondary" className="text-xs">
                        ✓ {k.replace(/_/g, " ")}
                      </Badge>
                    ))}
                </div>
              </div>

              {/* 分享 / 导出 */}
              <Separator />
              <div className="flex gap-3 text-gray-400">
                {/* 复制行程 */}
                <button
                  onClick={(e) => { e.stopPropagation(); handleCopy(plan); }}
                  className="p-1.5 rounded-md hover:bg-gray-100 hover:text-gray-900 transition-colors"
                  title={copiedId === plan.id ? "已复制" : "复制行程"}
                >
                  {copiedId === plan.id ? (
                    <svg className="w-4 h-4 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                  ) : (
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                    </svg>
                  )}
                </button>
                {/* 邮箱分享 */}
                <button
                  onClick={(e) => { e.stopPropagation(); shareViaEmail(plan); }}
                  className="p-1.5 rounded-md hover:bg-gray-100 hover:text-gray-900 transition-colors"
                  title="邮箱分享"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                  </svg>
                </button>
                {/* 导出 PDF */}
                <button
                  onClick={(e) => { e.stopPropagation(); exportItinerary(plan); }}
                  className="p-1.5 rounded-md hover:bg-gray-100 hover:text-gray-900 transition-colors"
                  title="导出 PDF"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                  </svg>
                </button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {rejecting ? (
        <div className="space-y-3">
          {/* 模式切换：仅在选了方案时显示 */}
          {selected && (
            <div className="flex rounded-lg border border-gray-200 overflow-hidden text-sm">
              <button
                onClick={() => setRejectMode("adjust")}
                className={`flex-1 px-3 py-2 transition-colors truncate ${
                  rejectMode === "adjust" ? "bg-gray-900 text-white" : "text-gray-600 hover:bg-gray-50"
                }`}
              >
                基于「{selectedPlan?.title}」调整
              </button>
              <button
                onClick={() => setRejectMode("full")}
                className={`flex-1 px-3 py-2 transition-colors border-l border-gray-200 ${
                  rejectMode === "full" ? "bg-gray-900 text-white" : "text-gray-600 hover:bg-gray-50"
                }`}
              >
                全部重新规划
              </button>
            </div>
          )}

          <textarea
            value={feedback}
            onChange={e => setFeedback(e.target.value)}
            placeholder={
              rejectMode === "adjust"
                ? "哪里需要调整？比如：时间太早了、想换个餐厅..."
                : "描述你想要的方案，比如：先吃午饭，下午玩，傍晚吃晚饭..."
            }
            rows={2}
            autoFocus
            className="w-full resize-none rounded-xl border border-gray-200 px-4 py-3 text-sm
                       placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-gray-900"
          />
          <div className="flex gap-3 justify-center">
            <Button variant="ghost" onClick={() => { setRejecting(false); setFeedback(""); }}>
              取消
            </Button>
            <Button variant="outline" onClick={submitReject}>
              提交反馈，重新规划
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex gap-3 justify-center">
          {selected ? (
            <Button variant="outline" onClick={() => openReject("adjust")} className="px-6">
              在此基础上调整
            </Button>
          ) : (
            <Button variant="outline" onClick={() => openReject("full")} className="px-6">
              重新规划
            </Button>
          )}
          <Button
            disabled={!selected}
            onClick={() => selected && onConfirm(selected)}
            className="px-8"
          >
            确认此方案，开始预订
          </Button>
        </div>
      )}
    </div>
  );
}
