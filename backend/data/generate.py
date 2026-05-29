"""
用本地 Ollama 模型生成合成餐厅和场所数据。
只需运行一次：uv run python data/generate.py
生成结果保存为 restaurants_full.json 和 venues_full.json
"""

import json
from pathlib import Path

from openai import OpenAI

DATA_DIR = Path(__file__).parent

# Ollama 暴露 OpenAI 兼容接口，无需 API Key
client = OpenAI(
    base_url="http://localhost:11434/v1",
    api_key="ollama",
)

RESTAURANT_PROMPT = """
生成 {{COUNT}} 条上海餐厅的 JSON 数据，用于本地活动规划 App 的演示。

要求：
1. 覆盖多种菜系：杭帮菜、本帮菜、粤菜、日料、川菜、西餐、素食、台式等
2. 混合分布：约一半适合家庭（has_kids_menu=true, has_low_calorie_options=true），一半适合朋友聚会
3. noise_level 分布：quiet / moderate / lively 各占一部分
4. 地址用上海真实区名和路名，坐标在上海范围内（lat: 31.1~31.4, lng: 121.3~121.6）
5. tags 字段要语义丰富，包含用户会用来描述这家餐厅的自然语言词汇，例如"适合聊天"、"环境安静"、"健康轻食"

每条数据格式如下（严格遵守）：
{
  "id": "rg001",
  "name": "餐厅名",
  "cuisine": "菜系",
  "coordinates": {"lat": 31.23, "lng": 121.47},
  "address": "区名+路名+门牌号",
  "distance_km": 2.5,
  "price_per_person": 120,
  "rating": 4.3,
  "has_kids_menu": true,
  "has_low_calorie_options": false,
  "noise_level": "moderate",
  "max_party_size": 8,
  "available_slots": ["17:30", "18:00", "19:00"],
  "tags": ["家庭聚餐", "儿童友好", "安静", "本帮菜", "性价比"]
}

直接输出 JSON 数组，不要任何解释文字。
"""

VENUE_PROMPT = """
生成 {{COUNT}} 条上海活动场所的 JSON 数据，用于本地活动规划 App 的演示。

要求：
1. category 覆盖：aquarium、kids_center、park、museum、escape_room、exhibition、citywalk
2. 混合分布：约一半 kids_friendly=true（适合带孩子），一半 kids_friendly=false（适合朋友）
3. 地址用上海真实区名和路名
4. tags 字段语义丰富，包含用户会说的自然语言，例如"适合亲子"、"室内不晒"、"团队挑战"

每条数据格式如下（严格遵守）：
{
  "id": "vg001",
  "name": "场所名",
  "category": "kids_center",
  "coordinates": {"lat": 31.23, "lng": 121.47},
  "address": "区名+路名+门牌号",
  "distance_km": 3.1,
  "price_per_person": 100,
  "rating": 4.4,
  "opening_hours": "10:00-20:00",
  "kids_friendly": true,
  "indoor": true,
  "tags": ["亲子乐园", "室内", "儿童游乐", "适合5岁以上"]
}

直接输出 JSON 数组，不要任何解释文字。
"""


def generate_batch(prompt: str, count: int) -> list[dict]:
    """单次生成 count 条，解析失败最多重试 3 次。"""
    filled_prompt = prompt.replace("{{COUNT}}", str(count))
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model="qwen3:8b",
                max_tokens=6000,
                messages=[{"role": "user", "content": filled_prompt}],
            )
            raw = resp.choices[0].message.content.strip()
            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start == -1 or end == 0:
                raise json.JSONDecodeError("未找到 JSON 数组", raw, 0)
            return json.loads(raw[start:end])
        except json.JSONDecodeError as e:
            print(f"  第 {attempt + 1} 次解析失败：{e}，重试...")
    print("  3 次均失败，跳过本批次")
    return []


def generate(prompt: str, label: str, total: int, batch_size: int = 15) -> list[dict]:
    """分批生成，避免单次输出过长导致 JSON 截断。"""
    results = []
    batches = (total + batch_size - 1) // batch_size
    for i in range(batches):
        remaining = total - len(results)
        current = min(batch_size, remaining)
        print(f"正在生成{label}第 {i + 1}/{batches} 批（{current} 条）...")
        batch = generate_batch(prompt, current)
        results.extend(batch)
        print(f"  本批获得 {len(batch)} 条，累计 {len(results)} 条")
    return results


def reassign_ids(data: list[dict], prefix: str) -> list[dict]:
    """重新分配 ID，保证全局唯一，格式如 r001, r002..."""
    for i, item in enumerate(data):
        item["id"] = f"{prefix}{i + 1:03d}"
    return data


def main():
    seed_restaurants = json.loads((DATA_DIR / "restaurants.json").read_text())
    seed_venues = json.loads((DATA_DIR / "venues.json").read_text())

    extra_restaurants = generate(RESTAURANT_PROMPT, "餐厅", total=42, batch_size=15)
    extra_venues = generate(VENUE_PROMPT, "场所", total=24, batch_size=12)

    # 合并后统一重新编号，消除分批生成导致的 ID 重复
    full_restaurants = reassign_ids(seed_restaurants + extra_restaurants, "r")
    full_venues = reassign_ids(seed_venues + extra_venues, "v")

    (DATA_DIR / "restaurants_full.json").write_text(
        json.dumps(full_restaurants, ensure_ascii=False, indent=2)
    )
    (DATA_DIR / "venues_full.json").write_text(
        json.dumps(full_venues, ensure_ascii=False, indent=2)
    )

    print(f"\n餐厅：{len(seed_restaurants)} 手工 + {len(extra_restaurants)} 生成 = {len(full_restaurants)} 条")
    print(f"场所：{len(seed_venues)} 手工 + {len(extra_venues)} 生成 = {len(full_venues)} 条")
    print("完成，已写出 restaurants_full.json 和 venues_full.json")


if __name__ == "__main__":
    main()
