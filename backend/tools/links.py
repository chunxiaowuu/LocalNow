"""
构建对外跳转链接（高德地图、预订平台）。

纯字符串拼接，不发网络请求。坐标/名称来自候选池真实数据，
由 generate_plans 在方案生成后回填到 TimelineItem，避免 LLM 编造链接。
"""
from __future__ import annotations

from urllib.parse import quote


def amap_marker_uri(name: str, lng: float, lat: float) -> str:
    """
    高德地图标记点链接：在网页/App 中定位到该 POI。
    坐标系固定 gaode（高德返回即 GCJ-02）。
    """
    return (
        "https://uri.amap.com/marker"
        f"?position={lng},{lat}"
        f"&name={quote(name)}"
        "&src=localnow&coordinate=gaode&callnative=1"
    )
