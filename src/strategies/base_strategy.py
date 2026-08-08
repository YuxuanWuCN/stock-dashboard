"""策略抽象基类 —— 移植自 KHunter strategy/base_strategy.py，去除外部依赖。

策略输入约定：
- df 为升序排列（日期从旧到新）的 DataFrame，必含列：
  date, open, high, low, close, volume
- 输出信号列表，每个信号为字典，统一含 date/close/key_date/reasons。
"""

from abc import ABC, abstractmethod

import pandas as pd


class BaseStrategy(ABC):
    """选股策略抽象基类。"""

    def __init__(self, name, params=None):
        self.name = name
        self.params = params or {}

    # ----------------------------------------------------------
    # 子类可重写
    # ----------------------------------------------------------

    def quick_filter(self, df: pd.DataFrame) -> bool:
        """快速过滤：只基于价格/量，不做复杂指标计算。返回 False 则直接淘汰。"""
        return True

    @abstractmethod
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算策略所需指标，返回添加指标列的 DataFrame（保持升序）。"""

    @abstractmethod
    def select_stocks(self, df: pd.DataFrame, stock_name: str = "") -> list:
        """选股逻辑：df 含指标列（升序），返回信号列表。"""

    def get_selection_criteria(self) -> list:
        """选股条件描述列表（用于展示）。"""
        return []

    # ----------------------------------------------------------
    # 通用校验
    # ----------------------------------------------------------

    def _validate_data(self, df: pd.DataFrame) -> bool:
        """数据完整性校验：非空、长度充足、必要字段齐全。"""
        if df is None or df.empty:
            return False
        if len(df) < 20:
            return False
        required = {"date", "open", "high", "low", "close", "volume"}
        if not required.issubset(set(df.columns)):
            return False
        return True

    def _validate_stock_name(self, stock_name: str) -> bool:
        """过滤退市/ST 股票名称。"""
        if not stock_name:
            return True
        invalid_keywords = ["退", "未知", "退市", "已退"]
        if any(kw in stock_name for kw in invalid_keywords):
            return False
        if stock_name.startswith("ST") or stock_name.startswith("*ST"):
            return False
        return True

    # ----------------------------------------------------------
    # 标准选股流程
    # ----------------------------------------------------------

    def execute_selection(self, df: pd.DataFrame, stock_code: str = "",
                          stock_name: str = "") -> list:
        """标准选股执行流程：校验 → 快速过滤 → 指标 → 选股。"""
        if not self._validate_data(df):
            return []
        if not self._validate_stock_name(stock_name):
            return []
        if not self.quick_filter(df):
            return []
        try:
            df = self.calculate_indicators(df)
        except Exception:
            return []
        if df is None or df.empty:
            return []
        return self.select_stocks(df, stock_name)

    def analyze_stock(self, stock_code: str, stock_name: str,
                      df: pd.DataFrame):
        """分析单只股票，返回标准化结果或 None。"""
        try:
            signals = self.execute_selection(df, stock_code, stock_name)
            if signals:
                return {"code": stock_code, "name": stock_name, "signals": signals}
            return None
        except Exception:
            return None
