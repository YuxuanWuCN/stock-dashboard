"""tests/test_return_basis.py —— M0 统一收益口径的独立验证.

手算夹具用于验证规则本身；真实面板夹具用于验证规则在 299 股 × 644 日上成立。
断言全部为强断言（BUG-0021 要求：不用 assertIsNotNone / 裸 assertTrue）。
"""

from __future__ import annotations

import math
import warnings

import numpy as np
import pandas as pd
import pytest

from src.data.return_basis import (
    BASIS_SOURCE_VALUES,
    CALIBER_WATERMARK,
    ReturnBasisConfig,
    ReturnBasisError,
    board_price_limit,
    caliber_mixing_report,
    compute_return_basis,
    declared_caliber,
    verify_caliber,
)

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
MASTER_PANEL = ROOT / "data/task_split/csmar_master/csmar_factor_panel_master.csv"
FACTORS_TABLE = ROOT / "data/task_split/factors_768d_all.csv"
DECLARATION_CONFIG = ROOT / "config/data_caliber/csmar_master_close_basis.json"


def _declaration(code: str, basis: str, *, total_return_available: bool = True) -> dict[str, object]:
    return {
        "stock_code": code,
        "close_basis": basis,
        "source_table": "unit-test-fixture",
        "adjustment": "fixture",
        "provenance": "tests/test_return_basis.py",
        "total_return_available": total_return_available,
    }


@pytest.fixture(scope="module")
def real_panel() -> pd.DataFrame:
    return pd.read_csv(
        MASTER_PANEL,
        dtype={"stock_code": str, "trade_date": str},
        usecols=["stock_code", "trade_date", "close", "volume", "turnover_rate", "market_value", "ret"],
    )


@pytest.fixture(scope="module")
def real_declarations() -> pd.DataFrame:
    import json

    spec = json.loads(DECLARATION_CONFIG.read_text(encoding="utf-8"))
    facts = pd.read_csv(FACTORS_TABLE, dtype={"code": str}, usecols=["code", "cohort_key"])
    rows = []
    for code, group in zip(facts["code"], facts["cohort_key"]):
        item = spec["cohorts"][group]
        rows.append(
            {
                "stock_code": code,
                "close_basis": item["close_basis"],
                "source_table": item["source_table"],
                "adjustment": item["adjustment"],
                "provenance": item["provenance"],
                "total_return_available": bool(item.get("total_return_available", False)),
            }
        )
    table = pd.DataFrame(rows)
    panel_codes = set(pd.read_csv(MASTER_PANEL, dtype={"stock_code": str}, usecols=["stock_code"])["stock_code"])
    return table[table["stock_code"].isin(panel_codes)].reset_index(drop=True)


# --------------------------------------------------------------------------- 板块限制
def test_board_price_limit_matches_listing_board() -> None:
    assert math.isclose(board_price_limit("600000"), 0.105, rel_tol=1e-12)
    assert math.isclose(board_price_limit("000001"), 0.105, rel_tol=1e-12)
    assert math.isclose(board_price_limit("300750"), 0.205, rel_tol=1e-12)
    assert math.isclose(board_price_limit("688981"), 0.205, rel_tol=1e-12)
    assert math.isclose(board_price_limit("600000", 0.0), 0.10, rel_tol=1e-12)


def test_board_price_limit_rejects_malformed_code() -> None:
    for bad in ("12345", "1234567", "abcdef", ""):
        with pytest.raises(ReturnBasisError, match="6 位数字字符串"):
            board_price_limit(bad)


# --------------------------------------------------------------------------- 声明表校验
def test_declared_caliber_normalizes_leading_zeros_and_sorts() -> None:
    table = pd.DataFrame([_declaration("1", "unadjusted"), _declaration("000021", "forward_adjusted")])
    out = declared_caliber(table)
    assert out["stock_code"].tolist() == ["000001", "000021"]
    assert out["caliber_watermark"].eq(CALIBER_WATERMARK).all()
    assert bool(out["total_return_available"].iloc[0]) is True


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda d: d.drop(columns=["provenance"]), "缺少列"),
        (lambda d: d.assign(close_basis="mystery"), "close_basis 含非法取值"),
        (lambda d: pd.concat([d, d], ignore_index=True), "重复 stock_code"),
        (lambda d: d.assign(provenance="   "), "不允许为空"),
        (lambda d: d.iloc[0:0], "声明表为空"),
    ],
)
def test_declared_caliber_fails_closed(mutate, match: str) -> None:
    base = pd.DataFrame([_declaration("600000", "unadjusted")])
    with pytest.raises(ReturnBasisError, match=match):
        declared_caliber(mutate(base))


