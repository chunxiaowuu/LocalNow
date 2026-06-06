"""
amap_http 测试。

不依赖真实网络：API Key 为空时走 fallback 路径，
内部函数通过直接调用验证映射逻辑。
"""
from unittest.mock import patch

import pytest

from models.schemas import ActivityCategory, NoiseLevel
from tools.amap_http import (
    _DEFAULT_SLOTS,
    _fallback_restaurants,
    _fallback_venues,
    _infer_noise_level,
    _parse_coordinates,
    _typecode_to_category,
    fetch_restaurants,
    fetch_venues,
)


# ---------------------------------------------------------------------------
# 内部工具函数
# ---------------------------------------------------------------------------

class TestParseCoordinates:
    def test_valid(self):
        c = _parse_coordinates("121.4737,31.2304")
        assert c.lng == pytest.approx(121.4737)
        assert c.lat == pytest.approx(31.2304)

    def test_invalid_returns_default(self):
        c = _parse_coordinates("bad_data")
        assert c.lat == pytest.approx(31.2304)
        assert c.lng == pytest.approx(121.4737)

    def test_empty_returns_default(self):
        c = _parse_coordinates("")
        assert c.lat == pytest.approx(31.2304)


class TestTypecodeToCategory:
    def test_park(self):
        assert _typecode_to_category("110001") == ActivityCategory.park

    def test_museum(self):
        assert _typecode_to_category("140100") == ActivityCategory.museum

    def test_exhibition(self):
        assert _typecode_to_category("140200") == ActivityCategory.exhibition

    def test_aquarium(self):
        assert _typecode_to_category("140400") == ActivityCategory.aquarium

    def test_unknown_defaults_to_citywalk(self):
        assert _typecode_to_category("999999") == ActivityCategory.citywalk


class TestInferNoiseLevel:
    def test_cafe_is_quiet(self):
        assert _infer_noise_level("咖啡厅") == NoiseLevel.quiet

    def test_hotpot_is_lively(self):
        assert _infer_noise_level("火锅店") == NoiseLevel.lively

    def test_unknown_is_moderate(self):
        assert _infer_noise_level("中餐厅") == NoiseLevel.moderate

    def test_tea_is_quiet(self):
        assert _infer_noise_level("茶馆") == NoiseLevel.quiet


# ---------------------------------------------------------------------------
# Fallback 路径（不需要网络）
# ---------------------------------------------------------------------------

class TestFallback:
    def test_fallback_venues_returns_list(self):
        venues = _fallback_venues(5)
        assert len(venues) <= 5
        assert all(hasattr(v, "id") for v in venues)

    def test_fallback_venues_fills_visit_duration(self):
        venues = _fallback_venues(10)
        for v in venues:
            assert v.typical_visit_minutes > 0

    def test_fallback_restaurants_returns_list(self):
        rests = _fallback_restaurants(5)
        assert len(rests) <= 5
        assert all(hasattr(r, "id") for r in rests)

    def test_fallback_restaurants_have_slots(self):
        rests = _fallback_restaurants(5)
        for r in rests:
            assert isinstance(r.available_slots, list)


class TestFetchVenuesNoKey:
    """API Key 为空时应走 fallback，不发网络请求。"""

    def test_returns_venues_without_key(self):
        venues = fetch_venues("上海", [ActivityCategory.park])
        assert len(venues) > 0

    def test_respects_n_limit(self):
        venues = fetch_venues("上海", [], n=3)
        assert len(venues) <= 3

    def test_venue_has_required_fields(self):
        venues = fetch_venues("上海", [])
        v = venues[0]
        assert v.name
        assert v.id
        assert v.typical_visit_minutes > 0


class TestFetchRestaurantsNoKey:
    """API Key 为空时应走 fallback，不发网络请求。"""

    def test_returns_restaurants_without_key(self):
        rests = fetch_restaurants("上海")
        assert len(rests) > 0

    def test_respects_n_limit(self):
        rests = fetch_restaurants("上海", n=4)
        assert len(rests) <= 4

    def test_restaurant_has_required_fields(self):
        rests = fetch_restaurants("上海")
        r = rests[0]
        assert r.name
        assert r.id


