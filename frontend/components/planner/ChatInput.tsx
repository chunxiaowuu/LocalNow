"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";

interface Props {
  onSubmit: (message: string) => void;
  loading: boolean;
}

export function ChatInput({ onSubmit, loading }: Props) {
  const [value, setValue] = useState("");

  const handleSubmit = () => {
    const trimmed = value.trim();
    if (!trimmed || loading) return;
    onSubmit(trimmed);
    setValue("");
  };

  return (
    <div className="w-full max-w-2xl mx-auto">
      <div className="text-center mb-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">LocalNow</h1>
        <p className="text-gray-500">告诉我你想做什么，我来帮你安排好一切</p>
      </div>

      <div className="flex gap-3">
        <textarea
          className="flex-1 resize-none rounded-xl border border-gray-200 bg-white px-4 py-3 text-sm shadow-sm placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-gray-900 min-h-[80px]"
          placeholder="例如：今天下午带娃出去玩，顺便吃个饭，不要太远..."
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              handleSubmit();
            }
          }}
          disabled={loading}
        />
        <Button
          onClick={handleSubmit}
          disabled={!value.trim() || loading}
          className="self-end px-6 py-3 rounded-xl"
        >
          {loading ? "规划中..." : "开始规划"}
        </Button>
      </div>

      <div className="mt-4 flex gap-2 flex-wrap">
        {[
          "今天下午带5岁娃出去玩，老婆要减肥，不要太远",
          "周末和三个朋友下午玩4小时，预算300以内",
        ].map((example) => (
          <button
            key={example}
            onClick={() => setValue(example)}
            disabled={loading}
            className="text-xs text-gray-400 hover:text-gray-600 border border-gray-200 rounded-full px-3 py-1 transition-colors"
          >
            {example}
          </button>
        ))}
      </div>
    </div>
  );
}
