"""
基准统计函数单测（Issue #15）

- t 分布 CDF / 双侧 p 值：用 df=9 的已知分位点验证
  （t=1.833 ↔ p≈0.10，t=2.262 ↔ p≈0.05，t=3.250 ↔ p≈0.01）
- 配对检验：固定差值序列（零方差）、已知数据集的数量级断言
- 统一口径：compute_stats 的 score 字段与 CSV final_score 列一致
- MetricsCollector：首帧灶台空闲时间计入
"""

import math
import unittest
from types import SimpleNamespace

from playground.bench.stats import (
    DEGENERATE_P_FLOOR,
    paired_comparison,
    paired_t_test,
    t_cdf,
    t_ppf,
    t_two_sided_p,
)


class TestStudentTDistribution(unittest.TestCase):
    """t 分布概率函数（lgamma + betacf 实现）对照标准 t 分位数表"""

    def test_two_sided_p_at_known_df9_quantiles(self):
        # df=9 的双侧临界值：10% / 5% / 1%
        for t_crit, p_target in [(1.833, 0.10), (2.262, 0.05), (3.250, 0.01)]:
            p = t_two_sided_p(t_crit, 9)
            self.assertAlmostEqual(p, p_target, delta=5e-4)

    def test_two_sided_p_symmetric_and_bounds(self):
        self.assertEqual(t_two_sided_p(0.0, 9), 1.0)
        self.assertAlmostEqual(
            t_two_sided_p(1.5, 9), t_two_sided_p(-1.5, 9), places=12
        )
        self.assertLess(t_two_sided_p(10.0, 9), 1e-5)
        self.assertGreater(t_two_sided_p(10.0, 9), 0.0)

    def test_cdf_center_symmetry_monotone(self):
        self.assertEqual(t_cdf(0.0, 9), 0.5)
        self.assertAlmostEqual(t_cdf(1.5, 9) + t_cdf(-1.5, 9), 1.0, places=9)
        self.assertGreater(t_cdf(2.0, 9), t_cdf(1.0, 9))

    def test_ppf_matches_t_table(self):
        # t_{0.975}：df=4→2.776，df=9→2.262，df=29→2.045
        self.assertAlmostEqual(t_ppf(0.975, 4), 2.776, delta=1e-3)
        self.assertAlmostEqual(t_ppf(0.975, 9), 2.262, delta=1e-3)
        self.assertAlmostEqual(t_ppf(0.975, 29), 2.045, delta=1e-3)

    def test_ppf_inverts_cdf(self):
        for df in (4, 9, 29):
            t = t_ppf(0.975, df)
            self.assertAlmostEqual(t_cdf(t, df), 0.975, places=6)


