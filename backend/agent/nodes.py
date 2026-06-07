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
import itertools
import re
import uuid
from functools import partial
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
    FreeTextConstraints,
    Plan,
    RestaurantConstraints,
    Scenario,
    ToolErrorCode,
)
from tools.amap_http import fetch_restaurants, fetch_venues, geocode_city
from tools.geo import greedy_cluster, haversine_km
from tools.links import amap_marker_uri, amap_search_uri
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
            duration_hours=req.duration_hours,
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
            if extras.cuisine_request:
                constraints.cuisine_request = extras.cuisine_request
            if extras.cuisine_keywords:
                constraints.cuisine_keywords = extras.cuisine_keywords
            if extras.venue_request:
                constraints.venue_request = extras.venue_request
            if extras.venue_keywords:
                constraints.venue_keywords = extras.venue_keywords
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
# 节点 1b：重规划反馈解析（仅用户拒绝触发，search_candidates 之前）
# ---------------------------------------------------------------------------

class _ReplanConstraintUpdate(BaseModel):
    """fast LLM 从用户反馈文字中提取需要调整的约束。"""
    add_categories: list[ActivityCategory] = []
    remove_categories: list[ActivityCategory] = []
    budget_per_person: int | None = None
    max_distance_km: float | None = None
    cuisine_request: str = ""              # 反馈里新提到的想吃的食物，如 "改成想吃火锅"
    cuisine_keywords: list[str] = []       # 对应检索阶梯，具体→宽泛
    venue_request: str = ""                # 反馈里新提到的想去/想体验的活动，如 "想看特展"
    venue_keywords: list[str] = []         # 对应检索阶梯，具体→宽泛


_REPLAN_PARSE_SYSTEM = """\
你是一个意图提取器。根据用户对活动方案的反馈，提取需要调整的活动类别、数值约束、餐饮意图和活动意图。

活动类别枚举值：museum, exhibition, park, citywalk, aquarium, kids_center, escape_room

示例：
- "不喜欢博物馆，换成公园" → remove_categories:[museum,exhibition], add_categories:[park]
- "太贵了，预算150元" → budget_per_person:150
- "想去更近的地方，5公里内" → max_distance_km:5
- "餐厅换成火锅" → cuisine_request:"火锅", cuisine_keywords:["火锅","川渝火锅","餐厅 美食"]
- "想看那个莫奈特展" → venue_request:"莫奈特展", venue_keywords:["莫奈特展","艺术展览","美术馆","博物馆 展览馆"]

只提取用户明确提到的信息，未提及的字段保持为空/null。\
"""


def parse_replan_feedback(state: AgentState) -> dict:
    """
    将用户反馈文字转换为约束更新，重新写入 constraints 和 preference_weights。
    后续 search_candidates 会用更新后的 constraints 重新召回候选池。
    """
    feedback = state.get("replan_feedback", "").strip()
    if not feedback:
        return {}

    llm = get_llm("fast").with_structured_output(_ReplanConstraintUpdate)
    update: _ReplanConstraintUpdate = llm.invoke([
        SystemMessage(content=_REPLAN_PARSE_SYSTEM),
        HumanMessage(content=feedback),
    ])

    constraints = state["constraints"]
    preference_weights = dict(state.get("preference_weights") or {})

    # 更新 preferred_categories
    current_cats = list(constraints.activity.preferred_categories or [])
    remove_set = {c.value for c in update.remove_categories}
    current_cats = [c for c in current_cats if c.value not in remove_set]
    seen = {c.value for c in current_cats}
    for cat in update.add_categories:
        if cat.value not in seen:
            current_cats.append(cat)
            seen.add(cat.value)
    constraints.activity.preferred_categories = current_cats

    # 同步 preference_weights
    for cat in update.remove_categories:
        pref_key = _CAT_TO_PREF.get(cat.value, "")
        preference_weights.pop(pref_key, None)
    for cat in update.add_categories:
        pref_key = _CAT_TO_PREF.get(cat.value, "")
        if pref_key:
            preference_weights[pref_key] = preference_weights.get(pref_key, 0.0) + 1.0

    if update.budget_per_person is not None:
        constraints.budget_per_person = update.budget_per_person
    if update.max_distance_km is not None:
        constraints.max_distance_km = update.max_distance_km
    if update.cuisine_request:
        constraints.cuisine_request = update.cuisine_request
        constraints.cuisine_keywords = update.cuisine_keywords
    if update.venue_request:
        constraints.venue_request = update.venue_request
        constraints.venue_keywords = update.venue_keywords

    return {
        "constraints": constraints,
        "preference_weights": preference_weights,
    }