# --------------------------------------------------------------------------- 手算：不复权 close 必须走申报总收益
@pytest.fixture()
def hand_computed_panel() -> pd.DataFrame:
    """三支股票、四天的手算面板.

    600000 (unadjusted, 有申报总收益)：close 在第 3 日腰斩模拟 10 送 10，
        真实总收益应为 0，close 涨幅为 -0.5；
    000021 (forward_adjusted)：close 10 -> 11 -> 11 -> 10.89，日收益 0.1, 0.0, -0.01；
    300750 (forward_adjusted, 无申报总收益)：close 20 -> 22 -> 21.78 -> 24.0，
        日收益 0.1, -0.01, 0.1019...（按手算式在断言里重算）。
    """
    rows = [
        ("600000", "2024-01-02", 20.0, 1_000_000, 0.02, 20_000_000, 0.010),
        ("600000", "2024-01-03", 20.2, 1_000_000, 0.02, 20_200_000, -0.005),
        ("600000", "2024-01-04", 10.1, 2_000_000, 0.01, 20_200_000, 0.0),
        ("600000", "2024-01-05", 10.302, 2_000_000, 0.01, 20_604_000, 0.02),
        ("000021", "2024-01-02", 10.0, 500_000, 0.05, 5_000_000, np.nan),
        ("000021", "2024-01-03", 11.0, 500_000, 0.05, 5_500_000, np.nan),
        ("000021", "2024-01-04", 11.0, 500_000, 0.05, 5_500_000, np.nan),
        ("000021", "2024-01-05", 10.89, 500_000, 0.05, 5_445_000, np.nan),
        ("300750", "2024-01-02", 20.0, 300_000, 0.03, 6_000_000, np.nan),
        ("300750", "2024-01-03", 22.0, 300_000, 0.03, 6_600_000, np.nan),
        ("300750", "2024-01-04", 21.78, 300_000, 0.03, 6_534_000, np.nan),
        ("300750", "2024-01-05", 24.0, 300_000, 0.03, 7_200_000, np.nan),
    ]
    return pd.DataFrame(
        rows, columns=["stock_code", "trade_date", "close", "volume", "turnover_rate", "market_value", "ret"]
    )


@pytest.fixture()
def hand_computed_declarations() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _declaration("600000", "unadjusted", total_return_available=True),
            _declaration("000021", "forward_adjusted", total_return_available=False),
            _declaration("300750", "forward_adjusted", total_return_available=False),
        ]
    )


def test_unadjusted_split_day_uses_declared_total_return_not_price_crash(
    hand_computed_panel: pd.DataFrame, hand_computed_declarations: pd.DataFrame
) -> None:
    out = compute_return_basis(hand_computed_panel, hand_computed_declarations)
    sub = out[out["stock_code"] == "600000"].reset_index(drop=True)

    # close 10.1/20.2 - 1 = -0.5 是不复权除权跳空，申报总收益为 0.0
    assert math.isclose(float(sub.loc[2, "r_close"]), -0.5, rel_tol=1e-12)
    assert bool(sub.loc[2, "beyond_limit"]) is True
    assert math.isclose(float(sub.loc[2, "basis_return"]), 0.0, abs_tol=1e-15)
    assert str(sub.loc[2, "basis_source"]) == "declared_total_return"

    # 首日也有申报总收益，因此不依赖 close，仍然可用
    assert math.isclose(float(sub.loc[0, "basis_return"]), 0.010, rel_tol=1e-12)
    assert math.isclose(float(sub.loc[1, "basis_return"]), -0.005, rel_tol=1e-12)
    assert math.isclose(float(sub.loc[3, "basis_return"]), 0.02, rel_tol=1e-12)


