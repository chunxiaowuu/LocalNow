"""
LangGraph 节点函数。

每个节点接收 AgentState，返回需要更新的字段（partial update）。
节点只负责自己的职责，不直接操作其他节点的字段。

节点执行顺序（Workflow，非 ReAct）：
  parse_intent → search_candidates → generate_plans
      → check_availability → [interrupt: human_review]
      → execute_bookings → send_notification

条件边：
  check_availability 后：全部不可用 → replan（回 generate_plans）
  replan 次数超限 → handle_error
"""

import uuid
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from agent.state import AgentState
from config import config
from llm.factory import get_llm
from models.schemas import (
    BookingResult,
    ConstraintSet,
    Plan,
)
from tools.availability import check_restaurant_availability, check_venue_availability
from tools.booking import book_restaurant, book_venue
from tools.notification import send_trip_summary
from tools.search import search_restaurants, search_venues

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_system_prompt(subdir: str) -> str:
    return (_PROMPTS_DIR / subdir / "system.txt").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 节点 1：意图解析
# ---------------------------------------------------------------------------

def parse_intent(state: AgentState) -> dict:
    """
    从用户自然语言消息提取结构化约束（ConstraintSet）。
    使用 fast LLM + with_structured_output 保证输出符合 Pydantic schema。
    with_structured_output 在 Anthropic 下使用 tool_use，OpenAI 下使用 function calling，
    底层自动处理，节点代码与 provider 无关。
    """
    llm = get_llm("fast").with_structured_output(ConstraintSet)
    system_prompt = _load_system_prompt("intent_parser")

    constraints: ConstraintSet = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=state["user_message"]),
    ])

    return {
        "constraints": constraints,
        "scenario": constraints.scenario.value,
    }


# ---------------------------------------------------------------------------
# 节点 2：候选场所搜索
# ---------------------------------------------------------------------------

def search_candidates(state: AgentState) -> dict:
    """
    调用 search 工具，用约束过滤 + 语义检索拿到候选池。
    结果写入 AgentState 的 candidate_venues / candidate_restaurants 字段，
    供后续节点读取（不随 replan 重置，除非显式覆盖）。
    """
    constraints = state["constraints"]
    preference_text = state["user_message"]

    venues = search_venues(constraints, preference_text, n_results=8)
    restaurants = search_restaurants(constraints, preference_text, n_results=8)

    return {
        "candidate_venues": [v.model_dump() for v in venues],
        "candidate_restaurants": [r.model_dump() for r in restaurants],
    }


# ---------------------------------------------------------------------------
# 节点 3：方案生成
# ---------------------------------------------------------------------------

class _PlansResponse(BaseModel):
    """Instructor/with_structured_output 要求顶层是对象，用 wrapper 包住 list[Plan]。"""
    plans: list[Plan]


def generate_plans(state: AgentState) -> dict:
    """
    使用 main LLM 生成 max_candidate_plans 个风格不同的方案骨架。
    with_structured_output(_PlansResponse) 自动验证 schema，失败时抛 ValidationError。
    行程时间由 LLM 根据坐标距离自行估算（合并进 prompt，无需独立工具）。
    """
    llm = get_llm("main").with_structured_output(_PlansResponse)
    system_prompt = _load_system_prompt("planner")
    constraints = state["constraints"]

    venues = state.get("candidate_venues", [])
    restaurants = state.get("candidate_restaurants", [])

    user_content = f"""
用户需求：{state["user_message"]}

约束条件：
- 场景：{constraints.scenario.value}
- 人数：{constraints.group_size} 人
- 最远距离：{constraints.max_distance_km} km
- 人均预算：{constraints.budget_per_person} 元
- 活动时长：{constraints.duration_hours} 小时

候选场所（已通过硬约束过滤）：
{venues}

候选餐厅（已通过硬约束过滤）：
{restaurants}

请生成 {config.max_candidate_plans} 个风格不同的活动方案。
"""

    response: _PlansResponse = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_content),
    ])

    plans = response.plans
    for p in plans:
        p.id = f"plan-{uuid.uuid4().hex[:8]}"

    return {"candidate_plans": plans}


