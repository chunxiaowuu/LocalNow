"use client";

import { useState } from "react";
import { Plan } from "@/lib/types";
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

  const selectedPlan = plans.find(p => p.id === selected);

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
                      <p className="text-sm font-medium text-gray-800 truncate">{item.name}</p>
                      {item.notes && (
                        <p className="text-xs text-gray-400 truncate">{item.notes}</p>
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