def test_forward_adjusted_close_return_matches_hand_computation(
    hand_computed_panel: pd.DataFrame, hand_computed_declarations: pd.DataFrame
) -> None:
    out = compute_return_basis(hand_computed_panel, hand_computed_declarations)

    a = out[out["stock_code"] == "000021"]["basis_return"].tolist()
    assert a[0] is None or pd.isna(a[0])
    assert math.isclose(float(a[1]), 0.1, rel_tol=1e-12)
    assert math.isclose(float(a[2]), 0.0, rel_tol=1e-12)
    assert math.isclose(float(a[3]), 10.89 / 11.0 - 1.0, rel_tol=1e-12)

    b = out[out["stock_code"] == "300750"]["basis_return"].tolist()
    assert math.isclose(float(b[1]), 0.1, rel_tol=1e-12)
    assert math.isclose(float(b[2]), 21.78 / 22.0 - 1.0, rel_tol=1e-12)
    assert math.isclose(float(b[3]), 24.0 / 21.78 - 1.0, rel_tol=1e-12)
    assert set(out["basis_source"]) <= set(BASIS_SOURCE_VALUES)


def test_first_day_rows_are_unavailable_and_never_zero(
    hand_computed_panel: pd.DataFrame, hand_computed_declarations: pd.DataFrame
) -> None:
    out = compute_return_basis(hand_computed_panel, hand_computed_declarations)
    first = out[out["basis_source"] == "unavailable"]
    # 两支"前复权且无申报总收益"的股票首日不可用；600000 首日有申报总收益故可用
    assert sorted(first["stock_code"].tolist()) == ["000021", "300750"]
    assert first["trade_date"].tolist() == ["2024-01-02", "2024-01-02"]
    assert bool(first["basis_return"].isna().all()) is True
    # 关键：缺失首日保留为 NaN，没有被填成 0.0 收益
    assert bool(first["r_close"].isna().all()) is True
    assert len(first) == 2


def test_unadjusted_without_declared_return_is_not_fabricated() -> None:
    panel = pd.DataFrame(
        [
            ("000002", "2024-01-02", 30.0, 100_000, 0.04, 3_000_000, np.nan),
            ("000002", "2024-01-03", 15.0, 200_000, 0.02, 3_000_000, np.nan),
        ],
        columns=["stock_code", "trade_date", "close", "volume", "turnover_rate", "market_value", "ret"],
    )
    decl = pd.DataFrame([_declaration("000002", "unadjusted", total_return_available=False)])
    out = compute_return_basis(panel, decl)
    assert math.isclose(float(out.loc[1, "r_close"]), -0.5, rel_tol=1e-12)
    assert pd.isna(out.loc[1, "basis_return"])
    assert str(out.loc[1, "basis_source"]) == "unavailable"


# --------------------------------------------------------------------------- 复核判据
def test_verify_caliber_confirms_forward_adjusted_identity(
    hand_computed_panel: pd.DataFrame, hand_computed_declarations: pd.DataFrame
) -> None:
    verification = verify_caliber(hand_computed_panel, hand_computed_declarations, ReturnBasisConfig(min_rows_for_verdict=2))
    table = verification.set_index("stock_code")
    # 手算面板样本仅 3-4 行/支，恒等式平坦 -> 前复权判定为证据不足（inconclusive），
    # 而不复权 600000 因存在越限跳空被确认。
    assert table.loc["600000", "verdict"] == "confirmed"
    assert int(table.loc["600000", "n_beyond_limit"]) == 1
    assert table.loc["000021", "verdict"] == "inconclusive"


def test_verify_caliber_detects_forward_adjusted_convergence() -> None:
    """构造恒等式从 1.08 单调收敛到 1.000 的前复权序列（无越限跳空）。"""
    n = 250
    dates = pd.date_range("2024-01-02", periods=n, freq="B").strftime("%Y-%m-%d")
    shares = np.full(n, 1_000_000.0)
    close = 10.0 * np.ones(n)
    # 真实成交价（市值用）从 10.8 收敛到 10.0：close 记录的是前复权价
    real_price = np.linspace(10.8, 10.0, n)
    panel = pd.DataFrame(
        {
            "stock_code": ["000001"] * n,
            "trade_date": dates,
            "close": close,
            "volume": np.full(n, 50_000.0),
            "turnover_rate": np.full(n, 0.05),
            "market_value": real_price * shares,
            "ret": np.full(n, np.nan),
        }
    )
    decl = pd.DataFrame([_declaration("000001", "forward_adjusted", total_return_available=False)])
    verification = verify_caliber(panel, decl)
    row = verification.iloc[0]
    assert int(row["n_beyond_limit"]) == 0
    assert float(row["identity_first"]) == pytest.approx(1.08, rel=1e-9)
    assert float(row["identity_last"]) == pytest.approx(1.0, rel=1e-9)
    assert str(row["verdict"]) == "confirmed"


