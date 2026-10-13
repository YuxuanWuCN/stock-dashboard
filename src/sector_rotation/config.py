# -*- coding: utf-8 -*-
"""src/sector_rotation/config.py —— 板块轮动系统全局配置与行业标的字典

定义核心板块标的池、基准指数映射、量化阈值与风控参数。
对齐 SECTOR_ROTATION_SPEC 与 SCNU-RAG 真实板块研报元数据。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class SectorConfig:
    """板块配置元数据契约"""
    sector_id: str
    name: str
    tickers: Tuple[str, ...]
    benchmark: str
    description: str = ""


# ============================================================================
# 1. 核心三大板块定义（绿色电力新能源、存储芯片、黄金地缘避险）
# ============================================================================

SECTORS: Dict[str, SectorConfig] = {
    "green": SectorConfig(
        sector_id="green",
        name="新能源",
        tickers=(
            "001258",  # 立新能源 (新疆绿电消纳龙头)
            "002459",  # 晶澳科技 (光伏组件与海外出海)
            "002466",  # 天齐锂业 (锂电上游与资源保供)
            "601012",  # 隆基绿能 (硅片组件与BC技术创新)
            "600438",  # 通威股份 (高纯晶硅与电池制造)
            "300750",  # 宁德时代 (全球动力电池储能龙头)
        ),
        benchmark="000688",  # 科创50
        description="绿电公用事业与新能源",
    ),
    "storage": SectorConfig(
        sector_id="storage",
        name="存储芯片",
        tickers=(
            "688525",  # 佰维存储 (存储模组与先进封测)
            "688123",  # 聚辰股份 (EEPROM/SPD 芯片龙头)
            "603986",  # 兆易创新 (NOR Flash/MCU/DRAM 龙头)
            "688041",  # 海光信息 (国产算力与高端通用处理器)
            "688008",  # 澜起科技 (DDR5 内存接口芯片全球龙头)
            "002049",  # 紫光国微 (特种集成电路与智能芯片)
        ),
        benchmark="000688",  # 科创50
        description="存储芯片超级周期",
    ),
    "gold": SectorConfig(
        sector_id="gold",
        name="黄金避险",
        tickers=(
            "600547",  # 山东黄金 (黄金采选与资源储量龙头)
            "601899",  # 紫金矿业 (铜金多金属全球跨国巨头)
            "600489",  # 中金黄金 (央企黄金骨干与全产业链)
            "002155",  # 湖南黄金 (金锑双主业与战略资源)
            "000975",  # 山金国际 (高品位矿山与低现金成本)
            "600988",  # 赤峰黄金 (国际化海外矿山拓展)
            "600362",  # 江西铜业 (铜金冶炼与战略资源配置)
        ),
        benchmark="000001",  # 上证指数
        description="黄金地缘避险与大宗慢牛",
    ),
}

# 基准指数映射表
BENCHMARK_MAPPINGS: Dict[str, str] = {
    "green": "000688",
    "storage": "000688",
    "gold": "000001",
}

# 反向映射：代码 -> 板块ID
TICKER_TO_SECTOR: Dict[str, str] = {
    ticker: sector_id
    for sector_id, cfg in SECTORS.items()
    for ticker in cfg.tickers
}


# ============================================================================
# 2. 轮动量化门限与风控阈值
# ============================================================================

# 情绪下沉门限：板块得分低于此值可能触发轮动
SENTIMENT_DECLINE_THRESHOLD: float = -0.3

# 趋势确认交易日数：连续下沉天数要求
TREND_CONFIRM_DAYS: int = 3

# 候选切换目标板块最低情绪得分
MIN_TARGET_SENTIMENT: float = 0.5

# 渐进式调仓执行周期（天数）
ROTATION_EXECUTION_DAYS: int = 3

# 单次调仓日基准交易摩擦费率（0.1%）
TRANSACTION_COST_RATE: float = 0.001

# 最短持仓交易日要求（防频繁磨损）
MIN_HOLDING_DAYS: int = 5

# 单月最大轮动次数上限
MAX_ROTATION_PER_MONTH: int = 3

# 调仓完成后强制冷却期（交易日）
COOLDOWN_DAYS: int = 7

# 买入与卖出具体摩擦费率（印花税+佣金+滑点模型）
BUY_FEE_RATE: float = 0.00125    # 0.125%
SELL_FEE_RATE: float = 0.00175   # 0.175%

# 单轮调仓累计总费用风控硬顶（1.0%）
MAX_TOTAL_ROTATION_COST: float = 0.01

# 大模型决策咨询超时时间（秒）
LLM_TIMEOUT: int = 30

# 市场极端崩塌时的默认防御板块
DEFENSIVE_SECTOR: str = "gold"

# 行业预期基准成分股数（用于置信度样本覆盖率归一化）
EXPECTED_STOCKS_PER_SECTOR: int = 6

# 情绪取值边界
SENTIMENT_BOUND_MIN: float = -1.0
SENTIMENT_BOUND_MAX: float = 1.0

# 趋势标签定义
TREND_RISING: str = "rising"
TREND_STABLE: str = "stable"
TREND_DECLINING: str = "declining"

# 渐进式调仓每日权重调度序列（50% -> 30% -> 20%）
REALLOCATION_WEIGHTS: Tuple[float, float, float] = (0.50, 0.30, 0.20)


# ============================================================================
# 3. 辅助查询函数
# ============================================================================

def get_sector_config(sector: str) -> SectorConfig:
    """获取指定板块的配置对象。

    Args:
        sector: 板块标识符 ('green' | 'storage' | 'gold')

    Returns:
        SectorConfig 配置对象

    Raises:
        KeyError: 当板块未在配置中定义时抛出
    """
    if sector not in SECTORS:
        raise KeyError(f"未知的板块标识: '{sector}'，有效板块为: {list(SECTORS.keys())}")
    return SECTORS[sector]


def get_all_sector_ids() -> List[str]:
    """获取所有已注册板块标识符列表。"""
    return list(SECTORS.keys())


def get_all_tickers() -> List[str]:
    """获取全行业所有成分股代码列表（去重）。"""
    all_tickers: List[str] = []
    for cfg in SECTORS.values():
        for t in cfg.tickers:
            if t not in all_tickers:
                all_tickers.append(t)
    return all_tickers


def get_sector_for_ticker(ticker: str) -> Optional[str]:
    """根据股票代码查找所属板块。

    Args:
        ticker: 6位股票代码

    Returns:
        板块标识符，若未命中则返回 None
    """
    return TICKER_TO_SECTOR.get(str(ticker).strip())