# ---------------------------------------------------------------------------
# 网络失败时降级到 fallback
# ---------------------------------------------------------------------------

class TestFetchVenuesFallbackOnError:
    def test_network_error_falls_back(self):
        import httpx
        with patch("tools.amap_http.config") as mock_cfg, \
             patch("tools.amap_http._search_pois", side_effect=httpx.ConnectError("timeout")):
            mock_cfg.amap_api_key = "fake_key"
            venues = fetch_venues("上海", [ActivityCategory.park])
        assert len(venues) > 0

    def test_api_error_falls_back(self):
        with patch("tools.amap_http.config") as mock_cfg, \
             patch("tools.amap_http._search_pois", side_effect=ValueError("amap error")):
            mock_cfg.amap_api_key = "fake_key"
            venues = fetch_venues("上海", [])
        assert len(venues) > 0


class TestFetchRestaurantsFallbackOnError:
    def test_network_error_falls_back(self):
        import httpx
        with patch("tools.amap_http.config") as mock_cfg, \
             patch("tools.amap_http._search_pois", side_effect=httpx.ConnectError("timeout")):
            mock_cfg.amap_api_key = "fake_key"
            rests = fetch_restaurants("上海")
        assert len(rests) > 0


# ---------------------------------------------------------------------------
# 真实 API 响应的映射（mock httpx，不发真实请求）
# ---------------------------------------------------------------------------

_MOCK_POI_VENUE = {
    "id": "B001",
    "name": "测试公园",
    "type": "公园广场",
    "typecode": "110001",
    "location": "121.4737,31.2304",
    "address": "黄浦区测试路1号",
    "biz_ext": {"rating": "4.5", "cost": "50", "open_time": "08:00-18:00"},
}

_MOCK_POI_RESTAURANT = {
    "id": "R001",
    "name": "测试餐厅",
    "type": "中餐厅",
    "typecode": "050100",
    "location": "121.4737,31.2304",
    "address": "黄浦区测试路2号",
    "biz_ext": {"rating": "4.2", "cost": "80"},
}


class TestMappingWithMockApi:
    def test_venue_fields_mapped(self):
        with patch("tools.amap_http.config") as mock_cfg, \
             patch("tools.amap_http._search_pois", return_value=[_MOCK_POI_VENUE]):
            mock_cfg.amap_api_key = "fake_key"
            venues = fetch_venues("上海", [ActivityCategory.park])
        assert len(venues) == 1
        v = venues[0]
        assert v.id == "B001"
        assert v.name == "测试公园"
        assert v.category == ActivityCategory.park
        assert v.rating == pytest.approx(4.5)
        assert v.price_per_person == 50
        assert v.typical_visit_minutes == 60  # park = 60 min

    def test_restaurant_fields_mapped(self):
        with patch("tools.amap_http.config") as mock_cfg, \
             patch("tools.amap_http._search_pois", return_value=[_MOCK_POI_RESTAURANT]):
            mock_cfg.amap_api_key = "fake_key"
            rests = fetch_restaurants("上海")
        assert len(rests) == 1
        r = rests[0]
        assert r.id == "R001"
        assert r.name == "测试餐厅"
        assert r.available_slots == _DEFAULT_SLOTS
        assert r.noise_level == NoiseLevel.moderate

    def test_price_filter(self):
        with patch("tools.amap_http.config") as mock_cfg, \
             patch("tools.amap_http._search_pois", return_value=[_MOCK_POI_VENUE]):
            mock_cfg.amap_api_key = "fake_key"
            venues = fetch_venues("上海", [], max_price=30)
        assert len(venues) == 0  # 50元超出30元预算，被过滤

    def test_empty_poi_list_falls_back(self):
        with patch("tools.amap_http.config") as mock_cfg, \
             patch("tools.amap_http._search_pois", return_value=[]):
            mock_cfg.amap_api_key = "fake_key"
            venues = fetch_venues("上海", [])
        assert len(venues) > 0  # 空结果 → fallback
