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

import asyncio
import re
import uuid
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from agent.state import AgentState
from config import config
from llm.factory import get_llm
from models.schemas import (
    ActivityCategory,
    ActivityConstraints,
    ActivityPreference,
    AvailabilityResult,
    BookingResult,
    BookingStatus,
    ConstraintSet,
    Coordinates,
    FreeTextConstraints,
    Plan,
    RestaurantConstraints,
    Scenario,
    ToolErrorCode,
)
from tools.amap_http import fetch_restaurants, fetch_venues
from tools.geo import greedy_cluster, haversine_km
from tools.notification import send_trip_summary
from tools.travel import RESTAURANT_DURATION, neighborhood_radius_km

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

_PREFERENCE_TO_CATEGORIES: dict[ActivityPreference, list[ActivityCategory]] = {
    ActivityPreference.cultural: [ActivityCategory.museum, ActivityCategory.exhibition, ActivityCategory.citywalk],
    ActivityPreference.nature:   [ActivityCategory.park, ActivityCategory.citywalk],
    ActivityPreference.museum:   [ActivityCategory.museum, ActivityCategory.exhibition],
    ActivityPreference.social:   [ActivityCategory.escape_room, ActivityCategory.citywalk],
    ActivityPreference.family:   [ActivityCategory.aquarium, ActivityCategory.kids_center, ActivityCategory.park],
    ActivityPreference.food:     [],
}

_CITY_CENTERS: dict[str, Coordinates] = {
    "上海": Coordinates(lat=31.2304, lng=121.4737),
    "北京": Coordinates(lat=39.9042, lng=116.4074),
    "深圳": Coordinates(lat=22.5431, lng=114.0579),
    "广州": Coordinates(lat=23.1291, lng=113.2644),
    "杭州": Coordinates(lat=30.2741, lng=120.1551),
}
_DEFAULT_CENTER = Coordinates(lat=31.2304, lng=121.4737)

_CAT_TO_PREF: dict[str, str] = {
    "museum": "museum", "exhibition": "museum",
    "park": "nature",   "citywalk": "cultural",
    "aquarium": "family", "kids_center": "family",
    "escape_room": "social",
}


def _load_system_prompt(subdir: str) -> str:
    return (_PROMPTS_DIR / subdir / "system.txt").read_text(encoding="utf-8")


def _parse_hhmm(t: str) -> int:
    """'HH:MM' → 分钟数。"""
    h, m = t.strip().split(":")
    return int(h) * 60 + int(m)


def _check_hours(item_dict: dict, requested_time: str) -> AvailabilityResult:
    """用候选数据的 opening_hours 字段做营业时间检查，不查 mock store。"""
    raw = item_dict.get("opening_hours") or "09:00-22:00"
    # 提取第一个 HH:MM-HH:MM 片段，兼容高德多段/含星期的复杂格式
    match = re.search(r"(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})", raw)
    if not match:
        return AvailabilityResult(available=True, message=f"{item_dict.get('name', '')} 营业时间无法解析，默认可用")
    try:
        open_min  = _parse_hhmm(match.group(1))
        close_min = _parse_hhmm(match.group(2))
        req_min   = _parse_hhmm(requested_time)
        if open_min <= req_min < close_min:
            return AvailabilityResult(
                available=True,
                message=f"{item_dict.get('name', '')} {requested_time} 营业中",
            )
        return AvailabilityResult(
            available=False,
            error_code=ToolErrorCode.CLOSED,
            retryable=False,
            message=f"{item_dict.get('name', '')} {requested_time} 不在营业时间（{match.group(0)}）",
        )
    except Exception:
        return AvailabilityResult(available=True, message="营业时间解析异常，默认可用")


def _check_slots(rest_dict: dict, requested_time: str, party_size: int) -> AvailabilityResult:
    """用候选餐厅的 available_slots / max_party_size 检查预约可用性。"""
    name      = rest_dict.get("name", "")
    max_party = rest_dict.get("max_party_size", 10)

    if party_size > max_party:
        return AvailabilityResult(
            available=False,
            error_code=ToolErrorCode.NO_SEAT,
            retryable=False,
            message=f"{name} 最多容纳 {max_party} 人，当前需求 {party_size} 人",
        )

    slots = rest_dict.get("available_slots") or []
    if not slots or requested_time in slots:
        return AvailabilityResult(available=True, message=f"{name} {requested_time} 有空位")

    try:
        next_slot = next(
            (s for s in sorted(slots, key=_parse_hhmm) if _parse_hhmm(s) > _parse_hhmm(requested_time)),
            None,
        )
    except Exception:
        next_slot = None

    return AvailabilityResult(
        available=False,
        error_code=ToolErrorCode.NO_SEAT,
        retryable=True,
        next_available_slot=next_slot,
        message=(
            f"{name} {requested_time} 无空位，"
            + (f"最近可用：{next_slot}" if next_slot else "今日无更多空位")
        ),
    )


