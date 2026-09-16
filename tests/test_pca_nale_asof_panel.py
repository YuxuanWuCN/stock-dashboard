# -*- coding: utf-8 -*-
"""tests/test_pca_nale_asof_panel.py —— M2 as-of S0 面板工厂回归。

独立复核重点（不依赖门禁退出码、不依赖另一个 Agent 的结论）：
  1. **交易日历标签**：跨停牌/退市的 h 日标签按**日历**计数，用手算乘积逐位验证（F10 缺陷的反向守卫）；
  2. **训练期定标**：改动 ``cutoff`` 之后的特征/价格/市值，**不得**改变此前任何信号日的 S0 与 PC 得分
     （前视通道的时间往返测试）；
  3. **缺失即不可用**：缺特征的行必须出现在面板里并写明原因，S0 为 NaN，**绝不填 0**；
  4. **符号确定性**：把全部特征取反后 S0 必须不变（PCA 符号任意 + 对齐规则）；
  5. **NOT_ASOF 族**：静态 768 维嵌入族在任何配置下都被拒绝。
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from src.data.pca_nale_asof_panel import (
    ASOF_PANEL_VERSION,
    DECLARED_BIAS_WARNING,
    FEATURE_FAMILIES,
    NEUTRALIZATION_VERSION,
    PCA_VERSION,
    S0_PC5_PRIOR_VERSION,
    S0_VERSION,
    STATIC_EMBEDDING_FAMILY,
    AsofPanelConfig,
    AsofPanelError,
    _build_pca_engine,
    align_pca_signs,
    align_to_calendar,
    build_asof_panel,
    feature_family_columns,
    forward_return_labels,
    load_corpus_records,
    text_flow_features,
    trading_calendar_from_panel,
)

TECH_FEATURES = FEATURE_FAMILIES["price_technical_v1"]
FUND_FEATURES = FEATURE_FAMILIES["fundamental_v1"]
CALENDAR = tuple(pd.bdate_range("2024-01-01", periods=40).strftime("%Y-%m-%d"))
CODES = tuple(f"0000{i:02d}" for i in range(1, 13))
INDUSTRIES = {code: ("银行" if i < 4 else "白酒" if i < 8 else "医药") for i, code in enumerate(CODES)}


def _panel_fixture(seed: int = 7, drop: dict[str, list[str]] | None = None) -> pd.DataFrame:
    """合成主面板：12 支 × 40 交易日；可选删除若干 (code, date) 行以模拟停牌/退市。"""
    rng = np.random.default_rng(seed)
    rows = []
    for i, code in enumerate(CODES):
        price = 10.0 + i
        for j, date in enumerate(CALENDAR):
            price *= 1.0 + 0.004 * np.sin(i + j / 3.0) + float(rng.normal(0, 0.004))
            rows.append(
                {
                    "stock_code": code,
                    "trade_date": date,
                    "close": round(price, 4),
                    "market_value": 1e9 * (1.0 + i * 0.2) * (1.0 + 0.01 * j),
                    "sub_industry": INDUSTRIES[code],
                }
            )
    panel = pd.DataFrame(rows)
    for code, dates in (drop or {}).items():
        panel = panel[~((panel["stock_code"] == code) & (panel["trade_date"].isin(dates)))]
    return panel.reset_index(drop=True)


def _feature_frame(panel: pd.DataFrame, seed: int = 11, family: str = "price_technical_v1") -> pd.DataFrame:
    """合成特征表：确定性的"技术类"因子，与日期/代码相关但不可从价格直接反推。"""
    rng = np.random.default_rng(seed)
    columns = FEATURE_FAMILIES[family] if family != "text_flow_v1" else ()
    frame = panel.loc[:, ["stock_code", "trade_date"]].copy()
    code_index = {code: i for i, code in enumerate(CODES)}
    for column in columns:
        base = rng.normal(0.0, 1.0, size=len(CODES))
        frame[column] = [
            base[code_index[code]] + 0.05 * (int(date[-2:]) % 10)
            for code, date in zip(frame["stock_code"], frame["trade_date"])
        ]
    return frame


def _basis_fixture(panel: pd.DataFrame, seed: int = 5) -> pd.DataFrame:
    """合成统一口径收益面板：行集合与主面板**逐一对应**（停牌日没有收益行，与 M0 一致）。"""
    rng = np.random.default_rng(seed)
    codes = sorted(panel["stock_code"].unique())
    noise = {code: rng.normal(0.0005, 0.01, size=len(CALENDAR)) for code in codes}
    position = {date: j for j, date in enumerate(CALENDAR)}
    rows = []
    for code, date in zip(panel["stock_code"], panel["trade_date"]):
        j = position[date]
        rows.append(
            {
                "stock_code": code,
                "trade_date": date,
                "basis_return": float(noise[code][j]) if j > 0 else np.nan,
                "basis_source": "declared_total_return" if j > 0 else "unavailable",
            }
        )
    return pd.DataFrame(rows)


def _config(**overrides) -> AsofPanelConfig:
    params = dict(
        feature_family="price_technical_v1",
        n_components=5,
        train_window_days=10,
        min_train_rows=40,
        min_cross_section=8,
        horizons=(1, 5),
        signal_dates=CALENDAR[15:18],
    )
    params.update(overrides)
    return AsofPanelConfig(**params)


def _build(panel: pd.DataFrame | None = None, features: pd.DataFrame | None = None, config=None):
    panel = _panel_fixture() if panel is None else panel
    features = _feature_frame(panel) if features is None else features
    basis = _basis_fixture(panel)
    return build_asof_panel(
        features,
        panel,
        basis,
        CALENDAR,
        tuple(sorted(panel["stock_code"].unique())),
        config or _config(),
        corpus_version="fixture:test",
    )


# ---------------------------------------------------------------------------
# 1. 交易日历与占位行
# ---------------------------------------------------------------------------

def test_trading_calendar_is_sorted_unique_and_format_checked() -> None:
    panel = _panel_fixture()
    calendar = trading_calendar_from_panel(panel)

    assert calendar == CALENDAR
    assert list(calendar) == sorted(set(calendar))


def test_trading_calendar_rejects_bad_date_format() -> None:
    panel = _panel_fixture()
    broken = panel.copy()
    broken.loc[0, "trade_date"] = "2024/01/01"

    with pytest.raises(AsofPanelError, match="YYYY-MM-DD"):
        trading_calendar_from_panel(broken)


def test_align_to_calendar_marks_suspension_delisting_and_not_listed() -> None:
    suspended_dates = list(CALENDAR[10:13])
    panel = _panel_fixture(drop={"000001": suspended_dates})
    # 让 000012 在日历结束前 5 天退市（末行早于全池末日）
    panel = panel[~((panel["stock_code"] == "000012") & (panel["trade_date"] >= CALENDAR[35]))]
    aligned = align_to_calendar(panel, CALENDAR, CODES)

    assert len(aligned) == len(CODES) * len(CALENDAR)
    assert int(aligned["row_present"].sum()) == len(panel)
    status = aligned.set_index(["stock_code", "trade_date"])["status"]
    assert status[("000001", CALENDAR[9])] == "trading"
    assert status[("000001", CALENDAR[10])] == "suspended"
    assert status[("000001", CALENDAR[12])] == "suspended"
    assert status[("000001", CALENDAR[13])] == "trading"
    assert status[("000012", CALENDAR[36])] == "delisted"
    assert status[("000012", CALENDAR[39])] == "delisted"


def test_align_to_calendar_flags_not_listed_before_first_row() -> None:
    panel = _panel_fixture()
    panel = panel[~((panel["stock_code"] == "000002") & (panel["trade_date"] < CALENDAR[5]))]
    aligned = align_to_calendar(panel, CALENDAR, CODES)
    status = aligned.set_index(["stock_code", "trade_date"])["status"]

    assert status[("000002", CALENDAR[0])] == "not_listed"
    assert status[("000002", CALENDAR[4])] == "not_listed"
    assert status[("000002", CALENDAR[5])] == "trading"


# ---------------------------------------------------------------------------
# 2. 前瞻标签：必须按交易日历计数（F10 反向守卫）
# ---------------------------------------------------------------------------

def test_forward_label_is_hand_computed_on_calendar_grid() -> None:
    """手算：干净窗口内 5 日标签 = 连续 5 个日历交易日的复利收益乘积。"""
    panel = _panel_fixture()
    basis = _basis_fixture(panel)
    labels = forward_return_labels(basis, CALENDAR, CODES, horizons=(5,))

    returns = (
        basis[basis["stock_code"] == "000001"]
        .set_index("trade_date")["basis_return"]
        .reindex(CALENDAR)
    )
    expected = np.prod([1.0 + returns[CALENDAR[10 + k]] for k in range(1, 6)]) - 1.0
    got = labels.set_index(["stock_code", "trade_date"]).loc[("000001", CALENDAR[10]), "label_5"]

    assert got == pytest.approx(expected, rel=0, abs=1e-15)
    assert bool(labels.set_index(["stock_code", "trade_date"]).loc[("000001", CALENDAR[10]), "label_ok_5"]) is True


def test_suspension_inside_horizon_is_refused_while_naive_shift_would_lie() -> None:
    """反向能力守卫：停牌落在视界内时**按日历**必须拒绝，而"按可用行偏移"会给出一个假数字。

    这正是 F10 的实测缺陷：`groupby(code).shift(-h)` 数的是可用行，对停牌 14 天的股票，
    所谓"5 日"标签实际横跨约 19 个交易日。
    """
    panel = _panel_fixture(drop={"000001": list(CALENDAR[12:15])})
    basis = _basis_fixture(panel)
    labels = forward_return_labels(basis, CALENDAR, CODES, horizons=(5,))
    row = labels.set_index(["stock_code", "trade_date"]).loc[("000001", CALENDAR[10])]

    assert pd.isna(row["label_5"])
    assert bool(row["label_ok_5"]) is False
    assert row["label_reason_5"] == "suspended_inside_horizon"

    # 旧写法（按可用行偏移）会跳过停牌日、把更远的收益当成"5 日"，且是个有限数字
    returns = (
        basis[basis["stock_code"] == "000001"]
        .set_index("trade_date")["basis_return"]
        .reindex(CALENDAR)
    )
    available = returns.dropna()
    naive = np.prod([1.0 + available.iloc[11 + k] for k in range(5)]) - 1.0
    assert np.isfinite(naive)
    assert available.index[16] > CALENDAR[15]  # 证明 naive 确实跨过了停牌日


def test_forward_label_refused_across_suspension_inside_horizon() -> None:
    panel = _panel_fixture(drop={"000001": list(CALENDAR[21:23])})
    basis = _basis_fixture(panel)
    labels = forward_return_labels(basis, CALENDAR, CODES, horizons=(5,))
    row = labels.set_index(["stock_code", "trade_date"]).loc[("000001", CALENDAR[20])]

    assert pd.isna(row["label_5"])
    assert bool(row["label_ok_5"]) is False
    assert row["label_reason_5"] == "suspended_inside_horizon"


def test_forward_label_refused_for_delisted_and_not_listed_rows() -> None:
    panel = _panel_fixture()
    panel = panel[~((panel["stock_code"] == "000012") & (panel["trade_date"] >= CALENDAR[35]))]
    basis = _basis_fixture(panel)
    labels = forward_return_labels(basis, CALENDAR, CODES, horizons=(5,))
    indexed = labels.set_index(["stock_code", "trade_date"])

    delisted = indexed.loc[("000012", CALENDAR[36])]
    assert pd.isna(delisted["label_5"])
    assert delisted["label_reason_5"] == "delisted_on_signal_date"

    tail = indexed.loc[("000012", CALENDAR[34])]
    assert pd.isna(tail["label_5"])
    assert tail["label_reason_5"] == "delisted_inside_horizon"


def test_forward_label_refused_on_not_listed_row() -> None:
    panel = _panel_fixture()
    panel = panel[~((panel["stock_code"] == "000002") & (panel["trade_date"] < CALENDAR[3]))]
    basis = _basis_fixture(panel)
    labels = forward_return_labels(basis, CALENDAR, CODES, horizons=(5,))
    row = labels.set_index(["stock_code", "trade_date"]).loc[("000002", CALENDAR[1])]

    assert pd.isna(row["label_5"])
    assert row["label_reason_5"] == "not_listed_on_signal_date"


def test_forward_label_refused_when_calendar_runs_out() -> None:
    basis = _basis_fixture(_panel_fixture())
    labels = forward_return_labels(basis, CALENDAR, CODES, horizons=(5,))
    last = labels.set_index(["stock_code", "trade_date"]).loc[("000001", CALENDAR[-1])]

    assert pd.isna(last["label_5"])
    assert last["label_reason_5"] == "insufficient_calendar_after"


def test_forward_label_never_uses_unavailable_basis_return() -> None:
    basis = _basis_fixture(_panel_fixture())
    basis.loc[
        (basis["stock_code"] == "000003") & (basis["trade_date"] == CALENDAR[16]), "basis_return"
    ] = np.nan
    labels = forward_return_labels(basis, CALENDAR, CODES, horizons=(5,))
    row = labels.set_index(["stock_code", "trade_date"]).loc[("000003", CALENDAR[15])]

    assert pd.isna(row["label_5"])
    assert row["label_reason_5"] == "return_unavailable_inside_horizon"
    # 该支其他不受影响的信号日仍必须有标签（不得因一处缺失丢掉整支）
    other = labels.set_index(["stock_code", "trade_date"]).loc[("000003", CALENDAR[25])]
    assert bool(other["label_ok_5"]) is True


def test_forward_label_rejects_bad_inputs() -> None:
    with pytest.raises(AsofPanelError, match="缺少列"):
        forward_return_labels(pd.DataFrame({"stock_code": ["000001"]}), CALENDAR, CODES)
    basis = _basis_fixture(_panel_fixture())
    with pytest.raises(AsofPanelError, match="正整数"):
        forward_return_labels(basis, CALENDAR, CODES, horizons=(0,))


# ---------------------------------------------------------------------------
# 3. 文本流量特征：逐条 publish_time 的 as-of 语义
# ---------------------------------------------------------------------------

def test_text_flow_features_are_point_in_time() -> None:
    published_at_first_day = CALENDAR[10]
    records = pd.DataFrame(
        {
            "stock_code": ["000001", "000001", "000002"],
            "publish_date": [published_at_first_day, CALENDAR[20], CALENDAR[10]],
            "item_type": ["announcement", "news", "news"],
        }
    )
    features = text_flow_features(records, CALENDAR, CODES, windows=(5, 20), lag_days=1)
    indexed = features.set_index(["stock_code", "trade_date"])

    # 第 10 日发布的记录在第 10 日**不可**使用（lag_days=1 ⇒ 最早第 11 日）
    assert indexed.loc[("000001", CALENDAR[10]), "flow_total_w5"] == pytest.approx(0.0)
    assert indexed.loc[("000001", CALENDAR[11]), "flow_total_w5"] == pytest.approx(np.log1p(1.0))
    # 第 20 日发布的记录进入 20 日窗口与 5 日窗口
    assert indexed.loc[("000001", CALENDAR[21]), "flow_total_w5"] == pytest.approx(np.log1p(1.0))
    assert indexed.loc[("000001", CALENDAR[21]), "flow_news_w5"] == pytest.approx(np.log1p(1.0))
    # 20 日窗口内两条都在
    assert indexed.loc[("000001", CALENDAR[21]), "flow_total_w20"] == pytest.approx(np.log1p(2.0))
    # 第 10 日那条在窗口滑出后不再计入（第 11 日可用，20 日窗口到第 30 日仍含）
    assert indexed.loc[("000001", CALENDAR[31]), "flow_total_w20"] == pytest.approx(np.log1p(1.0))
    # 从未有记录的股票：计数为 0（log1p(0)），recency 取满值 1.0
    assert indexed.loc[("000003", CALENDAR[30]), "flow_total_w20"] == pytest.approx(0.0)
    assert indexed.loc[("000003", CALENDAR[30]), "flow_recency"] == pytest.approx(1.0)


def test_text_flow_recency_decreases_right_after_a_record() -> None:
    records = pd.DataFrame(
        {
            "stock_code": ["000001"],
            "publish_date": [CALENDAR[20]],
            "item_type": ["announcement"],
        }
    )
    features = text_flow_features(records, CALENDAR, CODES, windows=(5, 60), lag_days=1)
    indexed = features.set_index(["stock_code", "trade_date"])

    assert indexed.loc[("000001", CALENDAR[21]), "flow_recency"] == pytest.approx(0.0)
    assert indexed.loc[("000001", CALENDAR[22]), "flow_recency"] == pytest.approx(1.0 / 60.0)
    assert indexed.loc[("000001", CALENDAR[30]), "flow_recency"] == pytest.approx(9.0 / 60.0)


def test_text_flow_features_cover_full_grid_and_reject_bad_records() -> None:
    records = pd.DataFrame(
        {"stock_code": ["000001"], "publish_date": [CALENDAR[3]], "item_type": ["news"]}
    )
    features = text_flow_features(records, CALENDAR, CODES, windows=(5,))

    assert len(features) == len(CODES) * len(CALENDAR)
    assert set(features["stock_code"]) == set(CODES)
    with pytest.raises(AsofPanelError, match="缺少列"):
        text_flow_features(records.drop(columns=["item_type"]), CALENDAR, CODES)
    with pytest.raises(AsofPanelError, match="lag_days"):
        text_flow_features(records, CALENDAR, CODES, lag_days=-1)


def test_load_corpus_records_parses_real_jsonl_shape(tmp_path) -> None:
    payload = [
        {"item_type": "news", "title": "t", "content": "c", "source": "s",
         "publish_time": "2026-08-17 10:47:00", "url": "http://example.com"},
        {"item_type": "announcement", "title": "t2", "content": "c2", "source": "s",
         "publish_time": "2026-09-01 00:00:00", "url": "http://example.com/2"},
    ]
    (tmp_path / "000001.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in payload), encoding="utf-8"
    )
    records = load_corpus_records(tmp_path)

    assert list(records.columns) == ["stock_code", "publish_date", "item_type"]
    assert records["publish_date"].tolist() == ["2026-08-17", "2026-09-01"]
    assert records["item_type"].tolist() == ["news", "announcement"]


def test_load_corpus_records_fails_closed_on_missing_timestamp(tmp_path) -> None:
    (tmp_path / "000001.jsonl").write_text(
        json.dumps({"item_type": "news", "title": "t"}) + "\n", encoding="utf-8"
    )
    with pytest.raises(AsofPanelError, match="publish_time"):
        load_corpus_records(tmp_path)


# ---------------------------------------------------------------------------
# 4. 配置与特征族：NOT_ASOF 与按组可用性 fail-closed
# ---------------------------------------------------------------------------

def test_static_embedding_family_is_refused_outright() -> None:
    with pytest.raises(AsofPanelError, match="NOT_ASOF"):
        AsofPanelConfig(feature_family=STATIC_EMBEDDING_FAMILY)


def test_unknown_feature_family_is_refused() -> None:
    with pytest.raises(AsofPanelError, match="未声明的特征族"):
        AsofPanelConfig(feature_family="totally_made_up")


@pytest.mark.parametrize(
    "overrides,fragment",
    [
        ({"n_components": 0}, "n_components"),
        ({"train_window_days": 1}, "train_window_days"),
        ({"min_train_rows": 3, "n_components": 3}, "min_train_rows"),
        ({"min_cross_section": 4}, "min_cross_section"),
        ({"horizons": (0,)}, "视界"),
        ({"text_windows": (0,)}, "文本窗口"),
        ({"text_lag_days": -1}, "text_lag_days"),
        ({"min_signal_index": 0}, "min_signal_index"),
    ],
)
def test_config_validation_rejects_illegal_parameters(overrides: dict, fragment: str) -> None:
    with pytest.raises(AsofPanelError, match=fragment):
        _config(**overrides)


def test_feature_family_columns_expand_text_windows() -> None:
    config = _config(feature_family="text_flow_v1", text_windows=(3, 7))

    assert feature_family_columns(config) == (
        "flow_total_w3",
        "flow_news_w3",
        "flow_total_w7",
        "flow_news_w7",
        "flow_recency",
    )
    assert config.lookback_days() == 7
    assert _config().lookback_days() == 60


def test_family_mismatched_with_universe_fails_closed() -> None:
    """基本面族在只有技术类因子的股票池上必须报错，而不是产出全 NaN 假面板。"""
    panel = _panel_fixture()
    features = _feature_frame(panel, family="fundamental_v1")
    for column in FUND_FEATURES:
        features[column] = np.nan
    # 造一个确实含 roe 但 pe/pb 全缺的池子，确保触发"整列全缺"分支
    with pytest.raises(AsofPanelError, match="全部缺失"):
        build_asof_panel(
            features, panel, _basis_fixture(panel), CALENDAR, CODES,
            _config(feature_family="fundamental_v1"),
        )


def test_missing_feature_columns_are_reported() -> None:
    panel = _panel_fixture()
    features = _feature_frame(panel).drop(columns=["vol_60d"])

    with pytest.raises(AsofPanelError, match="缺少列"):
        build_asof_panel(features, panel, _basis_fixture(panel), CALENDAR, CODES, _config())


# ---------------------------------------------------------------------------
# 5. 面板产出：契约列、缺失不填 0、计数器
# ---------------------------------------------------------------------------

def test_panel_satisfies_data_contract_columns() -> None:
    result = _build()
    panel = result.panel
    contract = {
        "stock_code", "signal_date", "available_at", "raw_corpus_version",
        "embedding_model_version", "embedding_truncation_date", "feature_window_start",
        "s0_version", "pca_version", "neutralization_version", "S0", "close", "available_flags",
    }
    assert contract <= set(panel.columns)
    assert panel["s0_version"].unique().tolist() == [S0_VERSION]
    assert panel["pca_version"].unique().tolist() == [PCA_VERSION]
    assert panel["neutralization_version"].unique().tolist() == [NEUTRALIZATION_VERSION]
    assert panel["asof_panel_version"].unique().tolist() == [ASOF_PANEL_VERSION]
    assert panel["S0_pc5_prior"].notna().all()
    assert panel["s0_pc5_prior_version"].unique().tolist() == [S0_PC5_PRIOR_VERSION]
    assert panel["declared_bias_warning"].unique().tolist() == [DECLARED_BIAS_WARNING]
    assert "static_embedding_NOT_ASOF" in panel["available_flags"].iloc[0]
    assert result.summary()["available_rows"] == len(panel)


def test_missing_features_emit_unavailable_rows_without_zero_filling() -> None:
    panel = _panel_fixture()
    features = _feature_frame(panel)
    signal_date = CALENDAR[15]
    broken = (features["stock_code"] == "000005") & (features["trade_date"] == signal_date)
    features.loc[broken, ["mom_5d", "vol_20d"]] = np.nan

    result = _build(panel=panel, features=features)
    row = result.panel.set_index(["stock_code", "signal_date"]).loc[("000005", signal_date)]

    assert bool(row["is_available"]) is False
    assert str(row["unavailable_reason"]).startswith("feature_missing:")
    assert "mom_5d" in str(row["unavailable_reason"])
    assert "vol_20d" in str(row["unavailable_reason"])
    assert pd.isna(row["S0"])
    assert pd.isna(row["PC01_z"])
    assert pd.isna(row["S0_pc5_prior"])
    assert result.counters["rows_unavailable"] >= 1
    assert result.counters["rows_feature_missing"] >= 1
    # 同一天其他股票仍然可用（缺失不得整日失效）
    same_day = result.panel[result.panel["signal_date"] == signal_date]
    assert int(same_day["is_available"].sum()) >= 11


def test_missing_feature_row_does_not_change_earlier_dates_and_still_leaves_label() -> None:
    """缺特征只影响该行与该行**之后**的信号日（因其落入后续训练窗），此前信号日不得变化。"""
    panel = _panel_fixture()
    baseline = _build(panel=panel)
    features = _feature_frame(panel)
    broken_date = CALENDAR[16]
    features.loc[
        (features["stock_code"] == "000005") & (features["trade_date"] == broken_date), "amihud"
    ] = np.nan
    mutated = _build(panel=panel, features=features)

    keys = ["stock_code", "signal_date"]
    left = baseline.panel[baseline.panel["signal_date"] < broken_date].set_index(keys)["S0"].sort_index()
    right = mutated.panel[mutated.panel["signal_date"] < broken_date].set_index(keys)["S0"].sort_index()
    assert left.index.equals(right.index)
    assert np.array_equal(left.to_numpy(), right.to_numpy(), equal_nan=True)
    # 缺特征的行仍带标签（标签是目标，与特征可用性无关，便于核对拒绝原因）
    row = mutated.panel.set_index(keys).loc[("000005", broken_date)]
    assert pd.notna(row["label_1"])
    assert bool(row["is_available"]) is False


def test_no_available_signal_date_raises_instead_of_empty_panel() -> None:
    config = _config(signal_dates=CALENDAR[:2], train_window_days=10, min_train_rows=5000)
    with pytest.raises(AsofPanelError, match="没有任何信号日"):
        _build(config=config)


def test_signal_dates_outside_calendar_are_rejected() -> None:
    with pytest.raises(AsofPanelError, match="不在交易日历"):
        _build(config=_config(signal_dates=("2024-12-31",)))


# ---------------------------------------------------------------------------
# 6. 训练期定标：前视时间往返
# ---------------------------------------------------------------------------

def test_future_data_cannot_change_past_scores() -> None:
    """改动 cutoff 之后的特征/价格/市值/收益，此前信号日的 S0 与 PC 得分必须逐位不变。

    例外说明：``label_*`` 是**目标**，本来就依赖未来收益，故不参与本断言（见模块文档）。
    """
    cutoff = CALENDAR[16]
    panel = _panel_fixture()
    features = _feature_frame(panel)
    basis = _basis_fixture(panel)
    config = _config(signal_dates=CALENDAR[12:19])
    codes = tuple(sorted(panel["stock_code"].unique()))

    before = build_asof_panel(features, panel, basis, CALENDAR, codes, config)

    mutated_features = features.copy()
    mutated_panel = panel.copy()
    mutated_basis = basis.copy()
    future_mask = mutated_features["trade_date"] > cutoff
    mutated_features.loc[future_mask, list(TECH_FEATURES)] += 5.0
    mutated_panel.loc[mutated_panel["trade_date"] > cutoff, "market_value"] *= 3.0
    mutated_panel.loc[mutated_panel["trade_date"] > cutoff, "close"] *= 7.0
    mutated_basis.loc[mutated_basis["trade_date"] > cutoff, "basis_return"] += 0.05
    after = build_asof_panel(mutated_features, mutated_panel, mutated_basis, CALENDAR, codes, config)

    keys = ["stock_code", "signal_date"]
    score_columns = ["S0", "S0_pc5_prior", "PC01_z", "PC02_z", "PC05_z"]
    left = before.panel[before.panel["signal_date"] <= cutoff].set_index(keys).sort_index()
    right = after.panel[after.panel["signal_date"] <= cutoff].set_index(keys).sort_index()
    assert left.index.equals(right.index)
    for column in score_columns:
        assert np.array_equal(
            left[column].to_numpy(), right[column].to_numpy(), equal_nan=True
        ), f"{column} 被未来数据改变了"


def test_training_window_excludes_signal_date_and_report_records_it() -> None:
    result = _build()
    report = result.fit_report.set_index("signal_date")

    for signal_date in result.panel["signal_date"].unique():
        row = report.loc[signal_date]
        assert row["train_end"] < signal_date
        assert row["train_rows"] > 0
        assert set(row["pc_signs"]) <= {"+", "-"}
        assert len(row["pc_signs"]) == 5


def test_scores_are_cross_sectionally_standardised_and_neutralised() -> None:
    result = _build()
    day = result.panel[result.panel["signal_date"] == CALENDAR[16]]

    assert day["S0"].mean() == pytest.approx(0.0, abs=1e-12)
    assert day["S0"].std(ddof=1) == pytest.approx(1.0, rel=1e-9)
    # 独立复核中性化：残差对行业哑变量与对数市值正交
    design = pd.get_dummies(day["industry"].astype(str), dtype=float).to_numpy()
    design = np.column_stack([np.ones(len(day)), design, np.log(day["market_value"].to_numpy())])
    residual = day["S0"].to_numpy()
    coefficients, *_ = np.linalg.lstsq(design, residual, rcond=None)
    assert np.max(np.abs(design @ coefficients)) < 1e-9


def test_pc_sign_alignment_rule_hand_computed() -> None:
    """手算：载荷 [-3,1,0.5] 的最大绝对项为负 ⇒ 整行翻号；同理第二行。"""
    aligned, signs = align_pca_signs(np.array([[-3.0, 1.0, 0.5], [0.0, -2.0, 0.1]]))

    assert aligned.tolist() == [[3.0, -1.0, -0.5], [0.0, 2.0, -0.1]]
    assert signs.tolist() == [-1.0, -1.0]
    with pytest.raises(AsofPanelError, match="二维"):
        align_pca_signs(np.array([1.0, 2.0]))


def test_pc_sign_alignment_is_applied_inside_the_fitted_engine() -> None:
    """引擎产出的每个分量，其最大绝对载荷项必须为正（对 X 与 −X 都成立）。"""
    rng = np.random.default_rng(20260914)
    matrix = rng.normal(size=(30, 4))
    config = _config(n_components=4, min_train_rows=10)

    for data in (matrix, -matrix):
        _, pca, signs = _build_pca_engine(data, config)
        reference = np.argmax(np.abs(pca.components_), axis=1)
        top = pca.components_[np.arange(len(reference)), reference]
        assert (top > 0).all()
        assert signs.shape == (4,)
        assert set(np.unique(signs)) <= {-1.0, 1.0}


def test_fit_report_exposes_top_features_from_declared_family() -> None:
    result = _build()

    assert result.fit_report["pc_top_loadings_positive"].all()
    for entry in result.fit_report["pc_top_features"]:
        for name in str(entry).split(","):
            assert name in TECH_FEATURES


def test_build_is_deterministic_across_runs() -> None:
    first = _build()
    second = _build()

    assert np.array_equal(
        first.panel["S0"].to_numpy(), second.panel["S0"].to_numpy(), equal_nan=True
    )
    assert first.counters == second.counters


def test_explicit_industry_mapping_is_honoured() -> None:
    panel = _panel_fixture()
    features = _feature_frame(panel)
    result = build_asof_panel(
        features,
        panel,
        _basis_fixture(panel),
        CALENDAR,
        CODES,
        _config(),
        industries={code: "唯一行业" for code in CODES},
    )
    assert set(result.panel["industry"]) == {"唯一行业"}


def test_missing_industry_column_is_reported() -> None:
    panel = _panel_fixture().drop(columns=["sub_industry"])
    with pytest.raises(AsofPanelError, match="缺少行业列"):
        build_asof_panel(_feature_frame(panel), panel, _basis_fixture(panel), CALENDAR, CODES, _config())


def test_text_family_end_to_end_on_fixture() -> None:
    """文本族走通全链路：特征来自逐条 publish_time，S0 可用且标签按日历计数。"""
    panel = _panel_fixture()
    records = pd.DataFrame(
        {
            "stock_code": [code for code in CODES for _ in range(3)],
            "publish_date": [CALENDAR[5], CALENDAR[11], CALENDAR[14]] * len(CODES),
            "item_type": ["announcement", "news", "announcement"] * len(CODES),
        }
    )
    features = text_flow_features(records, CALENDAR, CODES, windows=(5, 20))
    config = AsofPanelConfig(
        feature_family="text_flow_v1",
        n_components=2,
        train_window_days=10,
        min_train_rows=40,
        min_cross_section=8,
        horizons=(5,),
        signal_dates=CALENDAR[15:17],
        text_windows=(5, 20),
    )
    result = build_asof_panel(
        features, panel, _basis_fixture(panel), CALENDAR, CODES, config, corpus_version="fixture:corpus"
    )

    assert result.panel["is_available"].all()
    assert result.panel["S0"].notna().all()
    assert result.counters["signal_dates_considered"] == 2
    # 第 11、14 日各发布 1 条、lag=1 ⇒ 第 15 日窗口（可用下标 11..15）内共 2 条
    assert result.panel.loc[result.panel["signal_date"] == CALENDAR[15], "flow_total_w5"].iloc[0] == pytest.approx(
        np.log1p(2.0)
    )
    assert result.panel.loc[result.panel["signal_date"] == CALENDAR[15], "flow_news_w5"].iloc[0] == pytest.approx(
        np.log1p(1.0)
    )