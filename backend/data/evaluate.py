"""
评估生成数据的质量。
运行：uv run python data/evaluate.py
"""

import json
import random
from collections import Counter
from pathlib import Path

from openai import OpenAI

from models.schemas import Restaurant, Venue

DATA_DIR = Path(__file__).parent
llm = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")


def check_duplicate_ids(data: list[dict], label: str) -> int:
    ids = [d.get("id", "") for d in data]
    counter = Counter(ids)
    duplicates = {k: v for k, v in counter.items() if v > 1}
    if duplicates:
        print(f"   ✗ 发现重复 ID：{duplicates}")
        return len(duplicates)
    print(f"   ✓ 无重复 ID")
    return 0


def evaluate_restaurants(data: list[dict]) -> int:
    """返回失败条数"""
    print("\n" + "=" * 50)
    print(f"餐厅数据评估（共 {len(data)} 条）")
    print("=" * 50)

    # ① 结构验证
    valid, errors = [], []
    for i, r in enumerate(data):
        try:
            valid.append(Restaurant(**r))
        except Exception as e:
            errors.append(f"第 {i + 1} 条（id={r.get('id', '?')}）：{e}")

    print(f"\n① 结构验证")
    print(f"   合法：{len(valid)} 条 / 失败：{len(errors)} 条")
    for e in errors:
        print(f"   ✗ {e}")

    print(f"\n   ID 唯一性检查：")
    dup_count = check_duplicate_ids(data, "餐厅")

    if not valid:
        return len(errors) + dup_count

    # ② 分布
    print(f"\n② 场景覆盖分布")
    kids_menu = sum(1 for r in valid if r.has_kids_menu)
    low_cal = sum(1 for r in valid if r.has_low_calorie_options)
    noise = Counter(r.noise_level.value for r in valid)
    print(f"   有儿童菜单（家庭场景）：{kids_menu} 条 ({kids_menu * 100 // len(valid)}%)")
    print(f"   有低卡选项（减肥场景）：{low_cal} 条 ({low_cal * 100 // len(valid)}%)")
    print(f"   噪音分布：{dict(noise)}")
    print(f"   人均价格：¥{min(r.price_per_person for r in valid)} ~ ¥{max(r.price_per_person for r in valid)}，均值 ¥{sum(r.price_per_person for r in valid) // len(valid)}")

    # ③ 语义多样性
    print(f"\n③ 语义多样性（tags）")
    all_tags = [tag for r in valid for tag in r.tags]
    unique_tags = set(all_tags)
    tag_counter = Counter(all_tags)
    print(f"   总 tags：{len(all_tags)}，唯一 tags：{len(unique_tags)}")
    print(f"   最常见：{tag_counter.most_common(5)}")
    print(f"   平均每条 tags：{len(all_tags) / len(valid):.1f}")

    # ④ 抽样
    print(f"\n④ 随机抽样（前 3 条）")
    for r in valid[:3]:
        print(f"   [{r.cuisine}] {r.name} | ¥{r.price_per_person}/人 | {r.noise_level.value} | {r.tags[:3]}")

    return len(errors) + dup_count


def evaluate_venues(data: list[dict]) -> int:
    """返回失败条数"""
    print("\n" + "=" * 50)
    print(f"场所数据评估（共 {len(data)} 条）")
    print("=" * 50)

    valid, errors = [], []
    for i, v in enumerate(data):
        try:
            valid.append(Venue(**v))
        except Exception as e:
            errors.append(f"第 {i + 1} 条（id={v.get('id', '?')}）：{e}")

    print(f"\n① 结构验证")
    print(f"   合法：{len(valid)} 条 / 失败：{len(errors)} 条")
    for e in errors:
        print(f"   ✗ {e}")

    print(f"\n   ID 唯一性检查：")
    dup_count = check_duplicate_ids(data, "场所")

    if not valid:
        return len(errors) + dup_count

    print(f"\n② 场景覆盖分布")
    kids = sum(1 for v in valid if v.kids_friendly)
    indoor = sum(1 for v in valid if v.indoor)
    categories = Counter(v.category.value for v in valid)
    print(f"   亲子友好（家庭场景）：{kids} 条 ({kids * 100 // len(valid)}%)")
    print(f"   室内场所：{indoor} 条 ({indoor * 100 // len(valid)}%)")
    print(f"   类型分布：{dict(categories)}")

    print(f"\n③ 语义多样性（tags）")
    all_tags = [tag for v in valid for tag in v.tags]
    print(f"   总 tags：{len(all_tags)}，唯一 tags：{len(set(all_tags))}")
    print(f"   平均每条 tags：{len(all_tags) / len(valid):.1f}")

    print(f"\n④ 随机抽样（前 3 条）")
    for v in valid[:3]:
        print(f"   [{v.category.value}] {v.name} | ¥{v.price_per_person}/人 | kids:{v.kids_friendly} | {v.tags[:3]}")

    return len(errors) + dup_count


def llm_spot_check(restaurants: list[dict], venues: list[dict]) -> None:
    print("\n" + "=" * 50)
    print("LLM 语义抽查（随机抽取 3 条餐厅 + 2 条场所）")
    print("=" * 50)

    samples = random.sample(restaurants, min(3, len(restaurants))) + \
              random.sample(venues, min(2, len(venues)))

    prompt = f"""你是数据质量审查员，检查以下上海本地活动规划 App 的模拟数据：

1. 名称是否像真实的上海餐厅/场所？
2. tags 和 noise_level / kids_friendly 等字段是否逻辑一致？
3. 价格是否符合该类型场所的市场水平？

数据：
{json.dumps(samples, ensure_ascii=False, indent=2)}

逐条给出1-2句评价，最后给出总体质量评分（1-5分）。用中文回答。"""

    resp = llm.chat.completions.create(
        model="qwen3:8b",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    print(resp.choices[0].message.content)


def main():
    restaurants = json.loads((DATA_DIR / "restaurants_full.json").read_text())
    venues = json.loads((DATA_DIR / "venues_full.json").read_text())

    r_errors = evaluate_restaurants(restaurants)
    v_errors = evaluate_venues(venues)
    llm_spot_check(restaurants, venues)

    # 基于实际结果的汇总，不写死文字
    total_errors = r_errors + v_errors
    print("\n" + "=" * 50)
    print("汇总")
    print("=" * 50)
    if total_errors == 0:
        print("✓ 结构验证全部通过，无重复 ID")
    else:
        print(f"✗ 共发现 {total_errors} 个问题（结构错误 + 重复ID），需要修复后再使用")
    print("场景覆盖建议：家庭/朋友各 > 40%；唯一 tags > 80；LLM 评分 >= 4")


if __name__ == "__main__":
    main()
