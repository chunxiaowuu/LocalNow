"""快速验证高德 API 真实返回结果，运行：uv run python scripts/test_amap_live.py"""
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.DEBUG)

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import config
from models.schemas import ActivityCategory
from tools.amap_http import _search_pois, fetch_restaurants, fetch_venues

print(f"AMAP_API_KEY 已配置: {'是' if config.amap_api_key else '否（将走 fallback）'}\n")

print("=" * 50)
print("原始 API 响应（博物馆，前2条）")
print("=" * 50)
try:
    pois = _search_pois("博物馆 展览馆", "上海", offset=2)
    print(f"返回 {len(pois)} 条 POI")
    if pois:
        print(json.dumps(pois[0], ensure_ascii=False, indent=2))
except Exception as e:
    print(f"API 调用失败: {e}")
print()

print("=" * 50)
print("搜索场所：博物馆 + 公园（上海，n=5）")
print("=" * 50)
venues = fetch_venues("上海", [ActivityCategory.museum, ActivityCategory.park], n=5)
for v in venues:
    print(f"  {v.name}")
    print(f"    分类: {v.category.value}  评分: {v.rating}  人均: ¥{v.price_per_person}")
    print(f"    地址: {v.address}")
    print(f"    坐标: {v.coordinates.lat}, {v.coordinates.lng}")
    print(f"    营业: {v.opening_hours}  游玩时长: {v.typical_visit_minutes}min")
    print()

print("=" * 50)
print("搜索餐厅：亲子餐厅（上海，n=5）")
print("=" * 50)
restaurants = fetch_restaurants("上海", has_kids_menu=True, n=5)
for r in restaurants:
    print(f"  {r.name}")
    print(f"    菜系: {r.cuisine}  评分: {r.rating}  人均: ¥{r.price_per_person}")
    print(f"    地址: {r.address}")
    print(f"    噪声: {r.noise_level.value}  可预约时段: {r.available_slots[:3]}...")
    print()
