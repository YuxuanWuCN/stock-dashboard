"""模拟盘组合绩效跟踪单元测试。"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools.paper_portfolio as pp


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _setup(tmp_path, portfolio=None, summary=None):
    data = tmp_path / "data"
    if portfolio is None:
        portfolio = {
            "name": "测试组合",
            "capital": 1000000,
            "cash_pct": 20,
            "items": [
                {"code": "000001", "name": "平安银行", "pct": 40},
                {"code": "MA", "name": "万事达", "pct": 40},
            ],
        }
    if summary is None:
        summary = {
            "items": [
                {"code": "000001", "name": "平安银行", "change_pct": 2.0, "last_date": "2026-08-07", "status": "ok"},
                {"code": "MA", "name": "万事达", "change_pct": -1.0, "last_date": "2026-08-07", "status": "ok"},
            ]
        }
    _write_json(data / "paper" / "portfolio.json", portfolio)
    _write_json(data / "summary.json", summary)
    return data


def test_report_calculates_weighted_return(tmp_path, monkeypatch):
    """组合收益=Σ权重×涨跌（现金权重按0），等权基准=股票平均。"""
    data = _setup(tmp_path)
    monkeypatch.setattr(pp, "DATA_DIR", str(data))
    monkeypatch.setattr(pp, "SUMMARY_PATH", str(data / "summary.json"))
    monkeypatch.setattr(pp, "PORTFOLIO_PATH", str(data / "paper" / "portfolio.json"))
    monkeypatch.setattr(pp, "PERFORMANCE_PATH", str(data / "paper" / "performance.json"))
    assert pp.report() == 0
    perf = json.loads((data / "paper" / "performance.json").read_text(encoding="utf-8"))
    rec = perf["records"][-1]
    # 40%×2.0 + 40%×(-1.0) + 20%×0 = 0.4% ；等权 (2.0-1.0)/2 = 0.5%
    assert rec["trade_date"] == "2026-08-07"
    assert rec["portfolio_return_pct"] == 0.4
    assert rec["equal_weight_return_pct"] == 0.5
    assert rec["valid_count"] == 2


def test_report_skips_stale(tmp_path, monkeypatch):
    """stale/failed 股票不参与等权，组合权重跳过。"""
    summary = {
        "items": [
            {"code": "000001", "change_pct": 2.0, "last_date": "2026-08-07", "status": "ok"},
            {"code": "MA", "change_pct": None, "last_date": "2026-01-14", "status": "stale"},
        ]
    }
    data = _setup(tmp_path, summary=summary)
    monkeypatch.setattr(pp, "DATA_DIR", str(data))
    monkeypatch.setattr(pp, "SUMMARY_PATH", str(data / "summary.json"))
    monkeypatch.setattr(pp, "PORTFOLIO_PATH", str(data / "paper" / "portfolio.json"))
    monkeypatch.setattr(pp, "PERFORMANCE_PATH", str(data / "paper" / "performance.json"))
    assert pp.report() == 0
    perf = json.loads((data / "paper" / "performance.json").read_text(encoding="utf-8"))
    rec = perf["records"][-1]
    assert rec["valid_count"] == 1
    assert rec["skipped"][0]["code"] == "MA"


def test_report_dedup_same_day(tmp_path, monkeypatch):
    """同一天重复记录会覆盖而不是追加。"""
    data = _setup(tmp_path)
    monkeypatch.setattr(pp, "DATA_DIR", str(data))
    monkeypatch.setattr(pp, "SUMMARY_PATH", str(data / "summary.json"))
    monkeypatch.setattr(pp, "PORTFOLIO_PATH", str(data / "paper" / "portfolio.json"))
    monkeypatch.setattr(pp, "PERFORMANCE_PATH", str(data / "paper" / "performance.json"))
    pp.report()
    pp.report()
    perf = json.loads((data / "paper" / "performance.json").read_text(encoding="utf-8"))
    assert len(perf["records"]) == 1