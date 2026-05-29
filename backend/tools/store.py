"""
ChromaDB 初始化与检索接口。

启动时从 JSON 文件加载数据并建立内存索引，供其他 Tool 模块通过
module-level 单例 `store` 直接使用。

两类查询分工：
  - 硬约束（精确匹配）：在 Python 层过滤 metadata，不走向量搜索
  - 软偏好（语义相似）：通过 ChromaDB query() 向量检索
"""

import json
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions

from models.schemas import Restaurant, Venue

# $in 操作符在 chromadb 0.5.0 之前存在 bug，多值过滤会 silently 返回空结果
def _check_chromadb_version() -> None:
    major, minor, *_ = (int(x) for x in chromadb.__version__.split(".")[:3])
    if (major, minor) < (0, 5):
        raise RuntimeError(
            f"chromadb >= 0.5.0 required, found {chromadb.__version__}. "
            "Run: uv add 'chromadb>=0.5'"
        )

_check_chromadb_version()

_DATA_DIR = Path(__file__).parent.parent / "data"

# ChromaDB 默认 embedding model：all-MiniLM-L6-v2（384 维），首次运行自动下载
_EF = embedding_functions.DefaultEmbeddingFunction()


def _to_doc_text(name: str, tags: list[str]) -> str:
    """将记录转换为嵌入文本：名称 + tags 拼接，用于语义检索。"""
    return f"{name} {' '.join(tags)}"


def _venue_metadata(v: dict) -> dict:
    """提取场所的结构化字段作为 ChromaDB metadata（只支持 str/int/float/bool）。"""
    return {
        "id": v["id"],
        "name": v["name"],
        "category": v["category"],
        "distance_km": float(v["distance_km"]),
        "price_per_person": int(v["price_per_person"]),
        "rating": float(v["rating"]),
        "kids_friendly": bool(v.get("kids_friendly", False)),
        "indoor": bool(v.get("indoor", True)),
        "opening_hours": v.get("opening_hours", ""),
        "address": v.get("address", ""),
        "tags_str": ",".join(v.get("tags", [])),
    }


def _restaurant_metadata(r: dict) -> dict:
    """提取餐厅的结构化字段作为 ChromaDB metadata。"""
    return {
        "id": r["id"],
        "name": r["name"],
        "cuisine": r.get("cuisine", ""),
        "distance_km": float(r["distance_km"]),
        "price_per_person": int(r["price_per_person"]),
        "rating": float(r["rating"]),
        "has_kids_menu": bool(r.get("has_kids_menu", False)),
        "has_low_calorie_options": bool(r.get("has_low_calorie_options", False)),
        "noise_level": r.get("noise_level", "moderate"),
        "max_party_size": int(r.get("max_party_size", 10)),
        "available_slots_str": ",".join(r.get("available_slots", [])),
        "address": r.get("address", ""),
        "tags_str": ",".join(r.get("tags", [])),
    }


class VenueStore:
    """场所向量索引，支持语义检索 + 硬约束过滤。"""

    def __init__(self, collection: chromadb.Collection, raw: list[dict]) -> None:
        self._col = collection
        # 保留原始 dict 便于重建完整对象（ChromaDB metadata 不存坐标等嵌套字段）
        self._raw: dict[str, dict] = {v["id"]: v for v in raw}

    def get(self, venue_id: str) -> Venue:
        """按 ID 精确查找，找不到抛 KeyError。"""
        return Venue(**self._raw[venue_id])

    def query(
        self,
        text: str,
        *,
        kids_friendly: bool | None = None,
        prefer_indoor: bool | None = None,
        max_distance_km: float | None = None,
        max_price: int | None = None,
        n_results: int = 10,
    ) -> list[Venue]:
        """
        语义检索 + metadata 过滤，返回 Venue 列表（按相似度降序）。

        ChromaDB where 子句只支持 AND 语义，多条件直接叠加。
        数值范围用 $lte / $gte 操作符。
        """
        where: dict = {}
        conditions: list[dict] = []

        if kids_friendly is not None:
            conditions.append({"kids_friendly": {"$eq": kids_friendly}})
        if prefer_indoor is not None:
            conditions.append({"indoor": {"$eq": prefer_indoor}})
        if max_distance_km is not None:
            conditions.append({"distance_km": {"$lte": max_distance_km}})
        if max_price is not None:
            conditions.append({"price_per_person": {"$lte": max_price}})

        if len(conditions) == 1:
            where = conditions[0]
        elif len(conditions) > 1:
            where = {"$and": conditions}

        kwargs: dict = {"query_texts": [text], "n_results": min(n_results, self._col.count())}
        if where:
            kwargs["where"] = where

        results = self._col.query(**kwargs)
        ids = results["ids"][0] if results["ids"] else []
        return [Venue(**self._raw[vid]) for vid in ids if vid in self._raw]