# ---------------------------------------------------------------------------
# 节点 1：意图解析
# ---------------------------------------------------------------------------

def parse_intent(state: AgentState) -> dict:
    """
    混合模式意图解析：
    - PlanRequest 路径（user_request 非空）：结构化字段直接映射，zero-LLM；
      仅 free_text 非空时调 fast LLM 提取补充约束。
    - 旧 UserRequest 路径（user_request 为空）：全量 LLM 提取，行为不变。
    """
    user_request = state.get("user_request") or {}

    if user_request:
        from models.schemas import PlanRequest
        req = PlanRequest(**user_request)
        duration_days = (req.end_date - req.start_date).days + 1

        # 偏好标签 → ActivityCategory（保序去重）
        preferred_categories: list[ActivityCategory] = []
        seen: set[ActivityCategory] = set()
        for pref in req.preferences:
            for cat in _PREFERENCE_TO_CATEGORIES.get(pref, []):
                if cat not in seen:
                    preferred_categories.append(cat)
                    seen.add(cat)

        # 偏好权重：每个标签贡献 1.0，可叠加
        preference_weights: dict[str, float] = {}
        for pref in req.preferences:
            preference_weights[pref.value] = preference_weights.get(pref.value, 0.0) + 1.0

        kids_friendly = ActivityPreference.family in req.preferences
        food_focused  = ActivityPreference.food  in req.preferences
        scenario      = Scenario.family if kids_friendly else Scenario.friends

        constraints = ConstraintSet(
            scenario=scenario,
            group_size=req.group_size,
            city=req.city,
            duration_days=duration_days,
            max_distance_km=req.max_distance_km,
            travel_modes=req.travel_modes,
            food_focused=food_focused,
            activity=ActivityConstraints(
                kids_friendly=kids_friendly,
                preferred_categories=preferred_categories,
            ),
            restaurant=RestaurantConstraints(
                has_kids_menu=kids_friendly,
            ),
        )

        if req.free_text.strip():
            llm = get_llm("fast").with_structured_output(FreeTextConstraints)
            extras: FreeTextConstraints = llm.invoke([
                SystemMessage(content=_load_system_prompt("intent_parser")),
                HumanMessage(content=req.free_text),
            ])
            if extras.start_time:
                constraints.start_time = extras.start_time
            if extras.duration_hours is not None:
                constraints.duration_hours = extras.duration_hours
            if extras.budget_per_person is not None:
                constraints.budget_per_person = extras.budget_per_person
            if extras.special_requirements:
                constraints.special_requirements = extras.special_requirements
            if extras.scenario is not None:
                constraints.scenario = extras.scenario
                scenario = extras.scenario

        return {
            "constraints": constraints,
            "scenario": scenario.value,
            "preference_weights": preference_weights,
        }

    # 旧路径：全量 LLM
    llm = get_llm("fast").with_structured_output(ConstraintSet)
    constraints = llm.invoke([
        SystemMessage(content=_load_system_prompt("intent_parser")),
        HumanMessage(content=state["user_message"]),
    ])
    return {
        "constraints": constraints,
        "scenario": constraints.scenario.value,
        "preference_weights": {},
    }


# ---------------------------------------------------------------------------
# 节点 2：候选场所搜索
# ---------------------------------------------------------------------------