def test_verify_caliber_does_not_contradict_unadjusted_on_drift_alone() -> None:
    """恒等式漂移不构成"不复权"的反证：解禁/增发同样改变流通股本。

    早期版本据此把 36 支 A 组股票误判为 contradicted（`scratch/debug_contradicted.py`
    实测），本测试锁定修正后的语义：无总收益可比对时只记 inconclusive。
    """
    n = 250
    dates = pd.date_range("2024-01-02", periods=n, freq="B").strftime("%Y-%m-%d")
    real_price = np.linspace(10.8, 10.0, n)
    panel = pd.DataFrame(
        {
            "stock_code": ["000001"] * n,
            "trade_date": dates,
            "close": np.full(n, 10.0),
            "volume": np.full(n, 50_000.0),
            "turnover_rate": np.full(n, 0.05),
            "market_value": real_price * 1_000_000.0,
            "ret": np.full(n, np.nan),
        }
    )
    decl = pd.DataFrame([_declaration("000001", "unadjusted", total_return_available=False)])
    row = verify_caliber(panel, decl).iloc[0]
    assert str(row["verdict"]) == "inconclusive"
    assert float(row["identity_drift"]) > 0.01
    assert "股本结构变动" in str(row["reason"])


def test_verify_caliber_contradicts_unadjusted_when_close_equals_total_return() -> None:
    """真反证：声明不复权，但 close 日收益与申报总收益逐行全等 ⇒ close 已复权。"""
    n = 250
    dates = pd.date_range("2024-01-02", periods=n, freq="B").strftime("%Y-%m-%d")
    close = 10.0 * np.cumprod(1.0 + np.full(n, 0.001))
    panel = pd.DataFrame(
        {
            "stock_code": ["600000"] * n,
            "trade_date": dates,
            "close": close,
            "volume": np.full(n, 50_000.0),
            "turnover_rate": np.full(n, 0.05),
            "market_value": close * 1_000_000.0,
            "ret": np.r_[np.nan, np.diff(close) / close[:-1]],
        }
    )
    decl = pd.DataFrame([_declaration("600000", "unadjusted", total_return_available=True)])
    row = verify_caliber(panel, decl).iloc[0]
    assert str(row["verdict"]) == "contradicted"
    assert "逐行全等" in str(row["reason"])


def test_contradicted_stock_is_excluded_from_basis() -> None:
    n = 200
    dates = pd.date_range("2024-01-02", periods=n, freq="B").strftime("%Y-%m-%d")
    close = np.full(n, 10.0)
    close[100] = 4.0  # -60%：复权序列不可能出现
    panel = pd.DataFrame(
        {
            "stock_code": ["600000"] * n,
            "trade_date": dates,
            "close": close,
            "volume": np.full(n, 10_000.0),
            "turnover_rate": np.full(n, 0.01),
            "market_value": close * 1_000_000.0,
            "ret": np.full(n, np.nan),
        }
    )
    decl = pd.DataFrame([_declaration("600000", "forward_adjusted", total_return_available=False)])
    out = compute_return_basis(panel, decl)
    assert str(out["basis_source"].iloc[101]) == "unavailable"
    assert int(out["basis_return"].notna().sum()) == 0


# --------------------------------------------------------------------------- 不变量
def test_row_order_invariance(
    hand_computed_panel: pd.DataFrame, hand_computed_declarations: pd.DataFrame
) -> None:
    shuffled = hand_computed_panel.sample(frac=1.0, random_state=11)
    frozen = verify_caliber(hand_computed_panel, hand_computed_declarations, ReturnBasisConfig(min_rows_for_verdict=2))
    left = compute_return_basis(hand_computed_panel, hand_computed_declarations, verification=frozen)
    right = compute_return_basis(shuffled, hand_computed_declarations, verification=frozen)

    assert list(left.columns) == [
        "stock_code",
        "trade_date",
        "close",
        "market_value",
        "declared_total_return",
        "r_close",
        "identity_ratio",
        "price_limit",
        "close_basis",
        "beyond_limit",
        "basis_return",
        "basis_source",
        "caliber_watermark",
    ]
    assert left.shape == right.shape == (12, 13)
    assert left["stock_code"].tolist() == right["stock_code"].tolist()
    assert left["trade_date"].tolist() == right["trade_date"].tolist()
    assert left["basis_return"].isna().tolist() == right["basis_return"].isna().tolist()
    assert np.allclose(
        left["basis_return"].fillna(-999.0).to_numpy(dtype="float64"),
        right["basis_return"].fillna(-999.0).to_numpy(dtype="float64"),
        rtol=0.0,
        atol=1e-15,
    )
    assert left["basis_source"].tolist() == right["basis_source"].tolist()
    pd.testing.assert_frame_equal(left, right)


