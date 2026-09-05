# -*- coding: utf-8 -*-
"""src/data/cache_manager.py —— 结构化量化数据与研报原子化缓存管理器

为 build_ranking、fetch_data 及各个回测与分析引擎提供高效、原子化的本地缓存管理，
支持 K 线数据、基本面财报及技术指标分级缓存与时效校验。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from src.utils import atomic_write_json

logger = logging.getLogger("cache_manager")


class KlineCacheManager:
    """K 线行情本地缓存管理器。"""

    def __init__(self, kline_dir: Optional[Path | str] = None):
        self.kline_dir = Path(kline_dir) if kline_dir else Path("docs/data/kline")

    def get_path(self, code: str) -> Path:
        return self.kline_dir / f"{code}.json"

    def load_kline(self, code: str) -> Optional[pd.DataFrame]:
        """读取已缓存的 K 线并转为标准 OHLCV DataFrame。支持对象列表和多列平行数组两种格式。"""
        p = self.get_path(code)
        if not p.exists():
            return None
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            dates = data.get("dates") or []
            kline = data.get("kline") or []
            volume = data.get("volume") or []

            if dates and kline and len(dates) == len(kline) and isinstance(kline[0], list):
                # 格式 B: dates, [open, close, low, high], volume
                rows = []
                for i, d in enumerate(dates):
                    bar = kline[i]
                    if not isinstance(bar, list) or len(bar) < 4:
                        continue
                    rows.append({
                        "date": d,
                        "open": bar[0],
                        "high": bar[3],
                        "low": bar[2],
                        "close": bar[1],
                        "volume": volume[i] if i < len(volume) else 0,
                    })
                return pd.DataFrame(rows) if rows else None
            elif kline and isinstance(kline[0], dict):
                # 格式 A: list of dicts
                df = pd.DataFrame(kline)
                date_col = "date" if "date" in df.columns else ("trade_date" if "trade_date" in df.columns else None)
                if date_col:
                    df[date_col] = pd.to_datetime(df[date_col])
                    df = df.sort_values(date_col).reset_index(drop=True)
                return df
            return None
        except Exception as e:
            logger.warning(f"读取 K 线缓存失败 [{code}]: {e}")
            return None

    def save_kline(self, code: str, kline_json_obj: dict) -> None:
        """原子化保存 K 线 JSON 缓存。"""
        p = self.get_path(code)
        atomic_write_json(kline_json_obj, str(p), logger)


class FundamentalCacheManager:
    """基本面财务与机构数据缓存管理器。"""

    def __init__(self, cache_dir: Optional[Path | str] = None, max_age_days: int = 7):
        self.cache_dir = Path(cache_dir) if cache_dir else Path("data/cache/fundamental")
        self.max_age_days = max_age_days
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_path(self, code: str) -> Path:
        return self.cache_dir / f"{code}.json"

    def load(self, code: str) -> Optional[Dict[str, Any]]:
        """读取基本面缓存，校验完整性与时效。"""
        p = self.get_path(code)
        if not p.exists():
            return None
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not (isinstance(data, dict) and isinstance(data.get("score"), (int, float))):
                return None
            cached_at = data.get("cached_at") or data.get("_cached_at")
            if cached_at:
                try:
                    c_date = datetime.fromisoformat(cached_at)
                    age = (datetime.now() - c_date).total_seconds() / 86400.0
                    if age > self.max_age_days:
                        return None
                except Exception:
                    pass
            return data
        except Exception as e:
            logger.warning(f"读取基本面缓存异常 [{code}]: {e}")
            return None

    def save(self, code: str, result: Dict[str, Any]) -> None:
        """保存基本面分析结果并附加时间戳。"""
        p = self.get_path(code)
        to_save = dict(result)
        to_save.setdefault("cached_at", datetime.now().isoformat())
        atomic_write_json(to_save, str(p), logger)
