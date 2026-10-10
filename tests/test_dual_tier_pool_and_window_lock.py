"""双层股票池与 5 日时序因果窗口锁定机制单元测试。

验证内容：
1. 观察池读写契约（独立存储，不污染核心 watchlist.csv）
2. 5 日时序因果窗口加锁与状态检查（is_stock_locked）
3. 核心池末位淘汰时的窗口锁定豁免机制（防止提前换手导致时序预测断裂）
4. 策略买点触发晋级核心池（promote_to_core_watchlist）
"""

import os
import tempfile
import unittest
from datetime import datetime, timedelta

from tools import auto_update_watchlist_top_gainers as pool_mgr


class DualTierPoolAndWindowLockTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.watchlist_file = os.path.join(self.temp_dir, "test_watchlist.csv")
        self.observation_file = os.path.join(self.temp_dir, "test_observation.csv")
        self.lock_state_file = os.path.join(self.temp_dir, "test_lock_state.json")

    def tearDown(self):
        for f in (self.watchlist_file, self.observation_file, self.lock_state_file):
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass
        if os.path.exists(self.temp_dir):
            try:
                os.rmdir(self.temp_dir)
            except Exception:
                pass

    def test_observation_pool_read_write(self):
        items = [
            {"code": "600001", "name": "测试A", "type": "stock", "category": "热点候选", "added_date": "2026-09-29", "change_pct": 9.98, "amount": 250000000.0},
            {"code": "000002", "name": "测试B", "type": "stock", "category": "热点候选", "added_date": "2026-09-29", "change_pct": 10.01, "amount": 320000000.0},
        ]
        pool_mgr.write_observation_pool(self.observation_file, items)
        loaded = pool_mgr.read_observation_pool(self.observation_file)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0]["code"], "600001")
        self.assertEqual(loaded[1]["code"], "000002")

    def test_window_lock_state_lifecycle(self):
        today_str = datetime.now().strftime("%Y-%m-%d")
        # 1. 初始未锁定
        self.assertFalse(pool_mgr.is_stock_locked("600519", as_of_date=today_str, lock_state={}))

        # 2. 加锁 5 日
        state = {}
        now = datetime.now()
        state["600519"] = {
            "entry_date": today_str,
            "locked_until_date": (now + timedelta(days=7)).strftime("%Y-%m-%d"),
            "lock_days": 5,
        }
        pool_mgr.save_lock_state(state, self.lock_state_file)

        loaded_state = pool_mgr.read_lock_state(self.lock_state_file)
        # 3. 窗口期内处于锁定状态
        self.assertTrue(pool_mgr.is_stock_locked("600519", as_of_date=today_str, lock_state=loaded_state))

        # 4. 超过锁定期（例如 15 天后）应解锁
        future_date = (now + timedelta(days=15)).strftime("%Y-%m-%d")
        self.assertFalse(pool_mgr.is_stock_locked("600519", as_of_date=future_date, lock_state=loaded_state))

    def test_evaluate_lowest_priority_exempts_locked_stocks(self):
        """验证处于 5 日预测窗口锁定期内的标的豁免末位淘汰。"""
        current_items = [
            {"code": "000001", "name": "标的1", "type": "stock", "category": "通用"},
            {"code": "000002", "name": "锁定标的", "type": "stock", "category": "策略晋级"},
            {"code": "000003", "name": "标的3", "type": "stock", "category": "通用"},
            {"code": "510300", "name": "沪深300ETF", "type": "etf", "category": "指数"},
        ]
        today_str = datetime.now().strftime("%Y-%m-%d")
        state = {
            "000002": {
                "entry_date": today_str,
                "locked_until_date": (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d"),
                "lock_days": 5,
            }
        }
        pool_mgr.save_lock_state(state, pool_mgr.WATCHLIST_LOCK_STATE_PATH)

        # 淘汰 1 只，000002 处于锁定期，510300 为 ETF，只能淘汰 000001 或 000003
        to_remove = pool_mgr.evaluate_lowest_priority_stocks(current_items, count_to_remove=1, as_of_date=today_str)
        self.assertNotIn("000002", to_remove)
        self.assertNotIn("510300", to_remove)
        self.assertTrue("000001" in to_remove or "000003" in to_remove)

    def test_promote_to_core_watchlist_adds_and_locks(self):
        """验证观察池黑马标的策略买点触发晋级，并自动施加 5 日时序锁。"""
        pool_mgr.write_watchlist(self.watchlist_file, [
            {"code": "600519", "name": "贵州茅台", "type": "stock", "category": "消费"}
        ])
        pool_mgr.write_observation_pool(self.observation_file, [
            {"code": "688525", "name": "佰维存储", "type": "stock", "category": "热点候选", "amount": 500000000.0}
        ])

        promoted = pool_mgr.promote_to_core_watchlist(
            codes=["688525"],
            watchlist_path=self.watchlist_file,
            observation_path=self.observation_file,
            max_size=10,
            lock_days=5,
        )
        self.assertEqual(promoted, 1)

        core_list = pool_mgr.read_current_watchlist(self.watchlist_file)
        self.assertEqual(len(core_list), 2)
        codes = [it["code"] for it in core_list]
        self.assertIn("688525", codes)
        self.assertTrue(pool_mgr.is_stock_locked("688525"))


if __name__ == "__main__":
    unittest.main()