def test_future_perturbation_cannot_change_past_basis(
    hand_computed_panel: pd.DataFrame, hand_computed_declarations: pd.DataFrame
) -> None:
    """时间可回放：改未来行情不得改历史 `basis_return`（须传冻结复核）。"""
    frozen = verify_caliber(hand_computed_panel, hand_computed_declarations, ReturnBasisConfig(min_rows_for_verdict=2))
    before = compute_return_basis(hand_computed_panel, hand_computed_declarations, verification=frozen)

    perturbed = hand_computed_panel.copy()
    mask = perturbed["trade_date"] > "2024-01-04"
    perturbed.loc[mask, "close"] *= 1.7
    perturbed.loc[mask, "market_value"] *= 0.3
    after = compute_return_basis(perturbed, hand_computed_declarations, verification=frozen)

    cut = before["trade_date"] <= "2024-01-04"
    left = before.loc[cut, ["stock_code", "trade_date", "basis_return"]].reset_index(drop=True)
    right = after.loc[after["trade_date"] <= "2024-01-04", ["stock_code", "trade_date", "basis_return"]].reset_index(drop=True)
    assert left.equals(right)
    assert bool(left["basis_return"].notna().any())


def test_missing_verification_warns_about_full_sample_leakage(
    hand_computed_panel: pd.DataFrame, hand_computed_declarations: pd.DataFrame
) -> None:
    with pytest.warns(UserWarning, match="全样本"):
        compute_return_basis(hand_computed_panel, hand_computed_declarations, ReturnBasisConfig(min_rows_for_verdict=2))


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda p: p.drop(columns=["turnover_rate"]), "缺少必需列"),
        (lambda p: pd.concat([p, p], ignore_index=True), "重复键"),
        (lambda p: p.assign(close=lambda d: d["close"].mask(d.index == 0, 0.0)), "非正值"),
        (lambda p: p.assign(trade_date=lambda d: d["trade_date"].mask(d.index == 1, "not-a-date")), "无法解析"),
        (lambda p: p.assign(stock_code=lambda d: d["stock_code"].mask(d.index == 2, "xx0021")), "非法证券代码"),
        (lambda p: p.iloc[0:0], "面板为空"),
    ],
)
def test_compute_return_basis_fails_closed_on_bad_input(
    mutate, match: str, hand_computed_panel: pd.DataFrame, hand_computed_declarations: pd.DataFrame
) -> None:
    cfg = ReturnBasisConfig(min_rows_for_verdict=2)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with pytest.raises(ReturnBasisError, match=match):
            compute_return_basis(mutate(hand_computed_panel), hand_computed_declarations, cfg)


def test_stock_without_declaration_is_rejected(
    hand_computed_panel: pd.DataFrame, hand_computed_declarations: pd.DataFrame
) -> None:
    cfg = ReturnBasisConfig(min_rows_for_verdict=2)
    trimmed = hand_computed_declarations[hand_computed_declarations["stock_code"] != "300750"]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with pytest.raises(ReturnBasisError, match="无口径声明|缺声明|拒绝"):
            compute_return_basis(hand_computed_panel, trimmed, cfg)


@pytest.mark.parametrize("bad", [(0.0, 0.01, 120), (0.005, -1.0, 120), (0.005, 0.01, 1), (0.005, 0.01, 120, "")])
def test_config_validates_its_own_parameters(bad) -> None:
    with pytest.raises(ReturnBasisError):
        if len(bad) == 4:
            ReturnBasisConfig(bad[0], bad[1], bad[2], total_return_column=bad[3])
        else:
            ReturnBasisConfig(*bad)


