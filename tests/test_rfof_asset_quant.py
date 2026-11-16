
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def research_path(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / "research-outputs/rfof_next_cycle/member1_asset_quant"))
    monkeypatch.syspath_prepend(str(root / "research-outputs/rfof_stability_20261108/tools"))


def test_dividend_and_split_are_returns_per_old_unit():
    from market import total_returns

    dates = pd.date_range("2024-01-02", periods=4)
    nav = pd.Series([100.0, 96.0, 49.0, 50.0], index=dates)
    events = pd.DataFrame({"cash": [5.0, 0.0], "ratio": [1.0, 2.0]}, index=dates[1:3])
    np.testing.assert_allclose(total_returns(nav, events), [0.01, 98 / 96 - 1, 50 / 49 - 1])
    with pytest.raises(ValueError, match="unmapped"):
        total_returns(nav.drop(dates[1]), events)
    with pytest.raises(ValueError, match="positive"):
        total_returns(nav * 0, events)


def test_provider_dividend_units_and_placeholders():
    from fetch_market import read_actions

    page = """
    <table><tr><th>除息日</th><th>每10份分红</th></tr>
    <tr><td>2025-12-30</td><td>每10份派现金11.5530元</td></tr></table>
    <table><tr><th>拆分折算日</th><th>拆分折算比例</th></tr>
    <tr><td>暂无拆分信息!</td><td>暂无拆分信息!</td></tr></table>
    """
    assert read_actions(page) == [("2025-12-30", 1.1553, 1.0)]
    with pytest.raises(ValueError, match="corporate action"):
        read_actions(page.replace("11.5530元", "missing"))


def test_hrp_vt_uses_weighted_risk_and_no_leverage():
    from stability_methods import vol_target_scale, weights_hrp, weights_hrp_vt

    returns = pd.DataFrame({"a": [.03, -.03, .01, -.01] * 15,
                            "b": [.02, .02, -.02, -.02] * 15})
    core = weights_hrp(returns)
    scale = vol_target_scale(returns @ core, target_vol=.08)
    result = weights_hrp_vt(returns, "cash")
    assert 0 < scale < 1
    np.testing.assert_allclose(result[core.index], core * scale)
    assert result["cash"] == pytest.approx(1 - scale)
    assert weights_hrp_vt(returns / 100, "cash")["cash"] == 0
    assert result.sum() == pytest.approx(1.0)


def test_drawdown_includes_loss_on_first_session():
    from backtest import metrics

    days = pd.date_range("2024-01-02", periods=3)
    stats = metrics(pd.Series([-.1, .1, 0.], index=days), pd.Series(0., index=days))
    assert stats["max_dd_pct"] == pytest.approx(-10)


def test_parameter_grid_applies_primary_and_median_separately():
    from stability_verdict import judge_method_results

    windows = ["FullSample", "Bear2015", "Bear2018", "Bear2022", "Bear2026"]
    rows = [("A0", "base", w, -20, 8) for w in windows]
    rows += [("A4", "primary", w, -16, 7.1) for w in windows]
    rows += [("A4", "bad1", "FullSample", -25, 7.1), ("A4", "bad2", "FullSample", -26, 7.1)]
    columns = ["method", "param_id", "window", "max_dd_pct", "ann_ret_pct"]
    decision = judge_method_results(pd.DataFrame(rows, columns=columns), primary_params={"A4": "primary"}).iloc[0]
    assert decision["c1_windows_better"] == 4
    assert decision["c2_full_dd_gain_pp"] == 4
    assert not decision["c2_median_better"]
    assert decision["c3_pass"]
    assert decision["verdict"] == "no_significant_improvement"


def test_futures_trend_is_lagged_and_margin_and_roll_are_additive():
    from backtest import futures_ledger

    dates = pd.bdate_range("2024-01-02", periods=25)
    one = pd.Series([100 + i for i in range(23)] + [60, 61], index=dates)
    quotes = pd.DataFrame({key: one for key in ("AU", "M", "CU")})
    cash = pd.Series(.0001, index=dates[21:])
    frame = futures_ledger(quotes, cash)
    fall = dates[-2]
    expected_roll = .002 * 6 / 252
    assert frame.loc[fall, "B0"] == pytest.approx(60 / 122 - 1)
    assert frame.loc[fall, "B1"] == pytest.approx(frame.loc[fall, "B0"] - expected_roll)
    assert frame.loc[fall, "B2"] == pytest.approx(frame.loc[fall, "B1"] + .85 * .0001)
    assert frame.loc[dates[-1], "B2"] == pytest.approx(.0001)
    with pytest.raises(ValueError, match="missing futures"):
        futures_ledger(quotes.drop(fall), cash)


def test_tax_crosses_bracket_and_equal_sacrifice_is_explicit():
    from retirement import eet_table, income_tax

    assert income_tax(40_000) - income_tax(28_000) == pytest.approx(640)
    rows = eet_table(0.0)
    assert rows["marginal_tax_pct"].tolist() == [3, 10, 20]
    assert rows["annual_tax_saving_cny"].tolist() == [360, 1200, 2400]
    assert rows["eet_end_balance_cny"].tolist() == [12000 * 30] * 3
    assert (rows["net_replacement_gain_pp"].iloc[0] == pytest.approx(0))
    assert rows["net_replacement_gain_pp"].iloc[2] > 0


