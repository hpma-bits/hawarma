"""
更新 reward.csv：使用 slug 而不是 display name，与 recipe_timeout.csv 对齐
"""

import csv
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')


def main():
    reward_path = Path("playground/reward.csv")
    timeout_path = Path("playground/recipe_timeout.csv")

    # 读取 timeout 获取 slug 映射
    slug_by_name = {}
    with open(timeout_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            slug_by_name[row["recipe"]] = row["slug"]

    print(f"recipe_timeout.csv has {len(slug_by_name)} recipes")

    # 读取 reward，更新
    rows = []
    with open(reward_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["recipe"]
            slug = slug_by_name.get(name)
            if slug:
                row["recipe"] = slug
                rows.append(row)
            else:
                print(f"  Warning: {name} not found in timeout, skipping")

    # 写回
    with open(reward_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["recipe", "base points with cond", "base points without cond", "visibility with cond", "visibility without cond"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Updated {reward_path} with {len(rows)} recipes (slugs)")


if __name__ == "__main__":
    main()