"""
两阶检索：硬约束过滤 + 语义相似度排序。

硬约束（kids_friendly、距离、预算等）通过 ChromaDB where 子句精确过滤；
软偏好（"安静"、"适合聊天"等自然语言）通过向量相似度排序。
两者在一次 ChromaDB query() 调用中完成，无需二次过滤。
"""

from models.schemas import ConstraintSet, Restaurant, Venue
from tools.store import get_store


def search_venues(
    constraints: ConstraintSet,
    preference_text: str,
    n_results: int = 10,
) -> list[Venue]:
    """
    检索符合约束的场所候选池。

    硬约束映射：
      - activity.kids_friendly=True  → 过滤掉不亲子的场所
      - activity.prefer_indoor=True  → 只返回室内场所
      - activity.preferred_categories → 只返回指定类型（空则不限）
      - max_distance_km              → 距离上限
      - budget_per_person            → 人均价格上限

    仅当约束字段为 True / 非空时才加入过滤条件，避免过度收窄候选池。
    preference_text 用于语义排序，通常传入用户原始消息。
    """
    ac = constraints.activity

    kids_friendly = True if ac.kids_friendly else None
    prefer_indoor = True if ac.prefer_indoor else None
    preferred_categories = (
        [c.value for c in ac.preferred_categories] if ac.preferred_categories else None
    )

    store = get_store()
    candidates = store.venues.query(
        text=preference_text,
        kids_friendly=kids_friendly,
        prefer_indoor=prefer_indoor,
        max_distance_km=constraints.max_distance_km,
        max_price=constraints.budget_per_person,
        n_results=n_results,
    )

    # preferred_categories 是多值 OR 过滤，在 Python 层做更直观
    # ChromaDB $in 在有其他 AND 条件时嵌套层级较深，此处数据量小不影响性能
    if preferred_categories:
        candidates = [v for v in candidates if v.category.value in preferred_categories]

    return candidates


def search_restaurants(
    constraints: ConstraintSet,
    preference_text: str,
    n_results: int = 10,
) -> list[Restaurant]:
    """
    检索符合约束的餐厅候选池。

    硬约束映射：
      - restaurant.has_kids_menu=True           → 必须有儿童菜单
      - restaurant.has_low_calorie_options=True → 必须有低卡选项
      - restaurant.noise_level                  → 噪音偏好（多值 OR，空则不限）
      - group_size                              → 餐厅最大容纳人数 >= 团队人数
      - max_distance_km                         → 距离上限
      - budget_per_person                       → 人均价格上限
    """
    rc = constraints.restaurant

    has_kids_menu = True if rc.has_kids_menu else None
    has_low_calorie = True if rc.has_low_calorie_options else None
    noise_levels = [n.value for n in rc.noise_level] if rc.noise_level else None

    store = get_store()
    return store.restaurants.query(
        text=preference_text,
        has_kids_menu=has_kids_menu,
        has_low_calorie_options=has_low_calorie,
        noise_levels=noise_levels,
        min_party_size=constraints.group_size,
        max_distance_km=constraints.max_distance_km,
        max_price=constraints.budget_per_person,
        n_results=n_results,
    )
