"""
Reward 数据查表模块

提供精确的分数和超时时间查表功能。
被核心引擎和 playground 共同使用。
"""

from __future__ import annotations


class RecipeRewardLookup:
    """
    加载 reward.csv 并提供精确的分数查表。

    CSV 格式：
        recipe,base points with cond,base points without cond,
               visibility with cond,visibility without cond
    """

    def __init__(self, csv_path: str = "data/reward.csv"):
        self._data: dict[str, dict[str, int]] = {}
        self._load(csv_path)

    def _load(self, csv_path: str) -> None:
        import csv
        from pathlib import Path

        path = Path(csv_path)
        if not path.exists():
            # 尝试从项目根目录查找
            path = Path(__file__).parent.parent.parent / csv_path

        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row["recipe"].strip()
                self._data[name] = {
                    "base_with_cond": int(row["base points with cond"]),
                    "base_without_cond": int(row["base points without cond"]),
                    "visibility_with_cond": int(row["visibility with cond"]),
                    "visibility_without_cond": int(row["visibility without cond"]),
                }

    def _get_multiplier(self, total_visibility: float, is_rush: bool) -> float:
        """根据总 visibility 区间和订单类型返回得分倍率。"""
        if total_visibility < 40:
            return 1.6 if is_rush else 1.0
        if total_visibility < 80:
            return 2.0 if is_rush else 1.1
        if total_visibility < 160:
            return 2.5 if is_rush else 1.2
        if total_visibility < 240:
            return 3.0 if is_rush else 1.3
        if total_visibility < 360:
            return 3.5 if is_rush else 1.4
        return 4.0 if is_rush else 1.5

    def get_score(
        self,
        recipe_name: str,
        has_condiments: bool,
        is_rush: bool,
        total_visibility: float | None = None,
    ) -> float:
        """
        计算 serve 的精确分数。

        Args:
            recipe_name: 菜品名称（slug）
            has_condiments: 是否添加了调料
            is_rush: 是否为 rush 订单
            total_visibility: 已完成订单的总 visibility，None 视为 0

        Returns:
            float: 该订单的得分
        """
        row = self._data.get(recipe_name)
        if not row:
            return 0.0

        if has_condiments:
            base = row["base_with_cond"]
            vis = row["visibility_with_cond"]
        else:
            base = row["base_without_cond"]
            vis = row["visibility_without_cond"]

        total = base + vis
        multiplier = self._get_multiplier(total_visibility or 0.0, is_rush)
        return float(total * multiplier)

    def get_visibility(self, recipe_name: str, has_condiments: bool) -> int:
        """
        获取订单的 visibility 值。

        Args:
            recipe_name: 菜品名称（slug）
            has_condiments: 是否添加了调料

        Returns:
            int: visibility 值，找不到返回 0
        """
        row = self._data.get(recipe_name)
        if not row:
            return 0
        return row["visibility_with_cond"] if has_condiments else row["visibility_without_cond"]

    def __contains__(self, recipe_slug: str) -> bool:
        return recipe_slug in self._data


class RecipeTimeoutLookup:
    """
    加载 recipe_timeout.csv 并提供精确的超时查表。
    
    CSV 格式：
        recipe,normal_timeout,rush_timeout
    """

    def __init__(self, csv_path: str = "data/recipe_timeout.csv"):
        self._data: dict[str, dict[str, float]] = {}
        self._load(csv_path)

    def _load(self, csv_path: str) -> None:
        import csv
        from pathlib import Path

        path = Path(csv_path)
        if not path.exists():
            path = Path(__file__).parent.parent.parent / csv_path

        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                slug = row["recipe"].strip()
                self._data[slug] = {
                    "normal_timeout": float(row["normal_timeout"]),
                    "rush_timeout": float(row["rush_timeout"]),
                }

    def get_timeout(self, recipe_slug: str, is_rush: bool) -> float | None:
        """
        获取订单超时时间。
        
        Args:
            recipe_slug: 配方的 slug
            is_rush: 是否为 rush 订单
            
        Returns:
            float: 超时时间（秒），如果找不到返回 None
        """
        row = self._data.get(recipe_slug)
        if not row:
            return None
        return row["rush_timeout"] if is_rush else row["normal_timeout"]

    def __contains__(self, recipe_slug: str) -> bool:
        return recipe_slug in self._data
