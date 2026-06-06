import math

from models.schemas import Coordinates, Venue

_EARTH_RADIUS_KM = 6371.0


def haversine_km(a: Coordinates, b: Coordinates) -> float:
    """两点间球面距离（km）。"""
    lat1, lng1 = math.radians(a.lat), math.radians(a.lng)
    lat2, lng2 = math.radians(b.lat), math.radians(b.lng)
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def greedy_cluster(
    venues: list[Venue],
    k: int,
    radius_km: float,
) -> list[list[Venue]]:
    """
    贪心地理聚类，将场所分配到 k 个簇（每天一个）。

    调用方负责在传入前按综合分降序排好。算法：
      1. 取剩余列表首位（最高分）为当前簇锚点
      2. 把距锚点 ≤ radius_km 的场所全部纳入该簇
      3. 剩余场所进入下一轮，重复直到 k 个簇全部建立
    """
    remaining = list(venues)
    clusters: list[list[Venue]] = []

    for _ in range(k):
        if not remaining:
            break
        anchor = remaining[0]
        in_cluster = [anchor]
        out_of_cluster = []
        for v in remaining[1:]:
            if haversine_km(anchor.coordinates, v.coordinates) <= radius_km:
                in_cluster.append(v)
            else:
                out_of_cluster.append(v)
        clusters.append(in_cluster)
        remaining = out_of_cluster

    return clusters
