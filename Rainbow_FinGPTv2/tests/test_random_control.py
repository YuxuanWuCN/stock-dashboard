"""随机对照组与历史快照重建的单元测试。"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools.random_control as rc
import tools.reconstruct_summary as rs


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


# ---------- reconstruct_summary ----------

def test_build_snapshot_from_kline(tmp_path, monkeypatch):
    """K线重建：涨跌 = (当日收-前收)/前收*100，休市日无数据。"""
    kdir = tmp_path / "kline"
    _write_json(kdir / "600519.json", {
        "dates": ["2026-08-10", "2026-08-11"],
        "kline": [[0, 10, 0, 0], [0, 10.5, 0, 0]], "volume": [1, 1],
    })
    _write_json(kdir / "000001.json", {
        "dates": ["2026-08-10", "2026-08-11"],
        "kline": [[0, 5, 0, 0], [0, 4.8, 0, 0]], "volume": [1, 1],
    })
    _write_json(kdir / "MISSING.json", {
        "dates": ["2026-08-10"],  # 无 8/11，应跳过
        "kline": [[0, 1, 0, 0]], "volume": [1],
    })
    _write_json(tmp_path / "summary.json", {"items": [
        {"code": "600519", "name": "贵州茅台", "type": "stock"},
        {"code": "000001", "name": "平安银行", "type": "stock"},
    ]})
    monkeypatch.setattr(rs, "KLINE_DIR", str(kdir))
    monkeypatch.setattr(rs, "SUMMARY_PATH", str(tmp_path / "summary.json"))
    snap = rs.build_snapshot("2026-08-11")
    assert snap["total"] == 2
    by_code = {it["code"]: it for it in snap["items"]}
    assert by_code["600519"]["change_pct"] == 5.0    # (10.5-10)/10
    assert by_code["000001"]["change_pct"] == -4.0   # (4.8-5)/5
    assert by_code["600519"]["name"] == "贵州茅台"    # 从 summary 取名称


def test_build_snapshot_empty_pool(tmp_path, monkeypatch):
    """无任何 K线覆盖时返回空快照。"""
    kdir = tmp_path / "kline"
    kdir.mkdir(parents=True)
    monkeypatch.setattr(rs, "KLINE_DIR", str(kdir))
    monkeypatch.setattr(rs, "SUMMARY_PATH", str(tmp_path / "summary.json"))
    snap = rs.build_snapshot("2026-08-11")
    assert snap["total"] == 0


# ---------- random_control ----------

def test_daily_changes_prefers_snapshot(tmp_path, monkeypatch):
    """快照优先于 summary（B 修复：历史缺口用 K线快照补齐）。"""
    snap_dir = tmp_path / "snapshots"
    _write_json(snap_dir / "2026-08-11.json", {
        "trade_date": "2026-08-11",
        "items": [
            {"code": "A", "change_pct": 1.0},
            {"code": "B", "change_pct": -2.0},
        ],
    })
    summary = {"items": [
        {"code": "A", "change_pct": 99.0, "last_date": "2026-08-11", "status": "stale"},
        {"code": "B", "change_pct": 99.0, "last_date": "2026-08-11", "status": "stale"},
    ]}
    monkeypatch.setattr(rc, "SNAPSHOT_DIR", str(snap_dir))
    by_date = rc._daily_changes_by_date(summary)
    # 快照的值优先，不是 summary 的 99.0
    assert by_date["2026-08-11"] == [("A", 1.0), ("B", -2.0)]


def test_daily_changes_summary_fallback(tmp_path, monkeypatch):
    """无快照时回退到 summary 的 ok 条目。"""
    monkeypatch.setattr(rc, "SNAPSHOT_DIR", str(tmp_path / "nonexistent"))
    summary = {"items": [
        {"code": "A", "change_pct": 1.0, "last_date": "2026-08-11", "status": "ok"},
        {"code": "B", "change_pct": None, "last_date": "2026-08-11", "status": "ok"},
        {"code": "C", "change_pct": 2.0, "last_date": "2026-08-12", "status": "stale"},
    ]}
    by_date = rc._daily_changes_by_date(summary)
    assert by_date["2026-08-11"] == [("A", 1.0)]
    assert "2026-08-12" not in by_date


def test_percentile_and_t_test():
    """分位与单侧 t 检验的正确性（手算小样本）。"""
    dist = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert rc._percentile(3.0, dist) == 60.0
    assert rc._percentile(6.0, dist) == 100.0
    assert rc._percentile(0.0, dist) == 0.0
    # 全正超额 → p 小
    p = rc._t_test_pvalue([1.0, 2.0, 1.5, 2.5, 2.0])
    assert p is not None and p < 0.05
    # 方差为 0（所有值相同）→ 无法计算 t，返回 None
    assert rc._t_test_pvalue([1.0, 1.0, 1.0, 1.0, 1.0]) is None
    # 全负超额 → p 大（单侧右侧）
    p2 = rc._t_test_pvalue([-1.0, -2.0, -1.5, -2.5, -2.0])
    assert p2 is not None and p2 > 0.95


def test_analyze_portfolio(tmp_path, monkeypatch):
    """组合 vs 随机抽样：分位与超额正确。"""
    perf = {"records": [{
        "trade_date": "2026-08-11",
        "portfolio_return_pct": 2.0,
        "items": [{"code": f"C{i}", "change_pct": 1.0} for i in range(3)],
    }]}
    by_date = {"2026-08-11": [(f"P{i}", 0.5) for i in range(50)]}
    result = rc.analyze_portfolio("test", perf, by_date, trials=100, seed_base=1)
    assert result["n_days"] == 1
    day = result["days"][0]
    assert day["holdings"] == 3
    # 组合 2.0% vs 随机 0.5% 均值 → 分位应很高
    assert day["percentile"] >= 99.0
    assert day["excess"] > 1.0
