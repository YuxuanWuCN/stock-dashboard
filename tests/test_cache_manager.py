# -*- coding: utf-8 -*-
"""tests/test_cache_manager.py —— 缓存管理器单元测试"""

import json
from datetime import datetime, timedelta
import pandas as pd
import pytest

from src.data.cache_manager import KlineCacheManager, FundamentalCacheManager


def test_kline_cache_manager(tmp_path):
    kline_dir = tmp_path / "kline"
    kline_dir.mkdir()
    mgr = KlineCacheManager(kline_dir=kline_dir)

    # 1. 缓存不存在
    assert mgr.load_kline("688525") is None

    # 2. 写入并读取
    sample_data = {
        "code": "688525",
        "kline": [
            {"date": "2026-01-01", "open": 10.0, "high": 11.0, "low": 9.5, "close": 10.5, "volume": 1000},
            {"date": "2026-01-02", "open": 10.5, "high": 12.0, "low": 10.2, "close": 11.8, "volume": 1500}
        ]
    }
    mgr.save_kline("688525", sample_data)

    df = mgr.load_kline("688525")
    assert df is not None
    assert len(df) == 2
    assert "close" in df.columns
    assert df["close"].iloc[1] == 11.8


def test_fundamental_cache_manager(tmp_path):
    cache_dir = tmp_path / "fundamental"
    mgr = FundamentalCacheManager(cache_dir=cache_dir, max_age_days=3)

    # 1. 缓存不存在
    assert mgr.load("000001") is None

    # 2. 正常写入与读取
    data = {"score": 85.5, "roe": 0.15}
    mgr.save("000001", data)

    cached = mgr.load("000001")
    assert cached is not None
    assert cached["score"] == 85.5
    assert "cached_at" in cached or "_cached_at" in cached

    # 3. 超期失效测试
    expired_data = dict(data)
    expired_data["cached_at"] = (datetime.now() - timedelta(days=5)).isoformat()
    p = mgr.get_path("000002")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(expired_data, f)

    assert mgr.load("000002") is None
