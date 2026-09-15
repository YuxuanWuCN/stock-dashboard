# -*- coding: utf-8 -*-
"""src/features/csmar_features.py - CSMAR因子库特征提取器

从CSMAR数据库提取P1基本面和P3动量特征
"""

from __future__ import annotations

import logging
from typing import Dict, Optional
import numpy as np
import pandas as pd

logger = logging.getLogger("csmar_features")


class CSMARFeatureExtractor:
    """基于CSMAR因子库的特征提取器"""
    
    def __init__(self, csmar_api):
        """
        参数:
            csmar_api: CSMAR API客户端实例
        """
        self.api = csmar_api
        self._cache = {}  # 简单缓存，避免重复请求
    
    def extract_p1_fundamental(self, ticker: str, date: str) -> float:
        """提取P1: 基本面稳健性得分
        
        指标组合:
        1. ROE (净资产收益率) - 盈利能力
        2. 资产负债率 - 财务稳健性
        3. 经营现金流/净利润 - 现金质量
        
        参数:
            ticker: 股票代码 (如 "000001.SZ")
            date: 日期 (如 "2026-08-01")
        
        返回:
            float: P1得分，范围 [-1.0, 1.0]
        """
        try:
            # 1. 获取ROE (使用最近一期财报)
            roe = self._get_financial_ratio(ticker, date, "roe")
            
            # 2. 获取资产负债率
            debt_ratio = self._get_financial_ratio(ticker, date, "debt_asset_ratio")
            
            # 3. 获取现金流质量 (经营现金流/净利润)
            cfo_ni = self._get_cashflow_quality(ticker, date)
            
            # 归一化到[-1, 1]
            p1_score = self._normalize_fundamental(roe, debt_ratio, cfo_ni)
            
            logger.debug(f"{ticker} P1: ROE={roe:.3f}, Debt={debt_ratio:.3f}, CFO/NI={cfo_ni:.3f} -> {p1_score:.3f}")
            
            return float(np.clip(p1_score, -1.0, 1.0))
            
        except Exception as e:
            logger.warning(f"{ticker} P1提取失败: {e}")
            return 0.0  # 失败返回中性值
    
    def extract_p3_momentum(self, ticker: str, date: str) -> float:
        """提取P3: 多周期动量得分
        
        周期组合:
        1. 5日动量 (权重 0.5) - 短期
        2. 20日动量 (权重 0.3) - 中期
        3. 60日动量 (权重 0.2) - 长期
        
        成交量确认: 放量上涨才算有效动量
        
        参数:
            ticker: 股票代码
            date: 日期
        
        返回:
            float: P3得分，范围 [-1.0, 1.0]
        """
        try:
            # 获取多周期收益率
            ret_5d = self._get_return(ticker, date, window=5)
            ret_20d = self._get_return(ticker, date, window=20)
            ret_60d = self._get_return(ticker, date, window=60)
            
            # 获取成交量比率 (5日成交量 / 20日平均成交量)
            vol_ratio = self._get_volume_ratio(ticker, date, window=5)
            
            # 加权组合
            momentum_raw = (
                0.5 * ret_5d +
                0.3 * ret_20d +
                0.2 * ret_60d
            )
            
            # 成交量确认 (vol_ratio > 1.0 表示放量)
            vol_factor = min(vol_ratio, 2.0) / 2.0  # clip到[0, 1]
            
            p3_score = momentum_raw * (0.5 + 0.5 * vol_factor)
            
            logger.debug(f"{ticker} P3: R5d={ret_5d:.3f}, R20d={ret_20d:.3f}, R60d={ret_60d:.3f}, Vol={vol_ratio:.2f} -> {p3_score:.3f}")
            
            return float(np.clip(p3_score, -1.0, 1.0))
            
        except Exception as e:
            logger.warning(f"{ticker} P3提取失败: {e}")
            return 0.0
    
    # ========== 内部辅助方法 ==========
    
    def _get_financial_ratio(self, ticker: str, date: str, ratio_name: str) -> float:
        """从CSMAR获取财务比率
        
        你需要根据实际CSMAR API替换这里的实现
        """
        cache_key = f"{ticker}_{date}_{ratio_name}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        # TODO: 替换为实际CSMAR API调用
        # 示例：
        # value = self.api.get_financial_indicator(
        #     stock_code=ticker,
        #     end_date=date,
        #     indicator=ratio_name
        # )
        
        # 临时mock（实际使用时删除）
        if ratio_name == "roe":
            value = 0.15  # 假设ROE=15%
        elif ratio_name == "debt_asset_ratio":
            value = 0.45  # 假设负债率=45%
        else:
            value = 0.0
        
        self._cache[cache_key] = value
        return value
    
    def _get_cashflow_quality(self, ticker: str, date: str) -> float:
        """获取现金流质量 (经营现金流/净利润)"""
        cache_key = f"{ticker}_{date}_cfo_ni"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        # TODO: 替换为实际CSMAR API调用
        # cfo = self.api.get_cashflow(ticker, date, "operating_cashflow")
        # ni = self.api.get_income(ticker, date, "net_income")
        # ratio = cfo / ni if ni != 0 else 1.0
        
        ratio = 1.2  # 临时mock
        
        self._cache[cache_key] = ratio
        return ratio
    
    def _get_return(self, ticker: str, date: str, window: int) -> float:
        """获取N日收益率"""
        cache_key = f"{ticker}_{date}_ret{window}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        # TODO: 替换为实际CSMAR API调用
        # ret = self.api.get_stock_return(ticker, date, window=window)
        
        ret = 0.05  # 临时mock: 5%收益率
        
        self._cache[cache_key] = ret
        return ret
    
    def _get_volume_ratio(self, ticker: str, date: str, window: int) -> float:
        """获取成交量比率 (近N日平均成交量 / 过去20日平均成交量)"""
        cache_key = f"{ticker}_{date}_vol{window}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        # TODO: 替换为实际CSMAR API调用
        # vol_recent = self.api.get_avg_volume(ticker, date, window=window)
        # vol_baseline = self.api.get_avg_volume(ticker, date, window=20)
        # ratio = vol_recent / vol_baseline if vol_baseline > 0 else 1.0
        
        ratio = 1.3  # 临时mock: 放量30%
        
        self._cache[cache_key] = ratio
        return ratio
    
    def _normalize_fundamental(self, roe: float, debt_ratio: float, cfo_ni: float) -> float:
        """归一化基本面指标到[-1, 1]
        
        规则:
        - ROE越高越好 (>20%优秀, <5%差)
        - 负债率越低越好 (<30%优秀, >70%差)
        - 现金流质量越高越好 (>1.2优秀, <0.8差)
        """
        # ROE得分 (假设合理范围5%-20%)
        roe_score = (roe - 0.125) / 0.075  # 中心12.5%, 标准差7.5%
        roe_score = np.clip(roe_score, -1.0, 1.0)
        
        # 负债率得分 (假设合理范围30%-70%)
        debt_score = -(debt_ratio - 0.5) / 0.2  # 50%为中性, 越高越差
        debt_score = np.clip(debt_score, -1.0, 1.0)
        
        # 现金流质量得分 (假设合理范围0.8-1.5)
        cfo_score = (cfo_ni - 1.15) / 0.35  # 中心1.15, 标准差0.35
        cfo_score = np.clip(cfo_score, -1.0, 1.0)
        
        # 加权组合 (ROE权重最大)
        fundamental_score = (
            0.5 * roe_score +
            0.3 * debt_score +
            0.2 * cfo_score
        )
        
        return fundamental_score


# ========== 单元测试 ==========
if __name__ == "__main__":
    # 简单测试
    class MockCSMAR:
        """Mock CSMAR API用于测试"""
        pass
    
    extractor = CSMARFeatureExtractor(MockCSMAR())
    
    # 测试P1
    p1 = extractor.extract_p1_fundamental("000001.SZ", "2026-08-01")
    print(f"P1基本面得分: {p1:.3f}")
    assert -1.0 <= p1 <= 1.0, "P1超出范围"
    
    # 测试P3
    p3 = extractor.extract_p3_momentum("000001.SZ", "2026-08-01")
    print(f"P3动量得分: {p3:.3f}")
    assert -1.0 <= p3 <= 1.0, "P3超出范围"
    
    print("✅ CSMAR特征提取器测试通过")
