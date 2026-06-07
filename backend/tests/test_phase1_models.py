"""Phase 1 数据模型测试。"""
from datetime import date


from models.schemas import (
    ActivityCategory,
    ActivityPreference,
    ConstraintSet,
    Coordinates,
    FreeTextConstraints,
    PlanRequest,
    Scenario,
    TimelineItem,
    TravelMode,
    UserRequest,
    Venue,
)


# ---------------------------------------------------------------------------
# UserRequest
# ---------------------------------------------------------------------------

class TestUserRequest:
    def test_legacy_message_field(self):
        """旧接口：message 字段正常工作。"""
        req = UserRequest(message="我想和朋友出去玩")
        assert req.message == "我想和朋友出去玩"


class TestPlanRequest:
    def test_structured_fields(self):
        req = PlanRequest(
            start_date=date(2026, 6, 7),
            end_date=date(2026, 6, 8),
            preferences=[ActivityPreference.cultural, ActivityPreference.food],
            max_distance_km=10.0,
            group_size=4,
            travel_modes=[TravelMode.taxi, TravelMode.metro],
            city="上海",
            free_text="带了一位老人，人均预算300元",
        )
        assert req.group_size == 4
        assert ActivityPreference.food in req.preferences
        assert req.city == "上海"

    def test_defaults(self):
        req = PlanRequest(
            start_date=date(2026, 6, 7),
            end_date=date(2026, 6, 7),
        )
        assert req.group_size == 2
        assert req.max_distance_km == 5.0
        assert req.free_text == ""
        assert TravelMode.taxi in req.travel_modes

    def test_duration_days_calculation(self):
        req = PlanRequest(
            start_date=date(2026, 6, 7),
            end_date=date(2026, 6, 9),
        )
        days = (req.end_date - req.start_date).days + 1
        assert days == 3


# ---------------------------------------------------------------------------
# FreeTextConstraints
# ---------------------------------------------------------------------------

class TestFreeTextConstraints:
    def test_partial_fields(self):
        ftc = FreeTextConstraints(
            start_time="14:00",
            budget_per_person=300,
            special_requirements=["适老化", "对海鲜过敏"],
        )
        assert ftc.duration_hours is None   # 未提及，为 None
        assert ftc.scenario is None
        assert len(ftc.special_requirements) == 2

    def test_all_none_by_default(self):
        ftc = FreeTextConstraints()
        assert ftc.start_time is None
        assert ftc.duration_hours is None
        assert ftc.budget_per_person is None
        assert ftc.special_requirements == []


# ---------------------------------------------------------------------------
# ConstraintSet 新字段
# ---------------------------------------------------------------------------

class TestConstraintSet:
    def test_new_fields_defaults(self):
        cs = ConstraintSet(scenario=Scenario.friends, group_size=4)
        assert cs.city == "上海"
        assert cs.start_time == "10:00"
        assert cs.duration_days == 1
        assert cs.food_focused is False

    def test_new_fields_set(self):
        cs = ConstraintSet(
            scenario=Scenario.family,
            group_size=3,
            city="北京",
            start_time="09:00",
            duration_days=2,
            food_focused=True,
        )
        assert cs.city == "北京"
        assert cs.duration_days == 2
        assert cs.food_focused is True

    def test_travel_modes_default(self):
        cs = ConstraintSet(scenario=Scenario.friends, group_size=2)
        assert TravelMode.walk in cs.travel_modes or TravelMode.taxi in cs.travel_modes


# ---------------------------------------------------------------------------
# Venue 新字段
# ---------------------------------------------------------------------------

class TestVenue:
    def _make_venue(self, **kwargs) -> Venue:
        defaults = dict(
            id="v001",
            name="测试场所",
            category=ActivityCategory.museum,
            coordinates=Coordinates(lat=31.23, lng=121.47),
            address="测试地址",
            distance_km=2.0,
            price_per_person=50,
            rating=4.5,
            opening_hours="09:00-17:00",
        )
        defaults.update(kwargs)
        return Venue(**defaults)

    def test_typical_visit_minutes_default(self):
        v = self._make_venue()
        assert v.typical_visit_minutes == 90

    def test_typical_visit_minutes_set(self):
        v = self._make_venue(typical_visit_minutes=120)
        assert v.typical_visit_minutes == 120

    def test_mock_data_still_loads(self):
        """确认现有 mock JSON 数据能兼容新字段（typical_visit_minutes 有默认值）。"""
        import json
        from pathlib import Path
        data_path = Path(__file__).parent.parent / "data" / "venues_full.json"
        if data_path.exists():
            venues = [Venue(**v) for v in json.loads(data_path.read_text())]
            assert len(venues) > 0
            for v in venues:
                assert v.typical_visit_minutes == 90  # 旧数据用默认值


# ---------------------------------------------------------------------------
# TimelineItem 新字段
# ---------------------------------------------------------------------------

class TestTimelineItem:
    def test_day_field_default(self):
        item = TimelineItem(
            name="上海博物馆",
            address="人民大道201号",
            start_time="10:00",
            end_time="11:30",
            category="activity",
        )
        assert item.day == 1

    def test_day_field_set(self):
        item = TimelineItem(
            day=2,
            name="晚餐",
            address="某餐厅",
            start_time="18:00",
            end_time="19:00",
            category="restaurant",
        )
        assert item.day == 2

    def test_multiday_timeline(self):
        items = [
            TimelineItem(day=1, name="A", address="", start_time="10:00", end_time="11:30", category="activity"),
            TimelineItem(day=1, name="B", address="", start_time="12:00", end_time="13:00", category="restaurant"),
            TimelineItem(day=2, name="C", address="", start_time="10:00", end_time="12:00", category="activity"),
        ]
        day1 = [i for i in items if i.day == 1]
        day2 = [i for i in items if i.day == 2]
        assert len(day1) == 2
        assert len(day2) == 1
