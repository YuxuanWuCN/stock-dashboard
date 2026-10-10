# -*- coding: utf-8 -*-
"""
数据模型与契约定义 (src/data/schemas.py)
----------------------------------------
定义郑商所纯碱 (SA) 与玻璃 (FG) 产业链数据管道的强类型结构、
字段约束与质量校验规则。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import pandas as pd
import numpy as np


@dataclass(frozen=True)
class FuturesMarketRecord:
    """单一交易日期货日线行情记录"""
    date: str
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    open_interest: float
    settle: float

    def validate(self) -> None:
        assert self.open > 0, f"开盘价必须大于 0: {self.open}"
        assert self.high >= self.low, f"最高价必须大于等于最低价: high={self.high}, low={self.low}"
        assert self.close > 0, f"收盘价必须大于 0: {self.close}"
        assert self.volume >= 0, f"成交量不能为负: {self.volume}"
        assert self.open_interest >= 0, f"持仓量不能为负: {self.open_interest}"


@dataclass(frozen=True)
class BasisRecord:
    """期现基差与现货记录"""
    date: str
    symbol: str
    futures_price: float
    spot_price: float
    basis: float
    basis_rate: float

    def validate(self) -> None:
        assert self.futures_price > 0, "期货价格必须大于 0"
        assert self.spot_price > 0, "现货价格必须大于 0"
        expected_basis = round(self.futures_price - self.spot_price, 4)
        assert abs(self.basis - expected_basis) < 0.01, (
            f"基差定义不满足 Futures - Spot: basis={self.basis}, expected={expected_basis}"
        )


@dataclass(frozen=True)
class OptionIVRecord:
    """期权隐含波动率与领子偏度记录"""
    date: str
    iv_atm: float
    collar_skew: float
    is_synthetic: bool = False

    def validate(self) -> None:
        assert self.iv_atm > 0, f"平值隐波必须为正: {self.iv_atm}"
        assert -1.0 <= self.collar_skew <= 1.0, f"领子偏度超出合理区间: {self.collar_skew}"


@dataclass
class AlignedFeatureRecord:
    """对齐后的产业链特征数据行契约"""
    date: str
    # 期货基础行情 - SA
    open_sa: float
    high_sa: float
    low_sa: float
    close_sa: float
    volume_sa: float
    open_interest_sa: float
    settle_sa: float
    delta_oi_sa: float
    symbol_sa: str
    # 期货基础行情 - FG
    open_fg: float
    high_fg: float
    low_fg: float
    close_fg: float
    volume_fg: float
    open_interest_fg: float
    settle_fg: float
    delta_oi_fg: float
    symbol_fg: str
    # 基差与现货
    spot_sa: float
    basis_sa: float
    basis_rate_sa: float
    spot_fg: float
    basis_fg: float
    # 收益率与多尺度波动率
    log_ret_sa: float
    log_ret_fg: float
    vol_20d_sa: float
    vol_60d_sa: float
    vol_20d_fg: float
    vol_60d_fg: float
    parkinson_vol_sa: float
    parkinson_vol_fg: float
    # 价差、比价与虚拟加工利润
    spread_fg_sa: float
    ratio_fg_sa: float
    price_ratio_fg_sa: float
    crush_spread: float
    # 动态相关性
    rolling_corr_20d: float
    rolling_corr_60d: float
    # 日内振幅极差
    sa_daily_range_pct: float
    fg_daily_range_pct: float
    # 期权特征
    iv_atm_sa: float
    collar_skew_sa: float
    # Round 1 演化新增特征 (默认值保障 dataclass 向后兼容性)
    convenience_yield_sa: float = 0.0
    roll_yield_sa: float = 0.0
    term_structure_slope_sa: float = 0.0
    chi_short_sa: float = 0.0
    xi_long_sa: float = 0.0
    tsmom_sa: float = 0.0
    basis_convergence_speed_sa: float = 0.04
    warehouse_receipts_sa: float = 6000.0
    inventory_sa: float = 75.0


REQUIRED_COLUMNS: List[str] = [
    "date",
    "close_sa", "open_sa", "high_sa", "low_sa", "volume_sa", "open_interest_sa",
    "close_fg", "open_fg", "high_fg", "low_fg",
    "spot_sa", "basis_sa", "basis_rate_sa", "spot_fg", "basis_fg",
    "log_ret_sa", "log_ret_fg",
    "vol_20d_sa", "vol_60d_sa", "vol_20d_fg", "vol_60d_fg",
    "parkinson_vol_sa",
    "spread_fg_sa", "price_ratio_fg_sa", "crush_spread",
    "rolling_corr_20d", "rolling_corr_60d"
]

EXTENDED_COLUMNS: List[str] = REQUIRED_COLUMNS + [
    "ratio_fg_sa", "settle_sa", "delta_oi_sa", "symbol_sa",
    "volume_fg", "open_interest_fg", "settle_fg", "delta_oi_fg", "symbol_fg",
    "parkinson_vol_fg", "sa_daily_range_pct", "fg_daily_range_pct",
    "iv_atm_sa", "collar_skew_sa",
    # Round 1 Evolution: 基差期限结构、便利收益与动量特征
    "convenience_yield_sa", "roll_yield_sa", "term_structure_slope_sa",
    "chi_short_sa", "xi_long_sa", "tsmom_sa",
    "basis_convergence_speed_sa", "warehouse_receipts_sa", "inventory_sa"
]


def validate_aligned_dataframe(df: pd.DataFrame, min_rows: int = 1650) -> List[str]:
    """
    对对齐特征 DataFrame 进行全方位契约门禁校验。
    返回错误信息列表，若为空列表则表明全部通过。
    """
    errors: List[str] = []

    # 1. 行数门禁
    if len(df) < min_rows:
        errors.append(f"数据行数不足: 当前 {len(df)} 行, 要求至少 {min_rows} 行")

    # 2. 必须列存在性门禁
    missing_cols = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_cols:
        errors.append(f"缺失必要特征列: {missing_cols}")

    # 3. 0.000% 缺失率门禁
    null_counts = df.isnull().sum()
    cols_with_nulls = null_counts[null_counts > 0]
    if not cols_with_nulls.empty:
        errors.append(f"存在 NaN 缺失值 (违反 0.0% 缺失率门禁): {cols_with_nulls.to_dict()}")

    # 4. 时间序列严格单调递增门禁
    if "date" in df.columns:
        date_series = pd.to_datetime(df["date"])
        diffs = date_series.diff().dropna()
        if not (diffs.dt.total_seconds() > 0).all():
            errors.append("时间序列非严格单调递增，存在乱序或重复日期")

    # 5. 数值物理边界门禁
    if "close_sa" in df.columns and (df["close_sa"] <= 0).any():
        errors.append("纯碱收盘价包含非正数")
    if "close_fg" in df.columns and (df["close_fg"] <= 0).any():
        errors.append("玻璃收盘价包含非正数")
    if "spot_sa" in df.columns and (df["spot_sa"] <= 0).any():
        errors.append("纯碱现货价包含非正数")
    if "spot_fg" in df.columns and (df["spot_fg"] <= 0).any():
        errors.append("玻璃现货价包含非正数")

    for corr_col in ["rolling_corr_20d", "rolling_corr_60d"]:
        if corr_col in df.columns:
            invalid_corr = df[(df[corr_col] < -1.0 - 1e-6) | (df[corr_col] > 1.0 + 1e-6)]
            if not invalid_corr.empty:
                errors.append(f"{corr_col} 超出 [-1.0, 1.0] 数学边界: 违规行数 {len(invalid_corr)}")

    for vol_col in ["vol_20d_sa", "vol_60d_sa", "vol_20d_fg", "vol_60d_fg", "parkinson_vol_sa", "parkinson_vol_fg"]:
        if vol_col in df.columns:
            if (df[vol_col] <= 0).any():
                errors.append(f"{vol_col} 波动率必须为严格正数")

    # 6. Round 1 期限结构与基差特征边界校验
    if "convenience_yield_sa" in df.columns:
        invalid_cy = df[(df["convenience_yield_sa"] < -1.5) | (df["convenience_yield_sa"] > 3.0)]
        if not invalid_cy.empty:
            errors.append(f"convenience_yield_sa 超出 [-1.5, 3.0] 物理边界: 违规行数 {len(invalid_cy)}")

    if "tsmom_sa" in df.columns:
        invalid_tsmom = df[(df["tsmom_sa"] < -1.0 - 1e-6) | (df["tsmom_sa"] > 1.0 + 1e-6)]
        if not invalid_tsmom.empty:
            errors.append(f"tsmom_sa 超出 [-1.0, 1.0] 数学边界: 违规行数 {len(invalid_tsmom)}")

    if "basis_convergence_speed_sa" in df.columns:
        invalid_speed = df[(df["basis_convergence_speed_sa"] < 0.01) | (df["basis_convergence_speed_sa"] > 0.25)]
        if not invalid_speed.empty:
            errors.append(f"basis_convergence_speed_sa 超出 [0.01, 0.25] 物理边界: 违规行数 {len(invalid_speed)}")

    if "warehouse_receipts_sa" in df.columns:
        invalid_wr = df[(df["warehouse_receipts_sa"] < 0.0) | (df["warehouse_receipts_sa"] > 50000.0)]
        if not invalid_wr.empty:
            errors.append(f"warehouse_receipts_sa 超出 [0, 50000] 仓单范围: 违规行数 {len(invalid_wr)}")

    if "inventory_sa" in df.columns:
        invalid_inv = df[(df["inventory_sa"] < 10.0) | (df["inventory_sa"] > 300.0)]
        if not invalid_inv.empty:
            errors.append(f"inventory_sa 超出 [10.0, 300.0] 库存范围: 违规行数 {len(invalid_inv)}")

    return errors
