"""
LangGraph 状态图组装。

节点执行路径（Workflow，非 ReAct）：
  parse_intent → search_candidates → generate_plans
      → check_availability
          ├─ 有可用方案 → human_review（interrupt）
          │       ├─ 用户确认 → execute_bookings → send_notification → END
          │       └─ 用户拒绝 → generate_plans（重规划）
          └─ 全部不可用
                  ├─ replan_count < max → generate_plans（重规划）
                  └─ replan_count >= max → handle_error → END
"""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agent.nodes import (
    check_availability,
    execute_bookings,
    generate_plans,
    handle_error,
    parse_intent,
    search_candidates,
    send_notification,
)
from agent.state import AgentState
from config import config


# ---------------------------------------------------------------------------
# 共享辅助函数
# ---------------------------------------------------------------------------

def _plan_is_available(plan, results: dict, venue_candidates: list, rest_candidates: list) -> bool:
    """
    检查方案中所有活动和餐厅是否都可用。
    不依赖 LLM 生成的 booking_required 字段——餐厅始终验证可用性，
    避免因 LLM 漏设该字段导致不可用方案被错误推给用户。
    """
    for item in plan.timeline:
        if item.category == "activity":
            matched = next(
                (v for v in venue_candidates if v["name"] == item.name), None
            )
        elif item.category == "restaurant":
            matched = next(
                (r for r in rest_candidates if r["name"] == item.name), None
            )
        else:
            continue  # transport 等其他类型不检查

        if matched is None:
            continue  # 候选池里找不到对应记录，跳过（不阻断）

        result = results.get(matched["id"])
        if result is not None and not result.available:
            # 明确查过且不可用才阻断；未查过（None）不视为不可用
            return False

    return True


# ---------------------------------------------------------------------------
# Human-in-the-Loop 节点
# ---------------------------------------------------------------------------

def human_review(state: AgentState) -> dict:
    """
    暂停执行，等待用户从候选方案中选择一个并确认。
    只将所有环节均可用的方案推给用户，避免用户选到部分不可用的方案。
    """
    results = state.get("availability_results") or {}
    venue_candidates = state.get("candidate_venues", [])
    rest_candidates = state.get("candidate_restaurants", [])
    recent_plans = state["candidate_plans"][-config.max_candidate_plans:]

    # 只展示完全可用的方案
    available_plans = [
        p for p in recent_plans
        if _plan_is_available(p, results, venue_candidates, rest_candidates)
    ]

    payload = interrupt({"plans": [p.model_dump() for p in available_plans]})

    confirmed: bool = payload.get("confirmed", False)
    selected_id: str = payload.get("selected_plan_id", "")
    feedback: str    = payload.get("feedback", "")

    if not confirmed:
        return {
            "user_confirmed": False,
            "selected_plan": None,
            "replan_feedback": feedback,
            "replan_base_plan_id": selected_id,  # "" = 全部重新规划，非空 = 基于此方案调整
        }

    selected = next((p for p in available_plans if p.id == selected_id), None)
    return {"user_confirmed": True, "selected_plan": selected, "replan_feedback": "", "replan_base_plan_id": ""}


# ---------------------------------------------------------------------------
# 条件边函数
# ---------------------------------------------------------------------------

def _route_after_availability(state: AgentState) -> str:
    """
    可用性检查后的路由：
    - 至少一个方案全部可用 → human_review
    - 全部不可用且未超重规划上限 → generate_plans
    - 超过上限 → handle_error
    """
    results = state.get("availability_results") or {}
    recent_plans = state["candidate_plans"][-config.max_candidate_plans:]
    venue_candidates = state.get("candidate_venues", [])
    rest_candidates = state.get("candidate_restaurants", [])

    any_available = any(
        _plan_is_available(p, results, venue_candidates, rest_candidates)
        for p in recent_plans
    )

    if any_available:
        return "human_review"

    replan_count = state.get("replan_count", 0)
    if replan_count >= config.max_replan_count:
        return "handle_error"

    return "generate_plans"


def _route_after_human_review(state: AgentState) -> str:
    """用户确认 → 执行；用户拒绝 → 重规划。"""
    if state.get("user_confirmed") and state.get("selected_plan"):
        return "execute_bookings"
    return "generate_plans"


def _increment_replan(state: AgentState) -> dict:
    """重规划前将计数器 +1，防止无限循环。"""
    return {"replan_count": state.get("replan_count", 0) + 1}


# ---------------------------------------------------------------------------
# 图的组装
# ---------------------------------------------------------------------------

def build_graph() -> StateGraph:
    builder = StateGraph(AgentState)

    # 注册节点
    builder.add_node("parse_intent", parse_intent)
    builder.add_node("search_candidates", search_candidates)
    builder.add_node("generate_plans", generate_plans)
    builder.add_node("check_availability", check_availability)
    builder.add_node("human_review", human_review)
    builder.add_node("execute_bookings", execute_bookings)
    builder.add_node("send_notification", send_notification)
    builder.add_node("handle_error", handle_error)
    builder.add_node("increment_replan", _increment_replan)

    # 主路径
    builder.add_edge(START, "parse_intent")
    builder.add_edge("parse_intent", "search_candidates")
    builder.add_edge("search_candidates", "generate_plans")
    builder.add_edge("generate_plans", "check_availability")

    # check_availability 后的条件分支
    builder.add_conditional_edges(
        "check_availability",
        _route_after_availability,
        {
            "human_review": "human_review",
            "generate_plans": "increment_replan",
            "handle_error": "handle_error",
        },
    )

    # 重规划回路
    builder.add_edge("increment_replan", "generate_plans")

    # human_review 后的条件分支
    builder.add_conditional_edges(
        "human_review",
        _route_after_human_review,
        {
            "execute_bookings": "execute_bookings",
            "generate_plans": "increment_replan",
        },
    )

    # 执行路径
    builder.add_edge("execute_bookings", "send_notification")
    builder.add_edge("send_notification", END)
    builder.add_edge("handle_error", END)

    return builder


def create_graph():
    """
    返回编译好的图，带 MemorySaver 支持 HiL interrupt 恢复。
    暂停点由 human_review 节点内部的 interrupt() 控制，
    不在 compile() 层声明 interrupt_before，避免双重暂停。
    """
    checkpointer = MemorySaver()
    return build_graph().compile(checkpointer=checkpointer)


# 模块级单例
graph = create_graph()
