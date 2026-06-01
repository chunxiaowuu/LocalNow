"use client";

import { BookingResult } from "@/lib/types";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

interface Props {
  summary: string;
  bookingResults: BookingResult[];
  onReset: () => void;
}

export function ExecSummary({ summary, bookingResults, onReset }: Props) {
  const totalCost = bookingResults.reduce((sum, r) => sum + r.cost, 0);

  return (
    <div className="w-full max-w-2xl mx-auto space-y-6">
      {/* 通知消息 */}
      <Card className="border-green-100 bg-green-50">
        <CardContent className="pt-6">
          <div className="flex items-start gap-3">
            <div className="w-8 h-8 rounded-full bg-green-100 flex items-center justify-center flex-shrink-0">
              <svg className="w-4 h-4 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <div>
              <p className="text-sm font-medium text-green-800 mb-1">行程已安排完毕！</p>
              <p className="text-sm text-green-700 whitespace-pre-wrap">{summary}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* 预订详情 */}
      <div>
        <h3 className="text-sm font-medium text-gray-500 mb-3">预订详情</h3>
        <div className="space-y-2">
          {bookingResults.map((result, i) => (
            <div
              key={i}
              className="flex items-center justify-between py-3 px-4 rounded-lg bg-white border border-gray-100"
            >
              <div className="flex items-center gap-3">
                <Badge
                  variant={result.status === "success" ? "default" : "destructive"}
                  className="text-xs"
                >
                  {result.action}
                </Badge>
                <div>
                  <p className="text-sm font-medium text-gray-800">{result.target_name}</p>
                  <p className="text-xs text-gray-400">{result.detail}</p>
                </div>
              </div>
              {result.cost > 0 && (
                <span className="text-sm font-medium text-gray-600">¥{result.cost}</span>
              )}
            </div>
          ))}
        </div>

        {totalCost > 0 && (
          <div className="flex justify-between items-center mt-4 pt-4 border-t border-gray-100">
            <span className="text-sm text-gray-500">预计总花费</span>
            <span className="text-base font-semibold text-gray-900">¥{totalCost}</span>
          </div>
        )}
      </div>

      <Button variant="outline" onClick={onReset} className="w-full">
        重新规划一次
      </Button>
    </div>
  );
}
