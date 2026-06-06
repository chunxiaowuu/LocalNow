from models.schemas import ActivityCategory, TravelMode

VISIT_DURATION: dict[ActivityCategory, int] = {
    ActivityCategory.museum:      90,
    ActivityCategory.aquarium:   120,
    ActivityCategory.park:        60,
    ActivityCategory.kids_center: 90,
    ActivityCategory.escape_room: 90,
    ActivityCategory.exhibition:  60,
    ActivityCategory.citywalk:    60,
}

RESTAURANT_DURATION = 60


def neighborhood_radius_km(duration_hours: float, travel_modes: list[TravelMode]) -> float:
    """活动总时长和交通方式决定地理聚类半径。"""
    if duration_hours <= 4:
        base = 2.5
    elif duration_hours <= 8:
        base = 4.0
    else:
        base = 5.0

    if TravelMode.taxi in travel_modes or TravelMode.bike in travel_modes:
        multiplier = 1.6
    elif TravelMode.metro in travel_modes:
        multiplier = 1.2
    else:
        multiplier = 1.0

    return base * multiplier


def estimate_travel(
    distance_km: float,
    travel_modes: list[TravelMode],
) -> tuple[int, TravelMode]:
    """经验公式估算交通时间，返回 (分钟, 选用的交通方式)。"""
    if distance_km < 0.8:
        return 10, TravelMode.walk

    if TravelMode.taxi in travel_modes:
        minutes = max(10, int(distance_km * 3 + 5))
        return minutes, TravelMode.taxi

    if TravelMode.metro in travel_modes:
        minutes = int(distance_km * 2 + 15)
        return minutes, TravelMode.metro

    if TravelMode.bike in travel_modes:
        minutes = max(10, int(distance_km * 4))
        return minutes, TravelMode.bike

    minutes = max(10, int(distance_km * 12))
    return minutes, TravelMode.walk
