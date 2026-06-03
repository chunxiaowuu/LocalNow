import pytest
from models.schemas import ActivityCategory, TravelMode
from tools.travel import (
    RESTAURANT_DURATION,
    VISIT_DURATION,
    estimate_travel,
    neighborhood_radius_km,
)


class TestVisitDuration:
    def test_all_categories_covered(self):
        for cat in ActivityCategory:
            assert cat in VISIT_DURATION, f"{cat} missing from VISIT_DURATION"

    def test_aquarium_longest(self):
        assert VISIT_DURATION[ActivityCategory.aquarium] == max(VISIT_DURATION.values())

    def test_restaurant_duration(self):
        assert RESTAURANT_DURATION == 60


class TestNeighborhoodRadius:
    def test_short_trip_walk_only(self):
        r = neighborhood_radius_km(3.0, [TravelMode.walk])
        assert r == pytest.approx(2.5)

    def test_short_trip_taxi(self):
        r = neighborhood_radius_km(3.0, [TravelMode.taxi])
        assert r == pytest.approx(2.5 * 1.6)

    def test_medium_trip_metro(self):
        r = neighborhood_radius_km(6.0, [TravelMode.metro])
        assert r == pytest.approx(4.0 * 1.2)

    def test_long_trip_taxi(self):
        r = neighborhood_radius_km(10.0, [TravelMode.taxi])
        assert r == pytest.approx(5.0 * 1.6)

    def test_boundary_4h(self):
        assert neighborhood_radius_km(4.0, [TravelMode.walk]) == pytest.approx(2.5)

    def test_boundary_8h(self):
        assert neighborhood_radius_km(8.0, [TravelMode.walk]) == pytest.approx(4.0)

    def test_boundary_above_8h(self):
        assert neighborhood_radius_km(8.1, [TravelMode.walk]) == pytest.approx(5.0)


class TestEstimateTravel:
    def test_walking_short_distance(self):
        mins, mode = estimate_travel(0.5, [TravelMode.walk, TravelMode.taxi])
        assert mins == 10
        assert mode == TravelMode.walk

    def test_taxi_preferred(self):
        mins, mode = estimate_travel(3.0, [TravelMode.taxi, TravelMode.metro])
        assert mode == TravelMode.taxi
        assert mins == max(10, int(3.0 * 3 + 5))

    def test_metro_fallback(self):
        mins, mode = estimate_travel(3.0, [TravelMode.metro])
        assert mode == TravelMode.metro
        assert mins == int(3.0 * 2 + 15)

    def test_bike_fallback(self):
        mins, mode = estimate_travel(2.0, [TravelMode.bike])
        assert mode == TravelMode.bike
        assert mins == max(10, int(2.0 * 4))

    def test_walk_only_long_distance(self):
        mins, mode = estimate_travel(2.0, [TravelMode.walk])
        assert mode == TravelMode.walk
        assert mins == max(10, int(2.0 * 12))

    def test_taxi_minimum_10_min(self):
        mins, mode = estimate_travel(1.0, [TravelMode.taxi])
        assert mins >= 10
        assert mode == TravelMode.taxi
