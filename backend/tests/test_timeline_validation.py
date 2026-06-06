"""validate_timeline 单元测试：纯函数，不调 LLM。"""
from agent.nodes import validate_timeline
from models.schemas import ConstraintSet, Plan, Scenario, TimelineItem


def _item(name, start, end, *, day=1, category="activity", cost=0):
    return TimelineItem(
        day=day, name=name, address="x",
        start_time=start, end_time=end, category=category, estimated_cost=cost,
    )


def _plan(items):
    return Plan(
        id="p1", title="测试方案", summary="",
        timeline=items, total_duration_minutes=0, total_cost_estimate=0,
    )


def _constraints(**kw):
    base = dict(scenario=Scenario.friends, group_size=2,
                duration_hours=5.0, duration_days=1, budget_per_person=300)
    base.update(kw)
    return ConstraintSet(**base)


class TestValidTimeline:
    def test_clean_single_day_passes(self):
        plan = _plan([
            _item("博物馆", "10:00", "11:30", cost=50),
            _item("餐厅", "12:00", "13:00", category="restaurant", cost=80),
        ])
        assert validate_timeline(plan, _constraints()) == []

    def test_back_to_back_not_overlap(self):
        # 上一环节结束 == 下一环节开始，不算重叠
        plan = _plan([
            _item("A", "10:00", "11:00"),
            _item("B", "11:00", "12:00", category="restaurant"),
        ])
        assert validate_timeline(plan, _constraints()) == []


class TestTimeErrors:
    def test_overlap_detected(self):
        plan = _plan([
            _item("A", "10:00", "12:00"),
            _item("B", "11:00", "13:00", category="restaurant"),
        ])
        errs = validate_timeline(plan, _constraints())
        assert any("重叠" in e for e in errs)

    def test_end_before_start(self):
        plan = _plan([_item("A", "14:00", "12:00")])
        errs = validate_timeline(plan, _constraints())
        assert any("结束早于开始" in e for e in errs)

    def test_daily_span_exceeds_duration(self):
        # 09:00→18:00 = 540min，duration 5h=300min（+15 容差）→ 超
        plan = _plan([
            _item("A", "09:00", "10:30"),
            _item("B", "16:30", "18:00", category="restaurant"),
        ])
        errs = validate_timeline(plan, _constraints(duration_hours=5.0))
        assert any("超过每天上限" in e for e in errs)

    def test_within_tolerance_passes(self):
        # 10:00→15:10 = 310min，duration 5h=300 + 15 容差 = 315 → 通过
        plan = _plan([
            _item("A", "10:00", "11:30"),
            _item("B", "13:40", "15:10", category="restaurant"),
        ])
        assert validate_timeline(plan, _constraints(duration_hours=5.0)) == []


class TestCostAndDays:
    def test_over_budget(self):
        plan = _plan([
            _item("A", "10:00", "11:30", cost=200),
            _item("B", "12:00", "13:00", category="restaurant", cost=200),
        ])
        errs = validate_timeline(plan, _constraints(budget_per_person=300))
        assert any("超过预算" in e for e in errs)

    def test_missing_day_in_multiday(self):
        # 行程 2 天，但只安排了 day 1
        plan = _plan([_item("A", "10:00", "11:30", day=1)])
        errs = validate_timeline(plan, _constraints(duration_days=2))
        assert any("缺少第" in e for e in errs)

    def test_multiday_complete_passes(self):
        plan = _plan([
            _item("A", "10:00", "11:30", day=1, cost=50),
            _item("B", "10:00", "11:30", day=2, cost=50),
        ])
        assert validate_timeline(plan, _constraints(duration_days=2)) == []
