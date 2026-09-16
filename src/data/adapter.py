# -*- coding: utf-8 -*-
"""src/data/adapter.py —— Unified DataOps & Multi-Market Factor Adapter (Week 1 Roadmap)

依据规范：
1. 《StockDashboard v3.0 & Serenity Chokepoint 12-Week Roadmap》Phase I: Week 1
2. 双轨制因子规范：学术 4 因子 (MKT, SMB, HML, MOM, rf) + 实盘扩展 3 因子 (LARGE_ORDER_INFLOW, NORTHBOUND_DELTA, INST_SEAT_RATIO)
3. 统一多市场数据 Schema：A 股 (AKShare / 东方财富) + 美股 (Kenneth French / Dartmouth) + 商业终端 (Wind/CSMAR) 映射
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from src.analysis.factor_providers import (
    BaseFactorProvider,
    AkshareProxyFactorProvider,
    KennethFrenchFactorProvider,
    CSMARFactorProvider,
    WindCSMARStubProvider,
    EastMoneyMiaoXiangProvider,
    SCNUAcademicFactorProvider
)

logger = logging.getLogger("data_adapter")


@dataclass
class MarketDataPacket:
    """标准化资产多市场数据封包。"""
    ticker: str
    market: str  # 'CN' or 'US'
    dates: pd.DatetimeIndex
    returns: pd.Series
    prices: pd.DataFrame  # open, high, low, close, volume, amount
    factors: pd.DataFrame  # MKT, SMB, HML, MOM, rf, (optional micro flows)
    cash_flow_indicators: Optional[Dict[str, float]] = None


class UnifiedDataAdapter:
    """统一多市场数据适配层 (DataOps Layer)。
    
    实现对底层不同数据源的彻底解耦与标准化映射：
    - 自动对齐时序日历（处理节假日、跳空与交易日交集）
    - 提供纯学术 Carhart 4 因子矩阵与实盘 7 因子增强矩阵的自由切换
    - 自动提取并勾稽资产现金流先行指标（预付款项、合同负债、Capex）
    - 原生支持华南师范大学/阿伯丁学院校内因子库 (data/school_factors/)
    """

    STANDARD_FACTOR_COLS = ["MKT", "SMB", "HML", "MOM", "rf"]
    EXTENDED_FLOW_COLS = ["LARGE_ORDER_INFLOW", "NORTHBOUND_DELTA", "INST_SEAT_RATIO"]

    @staticmethod
    def _normalise_date_bound(value: Any, label: str) -> pd.Timestamp:
        """解析边界日期，避免 Pandas 将 YYYYMMDD 整数当成纳秒。"""
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValueError(f"{label} 不能为空")
        candidate = value.strip() if isinstance(value, str) else value
        if isinstance(candidate, (bool, np.bool_)):
            raise ValueError(f"{label} 不是合法日期: {value!r}")
        if isinstance(candidate, (int, np.integer)):
            text = str(int(candidate))
            if not re.fullmatch(r"\d{8}", text):
                raise ValueError(f"{label} 不是合法日期: {value!r}")
            parsed = pd.to_datetime(text, format="%Y%m%d", errors="coerce")
        elif isinstance(candidate, (float, np.floating)):
            if not np.isfinite(float(candidate)) or float(candidate) != int(candidate):
                raise ValueError(f"{label} 不是合法日期: {value!r}")
            text = str(int(candidate))
            if not re.fullmatch(r"\d{8}", text):
                raise ValueError(f"{label} 不是合法日期: {value!r}")
            parsed = pd.to_datetime(text, format="%Y%m%d", errors="coerce")
        elif isinstance(candidate, str) and re.fullmatch(r"\d{8}", candidate):
            parsed = pd.to_datetime(candidate, format="%Y%m%d", errors="coerce")
        else:
            parsed = pd.to_datetime(candidate, errors="coerce")
        if pd.isna(parsed):
            raise ValueError(f"{label} 不是合法日期: {value!r}")
        timestamp = pd.Timestamp(parsed)
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_localize(None)
        return timestamp.normalize()

    def __init__(
        self,
        mode: str = "dual_track",  # 'academic_4factor', 'production_7factor', 'dual_track', 'school_scnu'
        cache_db: Optional[str | Path] = None,
        csmar_provider: Optional[BaseFactorProvider] = None,
        scnu_provider: Optional[BaseFactorProvider] = None,
        csmar_connection_params: Optional[Dict[str, Any]] = None,
        school_factor_dir: Optional[str | Path] = None,
        csmar_service: Any = None,
        csmar_query: Optional[Callable[..., Any]] = None,
        csmar_service_factory: Optional[Callable[..., Any]] = None,
        csmar_query_method: Optional[str] = None,
        csmar_query_params: Optional[Dict[str, Any]] = None,
        csmar_expected_trading_dates: Optional[Iterable[Any]] = None,
        school_expected_trading_dates: Optional[Iterable[Any]] = None,
        expected_trading_dates: Optional[Iterable[Any]] = None,
    ):
        self.mode = str(mode).strip().lower()
        # ``expected_trading_dates`` 是便捷别名；显式的市场参数优先。
        def freeze_calendar(value: Optional[Iterable[Any]]) -> Optional[tuple[Any, ...]]:
            if value is None:
                return None
            if isinstance(value, (str, bytes, Mapping)):
                raise ValueError(
                    "expected_trading_dates 必须是日期序列，不能是字符串或映射"
                )
            try:
                return tuple(value)
            except TypeError as exc:
                raise ValueError("expected_trading_dates 必须是可迭代日期序列") from exc

        shared_expected = freeze_calendar(expected_trading_dates)
        csmar_expected_trading_dates = freeze_calendar(csmar_expected_trading_dates)
        school_expected_trading_dates = freeze_calendar(school_expected_trading_dates)
        if csmar_expected_trading_dates is None:
            csmar_expected_trading_dates = shared_expected
        if school_expected_trading_dates is None:
            school_expected_trading_dates = shared_expected
        self.csmar_expected_trading_dates = csmar_expected_trading_dates
        self.school_expected_trading_dates = school_expected_trading_dates
        self.cache_db = str(cache_db or Path("data/cache/unified_adapter.db"))
        self.cn_provider = AkshareProxyFactorProvider(db_path=self.cache_db)
        self.us_provider = KennethFrenchFactorProvider(cache_dir=Path("data/cache/kenneth_french"))
        self.eastmoney_provider = EastMoneyMiaoXiangProvider(db_path=self.cache_db)
        # CSMAR 是学校提供的可选依赖。默认模式不导入 SDK，官方模式则必须
        # 明确查询成功，不能回退为开源代理或合成数据。
        self.csmar_provider = (
            csmar_provider
            if csmar_provider is not None
            else CSMARFactorProvider(
                service=csmar_service,
                query=csmar_query,
                service_factory=csmar_service_factory,
                query_method=csmar_query_method,
                query_params=csmar_query_params,
                connection_params=csmar_connection_params,
                expected_trading_dates=csmar_expected_trading_dates,
            )
        )
        self.scnu_provider = (
            scnu_provider
            if scnu_provider is not None
            else SCNUAcademicFactorProvider(
                data_dir=school_factor_dir or "data/school_factors",
                strict=self.mode in {"school_scnu", "scnu", "school"},
                api_provider=(
                    self.csmar_provider
                    if self.mode in {"school_scnu", "scnu", "school"}
                    else None
                ),
                expected_trading_dates=school_expected_trading_dates,
            )
        )
        self._factor_cache: Dict[Tuple[str, str, str, bool], pd.DataFrame] = {}
        self._ensure_cache()


    def _ensure_cache(self) -> None:
        """确保本地统一缓存数据库完备。"""
        os.makedirs(os.path.dirname(self.cache_db) if os.path.dirname(self.cache_db) else ".", exist_ok=True)
        with sqlite3.connect(self.cache_db) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS asset_kline_cache (
                    ticker TEXT,
                    date TEXT,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    amount REAL,
                    returns REAL,
                    PRIMARY KEY (ticker, date)
                )
            """)
            conn.commit()

    def _factor_frame_to_index(
        self,
        frame: pd.DataFrame,
        *,
        source: str,
        start_date: Any,
        end_date: Any,
        include_micro_flows: bool,
        expected_trading_dates: Optional[Iterable[Any]] = None,
    ) -> pd.DataFrame:
        """校验官方 provider 输出并转为按自然日索引的标准矩阵。"""
        start = self._normalise_date_bound(start_date, "start_date")
        end = self._normalise_date_bound(end_date, "end_date")
        if start > end:
            raise ValueError("start_date 不能晚于 end_date")

        if not isinstance(frame, pd.DataFrame):
            raise ValueError(f"{source} 返回类型不是 DataFrame")
        if frame.empty:
            if expected_trading_dates is not None:
                validator = CSMARFactorProvider(
                    expected_trading_dates=expected_trading_dates,
                    source=source,
                )
                expected = validator._normalise_expected_dates(start, end)
                if expected is not None and expected.empty:
                    empty = pd.DataFrame(
                        columns=self.STANDARD_FACTOR_COLS,
                        index=pd.DatetimeIndex([], name="date"),
                    )
                    empty.attrs["coverage_verified"] = True
                    return empty
                if expected is not None:
                    validator._validate_expected_coverage([], expected, source=source)
            raise ValueError(f"{source} 返回空结果，不能使用回退因子")

        required = ["date", *self.STANDARD_FACTOR_COLS]
        missing = [column for column in required if column not in frame.columns]
        if missing:
            raise ValueError(f"{source} 返回缺少标准列: {', '.join(missing)}")

        result = frame.copy()
        parsed_dates: List[pd.Timestamp | pd.NaT] = []
        for value in result["date"]:
            try:
                parsed_dates.append(self._normalise_date_bound(value, "date"))
            except (TypeError, ValueError, OverflowError):
                parsed_dates.append(pd.NaT)
        result["date"] = pd.Series(parsed_dates, index=result.index)
        if result["date"].isna().any():
            raise ValueError(f"{source} 返回非法日期")
        if result["date"].duplicated().any():
            raise ValueError(f"{source} 返回重复日期")
        for column in self.STANDARD_FACTOR_COLS:
            result[column] = pd.to_numeric(result[column], errors="coerce")
            if result[column].isna().any() or not np.isfinite(result[column].to_numpy()).all():
                raise ValueError(f"{source} 返回列 {column} 的非法数值")
        result = result.loc[(result["date"] >= start) & (result["date"] <= end)].copy()
        if result.empty:
            raise ValueError(f"{source} 没有落在请求日期范围内的记录")
        if expected_trading_dates is not None:
            validator = CSMARFactorProvider(
                expected_trading_dates=expected_trading_dates,
                source=source,
            )
            expected = validator._normalise_expected_dates(start, end)
            # ``expected`` 只能为 None when the input itself is None, which is
            # ruled out above; the guard keeps type checkers and callers clear.
            if expected is not None:
                validator._validate_expected_coverage(
                    result["date"], expected, source=source
                )
        result = result.sort_values("date").set_index("date")
        columns = list(self.STANDARD_FACTOR_COLS)
        if include_micro_flows:
            columns += [
                column for column in self.EXTENDED_FLOW_COLS if column in result.columns
            ]
        return result[columns]

    def get_market_factors(
        self,
        start_date: str,
        end_date: str,
        market: str = "CN",
        include_micro_flows: bool = True
    ) -> pd.DataFrame:
        """获取指定市场与日期的标准化多因子矩阵（带内存缓存）。"""
        market_norm = str(market).strip().upper()
        cache_key = (start_date, end_date, market_norm, include_micro_flows)
        if hasattr(self, "_factor_cache") and cache_key in self._factor_cache:
            return self._factor_cache[cache_key].copy()

        result = self._compute_market_factors(
            start_date=start_date,
            end_date=end_date,
            market=market_norm,
            include_micro_flows=include_micro_flows
        )
        if hasattr(self, "_factor_cache"):
            self._factor_cache[cache_key] = result.copy()
        return result

    def _compute_market_factors(
        self,
        start_date: str,
        end_date: str,
        market: str = "CN",
        include_micro_flows: bool = True
    ) -> pd.DataFrame:
        """内部实现：获取指定市场与日期的标准化多因子矩阵。
        
        Args:
            start_date: 'YYYY-MM-DD'
            end_date: 'YYYY-MM-DD'
            market: 'CN' 或 'US'
            include_micro_flows: 是否包含微观资金流因子
        
        Returns:
            pd.DataFrame: 包含 date 索引与标准因子列的 DataFrame
        """
        market = str(market).strip().upper()
        if market == "US":
            df = self.us_provider.get_daily_factors(start_date, end_date)
            df["date"] = pd.to_datetime(df["date"])
            df.set_index("date", inplace=True)
            return df[self.STANDARD_FACTOR_COLS]

        if market != "CN":
            raise ValueError(f"不支持的市场标识: {market!r}，仅支持 CN 或 US")

        if self.mode in {"csmar", "school_csmar", "academic_csmar"}:
            return self._factor_frame_to_index(
                self.csmar_provider.get_daily_factors(start_date, end_date),
                source="CSMAR",
                start_date=start_date,
                end_date=end_date,
                include_micro_flows=False,
                expected_trading_dates=self.csmar_expected_trading_dates,
            )

        if self.mode in {"school_scnu", "scnu", "school"}:
            return self._factor_frame_to_index(
                self.scnu_provider.get_daily_factors(start_date, end_date),
                source="SCNU",
                start_date=start_date,
                end_date=end_date,
                include_micro_flows=False,
                expected_trading_dates=self.school_expected_trading_dates,
            )

        # A 股市场
        if include_micro_flows and self.mode in ("production_7factor", "dual_track"):
            df = self.eastmoney_provider.get_factors_with_flows(start_date, end_date)
            if not df.empty:
                df["date"] = pd.to_datetime(df["date"])
                df.set_index("date", inplace=True)
                cols = [c for c in (self.STANDARD_FACTOR_COLS + self.EXTENDED_FLOW_COLS) if c in df.columns]
                return df[cols]

        df = self.cn_provider.get_daily_factors(start_date, end_date)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            df.set_index("date", inplace=True)
            return df[self.STANDARD_FACTOR_COLS]

        # 回退：生成正交合成因子
        dates = pd.date_range(start_date, end_date, freq="B")
        n = len(dates)
        np.random.seed(42)
        syn_df = pd.DataFrame({
            "MKT": np.random.normal(0.0004, 0.012, n),
            "SMB": np.random.normal(0.0001, 0.006, n),
            "HML": np.random.normal(0.00005, 0.007, n),
            "MOM": np.random.normal(0.0002, 0.008, n),
            "rf": np.full(n, 0.00015)
        }, index=dates)
        if include_micro_flows:
            syn_df["LARGE_ORDER_INFLOW"] = np.random.normal(-0.01, 0.04, n)
            syn_df["NORTHBOUND_DELTA"] = np.random.normal(0.005, 0.02, n)
            syn_df["INST_SEAT_RATIO"] = np.random.uniform(0.1, 0.5, n)
        return syn_df

    def assemble_market_packet(
        self,
        ticker: str,
        kline_df: pd.DataFrame,
        market: str = "CN",
        cash_flow_indicators: Optional[Dict[str, float]] = None
    ) -> MarketDataPacket:
        """将标的 K 线行情、因子矩阵与现金流指标装配为标准 MarketDataPacket。"""
        df = kline_df.copy()
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
        df.sort_index(inplace=True)

        if "returns" not in df.columns and "close" in df.columns:
            df["returns"] = df["close"].pct_change().fillna(0.0)

        start_date = df.index.min().strftime("%Y-%m-%d")
        end_date = df.index.max().strftime("%Y-%m-%d")

        factors_df = self.get_market_factors(
            start_date=start_date,
            end_date=end_date,
            market=market,
            include_micro_flows=(self.mode != "academic_4factor")
        )

        # 严格交集对齐交易日
        common_dates = df.index.intersection(factors_df.index)
        aligned_df = df.loc[common_dates]
        aligned_factors = factors_df.loc[common_dates]

        return MarketDataPacket(
            ticker=ticker,
            market=market,
            dates=common_dates,
            returns=aligned_df["returns"],
            prices=aligned_df[["open", "high", "low", "close", "volume", "amount"] if "amount" in aligned_df.columns else ["open", "high", "low", "close", "volume"]],
            factors=aligned_factors,
            cash_flow_indicators=cash_flow_indicators or {}
        )
