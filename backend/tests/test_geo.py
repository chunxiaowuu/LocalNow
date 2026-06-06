import math
import pytest
from models.schemas import ActivityCategory, Coordinates, Venue
from tools.geo import greedy_cluster, haversine_km


def _make_venue(name: str, lat: float, lng: float, rating: float = 4.0) -> Venue:
    return Venue(
        id=name,
        name=name,
        category=ActivityCategory.park,
        coordinates=Coordinates(lat=lat, lng=lng),
        address="",
        distance_km=0.0,
        price_per_person=0,
        rating=rating,
        opening_hours="09:00-18:00",
    )


# 上海市中心附近几个真实坐标对用于验证距离量级
_PEOPLE_SQUARE = Coordinates(lat=31.2304, lng=121.4737)   # 人民广场
_JING_AN_TEMPLE = Coordinates(lat=31.2245, lng=121.4479)  # 静安寺（约 2.5 km）
_PUDONG_LUJIAZUI = Coordinates(lat=31.2399, lng=121.4993) # 陆家嘴（约 3.5 km）


class TestHaversineKm:
    def test_same_point_is_zero(self):
        assert haversine_km(_PEOPLE_SQUARE, _PEOPLE_SQUARE) == pytest.approx(0.0)

    def test_people_square_to_jing_an(self):
        d = haversine_km(_PEOPLE_SQUARE, _JING_AN_TEMPLE)
        assert 2.0 < d < 3.5

    def test_people_square_to_lujiazui(self):
        d = haversine_km(_PEOPLE_SQUARE, _PUDONG_LUJIAZUI)
        assert 2.5 < d < 5.0

    def test_symmetric(self):
        d1 = haversine_km(_PEOPLE_SQUARE, _JING_AN_TEMPLE)
        d2 = haversine_km(_JING_AN_TEMPLE, _PEOPLE_SQUARE)
        assert d1 == pytest.approx(d2)

    def test_known_1_degree_latitude(self):
        a = Coordinates(lat=0.0, lng=0.0)
        b = Coordinates(lat=1.0, lng=0.0)
        d = haversine_km(a, b)
        assert d == pytest.approx(111.195, rel=0.01)


class TestGreedyCluster:
    def test_single_cluster(self):
        venues = [
            _make_venue("A", 31.23, 121.47),
            _make_venue("B", 31.24, 121.48),  # ~1.4 km from A
        ]
        clusters = greedy_cluster(venues, k=1, radius_km=5.0)
        assert len(clusters) == 1
        assert len(clusters[0]) == 2

    def test_two_clusters_by_distance(self):
        # A 和 B 在人民广场附近，C 在浦东（~3.5 km）
        a = _make_venue("A", 31.2304, 121.4737, rating=4.8)  # anchor for cluster 1
        b = _make_venue("B", 31.2310, 121.4740, rating=4.5)  # 紧邻 A
        c = _make_venue("C", 31.2399, 121.4993, rating=4.2)  # 距 A 约 3.5 km
        venues = [a, b, c]
        clusters = greedy_cluster(venues, k=2, radius_km=1.0)
        assert len(clusters) == 2
        assert a in clusters[0]
        assert b in clusters[0]
        assert c in clusters[1]

    def test_k_greater_than_venues(self):
        venues = [_make_venue("A", 31.23, 121.47)]
        clusters = greedy_cluster(venues, k=3, radius_km=5.0)
        assert len(clusters) == 1  # 只有 1 个场所，只能建 1 个簇

    def test_empty_venues(self):
        clusters = greedy_cluster([], k=2, radius_km=5.0)
        assert clusters == []

    def test_first_venue_is_anchor(self):
        # 传入已按分排好的列表，第一个应成为锚点
        high = _make_venue("High", 31.2304, 121.4737, rating=5.0)
        low  = _make_venue("Low",  31.2300, 121.4730, rating=3.0)
        clusters = greedy_cluster([high, low], k=1, radius_km=5.0)
        assert clusters[0][0] == high

    def test_radius_boundary(self):
        a = _make_venue("A", 31.2304, 121.4737)
        # B 距 A 约 2.5 km（静安寺方向）
        b = _make_venue("B", 31.2245, 121.4479)
        dist = haversine_km(a.coordinates, b.coordinates)

        # 半径刚好大于距离 → 同一簇
        clusters_in = greedy_cluster([a, b], k=2, radius_km=dist + 0.1)
        assert len(clusters_in[0]) == 2

        # 半径刚好小于距离 → 不同簇
        clusters_out = greedy_cluster([a, b], k=2, radius_km=dist - 0.1)
        assert len(clusters_out[0]) == 1
        assert len(clusters_out) == 2
