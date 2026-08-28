"""模拟盘组合绩效跟踪单元测试。"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools.paper_portfolio as pp
import tools.weekly_champion_analysis as weekly


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
def test_multi_portfolio_scan(tmp_path, monkeypatch):
    """report 命令应扫描 portfolio*.json 并为每个组合写独立绩效文件。"""
    data = _setup(tmp_path)
    agg = {
        "name": "激进组合", "capital": 1000000, "cash_pct": 0,
        "items": [{"code": "000001", "name": "平安银行", "pct": 100}],
    }
    _write_json(data / "paper" / "portfolio_aggressive.json", agg)
    monkeypatch.setattr(pp, "DATA_DIR", str(data))
    monkeypatch.setattr(pp, "SUMMARY_PATH", str(data / "summary.json"))
    monkeypatch.setattr(pp, "PORTFOLIO_PATH", str(data / "paper" / "portfolio.json"))
    monkeypatch.setattr(pp, "PERFORMANCE_PATH", str(data / "paper" / "performance.json"))
    files = pp._portfolio_files()
    assert len(files) == 2
    assert pp._performance_path_for(str(data / "paper" / "portfolio_aggressive.json")).endswith("performance_aggressive.json")
    assert pp.report(str(data / "paper" / "portfolio_aggressive.json")) == 0
    perf = json.loads((data / "paper" / "performance_aggressive.json").read_text(encoding="utf-8"))
    assert perf["records"][-1]["valid_count"] == 1

def test_benchmark_records_daily_return(tmp_path, monkeypatch):
    """全池等权日收益=有效股票涨跌幅平均，首次记录累计=当日。"""
    data = _setup(tmp_path)
    monkeypatch.setattr(pp, "DATA_DIR", str(data))
    monkeypatch.setattr(pp, "SUMMARY_PATH", str(data / "summary.json"))
    monkeypatch.setattr(pp, "BENCHMARK_PATH", str(data / "paper" / "benchmark.json"))
    monkeypatch.setattr(pp, "KLINE_DIR", str(data / "kline"))
    assert pp.benchmark() == 0
    bm = json.loads((data / "paper" / "benchmark.json").read_text(encoding="utf-8"))
    rec = bm["records"][-1]
    assert rec["trade_date"] == "2026-08-07"
    assert rec["daily_return_pct"] == 0.5          # (2.0 + (-1.0)) / 2
    assert rec["cumulative_return_pct"] == 0.5
    assert rec["valid_count"] == 2


def test_benchmark_dedup_same_day(tmp_path, monkeypatch):
    """同一天重复记录会覆盖而不是追加。"""
    data = _setup(tmp_path)
    monkeypatch.setattr(pp, "DATA_DIR", str(data))
    monkeypatch.setattr(pp, "SUMMARY_PATH", str(data / "summary.json"))
    monkeypatch.setattr(pp, "BENCHMARK_PATH", str(data / "paper" / "benchmark.json"))
    monkeypatch.setattr(pp, "KLINE_DIR", str(data / "kline"))
    assert pp.benchmark() == 0
    assert pp.benchmark() == 0
    bm = json.loads((data / "paper" / "benchmark.json").read_text(encoding="utf-8"))
    assert len(bm["records"]) == 1


def test_benchmark_backfills_from_kline(tmp_path, monkeypatch):
    """首次运行且模拟盘有起点时，用 kline 回填起点当日收益，累计从起点计算。"""
    summary = {
        "items": [
            {"code": "600519", "name": "贵州茅台", "change_pct": 1.0, "last_date": "2026-08-10", "status": "ok"},
            {"code": "000001", "name": "平安银行", "change_pct": -1.0, "last_date": "2026-08-10", "status": "ok"},
        ]
    }
    data = _setup(tmp_path, summary=summary)
    _write_json(data / "paper" / "performance.json", {
        "schema_version": "1.0", "portfolio_name": "x",
        "records": [{"trade_date": "2026-08-07"}],
    })
    # kline：600519 8/6=10 → 8/7=10.5 (+5%)；000001 8/6=5 → 8/7=4.8 (-4%)
    _write_json(data / "kline" / "600519.json", {
        "code": "600519", "name": "贵州茅台",
        "dates": ["2026-08-06", "2026-08-07"],
        "kline": [[0, 10, 0, 0], [0, 10.5, 0, 0]], "volume": [1, 1],
    })
    _write_json(data / "kline" / "000001.json", {
        "code": "000001", "name": "平安银行",
        "dates": ["2026-08-06", "2026-08-07"],
        "kline": [[0, 5, 0, 0], [0, 4.8, 0, 0]], "volume": [1, 1],
    })
    monkeypatch.setattr(pp, "DATA_DIR", str(data))
    monkeypatch.setattr(pp, "SUMMARY_PATH", str(data / "summary.json"))
    monkeypatch.setattr(pp, "PERFORMANCE_PATH", str(data / "paper" / "performance.json"))
    monkeypatch.setattr(pp, "BENCHMARK_PATH", str(data / "paper" / "benchmark.json"))
    monkeypatch.setattr(pp, "KLINE_DIR", str(data / "kline"))
    assert pp.benchmark() == 0
    bm = json.loads((data / "paper" / "benchmark.json").read_text(encoding="utf-8"))
    assert len(bm["records"]) == 2
    first = bm["records"][0]
    assert first["trade_date"] == "2026-08-07"
    assert first["source"] == "kline_backfill"
    assert first["daily_return_pct"] == 0.5         # (5 + (-4)) / 2
    last = bm["records"][1]
    assert last["trade_date"] == "2026-08-10"
    assert last["daily_return_pct"] == 0.0          # (1 + (-1)) / 2
    assert abs(last["cumulative_return_pct"] - 0.5) < 0.01  # (1+0.5%)*(1+0%)-1

def test_report_outputs_history_for_frontend(tmp_path, monkeypatch):
    """前端兼容：performance 文件除 records 外，还要有 history（date/total_return）与 holdings。"""
    data = _setup(tmp_path)
    monkeypatch.setattr(pp, "DATA_DIR", str(data))
    monkeypatch.setattr(pp, "SUMMARY_PATH", str(data / "summary.json"))
    monkeypatch.setattr(pp, "PORTFOLIO_PATH", str(data / "paper" / "portfolio.json"))
    monkeypatch.setattr(pp, "PERFORMANCE_PATH", str(data / "paper" / "performance.json"))
    assert pp.report() == 0
    perf = json.loads((data / "paper" / "performance.json").read_text(encoding="utf-8"))
    assert "history" in perf and "holdings" in perf
    assert perf["history"][-1]["date"] == "2026-08-07"
    # 唯一记录：total_return == 当日等权收益
    assert perf["history"][-1]["total_return"] == 0.5
    assert perf["history"][-1]["daily_return"] == 0.5
    # holdings 只含有效持仓（change_pct 非 None 的股票）
    codes = sorted(h["code"] for h in perf["holdings"])
    assert codes == ["000001", "MA"]


def test_report_history_compounds_over_multiple_days(tmp_path, monkeypatch):
    """history 的 total_return 应按日复利累计，而非简单相加。"""
    portfolio = {
        "name": "测试组合", "capital": 1000000, "cash_pct": 0,
        "items": [{"code": "000001", "name": "平安银行", "pct": 100}],
    }
    data = _setup(tmp_path, portfolio=portfolio)
    monkeypatch.setattr(pp, "DATA_DIR", str(data))
    monkeypatch.setattr(pp, "SUMMARY_PATH", str(data / "summary.json"))
    monkeypatch.setattr(pp, "PORTFOLIO_PATH", str(data / "paper" / "portfolio.json"))
    monkeypatch.setattr(pp, "PERFORMANCE_PATH", str(data / "paper" / "performance.json"))

    # 第一天：+10%
    _write_json(data / "summary.json", {
        "items": [{"code": "000001", "change_pct": 10.0, "last_date": "2026-08-07", "status": "ok"}],
    })
    pp.report()
    # 第二天：+10%（累计应为 (1.1*1.1-1)=21%，而不是 20%）
    _write_json(data / "summary.json", {
        "items": [{"code": "000001", "change_pct": 10.0, "last_date": "2026-08-08", "status": "ok"}],
    })
    pp.report()
    perf = json.loads((data / "paper" / "performance.json").read_text(encoding="utf-8"))
    assert len(perf["history"]) == 2
    assert perf["history"][0]["total_return"] == 10.0
    assert perf["history"][1]["total_return"] == 21.0
    # 时间升序
    assert [h["date"] for h in perf["history"]] == ["2026-08-07", "2026-08-08"]


def test_benchmark_outputs_history(tmp_path, monkeypatch):
    """基准文件同样输出 history（total_return 来自 cumulative_return_pct）。"""
    data = _setup(tmp_path)
    monkeypatch.setattr(pp, "DATA_DIR", str(data))
    monkeypatch.setattr(pp, "SUMMARY_PATH", str(data / "summary.json"))
    monkeypatch.setattr(pp, "BENCHMARK_PATH", str(data / "paper" / "benchmark.json"))
    monkeypatch.setattr(pp, "KLINE_DIR", str(data / "kline"))
    assert pp.benchmark() == 0
    bm = json.loads((data / "paper" / "benchmark.json").read_text(encoding="utf-8"))
    assert "history" in bm
    assert bm["history"][-1]["date"] == "2026-08-07"
    assert bm["history"][-1]["total_return"] == 0.5


def test_export_frontend_evolution(tmp_path, monkeypatch):
    """前端格式导出：champion 扁平字段 + llm_analysis 字符串。"""
    report_dir = tmp_path / "strategy_evolution"
    report_dir.mkdir()
    src = report_dir / "weekly_analysis_20260810_120000.json"
    src.write_text(json.dumps({
        "generated_at": "20260810_120000",
        "champion": {
            "name": "global",
            "stats": {"cumulative_return": 1.1, "sharpe": 3.667, "win_rate": 100.0, "max_drawdown": 0.0, "score": 24.72},
            "analysis": {
                "llm_analysis": {
                    "success_factors": ["高盈亏比", "严格止损"],
                    "sustainability": {"score": 5.5, "reasoning": "样本量小"},
                    "improvement_directions": [{"direction": "加过滤", "reason": "提高胜率"}],
                }
            },
        },
        "all_strategies": {"global": {"score": 24.72}},
        "variants": [{"name": "global_v1"}],
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(weekly, "ANALYSIS_DIR", str(report_dir))
    assert weekly.export_frontend_evolution() == 0
    out = json.loads((report_dir / "latest_evolution.json").read_text(encoding="utf-8"))
    ch = out["champion"]
    assert ch["name"] == "global"
    assert ch["cumulative_return"] == 1.1
    assert ch["sharpe_ratio"] == 3.667
    # 前端显示逻辑为 win_rate*100，故导出必须是小数
    assert ch["win_rate"] == 1.0
    assert ch["max_drawdown"] == 0.0
    assert "高盈亏比" in out["llm_analysis"]
    assert "严格止损" in out["llm_analysis"]
    assert "样本量小" in out["llm_analysis"]
    assert out["analysis_date"] == "20260810_120000"
    """组合清单包含全部 portfolio 文件与基准，is_benchmark 标记正确。"""
    data = _setup(tmp_path)
    # 多创建两个组合文件（防守 + 科技）
    _write_json(data / "paper" / "portfolio_defensive.json", {
        "name": "防守红利组合", "color": "#0ea5e9", "risk_profile": "defensive",
        "items": [{"code": "600519", "name": "贵州茅台", "pct": 10}],
    })
    _write_json(data / "paper" / "portfolio_tech.json", {
        "name": "科技成长组合", "color": "#8b5cf6", "risk_profile": "aggressive",
        "items": [{"code": "00700", "name": "腾讯控股", "pct": 10}],
    })
    monkeypatch.setattr(pp, "DATA_DIR", str(data))
    monkeypatch.setattr(pp, "BENCHMARK_PATH", str(data / "paper" / "benchmark.json"))
    monkeypatch.setattr(pp, "MANIFEST_PATH", str(data / "paper" / "manifest.json"))
    assert pp.manifest() == 0
    manifest = json.loads((data / "paper" / "manifest.json").read_text(encoding="utf-8"))
    keys = [e["key"] for e in manifest["portfolios"]]
    assert "steady" in keys and "defensive" in keys and "tech" in keys
    # 普通组合按 key 升序，基准线固定排在最后
    assert keys[-1] == "benchmark"
    assert keys[:-1] == sorted(keys[:-1])
    bench = [e for e in manifest["portfolios"] if e["is_benchmark"]]
    assert len(bench) == 1 and bench[0]["key"] == "benchmark"
    for e in manifest["portfolios"]:
        assert e["file"].endswith(".json")
        assert e["name"]

def test_report_backfills_base_date_from_kline(tmp_path, monkeypatch):
    """首次生成绩效且组合有 base_trade_date 时，用 kline 回填起点当日收益。"""
    portfolio = {
        "name": "测试组合", "capital": 1000000, "cash_pct": 0,
        "base_trade_date": "2026-08-07",
        "items": [
            {"code": "600519", "name": "贵州茅台", "pct": 50},
            {"code": "000001", "name": "平安银行", "pct": 50},
        ],
    }
    summary = {
        "items": [
            {"code": "600519", "change_pct": 1.0, "last_date": "2026-08-10", "status": "ok"},
            {"code": "000001", "change_pct": -1.0, "last_date": "2026-08-10", "status": "ok"},
        ]
    }
    data = _setup(tmp_path, portfolio=portfolio, summary=summary)
    # kline：600519 8/6=10 → 8/7=10.5 (+5%)；000001 8/6=5 → 8/7=4.8 (-4%)
    _write_json(data / "kline" / "600519.json", {
        "dates": ["2026-08-06", "2026-08-07"],
        "kline": [[0, 10, 0, 0], [0, 10.5, 0, 0]], "volume": [1, 1],
    })
    _write_json(data / "kline" / "000001.json", {
        "dates": ["2026-08-06", "2026-08-07"],
        "kline": [[0, 5, 0, 0], [0, 4.8, 0, 0]], "volume": [1, 1],
    })
    monkeypatch.setattr(pp, "DATA_DIR", str(data))
    monkeypatch.setattr(pp, "SUMMARY_PATH", str(data / "summary.json"))
    monkeypatch.setattr(pp, "PORTFOLIO_PATH", str(data / "paper" / "portfolio.json"))
    monkeypatch.setattr(pp, "PERFORMANCE_PATH", str(data / "paper" / "performance.json"))
    monkeypatch.setattr(pp, "KLINE_DIR", str(data / "kline"))
    assert pp.report() == 0
    perf = json.loads((data / "paper" / "performance.json").read_text(encoding="utf-8"))
    assert len(perf["records"]) == 2
    first = perf["records"][0]
    assert first["trade_date"] == "2026-08-07"
    assert first["source"] == "kline_backfill"
    # 加权：(50%×5% + 50%×-4%) = +0.5%
    assert first["portfolio_return_pct"] == 0.5
    last = perf["records"][1]
    assert last["trade_date"] == "2026-08-10"
    assert last["portfolio_return_pct"] == 0.0  # (50%×1% + 50%×-1%)
