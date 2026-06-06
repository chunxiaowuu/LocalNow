"""
高德地图 HTTP REST 客户端。

只做数据获取和映射，不含业务逻辑。
API Key 为空或请求失败时自动 fallback 到本地 mock 数据。
"""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

import httpx

from config import config
from models.schemas import (
    ActivityCategory,
    Coordinates,
    NoiseLevel,
    Restaurant,
    Venue,
)
from tools.travel import VISIT_DURATION

logger = logging.getLogger(__name__)

_AMAP_SEARCH_URL  = "https://restapi.amap.com/v3/place/text"
_AMAP_GEOCODE_URL = "https://restapi.amap.com/v3/geocode/geo"
_DATA_DIR = Path(__file__).parent.parent / "data"

# 常用城市坐标缓存，避免重复调 Geocoding API
_CITY_CENTER_CACHE: dict[str, Coordinates] = {
    "上海": Coordinates(lat=31.2304, lng=121.4737),
    "北京": Coordinates(lat=39.9042, lng=116.4074),
    "深圳": Coordinates(lat=22.5431, lng=114.0579),
    "广州": Coordinates(lat=23.1291, lng=113.2644),
    "杭州": Coordinates(lat=30.2741, lng=120.1551),
    "成都": Coordinates(lat=30.5728, lng=104.0668),
    "重庆": Coordinates(lat=29.5630, lng=106.5516),
    "武汉": Coordinates(lat=30.5928, lng=114.3055),
    "西安": Coordinates(lat=34.3416, lng=108.9398),
    "南京": Coordinates(lat=32.0603, lng=118.7969),
    "苏州": Coordinates(lat=31.2990, lng=120.5853),
    "天津": Coordinates(lat=39.3434, lng=117.3616),
    "青岛": Coordinates(lat=36.0671, lng=120.3826),
    "厦门": Coordinates(lat=24.4798, lng=118.0894),
    "长沙": Coordinates(lat=28.2278, lng=112.9388),
}

_DEFAULT_SLOTS = [
    "11:30", "12:00", "12:30", "13:00",
    "17:30", "18:00", "18:30", "19:00", "19:30",
]

# 偏好标签 → 高德搜索关键词
_CATEGORY_KEYWORDS: dict[ActivityCategory, str] = {
    ActivityCategory.museum:      "博物馆 展览馆",
    ActivityCategory.exhibition:  "博物馆 展览馆",
    ActivityCategory.park:        "公园",
    ActivityCategory.aquarium:    "水族馆 动物园",
    ActivityCategory.kids_center: "儿童乐园",
    ActivityCategory.escape_room: "密室逃脱 剧本杀",
    ActivityCategory.citywalk:    "公园 景点 历史街区",
}
_DEFAULT_VENUE_KEYWORDS = "博物馆 公园 景点 展览"

# 高德 typecode 前4位 → ActivityCategory
_TYPECODE_MAP: dict[str, ActivityCategory] = {
    "1100": ActivityCategory.park,        # 公园广场
    "1400": ActivityCategory.museum,      # 科教文化
    "1401": ActivityCategory.museum,      # 博物馆
    "1402": ActivityCategory.exhibition,  # 展览馆
    "1404": ActivityCategory.aquarium,    # 动物园/水族馆
    "0803": ActivityCategory.kids_center, # 儿童乐园
    "0804": ActivityCategory.escape_room, # 娱乐场所
}


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------

