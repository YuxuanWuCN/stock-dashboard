# -*- coding: utf-8 -*-
"""tests/test_enrich_master_bc.py —— B/C 技术因子并入 master 面板（可手算小样本）。

覆盖：正常并入且逐格数值手算比对、A 组行逐位不变、重复键拒绝、代码集不符拒绝、
B/C 行已有技术值拒绝、布尔列越界拒绝、覆盖率塌陷拒绝、ret/标准列不可触碰。
全部使用合成夹具，不碰真实数据目录。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.enrich_master_panel_bc_technical import (
    TECHNICAL_FEATURES,
    EnrichmentError,
    enrich,
)

DATES = [f"2024-01-{day:02d}" for day in range(2, 12)]  # 10 个交易日
A_CODES = ["600001", "600002"]
B_CODES = ["000001", "000002"]
C_CODES = ["600519", "000858"]


def _master_frame(with_a_technicals: bool = True) -> pd.DataFrame:
    rows = []
    position = 0
    for group, codes in (("A", A_CODES), ("B", B_CODES), ("C", C_CODES)):
        for code in codes:
            for day_index, date in enumerate(DATES):
                position += 1
                row = {
                    "stock_code": code,
                    "trade_date": date,
                    "close": 10.0 + position * 0.01,
                    "volume": 1e5 + position,
                    "turnover_rate": 0.01 + 1e-6 * position,
                    "market_value": 1e9 + position,
                    "pe_ttm": 12.0 + position * 0.001 if group != "A" else np.nan,
                    "pb": 1.5 if group != "A" else np.nan,
                    "roe": 0.11 if group != "A" else np.nan,
                    "ret": 0.001 * position if group == "A" else np.nan,
                }
                for column_index, column in enumerate(TECHNICAL_FEATURES):
                    if group == "A" and with_a_technicals:
                        row[column] = float((position + column_index) % 7) - 3.0
                    else:
                        row[column] = np.nan
                rows.append(row)
    return pd.DataFrame(rows)


def _daily_panel(codes: list[str], *, fill_fraction: float = 1.0, boolean_override=None) -> pd.DataFrame:
    rows = []
    position = 0
    for code in codes:
        for day_index, date in enumerate(DATES):
            position += 1
            if day_index >= len(DATES) * fill_fraction:
                continue  # 模拟停牌缺行
            row = {"stock_code": code, "trade_date": date}
            for column_index, column in enumerate(TECHNICAL_FEATURES):
                if column in ("hit_limit", "abnormal_trd"):
                    row[column] = 1 if (position + column_index) % 5 == 0 else 0
                elif column == "price_pos":
                    row[column] = min(1.0, max(0.0, 0.3 + 0.01 * column_index))
                elif column == "amplitude":
                    row[column] = abs(np.sin(position + column_index)) + 1e-6
                else:
                    row[column] = float(position + column_index) / 100.0
            if boolean_override is not None:
                row["hit_limit"] = boolean_override
            rows.append(row)
    return pd.DataFrame(rows)


def _sources() -> dict[str, pd.DataFrame]:
    return {"student_B": _daily_panel(B_CODES), "student_C": _daily_panel(C_CODES)}


def _cohort_codes() -> dict[str, list[str]]:
    return {"student_B": B_CODES, "student_C": C_CODES}


# ---------------------------------------------------------------------------
# 正常路径：逐格手算
# ---------------------------------------------------------------------------

def test_merge_writes_exact_values_into_bc_rows() -> None:
    master = _master_frame()
    enriched, audit = enrich(master, _sources(), _cohort_codes())
    panel = _daily_panel(B_CODES)

    probe = panel.iloc[3]
    mask = (enriched["stock_code"] == probe["stock_code"]) & (enriched["trade_date"] == probe["trade_date"])
    row = enriched.loc[mask].iloc[0]
    for column in TECHNICAL_FEATURES:
        assert row[column] == pytest.approx(float(probe[column])), column
    # 标准列与 ret 不被触碰
    assert row["close"] == pytest.approx(float(master.loc[mask, "close"].iloc[0]))
    assert pd.isna(row["ret"])

    assert audit["cohorts"]["student_B"]["n_rows"] == len(B_CODES) * len(DATES)
    assert audit["touched_rows"] == (len(B_CODES) + len(C_CODES)) * len(DATES)


def test_a_rows_and_standard_columns_stay_bit_identical() -> None:
    master = _master_frame()
    enriched, _ = enrich(master, _sources(), _cohort_codes())
    a_mask = master["stock_code"].isin(A_CODES)
    pd.testing.assert_frame_equal(
        enriched.loc[a_mask].reset_index(drop=True), master.loc[a_mask].reset_index(drop=True)
    )
    # B/C 的标准 9 列也必须原样保留（本夹具 pe_ttm 等非空）
    bc_mask = master["stock_code"].isin(B_CODES + C_CODES)
    standard = ["stock_code", "trade_date", "close", "volume", "turnover_rate", "market_value", "pe_ttm", "pb", "roe"]
    pd.testing.assert_frame_equal(
        enriched.loc[bc_mask, standard].reset_index(drop=True),
        master.loc[bc_mask, standard].reset_index(drop=True),
    )


def test_suspension_rows_stay_nan() -> None:
    master = _master_frame()
    sources = {
        "student_B": _daily_panel(B_CODES, fill_fraction=0.8),
        "student_C": _daily_panel(C_CODES),
    }
    # fill_fraction=0.8 ⇒ 每支 2 行停牌缺行；总体覆盖率 = 0.8 ≥ 0.95？否 ⇒ 必须拒绝，
    # 因为逐支覆盖 80% 低于 90% 的下限（fail-closed 而不是静默写盘）。
    with pytest.raises(EnrichmentError, match="覆盖率"):
        enrich(master, sources, _cohort_codes())


# ---------------------------------------------------------------------------
# fail-closed 路径
# ---------------------------------------------------------------------------

def test_refuses_duplicate_keys_in_source_panel() -> None:
    master = _master_frame()
    panel = _daily_panel(B_CODES)
    duplicated = pd.concat([panel, panel.iloc[[0]]], ignore_index=True)
    with pytest.raises(EnrichmentError, match="重复"):
        enrich(master, {"student_B": duplicated, "student_C": _daily_panel(C_CODES)}, _cohort_codes())


def test_refuses_code_set_mismatch() -> None:
    master = _master_frame()
    panel = _daily_panel(B_CODES[:-1])  # 少一支
    with pytest.raises(EnrichmentError, match="代码集与任务清单不符"):
        enrich(master, {"student_B": panel, "student_C": _daily_panel(C_CODES)}, _cohort_codes())


def test_refuses_code_in_two_cohorts() -> None:
    master = _master_frame()
    codes = {"student_B": B_CODES, "student_C": C_CODES + [B_CODES[0]]}
    with pytest.raises(EnrichmentError, match="同时出现在两组"):
        enrich(master, _sources(), codes)


def test_refuses_bc_rows_with_existing_technicals() -> None:
    master = _master_frame()
    master.loc[master["stock_code"].isin(B_CODES), "mom_5d"] = 1.23
    with pytest.raises(EnrichmentError, match="疑似重复并入"):
        enrich(master, _sources(), _cohort_codes())


def test_refuses_non_boolean_flags() -> None:
    master = _master_frame()
    panel = _daily_panel(B_CODES, boolean_override=2)
    with pytest.raises(EnrichmentError, match="0/1 之外取值"):
        enrich(master, {"student_B": panel, "student_C": _daily_panel(C_CODES)}, _cohort_codes())


def test_refuses_impossible_price_pos() -> None:
    master = _master_frame()
    panel = _daily_panel(B_CODES)
    panel.loc[panel.index[0], "price_pos"] = 1.5
    with pytest.raises(EnrichmentError, match="price_pos"):
        enrich(master, {"student_B": panel, "student_C": _daily_panel(C_CODES)}, _cohort_codes())


def test_refuses_negative_amplitude() -> None:
    master = _master_frame()
    panel = _daily_panel(B_CODES)
    panel.loc[panel.index[0], "amplitude"] = -0.01
    with pytest.raises(EnrichmentError, match="amplitude"):
        enrich(master, {"student_B": panel, "student_C": _daily_panel(C_CODES)}, _cohort_codes())


def test_refuses_master_with_duplicate_keys() -> None:
    master = _master_frame()
    master = pd.concat([master, master.iloc[[0]]], ignore_index=True)
    with pytest.raises(EnrichmentError, match="重复"):
        enrich(master, _sources(), _cohort_codes())


def test_enrich_is_idempotent_per_cohort() -> None:
    master = _master_frame()
    # 第一轮只并 B
    enriched_b, audit_b = enrich(master, {"student_B": _daily_panel(B_CODES)}, {"student_B": B_CODES})
    assert audit_b["cohorts"]["student_B"]["n_rows"] == len(B_CODES) * len(DATES)
    # 第二轮重复并 B：必须拒绝（防重复写入）
    with pytest.raises(EnrichmentError, match="疑似重复并入"):
        enrich(enriched_b, {"student_B": _daily_panel(B_CODES)}, {"student_B": B_CODES})
    # 第二轮并 C：互不影响，成功
    enriched_bc, audit_bc = enrich(enriched_b, {"student_C": _daily_panel(C_CODES)}, {"student_C": C_CODES})
    assert audit_bc["cohorts"]["student_C"]["n_rows"] == len(C_CODES) * len(DATES)
    # B 值在两轮之间逐位不变
    b_mask = master["stock_code"].isin(B_CODES)
    cols = ["stock_code", "trade_date", *TECHNICAL_FEATURES]
    pd.testing.assert_frame_equal(
        enriched_bc.loc[b_mask, cols].reset_index(drop=True),
        enriched_b.loc[b_mask, cols].reset_index(drop=True),
    )