class TestPairedComparison(unittest.TestCase):
    """配对 t 检验 + 效应量"""

    def test_known_dataset_magnitudes(self):
        # 差值 1..10（n=10, df=9）：mean=5.5, 样本 std=3.0277
        # t = 5.5/(3.0277/sqrt(10)) ≈ 5.7446；p ≈ 2.8e-4（介于 1e-4 与 1e-3）
        # 95% CI = 5.5 ± 2.262*0.9574 ≈ [3.33, 7.67]；Cohen's d ≈ 1.817
        a = [float(x) for x in range(1, 11)]
        ps = paired_comparison(a, [0.0] * 10)

        self.assertEqual(ps.n, 10)
        self.assertEqual(ps.df, 9)
        self.assertAlmostEqual(ps.mean_diff, 5.5, places=9)
        self.assertAlmostEqual(ps.t_stat, 5.7446, places=3)
        self.assertGreaterEqual(ps.p_value, 1e-4)
        self.assertLessEqual(ps.p_value, 1e-3)
        self.assertAlmostEqual(ps.cohen_d, 1.8166, places=3)
        self.assertAlmostEqual(ps.ci_low, 3.334, places=2)
        self.assertAlmostEqual(ps.ci_high, 7.666, places=2)
        self.assertLess(ps.ci_low, ps.mean_diff)
        self.assertGreater(ps.ci_high, ps.mean_diff)
        self.assertIsNone(ps.degenerate)

    def test_fixed_difference_zero_variance(self):
        # d_std == 0 且 d_mean != 0：p 取 1e-12 下限并标注，不硬编码 0.0
        a = [float(x) + 2.0 for x in range(10)]
        b = [float(x) for x in range(10)]
        ps = paired_comparison(a, b)

        self.assertEqual(ps.degenerate, "zero-variance")
        self.assertEqual(ps.p_value, DEGENERATE_P_FLOOR)
        self.assertNotEqual(ps.p_value, 0.0)
        self.assertEqual(ps.mean_diff, 2.0)
        self.assertEqual(math.isinf(ps.t_stat), True)

    def test_identical_sequences(self):
        a = [3.0, 4.0, 5.0, 6.0]
        ps = paired_comparison(a, list(a))

        self.assertEqual(ps.degenerate, "identical")
        self.assertEqual(ps.p_value, 1.0)
        self.assertEqual(ps.mean_diff, 0.0)
        self.assertEqual(ps.cohen_d, 0.0)
        self.assertEqual(ps.ci_low, 0.0)
        self.assertEqual(ps.ci_high, 0.0)

    def test_short_or_mismatched_inputs_return_none(self):
        self.assertIsNone(paired_comparison([1.0], [1.0]))
        self.assertIsNone(paired_comparison([1.0, 2.0], [1.0]))

    def test_paired_t_test_wrapper_matches(self):
        a = [float(x) for x in range(1, 11)]
        t, p = paired_t_test(a, [0.0] * 10)
        ps = paired_comparison(a, [0.0] * 10)
        self.assertEqual(t, ps.t_stat)
        self.assertEqual(p, ps.p_value)

        # 旧接口的退化行为不再出现：identical 序列 p=1.0 而非 0.0
        t, p = paired_t_test([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
        self.assertEqual((t, p), (0.0, 1.0))


class TestUnifiedScoreCaliber(unittest.TestCase):
    """表格/检验与 CSV 统一使用 final_score 口径"""

    def _episode_result(self, total_reward: float, total_visibility: float):
        from playground.core.episode import EpisodeResult

        return EpisodeResult(
            total_reward=total_reward,
            steps=10,
            actions_taken=5,
            orders_served=1,
            orders_timeout=0,
            final_time=90.0,
            seed=1,
            strategy_name="s",
            total_visibility=total_visibility,
        )

    def test_compute_stats_score_matches_final_score(self):
        from playground.bench.compare import compute_stats

        results = [self._episode_result(100.0, 12.0), self._episode_result(120.0, 8.0)]
        stats = compute_stats(results)
        # final_score = reward + visibility，与 CSV final_score 列一致
        self.assertAlmostEqual(stats.avg_score, (112.0 + 128.0) / 2, places=9)
        self.assertAlmostEqual(stats.max_score, 128.0)
        self.assertAlmostEqual(stats.min_score, 112.0)
        # 旧口径字段保留（reward 均值）
        self.assertAlmostEqual(stats.avg_reward, 110.0, places=9)


class TestMetricsCollectorFirstFrameIdle(unittest.TestCase):
    """Issue #15：首帧灶台空闲时间必须计入"""

    def _make_obs(self, time: float, busy: bool):
        return SimpleNamespace(
            time=time,
            cookers={
                "c1": SimpleNamespace(busy=busy, done_at=None),
            },
            stockpile={},
            game_duration=90.0,
        )

    def test_first_interval_counted_as_idle(self):
        from playground.bench.metric import MetricsCollector

        collector = MetricsCollector(total_cookers=1, total_stockpile_slots=1)
        obs = self._make_obs(time=2.0, busy=False)
        collector.update(obs, None, SimpleNamespace(info={}))

        # 修复前：首帧先遍历空的 _cooker_idle_time 再初始化，2.0 秒空闲被漏计
        self.assertAlmostEqual(collector._cooker_idle_time["c1"], 2.0, places=9)


if __name__ == "__main__":
    unittest.main()