def geocode_city(city: str) -> Coordinates:
    """
    解析城市名为坐标中心点。优先查本地缓存，未命中时调高德 Geocoding API。
    API 失败时 fallback 到上海，并记录警告。
    """
    if city in _CITY_CENTER_CACHE:
        return _CITY_CENTER_CACHE[city]

    _SHANGHAI = Coordinates(lat=31.2304, lng=121.4737)
    try:
        resp = httpx.get(
            _AMAP_GEOCODE_URL,
            params={"key": config.amap_api_key, "address": city, "output": "JSON"},
            timeout=5.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "1" and data.get("geocodes"):
            loc = data["geocodes"][0]["location"]  # "lng,lat"
            lng_str, lat_str = loc.split(",")
            coords = Coordinates(lat=float(lat_str), lng=float(lng_str))
            _CITY_CENTER_CACHE[city] = coords  # 缓存结果
            return coords
        logger.warning("geocode_city: no result for '%s', fallback to Shanghai", city)
    except Exception as e:
        logger.warning("geocode_city failed for '%s': %s, fallback to Shanghai", city, e)

    return _SHANGHAI


def _search_pois(keywords: str, city: str, types: str = "", offset: int = 20) -> list[dict]:
    """调用高德 /v3/place/text，返回原始 POI 列表。失败返回空列表。"""
    params = {
        "key":      config.amap_api_key,
        "keywords": keywords,
        "city":     city,
        "offset":   offset,
        "output":   "JSON",
        "extensions": "all",
    }
    if types:
        params["types"] = types

    resp = httpx.get(_AMAP_SEARCH_URL, params=params, timeout=8.0)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "1":
        raise ValueError(f"amap error: {data.get('info')}")
    return data.get("pois", [])


def _biz(poi: dict) -> dict:
    """安全提取 biz_ext，高德在无商业数据时返回 [] 而非 {}。"""
    b = poi.get("biz_ext")
    return b if isinstance(b, dict) else {}


def _typecode_to_category(typecode: str) -> ActivityCategory:
    prefix = typecode[:4]
    return _TYPECODE_MAP.get(prefix, ActivityCategory.citywalk)


def _parse_coordinates(location: str) -> Coordinates:
    """高德 location 格式为 'lng,lat'。"""
    try:
        lng_str, lat_str = location.split(",")
        return Coordinates(lat=float(lat_str), lng=float(lng_str))
    except Exception:
        return Coordinates(lat=31.2304, lng=121.4737)


def _infer_noise_level(type_name: str) -> NoiseLevel:
    quiet_keywords  = ("咖啡", "茶室", "茶馆", "轻食", "书店")
    lively_keywords = ("火锅", "烧烤", "快餐", "麻辣")
    if any(k in type_name for k in quiet_keywords):
        return NoiseLevel.quiet
    if any(k in type_name for k in lively_keywords):
        return NoiseLevel.lively
    return NoiseLevel.moderate


# ---------------------------------------------------------------------------
# 公开接口
# ---------------------------------------------------------------------------

def fetch_venues(
    city: str,
    categories: list[ActivityCategory],
    *,
    kids_friendly: bool = False,
    prefer_indoor: bool = False,
    max_price: int = 9999,
    keywords: str | None = None,
    allow_mock_fallback: bool = True,
    n: int = 20,
) -> list[Venue]:
    """
    搜索场所并映射到 Venue 模型。

    keywords：显式覆盖搜索关键词（冷启动检索阶梯逐级传入）；为 None 时按 categories 自动选词。
    allow_mock_fallback：True 时无结果/出错降级到本地 mock；False 时返回空列表，
      供上层冷启动阶梯继续尝试下一级关键词。
    """
    if not config.amap_api_key:
        return _fallback_venues(n) if allow_mock_fallback else []

    def _empty() -> list[Venue]:
        return _fallback_venues(n) if allow_mock_fallback else []

    try:
        if keywords is not None:
            # 冷启动检索词为用户精确诉求，不再叠加 categories / 亲子，避免污染 query
            search_kw = keywords
        else:
            if categories:
                search_kw = " ".join(
                    _CATEGORY_KEYWORDS.get(c, "") for c in categories if _CATEGORY_KEYWORDS.get(c)
                ) or _DEFAULT_VENUE_KEYWORDS
            else:
                search_kw = _DEFAULT_VENUE_KEYWORDS

            if kids_friendly:
                search_kw += " 亲子"

        pois = _search_pois(search_kw, city, offset=min(n, 25))
        if not pois:
            return _empty()

        venues: list[Venue] = []
        for poi in pois:
            try:
                cat = _typecode_to_category(poi.get("typecode", ""))
                coords = _parse_coordinates(poi.get("location", ""))
                price_raw = _biz(poi).get("cost", "0") or "0"
                try:
                    price = int(float(price_raw))
                except ValueError:
                    price = 0

                if price > max_price:
                    continue

                venues.append(Venue(
                    id=poi.get("id") or str(uuid.uuid4()),
                    name=poi["name"],
                    category=cat,
                    coordinates=coords,
                    address=poi.get("address", ""),
                    distance_km=0.0,
                    price_per_person=price,
                    rating=float(_biz(poi).get("rating") or 4.0),
                    opening_hours=_biz(poi).get("open_time") or "09:00-18:00",
                    kids_friendly=kids_friendly,
                    indoor=prefer_indoor,
                    tags=[poi.get("type", "")],
                    typical_visit_minutes=VISIT_DURATION.get(cat, 90),
                ))
            except Exception:
                continue

        # 全部被硬约束（如价格）过滤掉 → 返回空列表（冷启动阶梯据此继续降级），
        # 不退回 mock：那是"预算内无匹配"的真实结果，不是数据源失败。
        return venues[:n]

    except Exception as e:
        logger.warning("fetch_venues failed, using fallback: %s", e)
        return _empty()


def fetch_restaurants(
    city: str,
    *,
    has_kids_menu: bool = False,
    has_low_calorie: bool = False,
    noise_levels: list[NoiseLevel] | None = None,
    min_party_size: int = 1,
    max_price: int = 9999,
    keywords: str | None = None,
    allow_mock_fallback: bool = True,
    n: int = 20,
) -> list[Restaurant]:
    """
    搜索餐厅并映射到 Restaurant 模型。
    available_slots 使用固定默认值（高德不提供实时预约数据）。

    keywords：显式覆盖搜索关键词（冷启动检索阶梯逐级传入）；为 None 时按 flag 自动选词。
    allow_mock_fallback：True 时无结果/出错降级到本地 mock；False 时返回空列表，
      供上层冷启动阶梯继续尝试下一级关键词。
    """
    if not config.amap_api_key:
        return _fallback_restaurants(n) if allow_mock_fallback else []

    def _empty() -> list[Restaurant]:
        return _fallback_restaurants(n) if allow_mock_fallback else []

    try:
        if keywords is not None:
            search_kw = keywords
        elif has_kids_menu:
            search_kw = "亲子餐厅 家庭餐厅"
        elif has_low_calorie:
            search_kw = "健康轻食 沙拉"
        elif noise_levels and NoiseLevel.quiet in noise_levels:
            search_kw = "安静咖啡厅 茶室"
        else:
            search_kw = "餐厅 美食 老字号"

        pois = _search_pois(search_kw, city, types="050000", offset=min(n, 25))
        if not pois:
            return _empty()

        restaurants: list[Restaurant] = []
        for poi in pois:
            try:
                type_name = poi.get("type", "")
                price_raw = _biz(poi).get("cost", "0") or "0"
                try:
                    price = int(float(price_raw))
                except ValueError:
                    price = 0

                if price > max_price:
                    continue

                noise = _infer_noise_level(type_name)
                if noise_levels and noise not in noise_levels:
                    continue

                restaurants.append(Restaurant(
                    id=poi.get("id") or str(uuid.uuid4()),
                    name=poi["name"],
                    cuisine=type_name,
                    coordinates=_parse_coordinates(poi.get("location", "")),
                    address=poi.get("address", ""),
                    distance_km=0.0,
                    price_per_person=price,
                    rating=float(_biz(poi).get("rating") or 4.0),
                    has_kids_menu=has_kids_menu,
                    has_low_calorie_options=has_low_calorie,
                    noise_level=noise,
                    max_party_size=10,
                    available_slots=_DEFAULT_SLOTS,
                    tags=[type_name],
                ))
            except Exception:
                continue

        # 全部被硬约束（如价格）过滤掉 → 返回空列表（冷启动阶梯据此继续降级），
        # 不退回 mock：那是"预算内无匹配"的真实结果，不是数据源失败。
        return restaurants[:n]

    except Exception as e:
        logger.warning("fetch_restaurants failed, using fallback: %s", e)
        return _empty()


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------

def _fallback_venues(n: int) -> list[Venue]:
    try:
        raw = json.loads((_DATA_DIR / "venues_full.json").read_text(encoding="utf-8"))
        venues = []
        for item in raw[:n]:
            item.setdefault("typical_visit_minutes", 90)
            try:
                cat = ActivityCategory(item["category"])
                item["typical_visit_minutes"] = VISIT_DURATION.get(cat, 90)
            except ValueError:
                pass
            venues.append(Venue(**item))
        return venues
    except Exception as e:
        logger.error("fallback_venues failed: %s", e)
        return []


def _fallback_restaurants(n: int) -> list[Restaurant]:
    try:
        raw = json.loads((_DATA_DIR / "restaurants_full.json").read_text(encoding="utf-8"))
        return [Restaurant(**item) for item in raw[:n]]
    except Exception as e:
        logger.error("fallback_restaurants failed: %s", e)
        return []
