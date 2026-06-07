"""
LangGraph 条件边路由单元测试。

只测纯逻辑的路由函数，不涉及 LLM 调用：
  _route_after_availability  → 决定 check_availability 后走哪条边
  _route_after_human_review  → 决定用户确认/拒绝后走哪条边

构造最小化的 AgentState dict，验证路由结果是否符合预期。
"""


from agent.graph import _route_after_availability, _route_after_human_review
from models.schemas import (
    AvailabilityResult,
    Plan,
    TimelineItem,
    ToolErrorCode,
)


# ---------------------------------------------------------------------------
# 测试用数据工厂
# ---------------------------------------------------------------------------

def make_plan(venue_name: str = "测试水族馆", rest_name: str = "测试餐厅") -> Plan:
    return Plan(
        id="plan-test",
        title="测试方案",
        summary="测试",
        timeline=[
            TimelineItem(
                name=venue_name,
                address="测试地址",
                start_time="14:00",
                end_time="16:30",
                category="activity",
                booking_required=True,
                estimated_cost=190,
            ),
            TimelineItem(
                name=rest_name,
                address="测试地址",
                start_time="17:00",
                end_time="18:30",
                category="restaurant",
                booking_required=True,
                estimated_cost=85,
            ),
        ],
        total_duration_minutes=270,
        total_cost_estimate=275,
    )


def make_state(
    plans: list[Plan],
    availability_results: dict,
    replan_count: int = 0,
    venue_candidates: list[dict] | None = None,
    rest_candidates: list[dict] | None = None,
) -> dict:
    return {
        "candidate_plans": plans,
        "availability_results": availability_results,
        "replan_count": replan_count,
        "candidate_venues": venue_candidates or [{"id": "v001", "name": "测试水族馆"}],
        "candidate_restaurants": rest_candidates or [{"id": "r001", "name": "测试餐厅"}],
    }


# ---------------------------------------------------------------------------
# _route_after_availability 测试
# ---------------------------------------------------------------------------

class TestRouteAfterAvailability:

    def test_all_available_routes_to_human_review(self):
        """场所和餐厅都可用 → 进入 human_review 等待用户确认。"""
        plan = make_plan()
        state = make_state(
            plans=[plan],
            availability_results={
                "v001": AvailabilityResult(available=True),
                "r001": AvailabilityResult(available=True),
            },
        )
        assert _route_after_availability(state) == "human_review"

    def test_venue_unavailable_routes_to_replan(self):
        """场所不可用，replan_count 未超限 → 重规划。"""
        plan = make_plan()
        state = make_state(
            plans=[plan],
            availability_results={
                "v001": AvailabilityResult(
                    available=False,
                    error_code=ToolErrorCode.CLOSED,
                    retryable=False,
                ),
                "r001": AvailabilityResult(available=True),
            },
            replan_count=0,
        )
        assert _route_after_availability(state) == "generate_plans"

    def test_all_unavailable_at_limit_routes_to_error(self):
        """全不可用且 replan_count 已达上限 → handle_error。"""
        from config import config
        plan = make_plan()
        state = make_state(
            plans=[plan],
            availability_results={
                "v001": AvailabilityResult(available=False, error_code=ToolErrorCode.CLOSED),
                "r001": AvailabilityResult(available=False, error_code=ToolErrorCode.NO_SEAT),
            },
            replan_count=config.max_replan_count,
        )
        assert _route_after_availability(state) == "handle_error"

    def test_non_bookable_items_ignored(self):
        """booking_required=False 的环节不参与可用性判断，不阻断方案。"""
        plan = Plan(
            id="plan-test",
            title="无需预订方案",
            summary="测试",
            timeline=[
                TimelineItem(
                    name="随意散步",
                    address="外滩",
                    start_time="14:00",
                    end_time="15:00",
                    category="activity",
                    booking_required=False,
                ),
            ],
            total_duration_minutes=60,
            total_cost_estimate=0,
        )
        state = make_state(plans=[plan], availability_results={})
        assert _route_after_availability(state) == "human_review"

    def test_missing_availability_result_does_not_block(self):
        """候选池里有记录但没有对应可用性结果（未检查），不阻断方案。"""
        plan = make_plan()
        # availability_results 为空，说明还没查过这两个地方
        state = make_state(plans=[plan], availability_results={})
        # 找不到结果时跳过，方案视为可用
        assert _route_after_availability(state) == "human_review"

    def test_restaurant_unavailable_triggers_replan(self):
        """场所可用但餐厅无座 → 重规划。"""
        plan = make_plan()
        state = make_state(
            plans=[plan],
            availability_results={
                "v001": AvailabilityResult(available=True),
                "r001": AvailabilityResult(
                    available=False,
                    error_code=ToolErrorCode.NO_SEAT,
                    retryable=True,
                ),
            },
            replan_count=1,
        )
        assert _route_after_availability(state) == "generate_plans"


# ---------------------------------------------------------------------------
# _route_after_human_review 测试
# ---------------------------------------------------------------------------

class TestRouteAfterHumanReview:

    def test_confirmed_with_plan_routes_to_execute(self):
        """用户确认且 selected_plan 存在 → 执行预订。"""
        state = {
            "user_confirmed": True,
            "selected_plan": make_plan(),
        }
        assert _route_after_human_review(state) == "execute_bookings"

    def test_not_confirmed_routes_to_replan(self):
        """用户拒绝 → 重规划。"""
        state = {
            "user_confirmed": False,
            "selected_plan": None,
        }
        assert _route_after_human_review(state) == "generate_plans"

    def test_confirmed_but_no_plan_routes_to_replan(self):
        """confirmed=True 但 selected_plan 为 None（异常情况）→ 重规划。"""
        state = {
            "user_confirmed": True,
            "selected_plan": None,
        }
        assert _route_after_human_review(state) == "generate_plans"
