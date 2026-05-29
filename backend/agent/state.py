import operator
from typing import Annotated, Literal

from typing_extensions import TypedDict

from models.schemas import AvailabilityResult, BookingResult, ConstraintSet, Plan


class AgentState(TypedDict):
    # 用户输入
    user_message: str
    scenario: Literal["family", "friends"]

    # 约束（由 parse_intent 节点填入）
    constraints: ConstraintSet

    # 规划阶段
    # Annotated + operator.add：每次 replan 追加新方案，不覆盖旧的
    candidate_plans: Annotated[list[Plan], operator.add]
    availability_results: dict[str, AvailabilityResult]
    selected_plan: Plan | None

    # 执行阶段
    user_confirmed: bool
    booking_results: Annotated[list[BookingResult], operator.add]

    # 控制流
    replan_count: int       # 已重规划次数，超过 max_replan_count 则终止
    error: str | None

    # 最终输出
    summary_message: str