def test_withdrawal_reserve_is_an_internal_transfer_and_medical_obligation_identical():
    from retirement import annual_withdrawals

    result = annual_withdrawals(np.zeros((1, 26)), np.zeros((1, 26)), np.zeros((1, 26), bool),
                                100_000, dynamic=True, inflation=0, medical_rate=.01)
    assert result["requested_medical"][0, 17] == 0
    assert result["requested_medical"][0, 18] == pytest.approx(1_000)
    assert result["end_balance"][0, 18] == pytest.approx(
        result["end_balance"][0, 17] - result["paid_living"][0, 18] - 1_000)
    assert result["reserve"][0, 18] > 0
    assert result["ruined"][0]


def test_contiguous_blocks_and_seed_reproducibility():
    from retirement import block_indices

    first = block_indices(35, 15, 5, 4, 123)
    second = block_indices(35, 15, 5, 4, 123)
    assert first.shape == (4, 15)
    np.testing.assert_array_equal(first, second)
    assert (np.diff(first.reshape(4, 3, 5), axis=-1) == 1).all()
    with pytest.raises(ValueError, match="block"):
        block_indices(4, 15, 5, 4, 123)


def test_stock_ledger_carries_missing_mark_and_uses_declared_basis():
    from backtest import stock_ledger

    panel = pd.DataFrame([
        ("000001", "2024-01-02", 100., 0.01),
        ("000002", "2024-01-02", 100., None),
        ("000001", "2024-01-03", 50., 0.02),
        ("000002", "2024-01-03", 110., None),
        ("000002", "2024-01-04", 99., None),
    ], columns=["stock_code", "trade_date", "close", "ret"]).assign(
        volume=100, turnover_rate=.1, market_value=1000,
    )
    declarations = pd.DataFrame({
        "stock_code": ["000001", "000002"], "cohort": ["A", "B"],
        "close_basis": ["unadjusted", "forward_adjusted"], "source_table": ["A", "B"],
        "adjustment": ["unadjusted", "adjusted"], "provenance": ["fixture", "fixture"],
        "total_return_available": [True, False],
    })
    ledger, audit = stock_ledger(panel, declarations, cost_bps=0)
    assert audit["missing_stock_date_rows"] == 1
    assert ledger["net_return"].iloc[0] == pytest.approx(.06)
    assert ledger["unmarked_weight"].iloc[1] == pytest.approx(.51 / 1.06)
    assert ledger["net_return"].iloc[1] == pytest.approx(-.10 * .55 / 1.06)


def test_defense_rebalance_has_no_same_day_or_future_information():
    from backtest import defense_ledger
    from market import CASH, ETF_CODES

    dates = pd.bdate_range("2024-02-01", periods=58)
    n = np.arange(len(dates))
    market = pd.DataFrame(
        {code: .009 * np.sin(n * (k + 1) + k) for k, code in enumerate(ETF_CODES)},
        index=dates,
    )
    market[CASH] = .0001
    future = market.copy()
    quarter_open = pd.Timestamp("2024-04-01")
    future.loc[quarter_open:, "510300"] += .02
    left = defense_ledger(market, "A4", lookback=30, min_history=10)
    right = defense_ledger(future, "A4", lookback=30, min_history=10)
    np.testing.assert_allclose(left.loc[:quarter_open].filter(like="w_"),
                               right.loc[:quarter_open].filter(like="w_"))
    np.testing.assert_allclose(left.filter(like="w_").sum(axis=1), 1.0)
    assert left.filter(like="w_").min().min() >= 0


def test_duckdb_reader_reads_only_local_tables_and_keeps_codes(tmp_path):
    pytest.importorskip("duckdb")
    from market import PANEL, open_reader

    p = tmp_path / PANEL
    p.parent.mkdir(parents=True)
    pd.DataFrame({
        "stock_code": ["000037"], "trade_date": ["2024-01-02"], "close": [8.396],
        "volume": [12], "turnover_rate": [.001], "market_value": [10000.], "ret": [None],
    }).to_parquet(p, index=False)
    reader = open_reader(tmp_path, tmp_path, None)
    assert reader.stock_panel().at[0, "stock_code"] == "000037"
    with pytest.raises(FileNotFoundError):
        reader.fund_navs()
    pd.DataFrame({"code": ["017247"], "trade_date": ["2024-01-02"], "nav": [1.1]}).to_csv(
        tmp_path / "fund_nav.csv", index=False,
    )
    assert reader.fund_navs().at[0, "code"] == "017247"
    with pytest.raises(ValueError, match="module:factory"):
        open_reader(tmp_path, tmp_path, "bad")


def test_market_snapshot_rejects_tampering(tmp_path):
    import hashlib
    import json

    from market import snapshot_manifest

    out = {}
    for name in ("actions.csv", "etf_close.csv", "fund_nav.csv", "futures_close.csv"):
        p = tmp_path / name
        payload = f"{name}\n".encode()
        p.write_bytes(payload)
        out[name] = hashlib.sha256(payload).hexdigest()
    (tmp_path / "sources.json").write_text(json.dumps({"snapshot_sha256": out}), encoding="utf-8")
    assert snapshot_manifest(tmp_path)["snapshot_sha256"] == out
    (tmp_path / "actions.csv").write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash mismatch: actions.csv"):
        snapshot_manifest(tmp_path)
