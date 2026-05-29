"""
预订执行工具。

在用户确认方案后由 LangGraph 执行节点调用，对餐厅和场所分别处理。
所有操作均为 Mock 实现，模拟真实预订 API 的返回结构。

执行前会再做一次可用性确认（final check），防止规划到执行之间的窗口期失效。
若 final check 失败，直接返回 failed，由 LangGraph replan 节点处理。
"""

from models.schemas import BookingResult, BookingStatus
from tools.availability import check_restaurant_availability, check_venue_availability
from tools.store import get_store


def book_restaurant(
    restaurant_id: str,
    time_slot: str,
    party_size: int,
    *,
    original_time_slot: str | None = None,
) -> BookingResult:
    """
    预订餐厅座位。

    original_time_slot：用户最初请求的时间段。
    若与 time_slot 不同，说明已经过 fallback（如 17:30→18:30），
    在结果里标记 fallback_applied=True，供前端展示"已为您调整时间"。
    """
    try:
        restaurant = get_store().restaurants.get(restaurant_id)
    except KeyError:
        return BookingResult(
            action="订座",
            target_name=restaurant_id,
            status=BookingStatus.failed,
            detail=f"餐厅 {restaurant_id} 不存在",
        )

    # final check：再次确认可用性，防止规划到执行之间的窗口期失效
    avail = check_restaurant_availability(restaurant_id, time_slot, party_size)
    if not avail.available:
        return BookingResult(
            action="订座",
            target_name=restaurant.name,
            status=BookingStatus.failed,
            detail=avail.message,
        )

    fallback = original_time_slot is not None and original_time_slot != time_slot
    cost = restaurant.price_per_person * party_size

    return BookingResult(
        action="订座",
        target_name=restaurant.name,
        status=BookingStatus.success,
        detail=f"已预订 {time_slot} {party_size} 人，预计消费 ¥{cost}",
        cost=cost,
        fallback_applied=fallback,
    )


def book_venue(
    venue_id: str,
    party_size: int,
    requested_time: str,
) -> BookingResult:
    """
    购买场所门票。

    requested_time 用于 final check（确认在营业时间内），不影响购票本身。
    场所无时间段概念，成功即视为完成购票。
    """
    try:
        venue = get_store().venues.get(venue_id)
    except KeyError:
        return BookingResult(
            action="购票",
            target_name=venue_id,
            status=BookingStatus.failed,
            detail=f"场所 {venue_id} 不存在",
        )

    avail = check_venue_availability(venue_id, requested_time)
    if not avail.available:
        return BookingResult(
            action="购票",
            target_name=venue.name,
            status=BookingStatus.failed,
            detail=avail.message,
        )

    cost = venue.price_per_person * party_size

    return BookingResult(
        action="购票",
        target_name=venue.name,
        status=BookingStatus.success,
        detail=f"已购 {party_size} 张门票，合计 ¥{cost}",
        cost=cost,
    )
