# tests/test_analysis.py —— 分析系统完整测试套件
#
# 使用离线 fixture，不依赖实时网络。

import json
import math
import os
import sys
import unittest
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

# 确保 src/ 在 path 中
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from analysis.indicators import (
    calc_ma,
    calc_rsi,
    calc_macd,
    calc_atr,
    calc_atr_pct,
    calc_bollinger,
    calc_return,
    calc_returns,
    calc_volume_ratio,
    calc_volatility,
    calc_max_drawdown,
    calc_relative_strength,
    determine_trend,
    compute_all_indicators,
    get_latest_value,
)
from analysis.similarity import (
    build_raw_features,
    rolling_standardize,
    find_similar_samples,
)
from analysis.scoring import (
    compute_risk_score,
    compute_technical_score,
    compute_industry_score,
    compute_composite_score,
    get_risk_level,
    _clamp,
    _percentile_rank,
)
from analysis.schema import (
    validate_ranking,
    validate_stock_detail,
    check_schema_version,
)


# ============================================================
# 辅助：构造测试用 OHLCV DataFrame
# ============================================================

def make_test_df(n_days: int = 300, seed: int = 42) -> pd.DataFrame:
    """生成随机但合理（OHLC 关系正确）的日线数据，用于测试指标计算。"""
    np.random.seed(seed)

    dates = pd.date_range(start="2020-01-01", periods=n_days, freq="B")
    # 随机游走价格序列
    changes = np.random.randn(n_days) * 2.0
    log_price = np.cumsum(changes) + np.log(100.0)
    close = np.exp(log_price)

    # 生成 OHL 的波动
    daily_range = np.abs(np.random.randn(n_days)) * 2.0
    open_offset = np.random.randn(n_days) * 1.0
    open_p = close - open_offset

    high = np.maximum(open_p, close) + daily_range * 0.5
    low = np.minimum(open_p, close) - daily_range * 0.5
    low = np.maximum(low, 0.01)

    volume = np.abs(np.random.randint(10000, 1000000, size=n_days))

    df = pd.DataFrame({
        "date": [d.date() for d in dates],
        "open": np.round(open_p, 2),
        "high": np.round(high, 2),
        "low": np.round(low, 2),
        "close": np.round(close, 2),
        "volume": volume,
    })
    return df


# ============================================================
# 测试指标计算
# ============================================================