# ---------------------------------------------------------------------------
# 节点 2：候选场所搜索
# ---------------------------------------------------------------------------

async def _laddered_fetch(fetch_fn, ladder: list[str], requested: str, keep) -> tuple[list, dict]:
    """
    通用冷启动检索：沿 ladder（具体→宽泛）逐级调 fetch_fn，**过滤后**仍有候选才算命中。

    冷启动问题：用户提具体诉求（"爆啦兔头面" / "莫奈特展"），本地无完全匹配。
    解法：LLM 在 parse_intent 阶段把诉求扩成「具体→宽泛」的检索词阶梯，这里逐级
    向高德发起召回，从而降级到相近的热门候选。

    关键：命中判定基于 keep() 过滤后的存活数量，而非原始召回数量。
    否则一个窄词（如"莫奈特展"只召回 1 个馆）可能被距离/时长硬过滤清空，
    却因"有原始结果"提前终止阶梯，导致候选池为空且无法继续降级。

    fetch_fn：functools.partial 绑定好 city / 过滤参数的检索函数，
      需接受 keywords= 和 allow_mock_fallback= 两个关键字参数。
    keep：callable(item)->bool，对每个候选做硬过滤（距离/时长等），可带副作用（写 distance_km）。
    返回 (survivors, match)。match = {requested, matched_term, exact}；
      requested 为空（用户没提具体诉求）时返回空 dict。
    """
    # 沿阶梯逐级尝试，过滤后有存活即停（抑制 mock 兜底，便于继续降级）
    for tier, term in enumerate(ladder):
        raw = await asyncio.to_thread(fetch_fn, keywords=term, allow_mock_fallback=False)
        survivors = [x for x in raw if keep(x)]
        if survivors:
            match = {"requested": requested, "matched_term": term, "exact": tier == 0} if requested else {}
            return survivors, match

    # 阶梯未命中（或无具体诉求）→ 默认搜索，允许 mock 兜底
    raw = await asyncio.to_thread(fetch_fn)
    survivors = [x for x in raw if keep(x)]
    match = {"requested": requested, "matched_term": None, "exact": False} if requested else {}
    return survivors, match


