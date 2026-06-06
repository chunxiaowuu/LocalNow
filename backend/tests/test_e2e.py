"""
端到端测试脚本。

测试两个核心场景的完整流程：用户输入 → Agent 规划 → 用户确认 → 预订执行。
遇到 interrupt 时自动选第一个方案，模拟用户确认操作。

运行前提：后端已启动（uv run uvicorn api.main:app --port 8000）

运行方式：
  uv run python tests/test_e2e.py family    # 家庭场景
  uv run python tests/test_e2e.py friends   # 朋友场景
  uv run python tests/test_e2e.py all       # 两个场景都跑
"""

import json
import sys
import time
from dataclasses import dataclass, field

import httpx

BASE_URL = "http://localhost:8000"

# 两个测试场景的输入
SCENARIOS = {
    "family": "今天下午带5岁娃出去玩，老婆在减肥，不要太远",
    "friends": "周末和三个朋友下午玩，4个人，预算200以内",
}


# ---------------------------------------------------------------------------
# 结果收集
# ---------------------------------------------------------------------------

@dataclass
class E2EResult:
    scenario: str
    checks: list[tuple[str, bool, str]] = field(default_factory=list)  # (描述, 通过, 详情)
    constraints: dict = field(default_factory=dict)
    candidate_venues: list[dict] = field(default_factory=list)
    candidate_restaurants: list[dict] = field(default_factory=list)
    plans: list[dict] = field(default_factory=list)
    booking_results: list[dict] = field(default_factory=list)
    summary: str = ""
    error: str = ""

    def check(self, desc: str, passed: bool, detail: str = "") -> None:
        self.checks.append((desc, passed, detail))
        status = "✓" if passed else "✗"
        print(f"  {status} {desc}" + (f"：{detail}" if detail else ""))

    def print_summary(self) -> None:
        total = len(self.checks)
        passed = sum(1 for _, ok, _ in self.checks if ok)
        print(f"\n{'='*50}")
        print(f"场景【{self.scenario}】结果：{passed}/{total} 通过")
        if self.error:
            print(f"错误：{self.error}")
        print('='*50)


# ---------------------------------------------------------------------------
# SSE 客户端（同步读取 httpx 流）
# ---------------------------------------------------------------------------

def read_sse_stream(session_id: str, timeout: int = 600) -> list[dict]:
    """
    读取 SSE 流直到 interrupt、done 或 error 事件，返回收到的所有事件列表。
    timeout 单位秒，本地模型较慢设为 10 分钟。
    """
    events = []
    url = f"{BASE_URL}/session/{session_id}/stream"

    with httpx.Client(timeout=timeout) as client:
        with client.stream("GET", url, headers={"Accept": "text/event-stream"}) as resp:
            event_type = None
            for line in resp.iter_lines():
                if line.startswith("event:"):
                    event_type = line.split(":", 1)[1].strip()
                elif line.startswith("data:") and event_type:
                    data_str = line.split(":", 1)[1].strip()
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        data = {}
                    events.append({"type": event_type, "data": data})
                    print(f"    [SSE] {event_type}: {str(data)[:80]}...")
                    # interrupt / done / error 都是终止事件
                    if event_type in ("interrupt", "done", "error"):
                        return events
                    event_type = None
    return events


def confirm_plan(session_id: str, plan_id: str) -> None:
    resp = httpx.post(
        f"{BASE_URL}/session/{session_id}/confirm",
        json={"confirmed": True, "selected_plan_id": plan_id},
    )
    resp.raise_for_status()


# ---------------------------------------------------------------------------
# 验证函数
# ---------------------------------------------------------------------------

def validate_family(result: E2EResult) -> None:
    c = result.constraints

    result.check(
        "意图解析：识别为家庭场景",
        c.get("scenario") == "family",
        f"实际：{c.get('scenario')}",
    )
    result.check(
        "意图解析：kids_friendly=True",
        c.get("activity", {}).get("kids_friendly") is True,
        f"实际：{c.get('activity', {}).get('kids_friendly')}",
    )
    result.check(
        "意图解析：has_low_calorie_options=True",
        c.get("restaurant", {}).get("has_low_calorie_options") is True,
        f"实际：{c.get('restaurant', {}).get('has_low_calorie_options')}",
    )

    non_kids_venues = [v for v in result.candidate_venues if not v.get("kids_friendly")]
    result.check(
        "候选过滤：场所全部 kids_friendly",
        len(non_kids_venues) == 0,
        f"不亲子场所：{[v.get('name') for v in non_kids_venues]}",
    )

    non_lowcal_rests = [r for r in result.candidate_restaurants
                        if not r.get("has_low_calorie_options")]
    result.check(
        "候选过滤：餐厅全部有低卡选项",
        len(non_lowcal_rests) == 0,
        f"无低卡餐厅：{[r.get('name') for r in non_lowcal_rests]}",
    )

    _validate_common(result)


def validate_friends(result: E2EResult) -> None:
    c = result.constraints

    result.check(
        "意图解析：识别为朋友场景",
        c.get("scenario") == "friends",
        f"实际：{c.get('scenario')}",
    )
    result.check(
        "意图解析：group_size=4",
        c.get("group_size") == 4,
        f"实际：{c.get('group_size')}",
    )
    result.check(
        "意图解析：budget_per_person=200",
        c.get("budget_per_person") == 200,
        f"实际：{c.get('budget_per_person')}",
    )

    small_rests = [r for r in result.candidate_restaurants
                   if r.get("max_party_size", 0) < 4]
    result.check(
        "候选过滤：餐厅容纳人数 >= 4",
        len(small_rests) == 0,
        f"容量不足餐厅：{[r.get('name') for r in small_rests]}",
    )

    _validate_common(result)


