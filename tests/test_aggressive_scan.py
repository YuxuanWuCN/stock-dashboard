"""全库激进扫描工具单元测试。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools.aggressive_scan as ag


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _setup(tmp_path):
    data = tmp_path / "data"
    ranking = {
        "items": [
            {"rank": 1, "code": "AA", "name": "甲", "type": "us", "stale": False,
             "forecast": {"up_probability_3d_pct": 80.0, "up_probability_5d_pct": 70.0}},
            {"rank": 2, "code": "BB", "name": "乙", "type": "us", "stale": False,
             "forecast": {"up_probability_3d_pct": 50.0, "up_probability_5d_pct": 50.0}},
            {"rank": 3, "code": "CC", "name": "丙", "type": "hk", "stale": True,
             "forecast": {"up_probability_3d_pct": 99.0, "up_probability_5d_pct": 99.0}},
        ]
    }
    _write_json(data / "analysis" / "ranking.json", ranking)
    _write_json(data / "analysis" / "AA.json", {"technical": {"return_20d_pct": 30.0, "trend": "uptrend"}})
    _write_json(data / "analysis" / "BB.json", {"technical": {"return_20d_pct": -5.0, "trend": "downtrend"}})
    return data


def test_scan_sorts_and_skips_stale(tmp_path, monkeypatch):
    data = _setup(tmp_path)
    monkeypatch.setattr(ag, "DATA_DIR", str(data))
    rows = ag.scan(top=10)
    # CC 是 stale，应被跳过
    assert len(rows) == 2
    codes = [r["code"] for r in rows]
    assert "CC" not in codes
    # AA 激进分更高：70*0.4 + 80*0.3 + 30*0.85 = 28+24+25.5 = 77.5
    # （动量权重 0.75 → 0.85，2026-08-15 校准调参落地）
    assert rows[0]["code"] == "AA"
    assert abs(rows[0]["aggressive_score"] - 77.5) < 0.01
    # 扫描结果已保存
    out = json.loads((data / "paper" / "aggressive_scan.json").read_text(encoding="utf-8"))
    assert out["generated"] == 2