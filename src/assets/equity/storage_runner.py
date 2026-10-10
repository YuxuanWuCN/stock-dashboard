# src/assets/equity/storage_runner.py
"""
Rainbow-FinGPT v4.0 A股权益赛道 —— 存储芯片超级周期与高景气资产回测运行适配器
A-Share Equity Domain: Storage Supercycle & 202-Stock High-Prosperity Portfolio Runner.
"""

from typing import Dict, List, Optional, Any
from pathlib import Path
import json

from src.analysis.storage_backtest_runner import StorageBacktestRunner


class EquityStorageRunnerAdapter:
    """
    A 股权益赛道标准执行器适配层
    负责接入 202 只 A 股全域股票池与存储超级周期 / 黄金杠铃策略。
    """
    
    def __init__(self, raw_data_dir: Optional[Path] = None):
        self.runner = StorageBacktestRunner(raw_data_dir=raw_data_dir)

    def get_core_storage_universe(self) -> List[str]:
        """获取存储核心标的池"""
        return list(self.runner.STORAGE_TICKERS)

    def load_latest_metrics(self) -> Dict[str, Any]:
        """获取最新回测净值与多维评估指标"""
        metrics_file = Path("docs/data/quantitative/backtest_storage_2025q2_2026q7.json")
        if metrics_file.exists():
            try:
                with open(metrics_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "strategy_name": "Storage Supercycle Strategy",
            "benchmark": "CSI300",
            "tickers": self.runner.STORAGE_TICKERS,
            "status": "ready"
        }

    def execute_backtest(self) -> Dict[str, Any]:
        """执行全流程回测"""
        return self.runner.run()
