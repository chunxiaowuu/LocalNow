"""
availability 工具单元测试。

全部基于手工种子数据（restaurants.json / venues.json），结果确定性强：
  - r001 外婆家：available_slots=["17:00","18:30","19:00"]，max_party_size=8
  - v001 上海海洋水族馆：opening_hours="09:00-21:00"
"""


from models.schemas import ToolErrorCode
from tools.availability import (
    _next_available_slot,
    _parse_time,
    check_restaurant_availability,
    check_venue_availability,
)


# ---------------------------------------------------------------------------
# helper 函数
# ---------------------------------------------------------------------------

class TestParseTime:
    def test_normal(self):
        assert _parse_time("17:30") == 17 * 60 + 30

    def test_midnight(self):
        assert _parse_time("00:00") == 0

    def test_end_of_day(self):
        assert _parse_time("23:59") == 23 * 60 + 59


class TestNextAvailableSlot:
    SLOTS = ["17:00", "18:30", "19:00"]

    def test_finds_next_slot(self):
        assert _next_available_slot(self.SLOTS, "17:30") == "18:30"

    def test_no_slot_after_last(self):
        assert _next_available_slot(self.SLOTS, "19:00") is None

    def test_exact_match_not_counted(self):
        # "17:00" 本身不算"晚于"17:00，返回下一个
        assert _next_available_slot(self.SLOTS, "17:00") == "18:30"

    def test_empty_slots(self):
        assert _next_available_slot([], "17:00") is None


# ---------------------------------------------------------------------------
# 餐厅可用性
# ---------------------------------------------------------------------------

class TestCheckRestaurantAvailability:

    def test_r001_no_17_30_slot(self):
        """核心 demo fallback：17:30 没有空位，返回 18:30 作为替代。"""
        result = check_restaurant_availability("r001", "17:30", party_size=3)
        assert result.available is False
        assert result.error_code == ToolErrorCode.NO_SEAT
        assert result.retryable is True
        assert result.next_available_slot == "18:30"

    def test_r001_has_17_00_slot(self):
        """17:00 在 available_slots 里，应直接返回可用。"""
        result = check_restaurant_availability("r001", "17:00", party_size=3)
        assert result.available is True
        assert result.error_code is None

    def test_r001_has_18_30_slot(self):
        result = check_restaurant_availability("r001", "18:30", party_size=3)
        assert result.available is True

    def test_party_too_large_not_retryable(self):
        """人数超过 max_party_size=8，应换餐厅而非换时间。"""
        result = check_restaurant_availability("r001", "18:30", party_size=10)
        assert result.available is False
        assert result.error_code == ToolErrorCode.NO_SEAT
        assert result.retryable is False

    def test_party_at_capacity_boundary(self):
        """恰好等于 max_party_size，应允许预订。"""
        result = check_restaurant_availability("r001", "18:30", party_size=8)
        assert result.available is True

    def test_no_more_slots_after_last(self):
        """请求晚于最后一个时间段（19:00），next_available_slot 应为 None。"""
        result = check_restaurant_availability("r001", "20:00", party_size=3)
        assert result.available is False
        assert result.next_available_slot is None

    def test_invalid_restaurant_id(self):
        result = check_restaurant_availability("r999", "18:00", party_size=2)
        assert result.available is False
        assert result.retryable is False


# ---------------------------------------------------------------------------
# 场所可用性
# ---------------------------------------------------------------------------

class TestCheckVenueAvailability:

    def test_v001_open_during_day(self):
        """14:00 在 09:00-21:00 营业时间内。"""
        result = check_venue_availability("v001", "14:00")
        assert result.available is True
        assert result.error_code is None

    def test_v001_open_at_boundary(self):
        """09:00 是开门时间，应可用。"""
        result = check_venue_availability("v001", "09:00")
        assert result.available is True

    def test_v001_closed_after_hours(self):
        """21:00 是关门时间，不应可用（区间为左闭右开）。"""
        result = check_venue_availability("v001", "21:00")
        assert result.available is False
        assert result.error_code == ToolErrorCode.CLOSED
        assert result.retryable is False

    def test_v001_closed_before_open(self):
        """08:00 在开门前，应关闭。"""
        result = check_venue_availability("v001", "08:00")
        assert result.available is False
        assert result.error_code == ToolErrorCode.CLOSED

    def test_invalid_venue_id(self):
        result = check_venue_availability("v999", "14:00")
        assert result.available is False
        assert result.retryable is False