# ---------------------------------------------------------------------------
# 节点 4：可用性检查
# ---------------------------------------------------------------------------

def check_availability(state: AgentState) -> dict:
    """
    对最新一批方案里的场所和餐厅做可用性检查。
    结果写入 availability_results（dict，key 为 venue/restaurant id）。
    """
    recent_plans = state["candidate_plans"][-config.max_candidate_plans:]
    constraints = state["constraints"]
    results = dict(state.get("availability_results") or {})

    venue_candidates = state.get("candidate_venues", [])
    rest_candidates = state.get("candidate_restaurants", [])

    for plan in recent_plans:
        for item in plan.timeline:
            if item.category == "activity":
                matched = next(
                    (v for v in venue_candidates if v["name"] == item.name), None
                )
                if matched:
                    result = check_venue_availability(matched["id"], item.start_time)
                    results[matched["id"]] = result

            elif item.category == "restaurant":
                matched = next(
                    (r for r in rest_candidates if r["name"] == item.name), None
                )
                if matched:
                    result = check_restaurant_availability(
                        matched["id"], item.start_time, constraints.group_size
                    )
                    results[matched["id"]] = result

    return {"availability_results": results}


# ---------------------------------------------------------------------------
# 节点 5：执行预订
# ---------------------------------------------------------------------------

def execute_bookings(state: AgentState) -> dict:
    """
    对用户确认的方案执行所有预订。
    顺序执行各项（生产环境可改为 asyncio.gather 并行提速）。
    """
    plan = state["selected_plan"]
    constraints = state["constraints"]
    booking_results: list[BookingResult] = []

    venue_candidates = state.get("candidate_venues", [])
    rest_candidates = state.get("candidate_restaurants", [])

    for item in plan.timeline:
        if item.category == "activity":
            matched = next(
                (v for v in venue_candidates if v["name"] == item.name), None
            )
            if matched:
                result = book_venue(
                    matched["id"],
                    party_size=constraints.group_size,
                    requested_time=item.start_time,
                )
                booking_results.append(result)

        elif item.category == "restaurant":
            matched = next(
                (r for r in rest_candidates if r["name"] == item.name), None
            )
            if matched:
                result = book_restaurant(
                    matched["id"],
                    time_slot=item.start_time,
                    party_size=constraints.group_size,
                )
                booking_results.append(result)

    return {"booking_results": booking_results}


# ---------------------------------------------------------------------------
# 节点 6：发送通知
# ---------------------------------------------------------------------------

def send_notification(state: AgentState) -> dict:
    """
    用 fast LLM 生成行程确认消息，通过 notification 工具发送。
    """
    plan = state["selected_plan"]
    booking_results = state["booking_results"]
    constraints = state["constraints"]

    system_prompt = _load_system_prompt("notifier")
    llm = get_llm("fast")

    booking_summary = "\n".join(
        f"- {r.action} {r.target_name}：{r.status.value}，{r.detail}"
        for r in booking_results
    )

    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"""
行程方案：{plan.title}
{plan.summary}

预订结果：
{booking_summary}

场景：{"家庭" if constraints.scenario.value == "family" else "朋友聚会"}
请生成发送给{("老婆" if constraints.scenario.value == "family" else "朋友们")}的通知消息。
"""),
    ])

    message_content = response.content
    recipients = ["老婆"] if constraints.scenario.value == "family" else ["朋友们"]
    send_trip_summary(recipients, message_content)

    return {"summary_message": message_content}


# ---------------------------------------------------------------------------
# 节点 7：错误处理
# ---------------------------------------------------------------------------

def handle_error(state: AgentState) -> dict:
    """超过最大重规划次数或发生不可恢复错误时进入此节点。"""
    replan_count = state.get("replan_count", 0)
    return {
        "error": f"已尝试 {replan_count} 次规划，未能找到满足所有约束的方案。",
        "summary_message": "很抱歉，未能为您找到合适的方案，请放宽一些条件再试试。",
    }
