import operator
from typing import Annotated, Literal

from typing_extensions import TypedDict

from models.schemas import AvailabilityResult, BookingResult, ConstraintSet, Plan


class AgentState(TypedDict):
    # 用户输入
    user_message: str
    user_request: dict                   # 原始结构化 UserRequest（dict 形式）
    scenario: Literal["family", "friends"]

    # 约束（由 parse_intent 节点填入）
    constraints: ConstraintSet
    preference_weights: dict[str, float] # 由偏好标签驱动的排序权重

    # 搜索候选池（search_candidates 节点填入，后续节点只读）
    candidate_venues: list[dict]
    candidate_restaurants: list[dict]
    day_clusters: list[list[dict]]       # 每天的场所候选簇，[[day1], [day2], ...]
    available_activity_minutes_per_day: int  # 每天可用活动时间（分钟）

    # 规划阶段
    # Annotated + operator.add：每次 replan 追加新方案，不覆盖旧的
    candidate_plans: Annotated[list[Plan], operator.add]
    availability_results: dict[str, AvailabilityResult]
    selected_plan: Plan | None

    # 执行阶段
    user_confirmed: bool
    booking_results: Annotated[list[BookingResult], operator.add]

    # 控制流
    replan_count: int
    replan_feedback: str          # 用户重规划时输入的反馈文字
    replan_base_plan_id: str      # 用户选择作为调整基础的方案 ID（空串 = 全部重新规划）
    error: str | None

    # 最终输出
    summary_message: str