async def search_candidates(state: AgentState) -> dict:
    """
    真实召回：并行调高德 API，硬过滤，程序打分，地理聚类。
    amap_http 是同步 httpx，用 asyncio.to_thread 放入线程池以实现并行。
    """
    constraints = state["constraints"]

    # Step 1：每日可用活动时间（总时长 - 餐饮 - 交通预留）
    available_activity_minutes = max(
        30,
        int(constraints.duration_hours * 60) - RESTAURANT_DURATION - 60,
    )

    # Step 2：并行召回
    venues_raw, restaurants_raw = await asyncio.gather(
        asyncio.to_thread(
            fetch_venues,
            constraints.city,
            constraints.activity.preferred_categories,
            kids_friendly=constraints.activity.kids_friendly,
            prefer_indoor=constraints.activity.prefer_indoor,
            max_price=constraints.budget_per_person,
            n=20,
        ),
        asyncio.to_thread(
            fetch_restaurants,
            constraints.city,
            has_kids_menu=constraints.restaurant.has_kids_menu,
            has_low_calorie=constraints.restaurant.has_low_calorie_options,
            noise_levels=constraints.restaurant.noise_level or None,
            min_party_size=constraints.group_size,
            max_price=constraints.budget_per_person,
            n=20,
        ),
    )

    # Step 3：硬过滤（距城市中心距离 + 时长预算）
    city_center = _CITY_CENTERS.get(constraints.city, _DEFAULT_CENTER)

    venues: list = []
    for v in venues_raw:
        dist = haversine_km(v.coordinates, city_center)
        if dist > constraints.max_distance_km:
            continue
        if v.typical_visit_minutes > available_activity_minutes:
            continue
        v.distance_km = round(dist, 2)
        venues.append(v)

    restaurants: list = []
    for r in restaurants_raw:
        dist = haversine_km(r.coordinates, city_center)
        if dist > constraints.max_distance_km:
            continue
        r.distance_km = round(dist, 2)
        restaurants.append(r)

    # Step 4：程序打分排序
    preference_weights = state.get("preference_weights") or {}

    def venue_score(v) -> float:
        rating     = v.rating / 5.0
        budget_fit = max(0.0, 1.0 - v.price_per_person / max(constraints.budget_per_person, 1))
        pref_key   = _CAT_TO_PREF.get(v.category.value, "")
        pref       = min(1.0, preference_weights.get(pref_key, 0.0))
        return rating * 0.35 + budget_fit * 0.20 + pref * 0.45

    venues      = sorted(venues,      key=venue_score,       reverse=True)
    restaurants = sorted(restaurants, key=lambda r: r.rating, reverse=True)

    # Step 5：地理聚类（每天一个簇）
    radius       = neighborhood_radius_km(constraints.duration_hours, constraints.travel_modes)
    day_clusters = greedy_cluster(venues, k=constraints.duration_days, radius_km=radius)

    return {
        "candidate_venues":      [v.model_dump() for v in venues],
        "candidate_restaurants": [r.model_dump() for r in restaurants],
        "day_clusters":          [[v.model_dump() for v in c] for c in day_clusters],
        "available_activity_minutes_per_day": available_activity_minutes,
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

    # 餐厅候选格式化
    def _fmt_restaurant(r: dict) -> str:
        slots = r.get("available_slots", [])
        slots_str = "、".join(slots) if slots else "无需预约，直接前往"
        return (
            f"{r['name']} | {r.get('cuisine', '')} | "
            f"¥{r.get('price_per_person', 0)}/人 | "
            f"可预约时段：{slots_str}"
        )

    restaurants_text = "\n".join(_fmt_restaurant(r) for r in restaurants)

    # 收集上次可用性失败原因
    availability_results = state.get("availability_results") or {}
    failures = [
        v.message for v in availability_results.values()
        if not v.available and v.message
    ]

    # 重规划前缀：在 prompt 最前面给出调整指令 + 方案上下文
    replan_count        = state.get("replan_count", 0)
    replan_feedback     = state.get("replan_feedback", "")
    replan_base_plan_id = state.get("replan_base_plan_id", "")
    replan_prefix       = ""

    if replan_count > 0:
        issues: list[str] = []
        if replan_feedback:
            issues.append(f"用户反馈：{replan_feedback}")
        if failures:
            issues.append("以下项目不可用，需替换：\n" + "\n".join(f"  - {f}" for f in failures))
        issues_text = "\n".join(issues)

        all_prev = state.get("candidate_plans", [])

        # 用户选了某个方案作为调整基础
        base_plan = next((p for p in all_prev if p.id == replan_base_plan_id), None) if replan_base_plan_id else None

        if base_plan:
            base_timeline = "、".join(
                f"{item.start_time} {item.name}"
                for item in base_plan.timeline
                if item.category in ("activity", "restaurant")
            )
            replan_prefix = (
                f"【在选定方案基础上调整】用户选择「{base_plan.title}」作为调整起点"
                f"（{base_timeline}）。\n"
                "请保留用户未提出异议的部分，只针对以下问题进行修改：\n"
                + issues_text + "\n\n"
            )
        else:
            # 没有选基础方案 → 全部重新规划，但仍展示上次方案供参考
            prev_plans = all_prev[-config.max_candidate_plans:]
            prev_lines = [
                f"「{p.title}」：" + "、".join(
                    f"{item.start_time} {item.name}"
                    for item in p.timeline
                    if item.category in ("activity", "restaurant")
                )
                for p in prev_plans
            ]
            prev_context = ("\n上次方案供参考（用户觉得都不满意）：\n" + "\n".join(prev_lines) + "\n") if prev_lines else ""
            replan_prefix = (
                "【全部重新规划】用户对上次所有方案都不满意，请根据以下反馈重新设计：\n"
                + issues_text
                + prev_context + "\n"
            )

    user_content = f"""{replan_prefix}用户需求：{state["user_message"]}

约束条件：
- 场景：{constraints.scenario.value}
- 人数：{constraints.group_size} 人
- 最远距离：{constraints.max_distance_km} km
- 人均预算：{constraints.budget_per_person} 元
- 活动时长：{constraints.duration_hours} 小时

候选场所（已通过硬约束过滤）：
{venues}

候选餐厅（已通过硬约束过滤，**餐厅时间必须从「可预约时段」中选择**）：
{restaurants_text}

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
    直接使用 candidate_venues/restaurants 中已有的 opening_hours 和 available_slots，
    不再通过 ID 去查 mock store（store ID 与高德 API ID 不匹配，会导致全部返回"不存在"）。
    """
    recent_plans    = state["candidate_plans"][-config.max_candidate_plans:]
    constraints     = state["constraints"]
    results         = dict(state.get("availability_results") or {})
    venue_candidates = state.get("candidate_venues", [])
    rest_candidates  = state.get("candidate_restaurants", [])

    for plan in recent_plans:
        for item in plan.timeline:
            if item.category == "activity":
                matched = next((v for v in venue_candidates if v["name"] == item.name), None)
                if matched:
                    results[matched["id"]] = _check_hours(matched, item.start_time)

            elif item.category == "restaurant":
                matched = next((r for r in rest_candidates if r["name"] == item.name), None)
                if matched:
                    if item.booking_required:
                        results[matched["id"]] = _check_slots(matched, item.start_time, constraints.group_size)
                    else:
                        results[matched["id"]] = _check_hours(matched, item.start_time)

    return {"availability_results": results}


# ---------------------------------------------------------------------------
# 节点 5：执行预订
# ---------------------------------------------------------------------------

def execute_bookings(state: AgentState) -> dict:
    """
    对用户确认的方案执行所有预订。
    直接使用候选数据构造 BookingResult，不经过 mock store（store ID 与高德 ID 不匹配）。
    """
    plan = state["selected_plan"]
    constraints = state["constraints"]
    booking_results: list[BookingResult] = []

    venue_candidates = state.get("candidate_venues", [])
    rest_candidates = state.get("candidate_restaurants", [])

    for item in plan.timeline:
        if item.category == "activity":
            matched = next((v for v in venue_candidates if v["name"] == item.name), None)
            if matched:
                cost = matched.get("price_per_person", 0) * constraints.group_size
                booking_results.append(BookingResult(
                    action="购票",
                    target_name=matched["name"],
                    status=BookingStatus.success,
                    detail=f"已记录购票意向 {constraints.group_size} 张，预计 ¥{cost}（演示模式，请前往官方渠道完成购票）",
                    cost=cost,
                ))

        elif item.category == "restaurant" and item.booking_required:
            matched = next((r for r in rest_candidates if r["name"] == item.name), None)
            if matched:
                cost = matched.get("price_per_person", 0) * constraints.group_size
                booking_results.append(BookingResult(
                    action="订座",
                    target_name=matched["name"],
                    status=BookingStatus.success,
                    detail=f"已记录 {item.start_time} {constraints.group_size} 人订座意向，预计 ¥{cost}（演示模式，请通过大众点评 / 官方渠道确认）",
                    cost=cost,
                ))

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