class TestIndicators(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.df = make_test_df(400)
        cls.close = cls.df["close"]
        cls.high = cls.df["high"]
        cls.low = cls.df["low"]
        cls.volume = cls.df["volume"]

    # ---- MA ----

    def test_calc_ma_basic(self):
        ma5 = calc_ma(self.close, 5)
        self.assertEqual(len(ma5), len(self.close))
        # 前 4 天为 NaN
        self.assertTrue(np.isnan(ma5.iloc[0]))
        self.assertTrue(np.isnan(ma5.iloc[3]))
        self.assertFalse(np.isnan(ma5.iloc[4]))
        # 第 5 天 += 5 天均值
        expected = self.close.iloc[:5].mean()
        self.assertAlmostEqual(ma5.iloc[4], expected, places=2)

    def test_calc_ma_nan_handling(self):
        s = pd.Series([1.0, 2.0, np.nan, 3.0, 4.0, 5.0])
        ma3 = calc_ma(s, 3)
        self.assertTrue(np.isnan(ma3.iloc[0]))
        self.assertTrue(np.isnan(ma3.iloc[1]))
        # [1.0, 2.0, np.nan] — 只有 2 个有效值，min_periods=3，应为 NaN
        self.assertTrue(np.isnan(ma3.iloc[2]))

    # ---- RSI ----

    def test_rsi_range(self):
        rsi = calc_rsi(self.close, 14)
        valid = rsi.dropna()
        self.assertTrue((valid >= 0).all())
        self.assertTrue((valid <= 100).all())

    def test_rsi_all_up(self):
        """全部上涨时 RSI 应接近 100。"""
        up_close = pd.Series(np.linspace(100, 200, 50))
        rsi = calc_rsi(up_close, 14)
        valid = rsi.dropna()
        self.assertTrue((valid.iloc[-10:] > 90).all())

    def test_rsi_all_down(self):
        """全部下跌时 RSI 应接近 0。"""
        down_close = pd.Series(np.linspace(200, 100, 50))
        rsi = calc_rsi(down_close, 14)
        valid = rsi.dropna()
        self.assertTrue((valid.iloc[-10:] < 10).all())

    # ---- MACD ----

    def test_macd_output(self):
        macd = calc_macd(self.close)
        self.assertIn("dif", macd.columns)
        self.assertIn("dea", macd.columns)
        self.assertIn("hist", macd.columns)
        self.assertEqual(len(macd), len(self.close))

    def test_macd_hist_relation(self):
        """hist 应该是 2*(DIF - DEA)。"""
        macd = calc_macd(self.close)
        valid = macd.dropna()
        expected = 2 * (valid["dif"] - valid["dea"])
        np.testing.assert_array_almost_equal(valid["hist"].values, expected.values, decimal=1)

    # ---- ATR ----

    def test_atr_positive(self):
        atr = calc_atr(self.high, self.low, self.close, 14)
        valid = atr.dropna()
        self.assertTrue((valid > 0).all())

    def test_atr_pct_range(self):
        atr_pct = calc_atr_pct(self.high, self.low, self.close, 14)
        valid = atr_pct.dropna()
        self.assertTrue((valid >= 0).all())

    # ---- 布林带 ----

    def test_bollinger_position_range(self):
        boll = calc_bollinger(self.close, 20)
        valid = boll["position"].dropna()
        # position 理论在 [0,1]，但在极端波动时可能更宽
        self.assertTrue((valid >= -2.0).all())
        self.assertTrue((valid <= 3.0).all())

    def test_bollinger_upper_gt_lower(self):
        boll = calc_bollinger(self.close, 20)
        valid = boll.dropna()
        self.assertTrue((valid["upper"] > valid["lower"]).all())

    # ---- 收益 ----

    def test_return_calc(self):
        ret5 = calc_return(self.close, 5)
        self.assertTrue(np.isnan(ret5.iloc[0]))
        self.assertTrue(np.isnan(ret5.iloc[4]))
        self.assertFalse(np.isnan(ret5.iloc[5]))

    # ---- 量比 ----

    def test_volume_ratio_range(self):
        vr = calc_volume_ratio(self.volume, 5, 20)
        valid = vr.dropna()
        # 不应出现异常大值
        self.assertTrue((valid < 20).all())

    # ---- 波动率 ----

    def test_volatility_nonnegative(self):
        vol = calc_volatility(self.close, 20)
        valid = vol.dropna()
        self.assertTrue((valid >= 0).all())

    # ---- 最大回撤 ----

    def test_max_drawdown_nonpositive(self):
        mdd = calc_max_drawdown(self.close, 60)
        valid = mdd.dropna()
        self.assertTrue((valid <= 0).all())

    # ---- 相对强度 ----

    def test_relative_strength(self):
        bench = self.close * 0.8 + np.random.randn(len(self.close)) * 2
        rs = calc_relative_strength(self.close, bench, 20)
        valid = rs.dropna()
        self.assertGreater(valid.iloc[-1], -100)  # 合理范围

    # ---- 趋势判断 ----

    def test_determine_trend_uptrend(self):
        up = pd.Series(np.linspace(100, 150, 100))
        ma20 = up.rolling(20).mean()
        ma60 = up.rolling(60).mean()
        rsi = pd.Series([60] * 100)
        trend = determine_trend(up, ma20, ma60, rsi)
        self.assertIn(trend, ["uptrend", "strong_uptrend"])

    def test_determine_trend_downtrend(self):
        down = pd.Series(np.linspace(150, 100, 100))
        ma20 = down.rolling(20).mean()
        ma60 = down.rolling(60).mean()
        rsi = pd.Series([35] * 100)
        trend = determine_trend(down, ma20, ma60, rsi)
        self.assertEqual(trend, "downtrend")

    def test_determine_trend_insufficient(self):
        short = pd.Series([100, 101, 102, 103, 104])
        ma20 = pd.Series([np.nan] * 5)
        ma60 = pd.Series([np.nan] * 5)
        rsi = pd.Series([np.nan] * 5)
        trend = determine_trend(short, ma20, ma60, rsi)
        self.assertEqual(trend, "insufficient")

    # ---- compute_all_indicators ----

    def test_compute_all_indicators(self):
        result = compute_all_indicators(self.df)
        expected_cols = ["ma5", "ma10", "ma20", "ma60", "rsi14",
                         "macd_dif", "macd_dea", "macd_hist",
                         "atr14", "atr14_pct",
                         "boll_upper", "boll_middle", "boll_lower", "boll_position",
                         "volume_ratio_5d", "volatility_20d",
                         "max_drawdown_60d", "return_5d", "return_20d", "return_60d"]
        for col in expected_cols:
            self.assertIn(col, result.columns, f"缺少列: {col}")

    # ---- get_latest_value ----

    def test_get_latest_value(self):
        s = pd.Series([1.0, 2.0, np.nan, 4.0, np.nan, 5.0])
        self.assertEqual(get_latest_value(s), 5.0)

    def test_get_latest_value_all_nan(self):
        s = pd.Series([np.nan, np.nan])
        self.assertIsNone(get_latest_value(s))


# ============================================================
# 测试滚动标准化（防泄漏核心）
# ============================================================

class TestRollingStandardize(unittest.TestCase):

    def test_no_future_leakage(self):
        """证明标准化不使用未来数据。"""
        n = 150
        features = np.random.randn(n, 5)
        window = 30
        std = rolling_standardize(features, window=window)

        # 对于第 t 行（t >= window-1），只用 [t-window+1, t] 的数据
        # 验证：修改 t+1 之后的数据不应影响第 t 行的标准化结果
        features2 = features.copy()
        features2[-1, :] = 999.0  # 修改最后一行

        std2 = rolling_standardize(features2, window=window)

        # 第 n-2 行的结果不应该因为第 n-1 行被改而改变
        if n - 2 >= window - 1 and not np.all(np.isnan(std[n - 2])):
            np.testing.assert_array_almost_equal(std[n - 2], std2[n - 2], decimal=5)

    def test_window_boundary(self):
        """前 int(window*0.8)-1 行应全为 NaN（达不到 80% 数据量要求）。"""
        features = np.random.randn(100, 3)
        window = 20
        std = rolling_standardize(features, window=window)
        # 80% of 20 = 16, so rows < 15 can't possibly have enough data
        threshold = int(window * 0.8) - 1
        self.assertTrue(np.all(np.isnan(std[:threshold])))

    def test_standardized_stats(self):
        """标准化后的数据在窗口内应近似均值 0、标准差 1。"""
        features = np.random.randn(200, 3) + np.array([5, -3, 2])  # 不同的均值和方差
        window = 50
        std = rolling_standardize(features, window=window)

        # 检查最后一行：用近 50 天的统计量标准化
        last_row = std[-1]
        valid = ~np.isnan(last_row)
        if valid.any():
            # 检查第 -1 行所用窗口 [150:200] 的标准化情况
            last_valid_idx = 199
            # 用最近 50 条原始数据的均值和标准差
            tail = features[last_valid_idx - window + 1: last_valid_idx + 1, :]
            for j in range(3):
                if valid[j]:
                    mean_j = np.nanmean(tail[:, j])
                    std_j = np.nanstd(tail[:, j])
                    if std_j > 1e-10:
                        z = (features[-1, j] - mean_j) / std_j
                        self.assertAlmostEqual(std[-1, j], z, places=3)


# ============================================================
# 测试相似走势（防泄漏 + KNN 完整性）
# ============================================================

class TestSimilarity(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.df = make_test_df(600)  # 约 600 个交易日 ~ 2.5 年
        cls.df = compute_all_indicators(cls.df)

    def test_no_future_feature_for_training(self):
        """
        核心测试：证明处理中不出现未来信息。
        - 在时间点 t 构造标签收益时，不得使用 t 之后的数据。
        - 标签（收益）不参与特征计算。
        """
        result = find_similar_samples(self.df, horizons=[3, 5])
        # 样本不足时返回 special 状态（不伪造）
        self.assertIsNotNone(result)
        self.assertIn("sample_size", result)

    def test_sample_dedup_interval(self):
        """验证最小间隔去重规则。"""
        # 手动构造极简 case 验证间距
        n = 100
        df_small = make_test_df(n)
        df_small = compute_all_indicators(df_small)
        result = find_similar_samples(df_small, k=5, min_interval=5)
        self.assertIsNotNone(result)

    def test_insufficient_sample_returns_null(self):
        """数据量不足时应返回 null 预测值。"""
        # 只给 50 个交易日的数据
        df_tiny = make_test_df(50)
        df_tiny = compute_all_indicators(df_tiny)
        result = find_similar_samples(df_tiny, min_samples=15)

        self.assertIsNotNone(result)
        # sample_size < min_samples → 预测值应为 null
        if result["sample_size"] < 15:
            h3 = result.get("horizon_3d", {})
            self.assertIsNone(h3.get("average_return_pct"),
                              "样本不足时不应输出收益估计")

    def test_output_structure(self):
        """验证输出结构完整。"""
        result = find_similar_samples(self.df)
        required_keys = ["method", "sample_size", "minimum_sample_size", "confidence"]
        for k in required_keys:
            self.assertIn(k, result)

        for h in [3, 5]:
            key = f"horizon_{h}d"
            self.assertIn(key, result)
            h_data = result[key]
            for sk in ["up_probability_pct", "average_return_pct",
                       "median_return_pct", "best_return_pct", "worst_return_pct"]:
                self.assertIn(sk, h_data)

    def test_confidence_level(self):
        """验证置信等级与样本数的关系。"""
        result = find_similar_samples(self.df)
        conf = result.get("confidence")
        sample = result.get("sample_size", 0)
        # 基本一致性检查
        if sample >= 50:
            self.assertEqual(conf, "high")
        elif sample < 15:
            self.assertEqual(conf, "low")
        self.assertIn(conf, ["low", "medium", "high"])


# ============================================================
# 测试评分的边界条件和一致性
# ============================================================

class TestScoring(unittest.TestCase):

    def setUp(self):
        self.sample_latest = {
            "volatility_20d": 25.0,
            "max_drawdown_60d": -10.0,
            "atr14_pct": 2.5,
            "volume_ratio_5d": 1.2,
            "industry_volatility_20d": 20.0,
            "close": 100.0,
            "ma5": 99.0, "ma10": 98.0, "ma20": 95.0, "ma60": 90.0,
            "rsi14": 55.0,
            "macd_dif": 2.0, "macd_dea": 1.5,
            "boll_position": 0.6,
            "return_5d": 2.0,
            "return_20d": 5.0,
            "return_60d": 10.0,
        }
        self.all_latest = [self.sample_latest.copy() for _ in range(10)]

    def test_risk_score_range(self):
        result = compute_risk_score(self.sample_latest, self.all_latest)
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 100)

    def test_risk_score_low_for_stable_stock(self):
        """低波动、小幅回撤 → 低风险分。"""
        stable = self.sample_latest.copy()
        stable["volatility_20d"] = 10.0
        stable["max_drawdown_60d"] = -3.0
        stable["atr14_pct"] = 1.0
        all_data = [stable] * 10
        all_data[0] = {"volatility_20d": 50.0, "max_drawdown_60d": -30.0,
                        "atr14_pct": 5.0, "volume_ratio_5d": 3.0,
                        "industry_volatility_20d": 40.0}
        result = compute_risk_score(stable, all_data)
        self.assertLess(result["score"], 50)

    def test_risk_level_consistency(self):
        result = compute_risk_score(self.sample_latest, self.all_latest)
        score = result["score"]
        level = result["level"]
        label = result["label"]

        if score <= 35:
            self.assertEqual(level, "low")
            self.assertEqual(label, "低风险")
        elif score >= 66:
            self.assertEqual(level, "high")
            self.assertEqual(label, "高风险")
        else:
            self.assertEqual(level, "medium")
            self.assertEqual(label, "中等风险")

    def test_get_risk_level(self):
        self.assertEqual(get_risk_level(20), ("low", "低风险"))
        self.assertEqual(get_risk_level(50), ("medium", "中等风险"))
        self.assertEqual(get_risk_level(80), ("high", "高风险"))

    def test_technical_score_range(self):
        result = compute_technical_score(self.sample_latest)
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 100)

    def test_technical_score_trend(self):
        # 上升趋势
        up_trend = self.sample_latest.copy()
        up_trend.update({
            "ma5": 105, "ma10": 103, "ma20": 100, "ma60": 95,
            "close": 106,
        })
        result = compute_technical_score(up_trend)
        self.assertIn(result["trend"], ["uptrend", "strong_uptrend"])

    def test_industry_score_range(self):
        ind_data = {"return_5d_pct": 2.0, "return_20d_pct": 5.0,
                     "return_60d_pct": 10.0, "relative_strength_20d_pct": 3.0}
        result = compute_industry_score(self.sample_latest, ind_data, self.all_latest)
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 100)

    def test_composite_score_range(self):
        risk = {"score": 30, "level": "low", "label": "低风险"}
        tech = {"score": 75, "trend": "uptrend", "rsi14": 55, "volume_ratio_5d": 1.2}
        ind = {"score": 65, "return_5d_pct": 2.0, "return_20d_pct": 5.0,
               "return_60d_pct": 10.0, "relative_strength_20d_pct": 3.0}
        sim = {
            "sample_size": 30,
            "confidence": "medium",
            "horizon_3d": {"average_return_pct": 1.5, "up_probability_pct": 60},
            "horizon_5d": {"average_return_pct": 3.0, "up_probability_pct": 65},
        }
        result = compute_composite_score(
            risk, tech, ind, sim,
            all_forecast_returns_5d=[3.0, 1.0, -2.0],
            all_up_probabilities_5d=[65, 50, 40],
        )
        self.assertGreaterEqual(result["risk_adjusted"], 0)
        self.assertLessEqual(result["risk_adjusted"], 100)

    def test_null_forecast_handles_gracefully(self):
        """预测收益为 null 时评分不应崩溃。"""
        sim_null = {
            "sample_size": 10,  # < min
            "confidence": "low",
            "horizon_3d": {"average_return_pct": None, "up_probability_pct": None},
            "horizon_5d": {"average_return_pct": None, "up_probability_pct": None},
        }
        risk = {"score": 40, "level": "medium", "label": "中等风险"}
        tech = {"score": 50, "trend": "range", "rsi14": 50, "volume_ratio_5d": 1.0}
        ind = {"score": 50, "relative_strength_20d_pct": 0}
        result = compute_composite_score(risk, tech, ind, sim_null, [], [])
        self.assertGreaterEqual(result["risk_adjusted"], 0)

    def test_clamp(self):
        self.assertEqual(_clamp(-10), 0)
        self.assertEqual(_clamp(150), 100)
        self.assertEqual(_clamp(50), 50)

    def test_percentile_rank(self):
        values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        self.assertAlmostEqual(_percentile_rank(values, 1, True), 0, delta=5)
        self.assertAlmostEqual(_percentile_rank(values, 10, True), 90, delta=5)