class RestaurantStore:
    """餐厅向量索引，支持语义检索 + 硬约束过滤。"""

    def __init__(self, collection: chromadb.Collection, raw: list[dict]) -> None:
        self._col = collection
        self._raw: dict[str, dict] = {r["id"]: r for r in raw}

    def get(self, restaurant_id: str) -> Restaurant:
        """按 ID 精确查找，找不到抛 KeyError。"""
        return Restaurant(**self._raw[restaurant_id])

    def query(
        self,
        text: str,
        *,
        has_kids_menu: bool | None = None,
        has_low_calorie_options: bool | None = None,
        noise_levels: list[str] | None = None,
        min_party_size: int | None = None,
        max_distance_km: float | None = None,
        max_price: int | None = None,
        n_results: int = 10,
    ) -> list[Restaurant]:
        """
        语义检索 + metadata 过滤，返回 Restaurant 列表（按相似度降序）。

        noise_levels 为多值过滤，ChromaDB 用 $in 操作符。
        min_party_size 用 $gte（max_party_size >= 所需人数）。
        """
        conditions: list[dict] = []

        if has_kids_menu is not None:
            conditions.append({"has_kids_menu": {"$eq": has_kids_menu}})
        if has_low_calorie_options is not None:
            conditions.append({"has_low_calorie_options": {"$eq": has_low_calorie_options}})
        if noise_levels:
            conditions.append({"noise_level": {"$in": noise_levels}})
        if min_party_size is not None:
            conditions.append({"max_party_size": {"$gte": min_party_size}})
        if max_distance_km is not None:
            conditions.append({"distance_km": {"$lte": max_distance_km}})
        if max_price is not None:
            conditions.append({"price_per_person": {"$lte": max_price}})

        where: dict = {}
        if len(conditions) == 1:
            where = conditions[0]
        elif len(conditions) > 1:
            where = {"$and": conditions}

        kwargs: dict = {"query_texts": [text], "n_results": min(n_results, self._col.count())}
        if where:
            kwargs["where"] = where

        results = self._col.query(**kwargs)
        ids = results["ids"][0] if results["ids"] else []
        return [Restaurant(**self._raw[rid]) for rid in ids if rid in self._raw]


class DataStore:
    """顶层单例，持有 venues 和 restaurants 两个子索引。"""

    def __init__(self) -> None:
        client = chromadb.EphemeralClient()  # 纯内存，进程结束自动销毁

        venues_raw = json.loads((_DATA_DIR / "venues_full.json").read_text())
        restaurants_raw = json.loads((_DATA_DIR / "restaurants_full.json").read_text())

        venue_col = client.create_collection("venues", embedding_function=_EF)
        venue_col.add(
            ids=[v["id"] for v in venues_raw],
            documents=[_to_doc_text(v["name"], v.get("tags", [])) for v in venues_raw],
            metadatas=[_venue_metadata(v) for v in venues_raw],
        )

        rest_col = client.create_collection("restaurants", embedding_function=_EF)
        rest_col.add(
            ids=[r["id"] for r in restaurants_raw],
            documents=[_to_doc_text(r["name"], r.get("tags", [])) for r in restaurants_raw],
            metadatas=[_restaurant_metadata(r) for r in restaurants_raw],
        )

        self.venues = VenueStore(venue_col, venues_raw)
        self.restaurants = RestaurantStore(rest_col, restaurants_raw)

        print(f"[store] loaded {len(venues_raw)} venues, {len(restaurants_raw)} restaurants")


_store: DataStore | None = None


def get_store() -> DataStore:
    """惰性单例：第一次调用时初始化，之后复用同一实例。

    延迟到调用时才读文件和建索引，避免测试环境或数据未生成时 import 报错。
    """
    global _store
    if _store is None:
        _store = DataStore()
    return _store
