"""
PlannerStrategy: deadline 感知的滚动时域调度策略（Issue #21）

与 GastronomeStrategy 的单动作贪心瀑布互补：每个决策周期先跑反应式安全层
（语义与 gastronome 顶层一致，独立实现，GastronomeStrategy 类零改动），
再对当前活跃订单（≤4）枚举完成顺序（排列 ≤24），对每个排列在纯 Python
世界模型（dict/Counter，不复用 GameSimulator）上做确定性前向仿真：

- 资源约束：食材按 recipe 的 ingredient-cooker 绑定开火；灶台占用串行
  （占用者需 store/过期 clear 让位）；组装站一次一单；玩家动作串行
  （每动作 0.3s，与模拟器 action_delay=0.3 同口径）；serve 落地后 1.5s
  serve 禁令窗口（期间可烹饪/移动/调味）
- 约束检查：食材落地 5s 过期窗口（含 0.5s 落地安全余量）、订单 deadline
  （`Order.timeout_at` 为局内相对秒数，#17 后与 state.time 同基；
  serve 落地需在 min(deadline, game_duration-0.3) 前 + 0.45s 余量）、
  is_in_animation_window 期间 serve 推迟、环境 target_recipe_slug 锁定规则
  镜像（变体配方共享食材对时按首个入空站食材的 slot 序推定并切换服务对象）
- 评分：Σ 完成订单 (base+vis)×加成（按订单生成时锁定的 spawned_at_visibility
  区间查 RecipeRewardLookup）× 早送餐贴现 exp(-λΔt)（vis 同贴现：早送高 vis
  单早跨阈值）− deadline 违约损失 − 清空当前组装站的滞回罚
- 执行：输出最优排列的首个原子动作；下周期滚动重规划

预烹饪 / 库存缓存等规划层不好表达的部分回退到 gastronome 同型启发式
（见 experiments/planner_strategy/design.md 第 5 节）。

输入: UnifiedState（只读；recipes 直读 state.recipes）
输出: core/actions.py 现有 Action 类型 | None

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

from __future__ import annotations

import itertools
import math
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from loguru import logger

from hawarma.core.actions import (
    Action,
    AddCondimentAction,
    ClearAssemblyAction,
    ClearCookerAction,
    CookAction,
    MoveToAssemblyAction,
    MoveToStockpileAction,
    PullFromStockpileAction,
    ServeOrderAction,
)
from hawarma.core.state import UnifiedState
from hawarma.agent.strategy import Strategy

if TYPE_CHECKING:
    from hawarma.core.reward import RecipeRewardLookup


@dataclass
class _OrderPlan:
    """单个活跃订单的规划静态信息（每个 decide() 重建一次）"""

    order_id: int
    slot_idx: int
    slug: str
    is_rush: bool
    deadline: float
    """有效截止 = min(timeout_at, game_duration - 0.3)，serve 落地需在此之前"""
    spawned_vis: float
    pairs: frozenset[tuple[str, str]]
    """(ingredient, cooker_type) 全集"""
    pair_list: tuple[tuple[str, str, float], ...]
    """按配方顺序的 (ing, cooker, duration)，确定性遍历用"""
    condiments: dict[str, int] = field(default_factory=dict)
    unit: float = 0.0
    """(base_with_cond + vis_with_cond) × multiplier(spawned_vis, is_rush)"""
    vis: float = 0.0
    """visibility_with_cond（planner 总是补齐调料）"""


class PlannerStrategy(Strategy):
    """deadline 感知的滚动时域调度：排列枚举 + 确定性前向仿真"""

    # ── 时间口径（沿用 gastronome 的 0.3s，与模拟器 action_delay=0.3 一致）──
    MOVE_TIME = 0.3
    CONDIMENT_TIME = 0.3
    SERVE_TIME = 0.3
    COOKER_RETENTION = 5.0

    # 落地安全余量：决策瞬间 → swipe 落地之间存在尾段延迟（同 gastronome）
    MOVE_SAFETY_MARGIN = 0.5
    # serve 落地相对 deadline 的保守余量（覆盖模拟器每步额外 0.1s tick 粒度）
    SERVE_DEADLINE_MARGIN = 0.45
    # 当前动画窗口剩余时长的保守估计（窗口起点不可观测）
    ANIMATION_WINDOW_EST = 1.5
    # serve 落地后的 slot 位移动画（serve 禁令窗口，期间可做其他动作但禁 serve）
    SERVE_BAN_WINDOW = 1.5

    # ── 评分参数（可调；见 experiments/planner_strategy/design.md）──
    TIME_DISCOUNT = 0.01
    """早送餐贴现率 λ：早送 → 场上空 → 新单早刷新"""
    LOSS_PENALTY_FACTOR = 1.0
    """deadline 违约罚 = 因子 × unit score（按超时损失计）"""
    ASSEMBLY_CLEAR_PENALTY = 30.0
    """滚动重规划滞回：需要清空当前非空组装站的排列的额外罚，防清-装抖动
    （量级 >> 贴现噪声、<< 单均分值 ~150-300，只翻转近似同分的排列选择）"""

    # ── 空闲回退（gastronome 同型启发式）──
    # planner 的前向仿真已按 min(timeout, game_duration) 钳制处理终局可行性，
    # 空闲回退只需保持忙碌到最后一轮可落地的烹饪：≈ min_cook + 组装 + serve
    PRECOOK_STOP_TIME = 5.0
    MAX_PRECOOK_STOCKPILE = 4
    MIN_PRECOOK_DURATION = 1.0

    # 仿真循环保护上限（动作 + 等待推进次数）
    MAX_ORDER_STEPS = 40
    MAX_TRACE_LEN = 96

    def __init__(self, reward_lookup: RecipeRewardLookup | None = None):
        """可注入共享 RecipeRewardLookup；未注入时 on_game_start 自建（同 gastronome）"""
        self._reward_lookup = reward_lookup

    def on_game_start(self, recipes: dict) -> None:
        """构建得分查表（未注入时自建；策略数据每次 decide 直读 state.recipes）"""
        if self._reward_lookup is None:
            from hawarma.core.reward import RecipeRewardLookup
            self._reward_lookup = RecipeRewardLookup()

    # ====================================================================
    # 主决策：反应式安全层 → 规划层 → 空闲回退
    # ====================================================================

    def decide(self, state: UnifiedState) -> Action | None:
        """serve → clear_expired → condiment（反应式）→ 排列规划 → 空闲回退"""
        if self._reward_lookup is None:
            # on_game_start 未被调用（decide 早于游戏开始）：显式报错（同 gastronome）
            raise RuntimeError(
                "PlannerStrategy._reward_lookup not initialized: "
                "call on_game_start() (or inject reward_lookup) before decide()"
            )
        # 1. 反应式安全层（正确性关键，规划无收益）
        if action := self._reactive_serve(state):
            return action
        if action := self._reactive_clear_expired(state):
            return action
        if action := self._reactive_condiment(state):
            return action

        # 2. 规划层：排列枚举 + 前向仿真
        plans = self._build_plans(state)
        if plans:
            action = self._plan_best_action(state, plans)
            if action is not None:
                return action

        # 3. 空闲回退（gastronome 同型：入库保护 + 预烹饪）
        return self._idle_action(state, plans)

    # ====================================================================
    # 反应式安全层
    # ====================================================================

    def _reactive_serve(self, state: UnifiedState) -> ServeOrderAction | None:
        """组装站齐料齐调料即送餐（动画窗口内禁 serve）；同配方多单选 unit 最高"""
        if state.is_in_animation_window:
            return None
        asm = state.assembly
        if not asm.ingredients_cookers:
            return None
        target_slug = asm.target_recipe_slug
        best_unit, best_idx = None, None
        for idx, order in enumerate(state.orders):
            if order is None or order.done:
                continue
            if target_slug and order.recipe_slug != target_slug:
                continue
            recipe = state.recipes.get(order.recipe_slug)
            if recipe is None or not self._ings_match(asm.ingredients_cookers, recipe):
                continue
            if not self._conds_complete(asm.condiments, recipe.condiments):
                continue
            unit = self._reward_lookup.get_score(
                order.recipe_slug, True, order.is_rush, order.spawned_at_visibility
            )
            if best_unit is None or unit > best_unit:
                best_unit, best_idx = unit, idx
        if best_idx is None:
            return None
        return ServeOrderAction(slot_idx=best_idx)

    def _reactive_clear_expired(self, state: UnifiedState) -> ClearCookerAction | None:
        """清第一个过期灶台（糊料卡灶是正确性问题）"""
        for cooker_name, cooker in state.cookers.items():
            if cooker.busy and cooker.is_expired(state.time):
                return ClearCookerAction(cooker=cooker_name)
        return None

    def _reactive_condiment(self, state: UnifiedState) -> AddCondimentAction | None:
        """食材齐 + 目标配方仍有活跃订单 → 补第一味缺失调料"""
        asm = state.assembly
        if not asm.ingredients_cookers:
            return None
        target_slug = asm.target_recipe_slug or self._infer_recipe_from_assembly(state)
        if target_slug is None:
            return None
        recipe = state.recipes.get(target_slug)
        if recipe is None or not self._ings_match(asm.ingredients_cookers, recipe):
            return None
        if not any(
            o and not o.done and o.recipe_slug == target_slug for o in state.orders
        ):
            return None
        for condiment, need in recipe.condiments.items():
            if asm.condiments.get(condiment, 0) < need:
                return AddCondimentAction(condiment=condiment)
        return None

    # ====================================================================
    # 规划层：排列枚举 + 前向仿真
    # ====================================================================

    def _build_plans(self, state: UnifiedState) -> list[_OrderPlan]:
        """活跃订单 → 规划信息（deadline 已过的不进排列）"""
        if self._reward_lookup is None:
            raise RuntimeError(
                "PlannerStrategy._reward_lookup not initialized: "
                "call on_game_start() (or inject reward_lookup) before decide()"
            )
        plans: list[_OrderPlan] = []
        for idx, order in enumerate(state.orders):
            if order is None or order.done:
                continue
            if order.is_expired(state.time):
                continue
            recipe = state.recipes.get(order.recipe_slug)
            if recipe is None:
                continue
            pair_list = tuple(
                (ing.name, ing.cooker_type, ing.duration) for ing in recipe.ingredients
            )
            plans.append(_OrderPlan(
                order_id=order.order_id,
                slot_idx=idx,
                slug=order.recipe_slug,
                is_rush=order.is_rush,
                deadline=min(order.timeout_at, state.game_duration - self.MOVE_TIME),
                spawned_vis=order.spawned_at_visibility,
                pairs=frozenset((n, c) for n, c, _ in pair_list),
                pair_list=pair_list,
                condiments=dict(recipe.condiments),
                unit=self._reward_lookup.get_score(
                    order.recipe_slug, True, order.is_rush, order.spawned_at_visibility
                ),
                vis=float(self._reward_lookup.get_visibility(order.recipe_slug, True)),
            ))
        plans.sort(key=lambda p: p.order_id)
        return plans

    def _build_world(self, state: UnifiedState) -> dict:
        """纯 Python 世界模型（每次 decide 一次；排列仿真时浅拷贝）"""
        cookers: dict[str, dict | None] = {}
        for name, c in state.cookers.items():
            if c.busy and c.item_name:
                done_at = c.done_at if c.done_at is not None else state.time
                cookers[name] = {
                    "ing": c.item_name,
                    "type": c.cooker_type or name,
                    "done_at": done_at,
                    "expired_at": (
                        c.expired_at if c.expired_at is not None
                        else done_at + self.COOKER_RETENTION
                    ),
                }
            else:
                cookers[name] = None
        stock: Counter = Counter()
        stock_kinds: set[tuple[str, str]] = set()
        for slot in state.stockpile.values():
            if slot.count > 0 and slot.item_name:
                pair = (slot.item_name, slot.cooker_type or "")
                stock[pair] += slot.count
                stock_kinds.add(pair)
        return {
            "cookers": cookers,
            "assembly_ings": set(state.assembly.ingredients_cookers),
            "assembly_cond": Counter(state.assembly.condiments),
            "target": state.assembly.target_recipe_slug,
            "stock": stock,
            "stock_kinds": stock_kinds,
            "n_slots": len(state.stockpile),
        }

    def _build_target_ctx(self, state: UnifiedState, plans: list[_OrderPlan]) -> dict:
        """环境侧 target_recipe_slug 设定规则的镜像（供仿真对齐真实 serve 校验）

        - move_to_assembly 首个食材入空站：先按 slot 序找含该 (name, cooker) 对的
          活跃订单，命中即锁定其配方；否则按 recipes 迭代序回退
        - pull_from_stockpile 首个食材入空站：仅按 recipes 迭代序回退
        """
        by_slot = sorted(
            ((p.slot_idx, p.slug, p.pairs) for p in plans), key=lambda x: x[0]
        )
        recipe_order = []
        for slug, recipe in state.recipes.items():
            recipe_order.append((slug, frozenset(
                (ing.name, ing.cooker_type) for ing in recipe.ingredients
            )))
        return {"by_slot": by_slot, "recipe_order": recipe_order}

    def _env_target_for_pair(
        self, pair: tuple[str, str], via_move: bool, ctx: dict
    ) -> str | None:
        if via_move:
            for _slot, slug, pairs in ctx["by_slot"]:
                if pair in pairs:
                    return slug
        for slug, pairs in ctx["recipe_order"]:
            if pair in pairs:
                return slug
        return None

    def _plan_best_action(self, state: UnifiedState, plans: list[_OrderPlan]) -> Action | None:
        """枚举排列 → 最优排列 trace 的首个可立即执行动作"""
        base_world = self._build_world(state)
        target_ctx = self._build_target_ctx(state, plans)
        t0 = state.time
        serve_gate = t0 + self.ANIMATION_WINDOW_EST if state.is_in_animation_window else 0.0

        best_score, best_trace = None, None
        for perm in itertools.permutations(plans):
            score, trace = self._simulate_perm(base_world, perm, plans, target_ctx, t0, serve_gate)
            if best_score is None or score > best_score + 1e-9:
                best_score, best_trace = score, trace

        if not best_trace:
            return None
        emit_time, act = best_trace[0]
        if emit_time > t0 + 1e-6:
            return None  # 首动作仍在未来（等待烹饪）→ 空闲回退
        return self._materialize(act, state)

    def _simulate_perm(
        self,
        base_world: dict,
        perm: tuple[_OrderPlan, ...],
        plans: list[_OrderPlan],
        target_ctx: dict,
        t0: float,
        serve_gate: float,
    ) -> tuple[float, list[tuple[float, tuple]]]:
        """确定性前向仿真一个完成顺序排列 → (评分, 动作轨迹)"""
        w = {
            "cookers": {
                k: (dict(v) if v is not None else None)
                for k, v in base_world["cookers"].items()
            },
            "assembly_ings": set(base_world["assembly_ings"]),
            "assembly_cond": Counter(base_world["assembly_cond"]),
            "target": base_world["target"],
            "stock": Counter(base_world["stock"]),
            "stock_kinds": set(base_world["stock_kinds"]),
            "n_slots": base_world["n_slots"],
            "serve_ban_until": 0.0,
        }
        player = t0
        trace: list[tuple[float, tuple]] = []
        score = 0.0
        consumed: set[int] = set()

        # 滞回罚：该排列要先清空当前非空组装站（食材对不兼容或 target 指向他配方）
        if w["assembly_ings"] and self._assembly_foreign(w, perm[0]):
            score -= self.ASSEMBLY_CLEAR_PENALTY

        for idx, info in enumerate(perm):
            if info.order_id in consumed:
                continue  # 已在本排列早前因 target 切换被实际服务
            deadline = info.deadline
            # 组装站归属：非本单配方的子集 / target 指向其他配方 → 先清（剪枝判定在清之前）
            foreign = bool(w["assembly_ings"]) and self._assembly_foreign(w, info)
            usable = set() if foreign else set(w["assembly_ings"])
            offset = self.MOVE_TIME if foreign else 0.0
            missing_list = [(n, c, d) for (n, c, d) in info.pair_list if (n, c) not in usable]

            if player + offset >= deadline:
                score -= self.LOSS_PENALTY_FACTOR * info.unit
                continue
            lb = offset + self._completion_lower_bound(w, player + offset, info, missing_list, serve_gate)
            if lb >= deadline:
                score -= self.LOSS_PENALTY_FACTOR * info.unit
                continue
            if foreign:
                trace.append((player, ("clear_asm",)))
                player += self.MOVE_TIME
                w["assembly_ings"] = set()
                w["assembly_cond"] = Counter()
                w["target"] = None

            outcome = self._run_acquire_loop(w, player, info, perm, target_ctx, trace)
            player = outcome["player"]
            served_plan = outcome.get("served_plan")
            if served_plan is not None:
                consumed.add(served_plan.order_id)
                # (unit + vis) 一体贴现：早送高 vis 单可更早跨 visibility 阈值，
                # 放大后续新单（加成按其 spawned_at_visibility 锁定）的倍率
                score += (served_plan.unit + served_plan.vis) * math.exp(
                    -self.TIME_DISCOUNT * (outcome["serve_time"] - t0)
                )
            else:
                score -= self.LOSS_PENALTY_FACTOR * info.unit

        return score, trace

    @staticmethod
    def _assembly_foreign(w: dict, info: _OrderPlan) -> bool:
        """组装站内容是否不能被 info 直接续用（食材对非子集，或 target 锁定其他配方）"""
        if not w["assembly_ings"] <= info.pairs:
            return True
        target = w["target"]
        return target is not None and target != info.slug

    def _run_acquire_loop(
        self,
        w: dict,
        player: float,
        info: _OrderPlan,
        perm: tuple[_OrderPlan, ...],
        target_ctx: dict,
        trace: list[tuple[float, tuple]],
    ) -> dict:
        """单订单取料→调料→serve 的执行器；返回 {'player', 'served_plan', 'serve_time'}

        环境的 target_recipe_slug 规则可能与排列头单不同（变体配方共享食材对时，
        首个入空站的食材按 slot 序锁定配方）。首个食材入站后按环境规则更新
        target，若指向其他活跃订单则切换当前服务对象，保证 serve 可通过
        环境的 target == order.recipe 校验。
        """
        cur = info
        deadline = cur.deadline
        pre_serve_cooks = 0
        for _ in range(self.MAX_ORDER_STEPS):
            if len(trace) >= self.MAX_TRACE_LEN:
                break
            missing_pairs = cur.pairs - w["assembly_ings"]

            if not missing_pairs:
                # 调料 → serve
                next_cond = None
                for cname, need in cur.condiments.items():
                    if w["assembly_cond"].get(cname, 0) < need:
                        next_cond = cname
                        break
                if next_cond is not None:
                    trace.append((player, ("cond", next_cond)))
                    player += self.CONDIMENT_TIME
                    w["assembly_cond"][next_cond] += 1
                    continue
                emit = max(player, w["serve_ban_until"])
                if emit + self.MOVE_TIME + self.SERVE_DEADLINE_MARGIN >= deadline:
                    break  # 违约：菜品留在组装站，下一单会清
                # serve 前先为后续订单开火（送餐仅 0.3s，但 5s 级烹饪早 0.3s
                # 启动净赚；serve 截止余量足够时才允许这次 0.3s 顺延；每次
                # serve 至多 1 次，避免多单备料把 serve 推迟过长）
                if (
                    pre_serve_cooks < 1
                    and emit + 2 * self.MOVE_TIME + self.SERVE_DEADLINE_MARGIN < deadline
                ):
                    pre_act = self._next_acquire_action(
                        w, player, cur, cur.pairs - w["assembly_ings"], perm
                    )
                    if pre_act is not None and pre_act[0] == "cook":
                        pre_serve_cooks += 1
                        player = self._apply_sim_action(w, player, pre_act, trace)
                        continue
                trace.append((emit, ("serve", cur.order_id)))
                serve_time = emit + self.SERVE_TIME
                w["assembly_ings"] = set()
                w["assembly_cond"] = Counter()
                w["target"] = None
                # serve 落地触发 slot 位移动画：1.5s serve 禁令窗口
                w["serve_ban_until"] = serve_time + self.SERVE_BAN_WINDOW
                return {
                    "player": serve_time,
                    "served_plan": cur,
                    "serve_time": serve_time,
                }

            act = self._next_acquire_action(w, player, cur, missing_pairs, perm)
            if act is not None:
                was_empty = not w["assembly_ings"]
                player = self._apply_sim_action(w, player, act, trace)
                if was_empty and act[0] in ("move", "pull"):
                    # 环境规则：首个食材入空站锁定 target_recipe_slug
                    pair = next(iter(w["assembly_ings"]))
                    w["target"] = self._env_target_for_pair(
                        pair, act[0] == "move", target_ctx
                    )
                    if w["target"] is not None and w["target"] != cur.slug:
                        switch_to = next(
                            (p for p in perm if p.slug == w["target"]), None
                        )
                        if switch_to is None:
                            break  # target 指向无活跃订单的配方：菜品不可服务，中断
                        cur = switch_to
                        deadline = cur.deadline
                continue

            # 等待：推进到最近的烹饪完成 / 食材过期事件
            nxt = None
            for occ in w["cookers"].values():
                if occ is None:
                    continue
                for evt in (occ["done_at"], occ["expired_at"]):
                    if evt > player and (nxt is None or evt < nxt):
                        nxt = evt
            if nxt is None or nxt >= deadline:
                break  # 无事件可等或等不到截止前 → 违约
            player = nxt

        return {"player": player, "served_plan": None, "serve_time": None}

    def _next_acquire_action(
        self,
        w: dict,
        player: float,
        info: _OrderPlan,
        missing_pairs: set[tuple[str, str]],
        perm: tuple[_OrderPlan, ...],
    ) -> tuple | None:
        """取料动作优先级：move(EDF) → cook/evict → pull → pipeline 预烹饪"""
        # 规则 1：移入已就绪食材（最早过期者优先）
        best_move: tuple[float, str, dict] | None = None
        for cname, occ in w["cookers"].items():
            if occ is None or (occ["ing"], occ["type"]) not in missing_pairs:
                continue
            if occ["done_at"] > player:
                continue
            if player + self.MOVE_TIME + self.MOVE_SAFETY_MARGIN >= occ["expired_at"]:
                continue  # 落地不安全
            if best_move is None or occ["expired_at"] < best_move[0]:
                best_move = (occ["expired_at"], cname, occ)
        if best_move is not None:
            return ("move", best_move[1], info.order_id)

        # 规则 2：为需新烹饪的缺失对开火（duration 降序）；绑定灶被占则让位
        need_cook = []
        for (n, c, d) in info.pair_list:
            if (n, c) not in missing_pairs:
                continue
            occ = w["cookers"].get(c)
            if occ is not None and occ["ing"] == n and occ["type"] == c:
                if occ["done_at"] > player:
                    continue  # 烹饪中，完成时及时移走（5s 窗口足够）
                if player + self.MOVE_TIME + self.MOVE_SAFETY_MARGIN < occ["expired_at"]:
                    continue  # 已完成且仍可安全移入（规则 1 处理）
                # 已完成但不再安全（临近/已过期）→ 清掉重cook（落入 need_cook）
            elif w["stock"].get((n, c), 0) > 0:
                continue  # 库存可取
            need_cook.append((n, c, d))
        need_cook.sort(key=lambda x: -x[2])
        for (n, c, d) in need_cook:
            occ = w["cookers"].get(c)
            if occ is None:
                return ("cook", n, c, d, info.order_id)
            if occ["done_at"] <= player:
                evict = self._evict_action(w, player, c, occ)
                if evict is not None:
                    return evict
                continue  # 无法让位（等过期）→ 看下一个候选
            # 占用者仍在烹饪 → 等待（落入 wait 分支）

        # 规则 3：库存取缺失食材
        for (n, c, _d) in info.pair_list:
            if (n, c) in missing_pairs and w["stock"].get((n, c), 0) > 0:
                return ("pull", n, c, info.order_id)

        # 规则 4：管道式预烹饪后续订单（绑定灶空闲 + 该单截止仍可达）。
        # 过期窗口不作为深度门控——撑不到直接使用的食材由规则 5 保护性入库
        # （store→pull 共 0.6s，库存不过期），这正是库存对 5s 窗口的扩展作用
        cur_pos = perm.index(info)
        est_use = self._estimate_finish(w, player, info, missing_pairs)
        for later in perm[cur_pos + 1:]:
            est_use += (
                self.MOVE_TIME * (len(later.pair_list) + sum(later.condiments.values()) + 1)
                + self.SERVE_BAN_WINDOW
            )
            if est_use >= later.deadline:
                continue  # 该单在此排列下已不可达，不为其备料
            cands = []
            for (n, c, d) in later.pair_list:
                if w["cookers"].get(c) is not None:
                    continue  # 绑定灶忙
                if w["stock"].get((n, c), 0) > 0:
                    continue
                if (n, c) in w["assembly_ings"]:
                    continue
                cands.append((n, c, d))
            if cands:
                cands.sort(key=lambda x: -x[2])
                n, c, d = cands[0]
                return ("cook", n, c, d, later.order_id)

        # 规则 5：保护性入库——后续订单需要、但撑不到其直接使用的 done 食材
        # （库存不过期；store+pull 共 0.6s，替代 5s 过期损失）
        est_use = self._estimate_finish(w, player, info, missing_pairs)
        for later in perm[cur_pos + 1:]:
            est_use += (
                self.MOVE_TIME * (len(later.pair_list) + sum(later.condiments.values()) + 1)
                + self.SERVE_BAN_WINDOW
            )
            for cname, occ in w["cookers"].items():
                if occ is None or occ["done_at"] > player:
                    continue
                pair = (occ["ing"], occ["type"])
                if pair in missing_pairs or pair in w["assembly_ings"]:
                    continue
                if pair not in later.pairs or w["stock"].get(pair, 0) > 0:
                    continue
                if player + self.MOVE_TIME + self.MOVE_SAFETY_MARGIN >= occ["expired_at"]:
                    continue  # 已不可安全入库
                if occ["expired_at"] - (self.MOVE_TIME + self.MOVE_SAFETY_MARGIN) >= est_use:
                    continue  # 能撑到直接使用，无需入库
                can_store = (
                    w["stock"].get(pair, 0) < 5
                    and (pair in w["stock_kinds"] or len(w["stock_kinds"]) < w["n_slots"])
                )
                if can_store:
                    return ("store", cname)

        return None  # 等待

    def _evict_action(
        self,
        w: dict,
        player: float,
        cooker_name: str,
        occ: dict,
    ) -> tuple | None:
        """绑定灶上 done 占位者的让位动作：过期 → clear；可入库 → store；否则 None（等过期）"""
        if player >= occ["expired_at"]:
            return ("clear_cooker", cooker_name)
        pair = (occ["ing"], occ["type"])
        safe = player + self.MOVE_TIME + self.MOVE_SAFETY_MARGIN < occ["expired_at"]
        can_store = (
            safe
            and w["stock"].get(pair, 0) < 5
            and (pair in w["stock_kinds"] or len(w["stock_kinds"]) < w["n_slots"])
        )
        if can_store:
            return ("store", cooker_name)
        return None

    def _apply_sim_action(
        self, w: dict, player: float, act: tuple, trace: list[tuple[float, tuple]]
    ) -> float:
        """在世界模型上应用动作，记录轨迹，返回新的 player 时刻"""
        trace.append((player, act))
        player += self.MOVE_TIME
        kind = act[0]
        if kind == "move":
            _, cname, _oid = act
            occ = w["cookers"][cname]
            w["assembly_ings"].add((occ["ing"], occ["type"]))
            w["cookers"][cname] = None
        elif kind == "cook":
            _, n, c, d, _oid = act
            done_at = player + d  # cook 落地于 player（= 发起时刻 + 0.3）
            w["cookers"][c] = {
                "ing": n, "type": c,
                "done_at": done_at,
                "expired_at": done_at + self.COOKER_RETENTION,
            }
        elif kind == "pull":
            _, n, c, _oid = act
            pair = (n, c)
            w["stock"][pair] -= 1
            if w["stock"][pair] <= 0:
                del w["stock"][pair]
                w["stock_kinds"].discard(pair)
            w["assembly_ings"].add(pair)
        elif kind == "store":
            _, cname = act
            occ = w["cookers"][cname]
            pair = (occ["ing"], occ["type"])
            w["stock"][pair] += 1
            w["stock_kinds"].add(pair)
            w["cookers"][cname] = None
        elif kind == "clear_cooker":
            _, cname = act
            w["cookers"][cname] = None
        # cond / clear_asm / serve 由调用方状态机处理（serve 清组装站在外层已做）
        return player

    def _completion_lower_bound(
        self,
        w: dict,
        t: float,
        info: _OrderPlan,
        missing_list: list[tuple[str, str, float]],
        serve_gate: float,
    ) -> float:
        """最早可完成时间下界（宁可低估不可高估，用于剪枝）"""
        max_ready = t
        n_init = 0
        for (n, c, d) in missing_list:
            occ = w["cookers"].get(c)
            if occ is not None and occ["ing"] == n and occ["type"] == c:
                ready = max(t, occ["done_at"])
            elif w["stock"].get((n, c), 0) > 0:
                ready = t
            else:
                n_init += 1
                emit = t + self.MOVE_TIME * n_init
                if occ is not None:
                    # 等占用者完成 + 让位动作后才能开火
                    emit = max(emit, occ["done_at"]) + self.MOVE_TIME
                ready = emit + self.MOVE_TIME + d
            max_ready = max(max_ready, ready)
        conds_missing = sum(
            max(0, need) for need in (
                n - w["assembly_cond"].get(cn, 0) for cn, n in info.condiments.items()
            )
        )
        lb = (
            max_ready
            + self.MOVE_TIME  # 最后一味食材入站
            + self.CONDIMENT_TIME * conds_missing
            + self.SERVE_TIME
            + self.SERVE_DEADLINE_MARGIN
        )
        if serve_gate > t:
            lb = max(lb, serve_gate + self.SERVE_TIME + self.SERVE_DEADLINE_MARGIN)
        return lb

    def _estimate_finish(
        self,
        w: dict,
        player: float,
        info: _OrderPlan,
        missing_pairs: set[tuple[str, str]],
    ) -> float:
        """当前单完成时间的粗估计（管道式预烹饪的过期可行性门控用）"""
        latest = player
        n_act = 1
        for (n, c, d) in info.pair_list:
            if (n, c) not in missing_pairs:
                continue
            occ = w["cookers"].get(c)
            if occ is not None and occ["ing"] == n and occ["type"] == c:
                ready = max(player, occ["done_at"])
            elif w["stock"].get((n, c), 0) > 0:
                ready = player + self.MOVE_TIME * n_act
            else:
                ready = player + self.MOVE_TIME * n_act + self.MOVE_TIME + d
            latest = max(latest, ready)
            n_act += 2  # 发起 + 入站
        conds_left = sum(
            max(0, need - w["assembly_cond"].get(cn, 0))
            for cn, need in info.condiments.items()
        )
        return latest + self.MOVE_TIME * (n_act + conds_left + 1)

    # ====================================================================
    # 动作落地（trace 首动作 → 真实 Action；前置条件不满足时返回 None）
    # ====================================================================

    def _materialize(self, act: tuple, state: UnifiedState) -> Action | None:
        kind = act[0]
        if kind == "cook":
            _, ing, cname, dur, oid = act
            cooker = state.cookers.get(cname)
            if cooker is None or cooker.busy:
                return None
            return CookAction(ingredient=ing, cooker=cname, duration=dur, order_id=oid)
        if kind == "move":
            _, cname, oid = act
            cooker = state.cookers.get(cname)
            if cooker is None or not cooker.busy or cooker.done_at is None:
                return None
            if state.time < cooker.done_at:
                return None
            if not self._is_arrival_safe(state.time, cooker.expired_at):
                logger.debug(
                    f"PlannerStrategy: skip move {cooker.item_name} on {cname}: "
                    f"remaining={cooker.expired_at - state.time:.2f}s < safety_margin"
                )
                return None
            return MoveToAssemblyAction(cooker=cname, order_id=oid)
        if kind == "pull":
            _, ing, ctype, _oid = act
            for slot_name, slot in state.stockpile.items():
                if slot.count > 0 and slot.item_name == ing and slot.cooker_type == ctype:
                    return PullFromStockpileAction(slot=slot_name, ingredient=ing)
            return None
        if kind == "cond":
            return AddCondimentAction(condiment=act[1])
        if kind == "serve":
            if state.is_in_animation_window:
                return None
            oid = act[1]
            for idx, order in enumerate(state.orders):
                if order is not None and not order.done and order.order_id == oid:
                    return ServeOrderAction(slot_idx=idx)
            return None
        if kind == "clear_asm":
            if not state.assembly.ingredients:
                return None
            return ClearAssemblyAction()
        if kind == "clear_cooker":
            cname = act[1]
            cooker = state.cookers.get(cname)
            if cooker is None or not cooker.busy or not cooker.is_expired(state.time):
                return None
            return ClearCookerAction(cooker=cname)
        if kind == "store":
            _, cname = act
            cooker = state.cookers.get(cname)
            if cooker is None or not cooker.busy or cooker.done_at is None:
                return None
            if state.time < cooker.done_at or not self._is_arrival_safe(
                state.time, cooker.expired_at
            ):
                return None
            slot = self._find_store_slot(state, cooker.item_name, cooker.cooker_type)
            if slot is None:
                return None
            return MoveToStockpileAction(cooker=cname, slot=slot)
        return None

    # ====================================================================
    # 空闲回退（gastronome 同型启发式：入库保护 + 预烹饪）
    # ====================================================================

    # 入库保护的风险阈值：done 食材剩余窗口低于该值时优先入库（先于预烹饪）
    STORE_RISK_WINDOW = 2.5

    def _idle_action(self, state: UnifiedState, plans: list[_OrderPlan]) -> Action | None:
        # 1a. 紧急入库：灶上 done、不被任何活跃订单需要、剩余窗口告急
        active_pairs: set[tuple[str, str]] = set()
        for p in plans:
            active_pairs |= p.pairs
        store_cands: list[tuple[float, str]] = []
        for cname, c in state.cookers.items():
            if not c.busy or c.done_at is None or state.time < c.done_at:
                continue
            if c.item_name is None or c.cooker_type is None:
                continue
            if (c.item_name, c.cooker_type) in active_pairs:
                continue
            if not self._is_arrival_safe(state.time, c.expired_at):
                continue
            if self._find_store_slot(state, c.item_name, c.cooker_type) is None:
                continue
            store_cands.append(((c.expired_at or 1e9), cname))
        store_cands.sort()
        if store_cands:
            expiry, cname = store_cands[0]
            if expiry - state.time < self.STORE_RISK_WINDOW:
                cooker = state.cookers[cname]
                slot = self._find_store_slot(state, cooker.item_name, cooker.cooker_type)
                return MoveToStockpileAction(cooker=cname, slot=slot)

        # 2. 预烹饪：剩余时间充足、有空闲灶、库存未满 → 最长 duration 优先
        if state.remaining_time < self.PRECOOK_STOP_TIME:
            return None
        free = {n for n, c in state.cookers.items() if not c.busy}
        if not free:
            return None
        total_stock = sum(s.count for s in state.stockpile.values())
        if total_stock >= self.MAX_PRECOOK_STOCKPILE:
            return None
        cooking = {
            (c.item_name, c.cooker_type)
            for c in state.cookers.values()
            if c.busy and c.item_name
        }
        in_use = cooking | set(state.assembly.ingredients_cookers) | {
            (s.item_name, s.cooker_type)
            for s in state.stockpile.values()
            if s.count > 0 and s.item_name
        }
        active_slugs = [p.slug for p in plans]
        fallback_slugs = [s for s in state.recipes if s not in active_slugs]

        def _best_candidate(slugs: list[str]) -> tuple[str, str, float] | None:
            cands: list[tuple[str, str, float]] = []
            for slug in slugs:
                recipe = state.recipes.get(slug)
                if recipe is None:
                    continue
                for ing in recipe.ingredients:
                    pair = (ing.name, ing.cooker_type)
                    if pair in in_use or ing.cooker_type not in free:
                        continue
                    if ing.duration < self.MIN_PRECOOK_DURATION:
                        continue
                    cands.append((ing.name, ing.cooker_type, ing.duration))
            if not cands:
                return None
            cands.sort(key=lambda x: -x[2])
            return cands[0]

        cand = _best_candidate(active_slugs) or _best_candidate(fallback_slugs)
        if cand is not None:
            ing, cooker, dur = cand
            oid = next(
                (p.order_id for p in plans if (ing, cooker) in p.pairs), None
            )
            return CookAction(ingredient=ing, cooker=cooker, duration=dur, order_id=oid)

        # 1b. 非紧急入库：无可预烹饪时回收 done 的多余食材
        if store_cands:
            cname = store_cands[0][1]
            cooker = state.cookers[cname]
            slot = self._find_store_slot(state, cooker.item_name, cooker.cooker_type)
            return MoveToStockpileAction(cooker=cname, slot=slot)
        return None

    # ====================================================================
    # 辅助（与 gastronome 同型，独立实现）
    # ====================================================================

    def _ings_match(self, actual: list[tuple[str, str]], recipe) -> bool:
        """组装站 (name, cooker) 集合与配方完全一致"""
        if len(actual) != len(recipe.ingredients):
            return False
        expected = {(ing.name, ing.cooker_type) for ing in recipe.ingredients}
        return set(actual) == expected

    def _conds_complete(self, applied: dict[str, int], needed: dict[str, int]) -> bool:
        for condiment, count in needed.items():
            if applied.get(condiment, 0) < count:
                return False
        return True

    def _infer_recipe_from_assembly(self, state: UnifiedState) -> str | None:
        """按 order_id 顺序找与组装站食材对精确匹配的活跃订单配方"""
        asm_pairs = set(state.assembly.ingredients_cookers)
        if not asm_pairs:
            return None
        active = [
            o for o in state.orders if o is not None and not o.done
        ]
        active.sort(key=lambda o: o.order_id)
        for order in active:
            recipe = state.recipes.get(order.recipe_slug)
            if recipe is None:
                continue
            if asm_pairs == {(ing.name, ing.cooker_type) for ing in recipe.ingredients}:
                return order.recipe_slug
        return None

    def _find_store_slot(
        self, state: UnifiedState, ingredient: str, cooker_type: str | None
    ) -> str | None:
        """可接收 (ingredient, cooker_type) 的库存槽：同类有余量优先，其次空槽"""
        for slot_name, slot in state.stockpile.items():
            if (
                slot.item_name == ingredient
                and slot.cooker_type == cooker_type
                and slot.count < 5
            ):
                return slot_name
        for slot_name, slot in state.stockpile.items():
            if slot.item_name is None or slot.count == 0:
                return slot_name
        return None

    def _is_arrival_safe(self, state_time: float, expired_at: float | None) -> bool:
        """move/store 能否在游戏内过期前落地（同 gastronome MOVE_SAFETY_MARGIN）"""
        if expired_at is None:
            return False
        return state_time + self.MOVE_TIME + self.MOVE_SAFETY_MARGIN < expired_at
