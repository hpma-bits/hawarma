"""
效率指标收集器

在游戏过程中收集事件和状态快照，游戏结束时计算效率指标。

设计原则：
- 非侵入式：不修改 SimEnv 或 GameSimulator
- 增量计算：按 tick 累计，避免存储完整历史
- 零影响：指标收集不影响游戏确定性

指标分类：
  A) 灶台利用率: idle_ratio — 灶台空闲时间占总游戏时间的比例
  B) 食材浪费:   expired_ingredients — 过期被丢弃的食材数量
  C) 组装站效率: clear_assembly_count — 清空组装站的次数（浪费已投入的工作）
  D) 库存流转:   stockpile_inserts, stockpile_pulls — 库存进出次数
  E) 吞吐量:     avg_serve_interval, max_serve_interval — 送餐间隔
  F) Agent效率:   none_ratio — 策略返回 None 的步数占比
  G) 库存压力:   stockpile_max_occupancy — 库存同时存放的最大食材数

用法:
    collector = MetricsCollector(total_cookers=4, total_stockpile_slots=3)
    while not game_over:
        action = agent.act(obs)
        result = env.step(action)
        collector.update(obs, action, result)
    metrics = collector.summarize()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hawarma.core.actions import Action


@dataclass
class EfficiencyMetrics:
    """一局游戏的完整效率指标"""

    # ── 灶台利用率 ──
    cooker_idle_time: dict[str, float]
    """各灶台的空闲时间（秒）"""
    cooker_idle_ratio: float
    """所有灶台的平均空闲率 (0~1)，越低越好"""

    # ── 食材浪费 ──
    expired_ingredients: int
    """过期被丢弃的食材数量"""
    cleared_cooker_count: int
    """手动清理灶台的次数（通常也是食材过期后清理）"""

    # ── 组装站效率 ──
    clear_assembly_count: int
    """清空组装站的次数（每次清空意味着已放入的食材浪费）"""

    # ── 库存流转 ──
    stockpile_inserts: int
    """食材存入库存的总次数"""
    stockpile_pulls: int
    """从库存取用的总次数"""
    stockpile_max_occupancy: int
    """库存同时存放的最大食材数（压力指标）"""

    # ── 吞吐量 ──
    avg_serve_interval: float
    """平均送餐间隔（秒），越低吞吐越快"""
    max_serve_interval: float
    """最大送餐间隔（秒）"""

    # ── Agent 行为效率 ──
    none_ratio: float
    """策略返回 None 的步数占比 (0~1)，越低 Agent 越忙"""
    total_steps: int
    """总决策步数"""
    none_steps: int
    """返回 None 的步数"""

    def to_dict(self) -> dict[str, float]:
        """转为扁平的 key-value 字典，方便 CSV 导出"""
        d: dict[str, float] = {}
        for name, idle in self.cooker_idle_time.items():
            d[f"idle_{name}"] = round(idle, 2)
        d["idle_ratio"] = round(self.cooker_idle_ratio, 3)
        d["expired"] = self.expired_ingredients
        d["cleared_cooker"] = self.cleared_cooker_count
        d["clear_assembly"] = self.clear_assembly_count
        d["stockpile_in"] = self.stockpile_inserts
        d["stockpile_out"] = self.stockpile_pulls
        d["stockpile_max"] = self.stockpile_max_occupancy
        d["serve_avg_gap"] = round(self.avg_serve_interval, 2)
        d["serve_max_gap"] = round(self.max_serve_interval, 2)
        d["none_ratio"] = round(self.none_ratio, 3)
        d["none_steps"] = self.none_steps
        d["total_steps"] = self.total_steps
        return d


class MetricsCollector:
    """
    增量效率指标收集器。

    在 run_episode 循环中每个 step 调用 update()，
    游戏结束时调用 summarize() 获取统计结果。
    """

    def __init__(self, total_cookers: int = 4, total_stockpile_slots: int = 3):
        # 灶台空闲时间计数
        self._total_cookers = total_cookers
        self._total_stockpile_slots = total_stockpile_slots
        self._cooker_idle_count = 0
        """上一帧空闲的灶台数量，用于增量计算 idle_time"""
        self._prev_time = 0.0

        # 累计值
        self._cooker_idle_time: dict[str, float] = {}
        self._expired = 0
        self._cleared_cooker = 0
        self._clear_assembly = 0
        self._stockpile_inserts = 0
        self._stockpile_pulls = 0
        self._stockpile_max = 0

        # 送餐间隔
        self._last_serve_time: float | None = None
        self._serve_diffs: list[float] = []

        # None 步数
        self._none_steps = 0
        self._total_steps = 0
        self._game_duration = 90.0

    def update(self, obs, action, step_result) -> None:
        """
        处理一步游戏循环的结果。

        Args:
            obs: 执行动作后的 UnifiedState
            action: 本步执行的动作（可能为 None）
            step_result: env.step() 返回的 StepResult
        """
        self._total_steps += 1

        # ── Agent 效率: None 步数 ──
        if action is None:
            self._none_steps += 1

        current_time = obs.time

        # ── 灶台空闲率: 增量计算 ──
        # 检查当前帧各灶台是否空闲
        idle_now = 0
        for name in self._cooker_idle_time:
            cooker = obs.cookers.get(name)
            if cooker is None or not cooker.busy:
                self._cooker_idle_time[name] += current_time - self._prev_time
                idle_now += 1
            elif cooker.busy and cooker.done_at and current_time < cooker.done_at:
                # still cooking, not idle
                pass
            else:
                # done but not moved (holding ingredient) — counts as idle
                self._cooker_idle_time[name] += current_time - self._prev_time
                idle_now += 1

        # 首次更新时初始化灶台名称
        if not self._cooker_idle_time:
            for name in obs.cookers:
                self._cooker_idle_time[name] = 0.0

        # ── 事件统计 ──
        for event in step_result.info.get("events", []):
            from playground.env_simulator_types import EventType
            etype = event.event_type

            if etype == EventType.INGREDIENT_EXPIRED:
                self._expired += 1

            elif etype == EventType.ORDER_SERVED:
                if self._last_serve_time is not None:
                    diff = current_time - self._last_serve_time
                    self._serve_diffs.append(diff)
                self._last_serve_time = current_time

            elif etype == EventType.INGREDIENT_MOVED_TO_STOCKPILE:
                self._stockpile_inserts += 1

        # ── 手动动作统计 ──
        if action is not None:
            action_name = type(action).__name__
            if action_name == "ClearCookerAction":
                self._cleared_cooker += 1
            elif action_name == "ClearAssemblyAction":
                self._clear_assembly += 1
            elif action_name == "PullFromStockpileAction":
                self._stockpile_pulls += 1

        # ── 库存最大占用 ──
        current_occ = sum(
            s.count for s in obs.stockpile.values() if s and s.count > 0
        )
        self._stockpile_max = max(self._stockpile_max, current_occ)

        self._prev_time = current_time
        self._game_duration = obs.game_duration

    def summarize(self) -> EfficiencyMetrics:
        """生成最终的效率指标"""
        total_cooker_time = sum(self._cooker_idle_time.values())
        total_possible_time = self._total_cookers * self._game_duration
        idle_ratio = total_cooker_time / total_possible_time if total_possible_time > 0 else 0.0

        avg_serve_interval = (
            sum(self._serve_diffs) / len(self._serve_diffs)
            if self._serve_diffs else 0.0
        )
        max_serve_interval = max(self._serve_diffs) if self._serve_diffs else 0.0

        none_ratio = self._none_steps / self._total_steps if self._total_steps > 0 else 0.0

        return EfficiencyMetrics(
            cooker_idle_time=dict(self._cooker_idle_time),
            cooker_idle_ratio=idle_ratio,
            expired_ingredients=self._expired,
            cleared_cooker_count=self._cleared_cooker,
            clear_assembly_count=self._clear_assembly,
            stockpile_inserts=self._stockpile_inserts,
            stockpile_pulls=self._stockpile_pulls,
            stockpile_max_occupancy=self._stockpile_max,
            avg_serve_interval=avg_serve_interval,
            max_serve_interval=max_serve_interval,
            none_ratio=none_ratio,
            total_steps=self._total_steps,
            none_steps=self._none_steps,
        )


def compute_efficiency_summary(
    all_metrics: list[EfficiencyMetrics],
    all_rewards: list[float],
) -> dict[str, float]:
    """
    对多局游戏的效率指标求平均，用于 benchmark 汇总。

    Args:
        all_metrics: 每局的 EfficiencyMetrics
        all_rewards: 每局的总奖励（用于计算效率-得分相关性）

    Returns:
        key-value 映射，可直接用于 StrategyStats 展示
    """
    import math

    n = len(all_metrics)
    if n == 0:
        return {}

    def avg(values: list[float]) -> float:
        return sum(values) / n

    result: dict[str, float] = {
        "avg_idle_ratio": avg([m.cooker_idle_ratio for m in all_metrics]),
        "avg_expired": avg([float(m.expired_ingredients) for m in all_metrics]),
        "avg_clear_asm": avg([float(m.clear_assembly_count) for m in all_metrics]),
        "avg_stockpile_in": avg([float(m.stockpile_inserts) for m in all_metrics]),
        "avg_stockpile_out": avg([float(m.stockpile_pulls) for m in all_metrics]),
        "avg_stockpile_max": avg([float(m.stockpile_max_occupancy) for m in all_metrics]),
        "avg_serve_gap": avg([m.avg_serve_interval for m in all_metrics]),
        "avg_none_ratio": avg([m.none_ratio for m in all_metrics]),
    }

    # 各灶台平均空闲时间
    if all_metrics and all_metrics[0].cooker_idle_time:
        for name in all_metrics[0].cooker_idle_time:
            idle_values = [m.cooker_idle_time.get(name, 0.0) for m in all_metrics]
            result[f"avg_idle_{name}"] = avg(idle_values)

    # 得分与空闲率的相关性（高相关性说明空闲率是关键瓶颈）
    if len(all_metrics) >= 3:
        idle_ratios = [m.cooker_idle_ratio for m in all_metrics]
        rewards = all_rewards
        r = _pearson_r(idle_ratios, rewards)
        result["corr_idle_reward"] = round(r, 3)

    return result


def _pearson_r(x: list[float], y: list[float]) -> float:
    """皮尔逊相关系数（简化版）"""
    n = len(x)
    if n < 3:
        return 0.0
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    num = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    den_x = sum((xi - mean_x) ** 2 for xi in x) ** 0.5
    den_y = sum((yi - mean_y) ** 2 for yi in y) ** 0.5
    if den_x < 1e-10 or den_y < 1e-10:
        return 0.0
    return num / (den_x * den_y)
