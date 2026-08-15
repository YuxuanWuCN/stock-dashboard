# -*- coding: utf-8 -*-
"""tests for tools/prediction_accuracy_harness.py

覆盖：正常输入（手算可验证）、边界（数据不足）、缺失数据（None/NaN）、
失败路径（文件缺失/损坏/长度不一致）、无未来函数结构检查。
"""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import prediction_accuracy_harness as pa  # noqa: E402


def make_data(closes, volumes=None, dates=None):
    """构造 load_kline 之后的格式（closes/volumes 已展开）。"""
    n = len(closes)
    if volumes is None:
        volumes = [1e6] * n
    if dates is None:
        dates = [f"2025-01-{i + 1:02d}" for i in range(n)]
    return {"code": "TST", "name": "测试股", "dates": dates, "closes": closes,
            "volumes": volumes, "ma": {}}


def make_raw(closes, volumes=None):
    """构造 kline 文件原始格式（供 load_kline 测试）。"""
    n = len(closes)
    if volumes is None:
        volumes = [1e6] * n
    kline = [[c, c, c, c] for c in closes]
    return {"code": "TST", "name": "测试股",
            "dates": [f"2025-01-{i + 1:02d}" for i in range(n)],
            "kline": kline, "volume": volumes, "ma": {}}


class TestLoadKline(unittest.TestCase):
    def test_missing_file_returns_none(self):
        self.assertIsNone(pa.load_kline(Path("不存在.json")))

    def test_length_mismatch_returns_none(self):
        d = make_raw([10.0, 11.0])
        d["volume"] = [1e6]  # 长度不一致
        import json
        import tempfile
        import os
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                        encoding="utf-8") as f:
            json.dump(d, f)
            p = f.name
        try:
            self.assertIsNone(pa.load_kline(Path(p)))
        finally:
            os.unlink(p)

    def test_malformed_json_returns_none(self):
        import tempfile
        import os
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                        encoding="utf-8") as f:
            f.write("{bad json")
            p = f.name
        try:
            self.assertIsNone(pa.load_kline(Path(p)))
        finally:
            os.unlink(p)


class TestComputeFeaturesNoLookahead(unittest.TestCase):
    def test_features_only_use_past(self):
        """未来数据变化不得影响 t 时刻的特征（无未来函数）。"""
        closes = [10.0 + i * 0.1 for i in range(100)]
        d1 = make_data(closes)
        d2 = make_data(closes[:80] + [99.0, 0.5, 99.0] + closes[83:])
        f1 = pa.compute_features(d1)
        f2 = pa.compute_features(d2)
        # t=70 处特征应完全一致（只用 <=70 的数据）
        for name in f1:
            self.assertTrue(
                math.isclose(f1[name][70], f2[name][70], rel_tol=1e-9, abs_tol=1e-12)
                or (math.isnan(f1[name][70]) and math.isnan(f2[name][70])),
                f"特征 {name} 在 t=70 受未来数据影响",
            )