def _validate_common(result: E2EResult) -> None:
    """两个场景共用的验证项。"""
    result.check(
        "方案生成：至少生成 1 个方案",
        len(result.plans) >= 1,
        f"方案数：{len(result.plans)}",
    )

    if result.plans:
        plan = result.plans[0]
        has_timeline = bool(plan.get("timeline"))
        result.check(
            "方案结构：timeline 不为空",
            has_timeline,
        )
        has_coverage = bool(plan.get("constraint_coverage"))
        result.check(
            "方案结构：包含 constraint_coverage",
            has_coverage,
            f"覆盖：{plan.get('constraint_coverage')}",
        )

    if result.booking_results:
        all_success = all(r.get("status") == "success" for r in result.booking_results)
        result.check(
            "预订执行：所有预订均成功",
            all_success,
            f"结果：{[(r.get('action'), r.get('status')) for r in result.booking_results]}",
        )
    else:
        result.check("预订执行：有预订结果", False, "booking_results 为空")

    result.check(
        "通知发送：summary_message 不为空",
        bool(result.summary),
        f"消息：{result.summary[:50]}..." if result.summary else "",
    )


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def run_scenario(name: str, message: str) -> E2EResult:
    result = E2EResult(scenario=name)
    print(f"\n{'='*50}")
    print(f"开始测试场景：【{name}】")
    print(f"输入：{message}")
    print('='*50)

    try:
        # 1. 创建会话
        resp = httpx.post(f"{BASE_URL}/session", json={"message": message})
        resp.raise_for_status()
        session_id = resp.json()["session_id"]
        print(f"Session ID: {session_id}")

        # 2. 第一段 SSE：运行到 interrupt
        print("\n[第一段 SSE] Agent 规划中...")
        start = time.time()
        events1 = read_sse_stream(session_id)
        print(f"第一段用时：{time.time() - start:.0f}s")

        # 检查是否收到 interrupt
        interrupt_event = next((e for e in events1 if e["type"] == "interrupt"), None)
        error_event = next((e for e in events1 if e["type"] == "error"), None)

        if error_event:
            result.error = error_event["data"].get("message", "unknown error")
            return result

        if not interrupt_event:
            result.error = "未收到 interrupt 事件"
            return result

        plans = interrupt_event["data"].get("plans", [])
        result.plans = plans
        print(f"\n收到 {len(plans)} 个方案，自动选择第一个")

        # 从 interrupt payload 里拿 constraints 和候选（通过 graph state）
        # 实际上这些在 interrupt payload 里没有，我们从 /result 拿不到（还没 done）
        # 改为从图的 checkpoint 里读（调 get_state）
        # 简化：先从 plan 的 constraint_coverage 推断，detail 验证靠后续

        # 3. 确认方案
        if plans:
            confirm_plan(session_id, plans[0]["id"])
            print("已确认方案，等待第二段 SSE...")

            # 4. 第二段 SSE：执行预订到 done
            print("\n[第二段 SSE] 执行预订中...")
            start = time.time()
            events2 = read_sse_stream(session_id)
            print(f"第二段用时：{time.time() - start:.0f}s")

            done_event = next((e for e in events2 if e["type"] == "done"), None)
            if done_event:
                result.booking_results = done_event["data"].get("booking_results", [])
                result.summary = done_event["data"].get("summary", "")

        # 5. 从后端拿完整 state（用 /result 端点）
        result_resp = httpx.get(f"{BASE_URL}/session/{session_id}/result", timeout=10)
        if result_resp.status_code == 200:
            state = result_resp.json().get("result", {}).get("values", {})
            constraints = state.get("constraints")
            if constraints and hasattr(constraints, "__dict__"):
                # Pydantic 对象
                result.constraints = constraints.model_dump() if hasattr(constraints, "model_dump") else {}
            elif isinstance(constraints, dict):
                result.constraints = constraints
            result.candidate_venues = state.get("candidate_venues", [])
            result.candidate_restaurants = state.get("candidate_restaurants", [])

    except Exception as e:
        result.error = str(e)

    return result


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "all"

    if arg == "all":
        targets = list(SCENARIOS.items())
    elif arg in SCENARIOS:
        targets = [(arg, SCENARIOS[arg])]
    else:
        print("用法：uv run python tests/test_e2e.py [family|friends|all]")
        sys.exit(1)

    results = []
    for name, message in targets:
        result = run_scenario(name, message)
        print("\n--- 验证结果 ---")

        if result.error:
            print(f"  ✗ 流程错误：{result.error}")
        else:
            if name == "family":
                validate_family(result)
            elif name == "friends":
                validate_friends(result)

        result.print_summary()
        results.append(result)

    # 总汇
    if len(results) > 1:
        total = sum(len(r.checks) for r in results)
        passed = sum(sum(1 for _, ok, _ in r.checks if ok) for r in results)
        print(f"\n全部场景：{passed}/{total} 通过")


if __name__ == "__main__":
    main()
