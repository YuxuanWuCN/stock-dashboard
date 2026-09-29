# -*- coding: utf-8 -*-
"""tests/test_m4_domain_extension.py —— M4 评测扩域（B/C 组）回归。

覆盖：domain B/C 配置合法性、B 域 + W-attn fail-closed、cohort 选取映射、
B 域端到端（无语料路径）跑通且报告并列登记 NO_CORPUS、C 域端到端（含 W-attn）跑通、
门控训练池规模与 gate_min_train_dates 的关系（>126 训练日设计不被降级声明误导）。
全部使用 tmp 合成输入，不碰真实数据目录。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.evaluate_pca_nale_integration import (
    DOMAIN_COHORTS,
    EvaluationConfig,
    EvaluationError,
    gate_min_train_dates_note,
    load_inputs,
    run_evaluation,
)
from tests.test_evaluate_pca_nale_integration import (
    CALENDAR,
    _smoke_config,
    _synthetic_inputs,
)


# ---------------------------------------------------------------------------
# 配置层
# ---------------------------------------------------------------------------

def test_domain_table_has_b_and_c_with_single_cohort_each() -> None:
    assert DOMAIN_COHORTS["B"] == ("student_B",)
    assert DOMAIN_COHORTS["C"] == ("student_C",)
    # 既有域不受影响（回归守卫）
    assert DOMAIN_COHORTS["A"] == ("student_A",)
    assert DOMAIN_COHORTS["AC"] == ("student_A", "student_C")


def test_config_accepts_domains_b_and_c() -> None:
    for domain in ("B", "C"):
        config = _smoke_config(f"ok-{domain}", domain=domain, networks=("W-ind",))
        assert config.domain == domain


@pytest.mark.parametrize("domain", ["D", "BC", "a", ""])
def test_config_rejects_unknown_domain(domain: str) -> None:
    with pytest.raises(EvaluationError, match="domain 只支持"):
        _smoke_config("bad-domain", domain=domain)


def test_domain_b_with_attention_network_fails_closed() -> None:
    # B 组在真实语料库中 0/100 有数据；评测器必须在配置层拒绝，而不是评出零边假结果。
    with pytest.raises(EvaluationError, match="W-attn 不可评"):
        _smoke_config("bad-b-attn", domain="B", networks=("W-ind", "W-attn"))


def test_domain_c_with_attention_network_is_allowed() -> None:
    config = _smoke_config("ok-c-attn", domain="C", networks=("W-ind", "W-attn"))
    assert "W-attn" in config.networks


# ---------------------------------------------------------------------------
# 输入装载：cohort 映射
# ---------------------------------------------------------------------------

def _inputs_with_three_cohorts(root: Path) -> dict[str, Path]:
    """在标准合成输入上扩成 A/B/C 三组 cohort（B 组另给无语料目录）。

    口径声明按真实仓库的声明结构补 B/C 两组（前复权、无申报总收益），
    否则 ``build_declarations`` 会对缺声明 fail-closed。
    """
    paths = _synthetic_inputs(root, codes=60)
    factors = pd.read_csv(paths["factors"], dtype={"code": str})
    factors["cohort_key"] = ["student_A"] * 20 + ["student_B"] * 20 + ["student_C"] * 20
    factors.to_csv(paths["factors"], index=False)

    caliber = json.loads(paths["caliber"].read_text(encoding="utf-8"))
    for group in ("student_B", "student_C"):
        caliber["cohorts"][group] = {
            "close_basis": "forward_adjusted",
            "source_table": "synthetic",
            "adjustment": "forward_adjusted_close_price",
            "provenance": "tests/test_m4_domain_extension.py",
            "total_return_available": False,
            "total_return_column": None,
            "total_return_field": None,
        }
    paths["caliber"].write_text(json.dumps(caliber, ensure_ascii=False), encoding="utf-8")

    # B 组在语料目录里没有任何 jsonl（对应真实仓库中 B 组零语料的事实）
    for path in Path(paths["corpus"]).glob("*.jsonl"):
        code = path.stem
        cohort = factors.loc[factors["code"] == code, "cohort_key"].iloc[0]
        if cohort == "student_B":
            path.unlink()
    return paths


def test_load_inputs_selects_only_requested_domain_codes(tmp_path: Path) -> None:
    paths = _inputs_with_three_cohorts(tmp_path)
    panel = pd.read_csv(paths["panel"], dtype={"stock_code": str})
    for domain, expected_key in (("A", "student_A"), ("B", "student_B"), ("C", "student_C")):
        config = _smoke_config(f"load-{domain}", domain=domain, networks=("W-ind",))
        inputs = load_inputs(paths, config)
        assert len(inputs.codes) == 20
        cohort_codes = set(inputs.codes) & set(panel["stock_code"])
        assert len(cohort_codes) == 20
        assert all(code in set(inputs.codes) for code in cohort_codes)


# ---------------------------------------------------------------------------
# 端到端（合成数据、tmp 根目录）
# ---------------------------------------------------------------------------

def test_end_to_end_domain_b_without_attention(tmp_path: Path) -> None:
    paths = _inputs_with_three_cohorts(tmp_path)
    config = _smoke_config(
        "m4-domain-b-smoke",
        domain="B",
        networks=("W-ind",),
        placebo_networks=("W-ind",),
    )
    summary = run_evaluation(config, paths=paths, root=tmp_path, verbose=False)
    assert summary["n_signal_dates_applied"] >= 1

    report = (tmp_path / "reports/tables/pca_nale_integration/m4-domain-b-smoke/report.md").read_text(
        encoding="utf-8"
    )
    # 第 4 节必须并列登记 B 域专属的不可评网络（无语料），不得静默缺席
    assert "`W-attn`（B 域）" in report
    assert "NO_CORPUS" in report
    manifest = json.loads(
        (tmp_path / "reports/tables/pca_nale_integration/m4-domain-b-smoke/manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["config"]["domain"] == "B"
    assert manifest["universe_size"] == 20


def test_end_to_end_domain_c_includes_attention(tmp_path: Path) -> None:
    paths = _inputs_with_three_cohorts(tmp_path)
    config = _smoke_config(
        "m4-domain-c-smoke",
        domain="C",
        networks=("W-ind", "W-attn"),
        placebo_networks=("W-ind",),
    )
    summary = run_evaluation(config, paths=paths, root=tmp_path, verbose=False)
    assert summary["n_signal_dates_applied"] >= 1
    report = (tmp_path / "reports/tables/pca_nale_integration/m4-domain-c-smoke/report.md").read_text(
        encoding="utf-8"
    )
    # C 域有语料：W-attn 正常评测，不出现 B 域专属的 NO_CORPUS 登记
    assert "NO_CORPUS" not in report
    assert "W-attn" in report


def test_report_gate_line_distinguishes_degraded_from_week1_default(tmp_path: Path) -> None:
    paths = _inputs_with_three_cohorts(tmp_path)
    degraded = _smoke_config(
        "m4-gate-degraded", domain="B", networks=("W-ind",), gate_min_train_dates=2
    )
    run_evaluation(degraded, paths=paths, root=tmp_path, verbose=False)

    base = tmp_path / "reports/tables/pca_nale_integration"
    degraded_report = (base / "m4-gate-degraded/report.md").read_text(encoding="utf-8")
    # 降级口径必须显式声明"降级"，不得与 Week1 默认混同
    assert "降级设置" in degraded_report
    assert "降级设置" not in gate_min_train_dates_note(126)
    assert "fallback" in gate_min_train_dates_note(126)


def test_gate_pool_below_min_train_dates_fails_closed_before_writing(tmp_path: Path) -> None:
    paths = _inputs_with_three_cohorts(tmp_path)
    # 合成日历只有 60 个交易日，训练池远小于 126 ⇒ 必须在创建任何产物目录前整体拒绝
    config = _smoke_config(
        "m4-gate-infeasible", domain="B", networks=("W-ind",), gate_min_train_dates=126
    )
    with pytest.raises(EvaluationError, match="训练池只有"):
        run_evaluation(config, paths=paths, root=tmp_path, verbose=False)
    assert not (tmp_path / "reports/tables/pca_nale_integration/m4-gate-infeasible").exists()
    assert not (tmp_path / "data/processed/pca_nale_integration/m4-gate-infeasible").exists()