async def search_candidates(state: AgentState) -> dict:
    """
    真实召回：并行调高德 API，硬过滤，程序打分，地理聚类。
    amap_http 是同步 httpx，用 asyncio.to_thread 放入线程池以实现并行。
    """
    constraints = state["constraints"]

    # Step 1：硬过滤谓词（距城市中心距离 + 场所游玩时长）。
    # 时长上限取「整段出行时长」而非扣除餐饮/交通后的活动预算——后者过严，
    # 3 小时出行会把 90 分钟的博物馆全部滤掉。精细的时间编排交给 planner。
    # city_center 用 geocode_city 动态解析（main 合入），避免非上海城市恒返回上海。
    city_center = geocode_city(constraints.city)
    full_outing_minutes = int(constraints.duration_hours * 60)

    def _set_dist(item) -> float:
        d = haversine_km(item.coordinates, city_center)
        item.distance_km = round(d, 2)
        return d

    def keep_venue(v) -> bool:
        return _set_dist(v) <= constraints.max_distance_km and v.typical_visit_minutes <= full_outing_minutes

    def keep_restaurant(r) -> bool:
        return _set_dist(r) <= constraints.max_distance_km

    # 放宽版：去掉距离约束（仍保留时长），仅作安全网用——
    # 宁可给一个略超距离的真实场所，也不能让候选池为空导致 LLM 编造通用占位。
    def keep_venue_relaxed(v) -> bool:
        _set_dist(v)
        return v.typical_visit_minutes <= full_outing_minutes

    def keep_restaurant_relaxed(r) -> bool:
        _set_dist(r)
        return True

    # Step 2：并行召回，场所与餐厅都走冷启动阶梯检索（过滤内置于阶梯，过滤后无存活则继续降级）。
    # partial 绑定 city / 过滤参数，_laddered_fetch 负责注入 keywords 并应用 keep。
    venue_fetch = partial(
        fetch_venues,
        constraints.city,
        constraints.activity.preferred_categories,
        kids_friendly=constraints.activity.kids_friendly,
        prefer_indoor=constraints.activity.prefer_indoor,
        max_price=constraints.budget_per_person,
        n=20,
    )
    restaurant_fetch = partial(
        fetch_restaurants,
        constraints.city,
        has_kids_menu=constraints.restaurant.has_kids_menu,
        has_low_calorie=constraints.restaurant.has_low_calorie_options,
        noise_levels=constraints.restaurant.noise_level or None,
        min_party_size=constraints.group_size,
        max_price=constraints.budget_per_person,
        n=20,
    )
    (venues, venue_match), (restaurants, cuisine_match) = await asyncio.gather(
        _laddered_fetch(venue_fetch, constraints.venue_keywords or [], constraints.venue_request.strip(), keep_venue),
        _laddered_fetch(restaurant_fetch, constraints.cuisine_keywords or [], constraints.cuisine_request.strip(), keep_restaurant),
    )

    # 安全网：阶梯后仍为空（多因距离过滤过严）→ 放宽距离再召回一次。
    # 关键：allow_mock_fallback=False，只对「本城真实结果」放宽距离；
    # 若高德对本城确实没有数据，宁可留空让 planner 如实标注，也不要注入异地（上海）mock 场所。
    if not venues:
        raw = await asyncio.to_thread(venue_fetch, allow_mock_fallback=False)
        venues = [v for v in raw if keep_venue_relaxed(v)]
        venue_match = {**venue_match, "distance_relaxed": True} if venue_match else venue_match
    if not restaurants:
        raw = await asyncio.to_thread(restaurant_fetch, allow_mock_fallback=False)
        restaurants = [r for r in raw if keep_restaurant_relaxed(r)]
        cuisine_match = {**cuisine_match, "distance_relaxed": True} if cuisine_match else cuisine_match

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
        # 供 planner 参考的每日活动净时长（扣除一顿餐 + 交通预留）
        "available_activity_minutes_per_day": max(
            30, full_outing_minutes - RESTAURANT_DURATION - 60
        ),
        "cuisine_match":         cuisine_match,
        "venue_match":           venue_match,
    }


# ---------------------------------------------------------------------------
# 节点 3：方案生成
# ---------------------------------------------------------------------------

class _PlansResponse(BaseModel):
    """Instructor/with_structured_output 要求顶层是对象，用 wrapper 包住 list[Plan]。"""
    plans: list[Plan]


def validate_timeline(plan: Plan, constraints: ConstraintSet) -> list[str]:
    """
    程序校验单个方案的时间/费用合理性，返回错误列表（空 = 通过）。
    LLM 自填的 constraint_coverage 不可信，这里做客观核对，失败项回灌 prompt 重试。

    校验项：
      ① 时间格式 / 单环节起止顺序
      ② 同一天内环节不重叠（连续性）
      ③ 每天总时长（首环节开始 → 末环节结束）不超过 duration_hours（含容差）
      ④ 人均费用不超过预算
      ⑤ 行程天数被完整覆盖
    """
    errors: list[str] = []
    by_day: dict[int, list] = {}
    for item in plan.timeline:
        by_day.setdefault(item.day, []).append(item)

    full_day_minutes = int(constraints.duration_hours * 60)
    tol = config.timeline_tolerance_min

    for day, items in sorted(by_day.items()):
        parsed = []
        for it in items:
            try:
                s, e = _parse_hhmm(it.start_time), _parse_hhmm(it.end_time)
            except Exception:
                errors.append(f"第{day}天「{it.name}」时间格式无法解析（{it.start_time}-{it.end_time}）")
                continue
            if e < s:
                errors.append(f"第{day}天「{it.name}」结束早于开始（{it.start_time}-{it.end_time}）")
            parsed.append((s, e, it))

        parsed.sort(key=lambda x: x[0])
        for (_, e1, i1), (s2, _, i2) in zip(parsed, parsed[1:]):
            if s2 < e1:
                errors.append(f"第{day}天「{i1.name}」与「{i2.name}」时间重叠（{i1.end_time} > {i2.start_time}）")

        if parsed:
            span = parsed[-1][1] - parsed[0][0]
            if span > full_day_minutes + tol:
                errors.append(f"第{day}天总时长 {span} 分钟超过每天上限 {full_day_minutes} 分钟")

    total_cost = sum(it.estimated_cost for it in plan.timeline)
    if total_cost > constraints.budget_per_person:
        errors.append(f"人均费用 {total_cost} 元超过预算 {constraints.budget_per_person} 元")

    missing = set(range(1, constraints.duration_days + 1)) - set(by_day)
    if missing:
        errors.append(f"缺少第 {sorted(missing)} 天的安排")

    return errors


