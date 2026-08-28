# tests/test_calibration_suggestions.py —— 校准系统修复测试（spec-kit 004 后续）
#
# 覆盖：
#   - 概率门槛读取：真实代码模式 up3 > N；模式缺失 → None（不产生幽灵建议）
#   - 建议生成：directional_accuracy 新口径；门槛缺失/样本不足 → 无幽灵建议
#   - applier：替换失败如实报未生效（返回 False、文件不变）；动量权重实际落地

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "tools"))

import calibration
import apply_calibration


# ============================================================
# 概率门槛读取
# ============================================================

def test_read_probability_threshold_real_pattern(tmp_path, monkeypatch):
    f = tmp_path / "rebalance.py"
    f.write_text('if risk < 40 and up3 > 65:\n    candidates.append(...)\n', encoding="utf-8")
    monkeypatch.setattr(calibration, "REBALANCE_ALL_FILE", f)
    assert calibration._read_probability_threshold() == 65


def test_read_probability_threshold_missing_pattern(tmp_path, monkeypatch):
    f = tmp_path / "rebalance.py"
    f.write_text('if risk < 40:\n    candidates.append(...)\n', encoding="utf-8")
    monkeypatch.setattr(calibration, "REBALANCE_ALL_FILE", f)
    assert calibration._read_probability_threshold() is None


def test_read_probability_threshold_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(calibration, "REBALANCE_ALL_FILE", tmp_path / "nope.py")
    assert calibration._read_probability_threshold() is None


# ============================================================
# 建议生成（新口径，无幽灵建议）
# ============================================================

def _analysis(aggressive_return=3.0, robust_return=-1.0, max_drawdown=-5.0):
    return {
        "portfolio_performance": {
            "aggressive": {"cumulative_return": aggressive_return, "max_drawdown": max_drawdown},
            "robust": {"cumulative_return": robust_return},
        }
    }


def test_suggestions_use_directional_and_real_gate(monkeypatch):
    monkeypatch.setattr(
        calibration, "_fresh_feedback_summary",
        lambda: {"directional_accuracy": 0.31, "decisive_sample_count": 58, "alignment_rate": 0.347},
    )
    monkeypatch.setattr(calibration, "_read_probability_threshold", lambda: 60)
    analyzer = calibration.CalibrationAnalyzer()
    suggestions = analyzer.generate_calibration_suggestions(_analysis(3.0, -1.0))
    by_type = {s["type"]: s for s in suggestions}
    assert "probability_threshold" in by_type
    t = by_type["probability_threshold"]
    assert t["current_value"] == 60
    assert t["suggested_value"] == 65
    assert t["affected_files"] == ["tools/rebalance_all_portfolios.py"]
    assert "31.0%" in t["reason"]
    # 动量建议带具体参数
    m = by_type["portfolio_strategy"]
    assert m["momentum_old"] == 0.75
    assert m["momentum_new"] == 0.85


def test_no_phantom_threshold_when_gate_missing(monkeypatch):
    monkeypatch.setattr(
        calibration, "_fresh_feedback_summary",
        lambda: {"directional_accuracy": 0.31, "decisive_sample_count": 58},
    )
    monkeypatch.setattr(calibration, "_read_probability_threshold", lambda: None)
    analyzer = calibration.CalibrationAnalyzer()
    suggestions = analyzer.generate_calibration_suggestions(_analysis(0.0, 0.0, max_drawdown=-5.0))
    assert all(s["type"] != "probability_threshold" for s in suggestions)


def test_no_threshold_when_directional_none(monkeypatch):
    monkeypatch.setattr(
        calibration, "_fresh_feedback_summary",
        lambda: {"directional_accuracy": None, "decisive_sample_count": 0},
    )
    monkeypatch.setattr(calibration, "_read_probability_threshold", lambda: 60)
    analyzer = calibration.CalibrationAnalyzer()
    suggestions = analyzer.generate_calibration_suggestions(_analysis(0.0, 0.0, max_drawdown=-5.0))
    assert all(s["type"] != "probability_threshold" for s in suggestions)


# ============================================================
# applier：如实报未生效 + 动量落地
# ============================================================

def _applier(tmp_path, monkeypatch, auto=True):
    monkeypatch.setattr(apply_calibration, "BACKUP_DIR", tmp_path / "backups")
    return apply_calibration.CalibrationApplier(auto_mode=auto)


def test_applier_threshold_no_match_reports_false(tmp_path, monkeypatch, capsys):
    f = tmp_path / "rebalance.py"
    f.write_text('if risk < 40:\n    pass\n', encoding="utf-8")
    applier = _applier(tmp_path, monkeypatch)
    suggestion = {
        "type": "probability_threshold", "priority": "high",
        "current_value": 60, "suggested_value": 65,
        "affected_files": [str(f)],
        "implementation": "x", "reason": "y",
    }
    result = applier.apply_probability_threshold(suggestion)
    out = capsys.readouterr().out
    assert result is False
    assert "未生效" in out
    assert "up3 > 65" not in f.read_text(encoding="utf-8")


def test_applier_threshold_applies_when_match(tmp_path, monkeypatch, capsys):
    f = tmp_path / "rebalance.py"
    f.write_text('if risk < 40 and up3 > 60:\n    pass\n', encoding="utf-8")
    applier = _applier(tmp_path, monkeypatch)
    suggestion = {
        "type": "probability_threshold", "priority": "high",
        "current_value": 60, "suggested_value": 65,
        "affected_files": [str(f)],
        "implementation": "x", "reason": "y",
    }
    assert applier.apply_probability_threshold(suggestion) is True
    capsys.readouterr()
    assert "up3 > 65" in f.read_text(encoding="utf-8")


def test_applier_momentum_applies(tmp_path, monkeypatch, capsys):
    f = tmp_path / "aggressive_scan.py"
    f.write_text("score = up5 * 0.4 + up3 * 0.3 + max(0, momentum) * 0.75\n", encoding="utf-8")
    applier = _applier(tmp_path, monkeypatch)
    suggestion = {
        "type": "portfolio_strategy", "priority": "medium",
        "affected_files": [str(f)],
        "implementation": "动量权重 0.75 → 0.85", "reason": "y",
        "momentum_old": 0.75, "momentum_new": 0.85,
    }
    assert applier.apply_portfolio_strategy(suggestion) is True
    capsys.readouterr()
    assert "momentum) * 0.85" in f.read_text(encoding="utf-8")
    assert (tmp_path / "backups").exists()


def test_applier_momentum_no_match_reports_false(tmp_path, monkeypatch, capsys):
    f = tmp_path / "aggressive_scan.py"
    f.write_text("score = up5 * 0.4\n", encoding="utf-8")
    applier = _applier(tmp_path, monkeypatch)
    suggestion = {
        "type": "portfolio_strategy", "priority": "medium",
        "affected_files": [str(f)],
        "implementation": "动量权重 0.75 → 0.85", "reason": "y",
        "momentum_old": 0.75, "momentum_new": 0.85,
    }
    assert applier.apply_portfolio_strategy(suggestion) is False
    assert "未生效" in capsys.readouterr().out


def test_applier_scoring_low_not_applied(tmp_path, monkeypatch, capsys):
    applier = _applier(tmp_path, monkeypatch)
    suggestion = {"type": "scoring_weights", "priority": "low", "reason": "r", "implementation": "i"}
    assert applier.apply_scoring_weights(suggestion) is False
    assert "等待更多数据" in capsys.readouterr().out
