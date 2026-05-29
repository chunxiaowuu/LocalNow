"""
booking 工具单元测试。

基于手工种子数据：
  - r001 外婆家：available_slots=["17:00","18:30","19:00"]，price_per_person=85，max_party_size=8
  - v001 上海海洋水族馆：opening_hours="09:00-21:00"，price_per_person=190
"""

from models.schemas import BookingStatus
from tools.booking import book_restaurant, book_venue


class TestBookRestaurant:

    def test_success(self):
        """正常预订：18:30 有空位，3人，应返回 success。"""
        result = book_restaurant("r001", "18:30", party_size=3)
        assert result.status == BookingStatus.success
        assert result.cost == 85 * 3
        assert result.fallback_applied is False

    def test_final_check_blocks_unavailable_slot(self):
        """17:30 没有空位，final check 应拦截，返回 failed。"""
        result = book_restaurant("r001", "17:30", party_size=3)
        assert result.status == BookingStatus.failed

    def test_fallback_applied_flag(self):
        """原始请求 17:30，实际预订 18:30，fallback_applied 应为 True。"""
        result = book_restaurant("r001", "18:30", party_size=3, original_time_slot="17:30")
        assert result.status == BookingStatus.success
        assert result.fallback_applied is True

    def test_no_fallback_when_slots_match(self):
        """original_time_slot 与 time_slot 相同，fallback_applied 应为 False。"""
        result = book_restaurant("r001", "18:30", party_size=3, original_time_slot="18:30")
        assert result.status == BookingStatus.success
        assert result.fallback_applied is False

    def test_party_too_large_blocked_by_final_check(self):
        """人数超过 max_party_size=8，final check 拦截，返回 failed。"""
        result = book_restaurant("r001", "18:30", party_size=10)
        assert result.status == BookingStatus.failed

    def test_invalid_restaurant_id(self):
        result = book_restaurant("r999", "18:30", party_size=2)
        assert result.status == BookingStatus.failed


class TestBookVenue:

    def test_success(self):
        """14:00 在营业时间内，2人，应返回 success。"""
        result = book_venue("v001", party_size=2, requested_time="14:00")
        assert result.status == BookingStatus.success
        assert result.cost == 190 * 2

    def test_closed_blocked_by_final_check(self):
        """22:00 超出营业时间，final check 应拦截，返回 failed。"""
        result = book_venue("v001", party_size=2, requested_time="22:00")
        assert result.status == BookingStatus.failed

    def test_cost_scales_with_party_size(self):
        result = book_venue("v001", party_size=4, requested_time="10:00")
        assert result.status == BookingStatus.success
        assert result.cost == 190 * 4

    def test_invalid_venue_id(self):
        result = book_venue("v999", party_size=2, requested_time="14:00")
        assert result.status == BookingStatus.failed
