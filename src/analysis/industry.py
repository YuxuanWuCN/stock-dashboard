# analysis/industry.py —— 行业板块数据与映射
#
# 职责：
# 1. 通过 AkShare 东财行业板块接口获取行业列表和历史行情
# 2. 建立行业别名映射
# 3. 行业接口失败时降级到市场指数（reference_type="index"）
# 4. 缓存行业数据，一次运行不重复请求

import logging
import time
from typing import Optional

import akshare as ak
import pandas as pd
import numpy as np

from .config import (
    INDUSTRY_ALIAS_MAP,
    MARKET_INDICES,
    get_market_index,
    REQUEST_INTERVAL,
    REQUEST_TIMEOUT,
    MAX_RETRIES,
)

logger = logging.getLogger("stock-dashboard.industry")


class IndustryProvider:
    """行业数据提供器，封装缓存与降级逻辑。"""

    def __init__(self):
        # 缓存：name -> DataFrame (含 date, close)
        self._industry_cache: dict[str, pd.DataFrame] = {}
        # 缓存：index_code -> DataFrame
        self._index_cache: dict[str, pd.DataFrame] = {}
        # 行业名称 -> 东财板块代码
        self._board_map: dict[str, str] = {}
        # 是否已初始化板块映射
        self._boards_loaded = False
        # 行业别名反向映射
        self._build_alias_reverse_map()

    def _build_alias_reverse_map(self):
        """建立别名→标准类别名映射。"""
        self._alias_to_category: dict[str, str] = {}
        for std_name, aliases in INDUSTRY_ALIAS_MAP.items():
            for alias in aliases:
                self._alias_to_category[alias] = std_name
            # 标准名自身也映射
            self._alias_to_category[std_name] = std_name

    def resolve_category(self, category: str) -> Optional[str]:
        """将 watchlist 中的 category 解析为标准类别名。"""
        if not category or not category.strip():
            return None
        cat = category.strip()
        return self._alias_to_category.get(cat, cat)

    # ============================================================
    # 板块列表加载
    # ============================================================

    def _load_board_map(self) -> bool:
        """加载东财行业板块列表，建立名称→代码映射。成功返回 True。"""
        if self._boards_loaded:
            return len(self._board_map) > 0

        for attempt in range(1 + MAX_RETRIES):
            try:
                df = ak.stock_board_industry_name_em()
                if df is None or df.empty:
                    logger.warning("东财行业板块列表返回空")
                    continue

                # 列名通常为: "板块名称", "板块代码"
                name_col = None
                code_col = None
                for col in df.columns:
                    if "名称" in col or col == "name":
                        name_col = col
                    if "代码" in col or col == "code":
                        code_col = col

                if name_col is None or code_col is None:
                    logger.warning("无法识别行业板块列表列名: %s", list(df.columns))
                    continue

                for _, row in df.iterrows():
                    name = str(row[name_col]).strip()
                    code = str(row[code_col]).strip()
                    if name and code:
                        self._board_map[name] = code

                self._boards_loaded = True
                logger.info("加载东财行业板块列表成功，共 %d 个板块", len(self._board_map))
                return True

            except Exception:
                logger.warning("加载行业板块列表失败 (attempt %d)", attempt + 1)

            if attempt < MAX_RETRIES:
                time.sleep(REQUEST_INTERVAL)

        self._boards_loaded = True  # 标记已尝试，避免重复重试
        return False

    def _find_board_code(self, category: str) -> Optional[str]:
        """根据类别名匹配东财板块代码。"""
        if not self._board_map:
            self._load_board_map()

        # 精确匹配
        if category in self._board_map:
            return self._board_map[category]

        # 模糊匹配（包含关系）
        for name, code in self._board_map.items():
            if category in name:
                return code

        # 应用别名
        std_name = self.resolve_category(category)
        if std_name and std_name != category:
            for name, code in self._board_map.items():
                if std_name in name or name in std_name:
                    return code

        return None

    # ============================================================
    # 行业行情抓取
    # ============================================================

    def get_industry_data(
        self, category: str
    ) -> tuple[Optional[pd.DataFrame], str, str]:
        """
        获取行业历史行情。

        返回:
        - df: 含 date, close 列的 DataFrame，失败为 None
        - reference_type: "industry" | "index"
        - reference_name: 行业名称或指数名称
        """
        std_name = self.resolve_category(category)

        # 尝试从缓存获取
        cache_key = std_name if std_name else category
        if cache_key in self._industry_cache:
            return self._industry_cache[cache_key], "industry", cache_key

        # 尝试东财行业板块
        board_code = self._find_board_code(category) if std_name else None
        if board_code:
            df = self._fetch_board_history(board_code, cache_key)
            if df is not None:
                self._industry_cache[cache_key] = df
                return df, "industry", cache_key

        # 降级：使用市场指数
        logger.info("行业 '%s' 降级为市场指数参照", category)
        index_info = get_market_index("000001")  # 默认上证
        df = self._fetch_index_history(index_info["code"], index_info["name"])
        if df is not None:
            return df, "index", index_info["name"]

        logger.error("行业 '%s' 所有数据源均失败", category)
        return None, "none", ""

    def _fetch_board_history(
        self, board_code: str, board_name: str
    ) -> Optional[pd.DataFrame]:
        """抓取行业板块历史行情。"""
        for attempt in range(1 + MAX_RETRIES):
            try:
                df = ak.stock_board_industry_hist_em(
                    symbol=board_code,
                    period="daily",
                    start_date="20210101",
                    end_date="20991231",
                    adjust="",
                )
                if df is None or df.empty:
                    logger.warning("行业板块 %s(%s) 返回空数据", board_name, board_code)
                    continue

                # 映射列名
                col_map = {}
                for col in df.columns:
                    if "日期" in col or col == "date":
                        col_map[col] = "date"
                    elif "收盘" in col or col == "close":
                        col_map[col] = "close"
                    elif "开盘" in col:
                        col_map[col] = "open"
                    elif "最高" in col:
                        col_map[col] = "high"
                    elif "最低" in col:
                        col_map[col] = "low"
                    elif "成交量" in col:
                        col_map[col] = "volume"

                df = df.rename(columns=col_map)

                if "date" not in df.columns or "close" not in df.columns:
                    logger.warning("行业板块数据缺少 date/close 列")
                    continue

                df["date"] = pd.to_datetime(df["date"], errors="coerce")
                df = df.dropna(subset=["date"])
                df["date"] = df["date"].dt.date
                df["close"] = pd.to_numeric(df["close"], errors="coerce")
                df = df.sort_values("date").reset_index(drop=True)

                logger.info("行业 %s(%s): %d 行数据", board_name, board_code, len(df))
                return df

            except Exception:
                logger.warning("抓取行业 %s(%s) 失败 (attempt %d)", board_name, board_code, attempt + 1)

            if attempt < MAX_RETRIES:
                time.sleep(REQUEST_INTERVAL)

        return None

    def _fetch_index_history(
        self, index_code: str, index_name: str
    ) -> Optional[pd.DataFrame]:
        """抓取市场指数历史行情（降级用）。"""
        cache_key = index_code
        if cache_key in self._index_cache:
            return self._index_cache[cache_key]

        for attempt in range(1 + MAX_RETRIES):
            try:
                prefix = "sh" if index_code.startswith(("0", "6", "5", "9")) else "sz"
                df = ak.stock_zh_index_daily(symbol=f"{prefix}{index_code}")
                if df is None or df.empty:
                    # 备用：stock_zh_a_hist
                    df = ak.stock_zh_a_hist(
                        symbol=index_code,
                        period="daily",
                        start_date="20210101",
                        end_date="20991231",
                        adjust="",
                    )
                if df is None or df.empty:
                    continue

                col_map = {}
                for col in df.columns:
                    if "日期" in col:
                        col_map[col] = "date"
                    elif "收盘" in col:
                        col_map[col] = "close"

                if "日期" not in df.columns:
                    df = df.rename(columns={"date": "date"}) if "date" in df.columns else df

                df = df.rename(columns=col_map)

                if "date" not in df.columns or "close" not in df.columns:
                    logger.warning("指数板块数据缺少 date/close 列")
                    continue

                df["date"] = pd.to_datetime(df["date"], errors="coerce")
                df = df.dropna(subset=["date"])
                df["date"] = df["date"].dt.date
                df["close"] = pd.to_numeric(df["close"], errors="coerce")
                df = df.sort_values("date").reset_index(drop=True)

                self._index_cache[cache_key] = df
                logger.info("指数 %s(%s): %d 行数据", index_name, index_code, len(df))
                return df

            except Exception:
                logger.warning("抓取指数 %s(%s) 失败 (attempt %d)", index_name, index_code, attempt + 1)

            if attempt < MAX_RETRIES:
                time.sleep(REQUEST_INTERVAL)

        return None

    def get_industry_close_series(
        self,
        category: str,
        dates: pd.Series,
    ) -> tuple[Optional[pd.Series], str, str, Optional[str]]:
        """
        获取与给定日期对齐的行业收盘价序列。

        返回:
        - series: 与 dates 对齐的 close 序列（NaN 填充缺失）
        - reference_type: "industry" | "index" | "none"
        - reference_name
        - benchmark_code: 板块代码（行业）或指数代码
        """
        df, ref_type, ref_name = self.get_industry_data(category)

        if df is None or df.empty or ref_type == "none":
            return None, ref_type, ref_name, None

        # 确定 benchmark_code
        if ref_type == "industry":
            benchmark_code = self._find_board_code(category)
        else:
            benchmark_code = get_market_index("000001")["code"]

        # 建立日期串并映射
        date_set = set(dates.dropna().tolist())
        df_indexed = df.set_index("date")
        aligned = []
        for d in dates:
            if pd.isna(d):
                aligned.append(np.nan)
            elif d in df_indexed.index:
                aligned.append(df_indexed.loc[d, "close"])
            else:
                aligned.append(np.nan)

        series = pd.Series(aligned, index=dates.index, dtype=float)
        return series, ref_type, ref_name, benchmark_code
