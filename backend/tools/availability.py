"""
可用性查询工具。

所有数据来自 Mock JSON，模拟真实 API 的返回结构。
错误码（NO_SEAT / CLOSED）直接驱动 LangGraph 的 replan 决策：
  retryable=True  → 换时间段重试
  retryable=False → 换地点（人数超限或永久关闭）
"""

from models.schemas import AvailabilityResult, ToolErrorCode
from tools.store import get_store


def _parse_time(t: str) -> int:
    """将 "HH:MM" 转为分钟数，便于大小比较。"""
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def _next_available_slot(slots: list[str], requested_time: str) -> str | None:
    """返回 slots 中第一个晚于 requested_time 的时间段，没有则返回 None。"""
    requested_minutes = _parse_time(requested_time)
    for slot in sorted(slots, key=_parse_time):
        if _parse_time(slot) > requested_minutes:
            return slot
    return None


def check_restaurant_availability(
    restaurant_id: str,
    requested_time: str,
    party_size: int,
) -> AvailabilityResult:
    """
    查询餐厅在指定时间段是否能容纳 party_size 人。

    两个独立检查，优先检查人数（人数超限换餐厅比换时间更合理）：
      1. party_size > max_party_size → NO_SEAT, retryable=False
      2. requested_time 不在 available_slots → NO_SEAT, retryable=True
                                                next_available_slot 指向下一个空位时间
    """
    try:
        restaurant = get_store().restaurants.get(restaurant_id)
    except KeyError:
        return AvailabilityResult(
            available=False,
            error_code=ToolErrorCode.NO_SEAT,
            retryable=False,
            message=f"餐厅 {restaurant_id} 不存在",
        )

    if party_size > restaurant.max_party_size:
        return AvailabilityResult(
            available=False,
            error_code=ToolErrorCode.NO_SEAT,
            retryable=False,
            message=f"{restaurant.name} 最多容纳 {restaurant.max_party_size} 人，当前需求 {party_size} 人",
        )

    slots = restaurant.available_slots
    if requested_time in slots:
        return AvailabilityResult(available=True, message=f"{restaurant.name} {requested_time} 有空位")

    next_slot = _next_available_slot(slots, requested_time)
    return AvailabilityResult(
        available=False,
        error_code=ToolErrorCode.NO_SEAT,
        retryable=True,
        next_available_slot=next_slot,
        message=(
            f"{restaurant.name} {requested_time} 无空位，"
            + (f"最近可用时间：{next_slot}" if next_slot else "今日无更多空位")
        ),
    )


def check_venue_availability(
    venue_id: str,
    requested_time: str,
) -> AvailabilityResult:
    """
    查询场所在指定时间是否在营业时间内。

    opening_hours 格式固定为 "HH:MM-HH:MM"。
    不在营业时间 → CLOSED, retryable=False（营业时间不会因重试改变）。
    """
    try:
        venue = get_store().venues.get(venue_id)
    except KeyError:
        return AvailabilityResult(
            available=False,
            error_code=ToolErrorCode.CLOSED,
            retryable=False,
            message=f"场所 {venue_id} 不存在",
        )

    open_str, close_str = venue.opening_hours.split("-")
    open_min = _parse_time(open_str.strip())
    close_min = _parse_time(close_str.strip())
    req_min = _parse_time(requested_time)

    if open_min <= req_min < close_min:
        return AvailabilityResult(
            available=True,
            message=f"{venue.name} {requested_time} 营业中（{venue.opening_hours}）",
        )

    return AvailabilityResult(
        available=False,
        error_code=ToolErrorCode.CLOSED,
        retryable=False,
        message=f"{venue.name} {requested_time} 不在营业时间内（{venue.opening_hours}）",
    )
