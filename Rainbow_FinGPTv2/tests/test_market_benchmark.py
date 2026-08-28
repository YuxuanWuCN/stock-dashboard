"""市场级对照组（选股池 vs 宽基指数）的单元测试。"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools.market_benchmark as mb


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_kline_daily_return(tmp_path, monkeypatch):
    """K线单日收益：(当日收-前收)/前收*100；缺数据返回 None。"""
    kdir = tmp_path / "kline"
    _write_json(kdir / "510300.json", {
        "dates": ["2026-08-10", "2026-08-11"],
        "kline": [[0, 100, 0, 0], [0, 101, 0, 0]], "volume": [1, 1],
    })
    monkeypatch.setattr(mb, "KLINE_DIR", str(kdir))
    assert mb._kline_daily_return("510300", "2026-08-11") == 1.0
    assert mb._kline_daily_return("510300", "2026-08-10") is None  # 无前收
    assert mb._kline_daily_return("510300", "2026-08-12") is None  # 无当日
    assert mb._kline_daily_return("999999", "2026-08-11") is None  # 无文件


def test_pool_daily_return(tmp_path, monkeypatch):
    """快照全部股票等权日收益；无快照/空快照返回 None。"""
    snap_dir = tmp_path / "snapshots"
    _write_json(snap_dir / "2026-08-11.json", {
        "trade_date": "2026-08-11",
        "items": [
            {"code": "A", "change_pct": 2.0},
            {"code": "B", "change_pct": -1.0},
            {"code": "C", "change_pct": None},  # 无效，跳过
        ],
    })
    monkeypatch.setattr(mb, "SNAPSHOT_DIR", str(snap_dir))
    assert mb._pool_daily_return("2026-08-11") == 0.5  # (2.0-1.0)/2
    assert mb._pool_daily_return("2026-08-12") is None


def test_collect_dates(tmp_path, monkeypatch):
    """绩效记录日中提取全部交易日。"""
    paper = tmp_path / "paper"
    _write_json(paper / "performance_a.json", {"records": [{"trade_date": "2026-08-11"}]})
    _write_json(paper / "performance_b.json", {"records": [{"trade_date": "2026-08-12"}]})
    _write_json(paper / "portfolio.json", {"records": [{"trade_date": "不应收集"}]})
    monkeypatch.setattr(mb, "PAPER_DIR", str(paper))
    assert mb.collect_dates() == ["2026-08-11", "2026-08-12"]


def test_t_test_consistent_with_random_control():
    """与 random_control 的 t 检验一致（同一实现口径）。"""
    import tools.random_control as rc
    diffs = [0.5, -0.2, 0.3, 0.1, -0.4]
    assert mb._t_test_pvalue(diffs) == rc._t_test_pvalue(diffs)