# --------------------------------------------------------------------------- 真实数据
def test_real_panel_basis_has_no_fabricated_crashes(
    real_panel: pd.DataFrame, real_declarations: pd.DataFrame
) -> None:
    """真实面板：统一口径后不得残留任何越过涨跌停的"收益"。"""
    frozen = verify_caliber(real_panel, real_declarations)
    out = compute_return_basis(real_panel, real_declarations, verification=frozen)

    assert len(out) == len(real_panel) == 192199
    assert out["stock_code"].nunique() == 299
    assert int((frozen["verdict"] == "contradicted").sum()) == 0
    assert set(frozen["verdict"]) <= {"confirmed", "inconclusive"}

    usable = out.dropna(subset=["basis_return"])
    assert len(usable) == 191999
    violations = usable[usable["basis_return"].abs() > usable["price_limit"]]
    assert len(violations) == 0, f"仍存在越限伪收益 {len(violations)} 行"
    assert float(usable["basis_return"].abs().max()) < 0.2006

    counts = out["basis_source"].value_counts().to_dict()
    assert counts["declared_total_return"] == 63399
    assert counts["forward_adjusted_close_return"] == 128600
    assert counts["unavailable"] == 200  # 仅 B/C 各一支的首日


def test_real_unadjusted_cohort_carries_real_exrights_artifacts(
    real_panel: pd.DataFrame, real_declarations: pd.DataFrame
) -> None:
    """A 组（不复权）必须被复核确认存在除权痕迹，否则口径声明可疑。"""
    frozen = verify_caliber(real_panel, real_declarations)
    unadjusted = frozen[frozen["declared_basis"] == "unadjusted"]
    assert len(unadjusted) == 99
    assert (unadjusted["verdict"] == "confirmed").all()
    assert int(unadjusted["n_beyond_limit"].sum()) == 12
    assert float(unadjusted["identity_drift"].max()) >= 0.0

    forward = frozen[frozen["declared_basis"] == "forward_adjusted"]
    assert len(forward) == 200
    assert int(forward["n_beyond_limit"].sum()) == 0
    # 155/200 有可观察的收敛证据，其余 45 支窗口内无公司行为（证据不足，非矛盾）
    assert int((forward["verdict"] == "confirmed").sum()) == 155
    assert int((forward["verdict"] == "inconclusive").sum()) == 45


def test_real_panel_cohort_assignment_matches_declaration(
    real_panel: pd.DataFrame, real_declarations: pd.DataFrame
) -> None:
    frozen = verify_caliber(real_panel, real_declarations)
    out = compute_return_basis(real_panel, real_declarations, verification=frozen)
    declared = out.groupby("close_basis")["stock_code"].nunique().to_dict()
    assert declared == {"forward_adjusted": 200, "unadjusted": 99}

    unadj = out[out["close_basis"] == "unadjusted"]
    assert int(unadj["beyond_limit"].sum()) == 12
    adj = out[out["close_basis"] == "forward_adjusted"]
    assert int(adj["beyond_limit"].sum()) == 0
    # 不复权组的收益全部来自申报总收益，绝不来自越限 close 跳空
    assert set(unadj["basis_source"]) == {"declared_total_return"}


def test_caliber_mixing_quantifies_a_group_dividend_loss(
    real_panel: pd.DataFrame, real_declarations: pd.DataFrame
) -> None:
    """误用 close 当收益的代价必须被量化：A 组年化约 3.1%。"""
    frozen = verify_caliber(real_panel, real_declarations)
    out = compute_return_basis(real_panel, real_declarations, verification=frozen)
    mixing = caliber_mixing_report(out)
    assert mixing["n_compared"] == pytest.approx(63300.0, rel=1e-9)
    assert 0.02 < mixing["annualized_gap"] < 0.045
    assert mixing["max_abs_daily_gap"] > 0.5
    assert 0.001 < mixing["share_gap_gt_1pct"] < 0.01
    assert mixing["coverage"] == pytest.approx(191999 / 192199, rel=1e-9)
    assert mixing["rows_basis_unavailable"] == pytest.approx(200.0, rel=1e-9)


def test_declaration_config_covers_every_panel_stock(real_declarations: pd.DataFrame) -> None:
    panel_codes = set(
        pd.read_csv(MASTER_PANEL, dtype={"stock_code": str}, usecols=["stock_code"])["stock_code"].unique()
    )
    declared = set(real_declarations["stock_code"])
    assert declared == panel_codes
    assert len(declared) == 299
    assert np.isin(real_declarations["close_basis"], ["forward_adjusted", "unadjusted"]).all()