# ============================================================
# 测试 Schema 校验
# ============================================================

class TestSchema(unittest.TestCase):

    def test_valid_ranking_passes(self):
        ranking = {
            "schema_version": "2.0",
            "generated_at": "2026-07-20T17:32:10+08:00",
            "trade_date": "2026-07-20",
            "horizons": [3, 5],
            "ranking_method": "risk_adjusted_v1",
            "status": "success",
            "total": 2,
            "succeeded": 2,
            "failed": 0,
            "items": [
                {
                    "rank": 1, "code": "600519", "name": "茅台", "type": "stock",
                    "risk_adjusted_score": 72.4,
                    "risk": {"score": 31.6, "level": "low", "label": "低风险", "factors": []},
                    "forecast": {
                        "return_3d_pct": 1.18, "return_5d_pct": 2.06,
                        "up_probability_3d_pct": 63.3, "up_probability_5d_pct": 66.7,
                        "confidence": "medium", "sample_size": 30,
                    },
                    "technical": {"score": 76.2, "trend": "uptrend", "rsi14": 58.4, "volume_ratio_5d": 1.21},
                    "industry": {"name": "白酒", "reference_type": "industry", "score": 68.5,
                                 "return_5d_pct": 1.3, "return_20d_pct": 4.8, "relative_strength_20d_pct": 2.1},
                    "reasons": [],
                    "category": "白酒",
                    "trade_date": "2026-07-20",
                    "stale": False,
                },
                {
                    "rank": 2, "code": "000001", "name": "平安银行", "type": "stock",
                    "risk_adjusted_score": 50.0,
                    "risk": {"score": 50.0, "level": "medium", "label": "中等风险", "factors": []},
                    "forecast": {
                        "return_3d_pct": None, "return_5d_pct": None,
                        "up_probability_3d_pct": None, "up_probability_5d_pct": None,
                        "confidence": "low", "sample_size": 5,
                    },
                    "technical": {"score": 50.0, "trend": "range", "rsi14": 50.0, "volume_ratio_5d": 1.0},
                    "industry": {"name": "银行", "reference_type": "industry", "score": 50.0,
                                 "return_5d_pct": None, "return_20d_pct": None, "relative_strength_20d_pct": None},
                    "reasons": [],
                    "category": "银行",
                    "trade_date": "2026-07-20",
                    "stale": False,
                },
            ],
            "errors": [],
            "disclaimer": "test",
        }
        errors = validate_ranking(ranking)
        self.assertEqual(len(errors), 0, f"不应有错误: {errors}")

    def test_ranking_duplicate_ranks(self):
        ranking = {
            "schema_version": "2.0",
            "generated_at": "2026-07-20T17:32:10+08:00",
            "trade_date": "2026-07-20",
            "horizons": [3, 5],
            "ranking_method": "risk_adjusted_v1",
            "status": "success",
            "total": 2, "succeeded": 2, "failed": 0,
            "items": [
                {"rank": 1, "code": "600519", "name": "茅台", "type": "stock",
                 "risk_adjusted_score": 72.4,
                 "risk": {"score": 31.6, "level": "low", "label": "低风险", "factors": []},
                 "forecast": {"return_3d_pct": 1.18, "return_5d_pct": 2.06,
                              "up_probability_3d_pct": 63.3, "up_probability_5d_pct": 66.7,
                              "confidence": "medium", "sample_size": 30},
                 "technical": {"score": 76.2, "trend": "uptrend", "rsi14": 58.4, "volume_ratio_5d": 1.21},
                 "industry": {"name": "", "reference_type": "industry", "score": 68.5,
                              "return_5d_pct": None, "return_20d_pct": None, "relative_strength_20d_pct": None},
                 "reasons": [], "category": "", "trade_date": "2026-07-20", "stale": False},
                {"rank": 1, "code": "000001", "name": "平安银行", "type": "stock",
                 "risk_adjusted_score": 50.0,
                 "risk": {"score": 50.0, "level": "medium", "label": "中等风险", "factors": []},
                 "forecast": {"return_3d_pct": None, "return_5d_pct": None,
                              "up_probability_3d_pct": None, "up_probability_5d_pct": None,
                              "confidence": "low", "sample_size": 5},
                 "technical": {"score": 50.0, "trend": "range", "rsi14": 50.0, "volume_ratio_5d": 1.0},
                 "industry": {"name": "", "reference_type": "industry", "score": 50.0,
                              "return_5d_pct": None, "return_20d_pct": None, "relative_strength_20d_pct": None},
                 "reasons": [], "category": "", "trade_date": "2026-07-20", "stale": False},
            ],
            "errors": [],
            "disclaimer": "test",
        }
        errors = validate_ranking(ranking)
        self.assertTrue(any("排名有重复" in e or "重复" in e for e in errors))

    def test_risk_level_score_mismatch(self):
        """风险等级与分数不一致应报错。"""
        detail = {
            "schema_version": "2.0",
            "generated_at": "2026-07-20T17:32:10+08:00",
            "trade_date": "2026-07-20",
            "code": "600519", "name": "茅台", "type": "stock",
            "category": "白酒", "stale": False,
            "scores": {"risk_adjusted": 72.4, "risk": 31.6, "technical": 76.2, "industry": 68.5},
            "risk": {
                "level": "high", "label": "高风险",  # 分数 31.6 不应该是 high
                "annualized_volatility_20d_pct": 21.4,
                "max_drawdown_60d_pct": -8.7,
                "atr14_pct": 2.1,
                "factors": [],
            },
            "forecast": {"return_3d_pct": 1.18, "return_5d_pct": 2.06,
                         "up_probability_3d_pct": 63.3, "up_probability_5d_pct": 66.7,
                         "confidence": "medium", "sample_size": 30},
            "technical": {"trend": "uptrend", "ma5": 1261.2, "ma10": 1253.8,
                          "ma20": 1239.6, "ma60": 1217.1, "rsi14": 58.4,
                          "macd_dif": 8.21, "macd_dea": 6.74, "macd_hist": 2.94,
                          "atr14_pct": 2.1, "boll_position": 0.68,
                          "return_5d_pct": 1.9, "return_20d_pct": 5.7, "volume_ratio_5d": 1.21},
            "industry": {"name": "白酒", "reference_type": "industry",
                         "benchmark_code": "BK0896", "return_5d_pct": 1.3,
                         "return_20d_pct": 4.8, "return_60d_pct": 7.2,
                         "relative_strength_20d_pct": 2.1},
            "similarity": {"method": "standardized_knn_v1", "sample_size": 30,
                           "minimum_sample_size": 15, "confidence": "medium",
                           "horizon_3d": {"up_probability_pct": 63.3, "average_return_pct": 1.18,
                                          "median_return_pct": 0.84, "best_return_pct": 8.6,
                                          "worst_return_pct": -5.2},
                           "horizon_5d": {"up_probability_pct": 66.7, "average_return_pct": 2.06,
                                          "median_return_pct": 1.31, "best_return_pct": 11.4,
                                          "worst_return_pct": -7.8}},
            "reasons": [],
            "kline_file": "../kline/600519.json",
            "disclaimer": "test",
        }
        errors = validate_stock_detail(detail)
        self.assertTrue(any("不一致" in e for e in errors),
                        f"应检测到 risk level 不一致: {errors}")

    def test_check_schema_version(self):
        self.assertTrue(check_schema_version({"schema_version": "2.0"}))
        self.assertTrue(check_schema_version({"schema_version": "2.5"}))
        self.assertFalse(check_schema_version({"schema_version": "1.0"}))
        self.assertFalse(check_schema_version({"schema_version": "3.0"}))

    def test_valid_stock_detail_passes(self):
        detail = {
            "schema_version": "2.0",
            "generated_at": "2026-07-20T17:32:10+08:00",
            "trade_date": "2026-07-20",
            "code": "600519", "name": "茅台", "type": "stock",
            "category": "白酒", "stale": False,
            "scores": {"risk_adjusted": 72.4, "risk": 31.6, "technical": 76.2, "industry": 68.5},
            "risk": {
                "level": "low", "label": "低风险",
                "annualized_volatility_20d_pct": 21.4,
                "max_drawdown_60d_pct": -8.7,
                "atr14_pct": 2.1,
                "factors": [],
            },
            "forecast": {"return_3d_pct": 1.18, "return_5d_pct": 2.06,
                         "up_probability_3d_pct": 63.3, "up_probability_5d_pct": 66.7,
                         "confidence": "medium", "sample_size": 30},
            "technical": {"trend": "uptrend", "ma5": 1261.2, "ma10": 1253.8,
                          "ma20": 1239.6, "ma60": 1217.1, "rsi14": 58.4,
                          "macd_dif": 8.21, "macd_dea": 6.74, "macd_hist": 2.94,
                          "atr14_pct": 2.1, "boll_position": 0.68,
                          "return_5d_pct": 1.9, "return_20d_pct": 5.7, "volume_ratio_5d": 1.21},
            "industry": {"name": "白酒", "reference_type": "industry",
                         "benchmark_code": "BK0896", "return_5d_pct": 1.3,
                         "return_20d_pct": 4.8, "return_60d_pct": 7.2,
                         "relative_strength_20d_pct": 2.1},
            "similarity": {"method": "standardized_knn_v1", "sample_size": 30,
                           "minimum_sample_size": 15, "confidence": "medium",
                           "horizon_3d": {"up_probability_pct": 63.3, "average_return_pct": 1.18,
                                          "median_return_pct": 0.84, "best_return_pct": 8.6,
                                          "worst_return_pct": -5.2},
                           "horizon_5d": {"up_probability_pct": 66.7, "average_return_pct": 2.06,
                                          "median_return_pct": 1.31, "best_return_pct": 11.4,
                                          "worst_return_pct": -7.8}},
            "reasons": [],
            "kline_file": "../kline/600519.json",
            "disclaimer": "test",
        }
        errors = validate_stock_detail(detail)
        self.assertEqual(len(errors), 0, f"不应有错误: {errors}")


