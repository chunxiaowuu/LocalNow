"""
pytest 共享 fixtures。

store fixture 设为 session 级：整个 test session 只初始化一次 ChromaDB，
避免每个测试函数都重新加载 JSON + 建索引（约 2-5 秒）。
"""

import pytest

from models.schemas import ActivityConstraints, ConstraintSet, Scenario


@pytest.fixture(scope="session")
def store():
    from tools.store import get_store
    return get_store()


@pytest.fixture
def family_constraints():
    return ConstraintSet(
        scenario=Scenario.family,
        group_size=3,
        max_distance_km=5.0,
        budget_per_person=200,
        activity=ActivityConstraints(kids_friendly=True),
    )


@pytest.fixture
def friends_constraints():
    return ConstraintSet(
        scenario=Scenario.friends,
        group_size=4,
        max_distance_km=5.0,
        budget_per_person=300,
    )