def validate_no_cross_day_repeat(
    plan: Plan, *, venue_pool: int, rest_pool: int, duration_days: int
) -> list[str]:
    """
    同一场所/餐厅不应跨天重复（多天行程）。**池子感知**：只有当该类别候选数
    ≥ 天数时才报错——否则候选不够分配到每一天，强制不重复只会逼 LLM 编造场所。
    """
    cat_pool = {"activity": venue_pool, "restaurant": rest_pool}
    days_of: dict[tuple[str, str], set[int]] = {}
    for item in plan.timeline:
        if item.category in cat_pool:
            days_of.setdefault((item.name, item.category), set()).add(item.day)
    return [
        f"「{name}」在第 {sorted(days)} 天重复出现，同一地点不要跨天重复"
        for (name, cat), days in days_of.items()
        if len(days) > 1 and cat_pool[cat] >= duration_days
    ]


# 两个方案场所集合的 Jaccard 相似度上限；> 此值视为"过于雷同"。
# 0.5 允许小方案共用 1 个最契合场所，但拒绝"场所全相同、只换时间"。
_PLAN_SIMILARITY_MAX = 0.5


def validate_plan_diversity(plans: list[Plan]) -> list[str]:
    """
    跨方案多样性校验：不同方案的场所集合不应高度雷同。
    允许最多共用 1 个最契合场所，但若两方案场所几乎相同则报错回灌重试。
    """
    def places(p: Plan) -> set[str]:
        return {it.name for it in p.timeline if it.category in ("activity", "restaurant")}

    errors: list[str] = []
    sets = [(p, places(p)) for p in plans]
    for (pa, a), (pb, b) in itertools.combinations(sets, 2):
        if not a or not b:
            continue
        jaccard = len(a & b) / len(a | b)
        if jaccard > _PLAN_SIMILARITY_MAX:
            shared = "、".join(sorted(a & b))
            errors.append(
                f"方案「{pa.title}」与「{pb.title}」场所高度雷同（共用：{shared}）；"
                "请让它们选用明显不同的场所，最多共用 1 个最契合的场所"
            )
    return errors


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

    # 已展示过的场所名（重规划时提示 LLM 避免重复）
    shown_section = ""
    if replan_count > 0:
        shown_names = {
            item.name
            for p in state.get("candidate_plans", [])
            for item in p.timeline
            if item.category in ("activity", "restaurant")
        }
        if shown_names:
            shown_section = (
                "\n已展示给用户的场所（**请优先选择新场所，避免重复**）：\n"
                + "、".join(sorted(shown_names)) + "\n"
            )

    # 冷启动诉求（餐饮 / 活动）：告知 LLM 原始诉求 + 是否精确命中
    def _cold_start_section(match: dict, kind: str, verb: str, place: str) -> str:
        req = match.get("requested")
        if not req:
            return ""
        if match.get("exact"):
            return (
                f"\n【用户指定{kind}】用户特别{verb}「{req}」，候选{place}中已包含相关选项，"
                f"请优先安排，并在该{place} notes 中点明这正是用户想要的。\n"
            )
        matched = match.get("matched_term")
        via = f"（已按相近类型「{matched}」检索）" if matched else ""
        return (
            f"\n【用户指定{kind}】用户特别{verb}「{req}」，但本地没有完全匹配的{place}{via}。"
            f"请从候选{place}中挑选主题/品类最接近的人气{place}，"
            f"并在该{place} notes 中如实告知用户：未找到「{req}」，这是相近的推荐。\n"
        )

    cuisine_section = _cold_start_section(state.get("cuisine_match") or {}, "餐饮", "想吃", "餐厅")
    venue_section   = _cold_start_section(state.get("venue_match") or {}, "活动", "想去/想体验", "场所")

    # 其他特殊要求（适老化、靠窗、轮椅通道等）
    special_section = ""
    if constraints.special_requirements:
        special_section = (
            "\n用户的其他特殊要求："
            + "、".join(constraints.special_requirements)
            + "（请尽量在方案安排或 notes 中体现）\n"
        )

    user_content = f"""{replan_prefix}用户需求：{state["user_message"]}

约束条件：
- 城市：{constraints.city}
- 场景：{constraints.scenario.value}
- 人数：{constraints.group_size} 人
- 行程天数：{constraints.duration_days} 天
- 每天活动时长：{constraints.duration_hours} 小时
- 最远距离：{constraints.max_distance_km} km
- 人均预算：{constraints.budget_per_person} 元
{venue_section}{cuisine_section}{special_section}{shown_section}
候选场所（已通过硬约束过滤）：
{venues}

候选餐厅（已通过硬约束过滤，**餐厅时间必须从「可预约时段」中选择**）：
{restaurants_text}

请生成 {config.max_candidate_plans} 个风格不同的活动方案。
"""

    # 生成 → 校验 → 失败回灌错误重试（最多 max_timeline_retries 次）。
    # 校验是程序硬核对，比 LLM 自填的 constraint_coverage 可靠。
    fix_feedback = ""
    plans: list[Plan] = []
    for attempt in range(config.max_timeline_retries + 1):
        response: _PlansResponse = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content + fix_feedback),
        ])
        plans = response.plans

        # 候选池规模决定是否启用"软"约束（不重复 / 多样 / 方案数）：
        # 池子太小时强制这些只会逼 LLM 编造场所或留白，故按池子大小放行。
        venue_pool = len({v["name"] for v in venues})
        rest_pool = len({r["name"] for r in restaurants})
        enforce_diversity = (venue_pool + rest_pool) >= config.max_candidate_plans + 3

        all_errors: list[str] = []
        for p in plans:
            all_errors += [f"方案「{p.title}」：{e}" for e in validate_timeline(p, constraints)]
            all_errors += [
                f"方案「{p.title}」：{e}"
                for e in validate_no_cross_day_repeat(
                    p, venue_pool=venue_pool, rest_pool=rest_pool,
                    duration_days=constraints.duration_days,
                )
            ]
        if enforce_diversity:
            all_errors += validate_plan_diversity(plans)
            if len(plans) < config.max_candidate_plans:
                all_errors.append(
                    f"只生成了 {len(plans)} 个方案，请生成 {config.max_candidate_plans} 个场所明显不同的方案"
                )

        if not all_errors:
            break
        # 还有重试机会才回灌；否则保留本轮结果（有方案胜过无方案）
        if attempt < config.max_timeline_retries:
            fix_feedback = (
                "\n\n⚠️ 上一轮方案存在以下问题（时间/费用/重复/雷同），请逐条修正后重新输出全部方案：\n"
                + "\n".join(f"- {e}" for e in all_errors) + "\n"
            )

    # 用候选池真实坐标回填 map_uri（程序权威设置，忽略 LLM 可能填的值，避免编造链接）
    coord_lookup: dict[str, dict] = {}
    for d in venues + restaurants:
        coords = d.get("coordinates") or {}
        if d.get("name") and "lat" in coords and "lng" in coords:
            coord_lookup[d["name"]] = coords

    for p in plans:
        p.id = f"plan-{uuid.uuid4().hex[:8]}"
        for item in p.timeline:
            c = coord_lookup.get(item.name)
            item.map_uri = amap_marker_uri(item.name, c["lng"], c["lat"]) if c else ""
            # 需预订的项目（餐厅默认需订座；活动按 LLM 的 booking_required）→ 高德搜索页。
            # else 必须清空：否则会保留 LLM 在该字段乱填的占位（如 "N/A"），前端渲染成相对链接 404。
            if item.category == "restaurant" or item.booking_required:
                item.booking_uri = amap_search_uri(item.name, constraints.city)
            else:
                item.booking_uri = ""

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