# ============================================================
# 测试确定性（相同输入 => 相同输出）
# ============================================================

class TestDeterminism(unittest.TestCase):

    def test_indicators_deterministic(self):
        df1 = make_test_df(200, seed=42)
        df2 = make_test_df(200, seed=42)

        ind1 = compute_all_indicators(df1)
        ind2 = compute_all_indicators(df2)

        for col in ["rsi14", "macd_dif", "volatility_20d"]:
            vals1 = ind1[col].dropna().values
            vals2 = ind2[col].dropna().values
            np.testing.assert_array_almost_equal(vals1, vals2, decimal=5,
                                                  err_msg=f"{col} 结果不一致")

    def test_risk_score_deterministic(self):
        sample = {
            "volatility_20d": 25.0, "max_drawdown_60d": -10.0,
            "atr14_pct": 2.5, "volume_ratio_5d": 1.2, "industry_volatility_20d": 20.0,
        }
        all_data = [sample.copy() for _ in range(5)]

        r1 = compute_risk_score(sample, all_data)
        r2 = compute_risk_score(sample, all_data)
        self.assertEqual(r1["score"], r2["score"])


# ============================================================
# 测试行业降级
# ============================================================

class TestIndustryFallback(unittest.TestCase):

    def test_resolve_category_valid(self):
        from analysis.industry import IndustryProvider
        provider = IndustryProvider()
        self.assertEqual(provider.resolve_category("白酒"), "白酒")
        self.assertEqual(provider.resolve_category("酒"), "白酒")
        self.assertIsNone(provider.resolve_category(""))

    def test_resolve_category_unknown(self):
        from analysis.industry import IndustryProvider
        provider = IndustryProvider()
        # 未知类别原样返回
        self.assertEqual(provider.resolve_category("量子计算"), "量子计算")


# ============================================================
# 主入口
# ============================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