class TestEvaluateStock(unittest.TestCase):
    def test_strictly_increasing_always_up_100(self):
        """手算可验证：连续上涨 100 天 -> 所有看涨信号与 always_up 均 100%。"""
        closes = [10.0 + i * 0.2 for i in range(130)]
        d = make_data(closes)
        r = pa.evaluate_stock(d, horizons=(1, 3, 5), max_lag=60)
        for h in (1, 3, 5):
            cell = r[f"baseline_always_up__h{h}"]
            self.assertEqual(cell["accuracy"], 1.0, f"h{h} always_up 应为 100%")
            self.assertGreater(cell["n"], 50)
            self.assertEqual(r[f"baseline_always_down__h{h}"]["accuracy"], 0.0)
        for sig in ("mom5", "mom10", "mom20"):
            cell = r[f"{sig}__h1"]
            self.assertIsNotNone(cell["accuracy"])
            self.assertGreaterEqual(cell["accuracy"], 0.99)

    def test_perfect_alternation_reversal_h1_100(self):
        """手算可验证：隔日涨跌交替 -> 反转信号 h=1 应为 100%，动量应为 0%。"""
        closes = []
        v = 10.0
        for i in range(130):
            closes.append(v)
            v += 0.5 if i % 2 == 0 else -0.5
        d = make_data(closes)
        r = pa.evaluate_stock(d, horizons=(1,), max_lag=60)
        self.assertIsNotNone(r["ret1_reversal__h1"]["accuracy"])
        self.assertGreaterEqual(r["ret1_reversal__h1"]["accuracy"], 0.98)
        self.assertLessEqual(r["ret1__h1"]["accuracy"], 0.02)

    def test_boundary_too_short(self):
        """边界：数据不足 -> 不崩溃，样本为 0，准确率为 None。"""
        closes = [10.0 + i * 0.1 for i in range(30)]  # < max_lag+horizon+5
        d = make_data(closes)
        r = pa.evaluate_stock(d, horizons=(1, 3, 5), max_lag=60)
        for h in (1, 3, 5):
            self.assertEqual(r[f"mom5__h{h}"]["n"], 0)
            self.assertIsNone(r[f"mom5__h{h}"]["accuracy"])

    def test_missing_values_skipped_gracefully(self):
        """缺失数据：ma 全 None、volume 含 None -> 不崩溃。"""
        closes = [10.0 + i * 0.1 for i in range(130)]
        d = make_data(closes, volumes=[None if i % 7 == 0 else 1e6
                                       for i in range(130)])
        d["ma"] = {"ma5": [None] * 130, "ma10": [None] * 130,
                   "ma20": [None] * 130, "ma60": [None] * 130}
        r = pa.evaluate_stock(d, horizons=(1, 3, 5), max_lag=60)
        # ma 类信号应无样本，动量类正常
        for h in (1, 3, 5):
            self.assertEqual(r[f"ma_ratio5__h{h}"]["n"], 0)
            self.assertGreater(r[f"mom5__h{h}"]["n"], 0)


class TestSelectiveAndCrossSectional(unittest.TestCase):
    def test_selective_threshold_direction(self):
        """阈值越高样本越少（单调），且方向正确。"""
        closes = [10.0 + i * 0.2 for i in range(130)]
        d = make_data(closes)
        r = pa.evaluate_selective_stock(d, horizons=(3,), max_lag=60)
        n_low = r["sel_mom5_th5bp__h3"]["n"]
        n_high = r["sel_mom5_th30bp__h3"]["n"]
        self.assertGreater(n_low, n_high)
        self.assertGreater(n_high, 0)
        self.assertGreaterEqual(r["sel_mom5_th30bp__h3"]["accuracy"], 0.99)

    def test_cross_sectional_hit_rate_bounds(self):
        """hit rate 必须在 [0,1]，且样本数与天数一致。"""
        import tempfile
        import os
        import json
        with tempfile.TemporaryDirectory() as td:
            kdir = Path(td)
            for i in range(12):
                closes = [10.0 + j * (0.1 + 0.01 * i) for j in range(130)]
                vols = [1e6 + ((j + i) % 5) * 1e5 for j in range(130)]
                kdir.joinpath(f"S{i:03d}.json").write_text(
                    json.dumps(make_raw(closes, volumes=vols)), encoding="utf-8")
            res = pa.run_cross_sectional_all(kdir, max_lag=60)
            # ma 类信号在夹具中无 ma 数据 -> 无样本(不崩溃)；其余应有样本
            for key, cell in res["pooled"].items():
                if key.startswith(("cs_ma_ratio20_", "cs_cross_5_20_")):
                    self.assertIsNone(cell["hit_rate"], key)
                    continue
                self.assertIsNotNone(cell["hit_rate"], key)
                self.assertGreaterEqual(cell["hit_rate"], 0.0, key)
                self.assertLessEqual(cell["hit_rate"], 1.0, key)
                self.assertGreater(cell["n"], 0, key)
                self.assertGreater(cell["days"], 0, key)


if __name__ == "__main__":
    unittest.main()
