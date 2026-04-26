"""
生成 recipe_timeout.csv：以 reward.csv 的顺序为基准，填充 recipe 的超时时间数据
"""

import csv
import json
import sys
from pathlib import Path


def calculate_timeout(total_cook_time: float, is_rush: bool) -> float:
    """复制模拟器的 _calculate_timeout 逻辑"""
    RUSH_TIMEOUT_MIN = 30.0
    RUSH_TIMEOUT_MAX = 45.0
    NORMAL_TIMEOUT_MIN = 55.0
    NORMAL_TIMEOUT_MAX = 75.0

    if is_rush:
        base = RUSH_TIMEOUT_MIN
        max_timeout = RUSH_TIMEOUT_MAX
    else:
        base = NORMAL_TIMEOUT_MIN
        max_timeout = NORMAL_TIMEOUT_MAX

    cook_factor = max(0.0, min(1.0, (total_cook_time - 2.0) / 4.0))
    timeout = base + (max_timeout - base) * (1.0 - cook_factor * 0.3)
    return round(timeout, 1)


def main():
    recipes_path = Path("data/recipes.json")
    reward_path = Path("playground/reward.csv")
    output_path = Path("playground/recipe_timeout.csv")

    # 加载 reward.csv 获取顺序
    reward_recipes = []
    with open(reward_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            reward_recipes.append(row["recipe"])

    print(f"reward.csv has {len(reward_recipes)} recipes")

    # 加载 recipes.json
    with open(recipes_path, "r", encoding="utf-8") as f:
        all_recipes = json.load(f)

    # 构建 slug -> recipe 映射
    recipes_by_name = {r["name"]: r for r in all_recipes}

    # 按 reward.csv 顺序生成
    rows = []
    for name in reward_recipes:
        recipe = recipes_by_name.get(name)
        if not recipe:
            sys.stdout.reconfigure(encoding='utf-8')
            print(f"  Warning: {name} not found")
            continue

        slug = recipe["slug"]
        durations = recipe.get("cook_durations", [])
        total_cook_time = sum(durations)
        num_ingredients = len(durations)

        normal_timeout = calculate_timeout(total_cook_time, is_rush=False)
        rush_timeout = calculate_timeout(total_cook_time, is_rush=True)

        rows.append({
            "recipe": name,
            "slug": slug,
            "num_ingredients": num_ingredients,
            "total_cook_time": total_cook_time,
            "normal_timeout": normal_timeout,
            "rush_timeout": rush_timeout,
        })

    # 写入
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["recipe", "slug", "num_ingredients", "total_cook_time", "normal_timeout", "rush_timeout"],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Generated {output_path} with {len(rows)} recipes")

    normal_values = [r["normal_timeout"] for r in rows]
    rush_values = [r["rush_timeout"] for r in rows]
    print(f"\nTimeout range:")
    print(f"  Normal: {min(normal_values)}s - {max(normal_values)}s")
    print(f"  Rush:   {min(rush_values)}s - {max(rush_values)}s")


if __name__ == "__main__":
    main()