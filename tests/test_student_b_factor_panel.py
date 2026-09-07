"""tests/test_student_b_factor_panel.py —— 同学 B（能源与材料组）因子面板契约测试。

与 ``test_student_a_factor_panel.py`` 共享三条硬约束，但 B 组有两条 A 组没有的约束：

1. **前导 0 是 B 组的核心风险**：B 池含 000591 太阳能、001258 立新能源、000831 中国稀土等
   深市标的，代码被读成整数即等同错配标的（000591 -> 591 会匹配到完全不同的证券）。
2. **合成数据防线**：``data/raw/backtest_paper_2024_2026_300stocks/market_prices.csv``
   覆盖 B 池 100/100 只标的、694 个交易日，是"看着就能用"的陷阱——它由
   ``np.random.uniform(15, 120) * cumprod(1 + beta*MKT + alpha/252 + N(0, vol))`` 生成，
   非真实行情。B 脚本必须显式拒绝，A 脚本没有这道防线。

全部使用可手算的小样本，不做任何网络请求，不依赖 pytest 之外的第三方包。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import scripts.build_student_b_factor_panel as bscript
from src.data.factor_panel import (
    FACTOR_COLUMNS,
    STANDARD_COLUMNS,
    SourceSchemaError,
    fill_within_stock,
    normalize_stock_code,
    read_source,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TASK_FILE = PROJECT_ROOT / "data" / "task_split" / "student_B_energy_materials_100.csv"
SYNTHETIC_PRICES = PROJECT_ROOT / "data" / "raw" / "backtest_paper_2024_2026_300stocks" / "market_prices.csv"


# ---------------------------------------------------------------------------
# 1. B 组任务池契约
# ---------------------------------------------------------------------------


def test_b_task_file_is_100_codes_all_6_digit_strings():
    frame = read_source(TASK_FILE, source_label="task")
    codes = [normalize_stock_code(c) for c in frame["code"]]
    assert len(codes) == 100
    assert len(set(codes)) == 100, "任务池不得有重复标的"
    assert all(len(c) == 6 and c.isdigit() for c in codes)


def test_b_task_file_keeps_leading_zero_codes():
    """B 池的深市标的必须带着前导 0 落盘，这是 B 组区别于 A 组的关键风险点。"""
    frame = read_source(TASK_FILE, source_label="task")
    codes = set(normalize_stock_code(c) for c in frame["code"])
    for expected in ("000591", "001258", "000831"):  # 太阳能 / 立新能源 / 中国稀土
        assert expected in codes, f"{expected} 缺失或被截断前导 0"
    assert any(c.startswith("0") for c in codes)


def test_b_task_file_covers_the_declared_sector_mix():
    """B 池 = 绿电与清洁公用 + 黄金有色与周期资源，且两侧都不能为空。"""
    frame = read_source(TASK_FILE, source_label="task")
    frame.columns = [c.replace("\ufeff", "") for c in frame.columns]
    mix = frame["sub_industry"].value_counts()
    assert mix.index.nunique() == 2, f"应只有两个子行业，实际：{list(mix.index)}"
    assert (mix >= 50).all(), f"两子行业各 50 只：{mix.to_dict()}"


# ---------------------------------------------------------------------------
# 2. 股票内填充：B 组代码不得互相借值
# ---------------------------------------------------------------------------


def _b_tiny_panel() -> pd.DataFrame:
    """300750/000591 两只标的 × 4 个交易日，可手算。

    600900: 30, NaN, 36, NaN   -> ffill 30, 30, 36, 36
    000591: NaN, 20, NaN, 24   -> ffill NaN, 20, 20, 24
    若错误跨标的填充：000591 首日会被填成 600900 的 30（错配标的）。
    """
    dates = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"])
    rows = [("600900", d, v) for d, v in zip(dates, [30.0, np.nan, 36.0, np.nan])]
    rows += [("000591", d, v) for d, v in zip(dates, [np.nan, 20.0, np.nan, 24.0])]
    frame = pd.DataFrame(rows, columns=["stock_code", "trade_date", "close"])
    for column in ("volume", "turnover_rate", "market_value", "pe_ttm", "pb", "roe"):
        frame[column] = np.nan
    return frame[list(STANDARD_COLUMNS)]


def test_b_ffill_is_per_stock_and_keeps_leading_zero_identity():
    filled, stats = fill_within_stock(_b_tiny_panel(), ["close"], method="ffill")
    assert set(filled.stock_code) == {"600900", "000591"}, "填充不得改变证券代码"
    assert filled.stock_code.str.fullmatch(r"\d{6}").all()

    a = filled[filled.stock_code == "600900"].close.tolist()
    b = filled[filled.stock_code == "000591"].close.tolist()
    assert a == [30.0, 30.0, 36.0, 36.0]
    assert np.isnan(b[0]), "000591 无本标的历史值时必须留空，不能拿 600900 的 30.0"
    assert b[1:] == [20.0, 20.0, 24.0]
    assert stats["600900"]["close"] == 2
    assert stats["000591"]["close"] == 1


def test_b_fill_does_not_collapse_leading_zero_into_a_different_stock():
    """000591 与 591 在规范化后必须仍是同一个标的，不会被拆成两只。"""
    panel = pd.DataFrame({
        "stock_code": ["000591", "591", "000591", "000591"],
        "trade_date": pd.to_datetime(
            ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]
        ),
        "close": [20.0, 21.0, np.nan, np.nan],
    })
    for column in ("volume", "turnover_rate", "market_value", "pe_ttm", "pb", "roe"):
        panel[column] = np.nan
    normalized = panel.assign(stock_code=[normalize_stock_code(c) for c in panel.stock_code])
    filled, _ = fill_within_stock(normalized[list(STANDARD_COLUMNS)], ["close"], method="ffill")
    assert filled.stock_code.nunique() == 1
    assert filled.close.tolist() == [20.0, 21.0, 21.0, 21.0]


def test_b_max_gap_stops_the_chain():
    panel = pd.DataFrame({
        "stock_code": ["600900"] * 4,
        "trade_date": pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]),
        "close": [30.0, np.nan, np.nan, np.nan],
    })
    for column in ("volume", "turnover_rate", "market_value", "pe_ttm", "pb", "roe"):
        panel[column] = np.nan
    filled, _ = fill_within_stock(panel[list(STANDARD_COLUMNS)], ["close"], method="ffill", max_gap=1)
    values = filled.close.tolist()
    assert values[:2] == [30.0, 30.0]
    assert all(np.isnan(v) for v in values[2:]), "连续缺口超过 max_gap 必须保留空值"


def test_b_fill_rejects_unknown_column_and_method():
    with pytest.raises(ValueError):
        fill_within_stock(_b_tiny_panel(), ["not_a_column"])
    with pytest.raises(ValueError):
        fill_within_stock(_b_tiny_panel(), ["close"], method="lag")


# ---------------------------------------------------------------------------
# 3. 合成数据防线（B 组特有）
# ---------------------------------------------------------------------------


def test_synthetic_fixture_is_mathematically_random_not_market_data(tmp_path, monkeypatch):
    """留下证据：被拒的夹具是随机数生成物，不是行情。

    真实 A 股日收益有肥尾（峰度约 5~10）与负偏；该夹具由 np.random.normal 直接生成，
    横截面峰度接近 0，可稳定区分。这一断言不依赖网络，也不依赖任何真实行情文件。
    """
    prices = pd.read_csv(SYNTHETIC_PRICES, index_col=0)
    task = read_source(TASK_FILE, source_label="task")
    codes = set(normalize_stock_code(c) for c in task["code"])
    universe = {c for c in prices.columns if c.isdigit()}
    # 陷阱的前提：它 100% 覆盖 B 池，所以"能用"，但用不得
    assert codes <= universe, f"B 池有 {len(codes - universe)} 只不在夹具内（则本防线失去意义）"

    returns = prices.loc[:, [c for c in universe]].pct_change().iloc[1:]
    kurt = returns.kurtosis().mean()
    skew = returns.skew().mean()
    assert kurt < 1.0, f"日收益横截面平均峰度 {kurt:.2f}，无肥尾 => 随机数而非行情"
    assert skew < 0.3, f"日收益横截面平均偏度 {skew:.2f}，与 A 股负偏特征不符"

    # 价格量级失真：600900 长江电力真实区间约 28~33 元，夹具给出 39~98 元
    assert float(prices["600900"].iloc[-1]) > 60.0
    assert float(prices["600519"].max()) > 3000.0, "茅台被生成到 5000 元以上"

    # 生成过程可复现（同 seed 下完全一致），说明它不是采集来的数据
    gen = pd.read_csv(
        SYNTHETIC_PRICES, index_col=0, dtype=str, keep_default_na=False
    )
    parsed = pd.read_csv(SYNTHETIC_PRICES, index_col=0)
    assert parsed.shape == gen.shape


def test_guard_rejects_synthetic_backtest_artifact_for_wide_price(tmp_path):
    with pytest.raises(SourceSchemaError, match="随机数生成"):
        bscript.read_wide_price(SYNTHETIC_PRICES)


def test_guard_rejects_synthetic_backtest_artifact_for_raw_file(tmp_path):
    with pytest.raises(SourceSchemaError, match="随机数生成"):
        bscript._guard_against_synthetic(SYNTHETIC_PRICES, "--raw-file")


def test_guard_rejects_synthetic_artifact_by_relative_path(tmp_path, monkeypatch):
    """相对路径必须同样被拦截，避免用相对路径绕过绝对路径防线。"""
    monkeypatch.chdir(PROJECT_ROOT)
    rel = "data/raw/backtest_paper_2024_2026_300stocks/market_prices.csv"
    with pytest.raises(SourceSchemaError, match="随机数生成"):
        bscript._guard_against_synthetic(Path(rel), "--wide-price")


def test_guard_allows_a_legitimate_real_source(tmp_path):
    real = tmp_path / "csmar_trade_dayadj.csv"
    real.write_text(
        "SecuCode,TrdTrdDt,TrdClsPrc\n600900,2024-01-02,30.12\n000591,2024-01-02,12.04\n",
        encoding="utf-8",
    )
    bscript._guard_against_synthetic(real, "--raw-file")  # 不抛异常即为通过
    args = bscript.parse_args(["--raw-file", str(real)])
    sources, provided = bscript.load_sources(args)
    assert list(sources) == ["csmar_trade_dayadj.csv"]
    assert "close" in provided


def test_guard_does_not_over_block_siblings(tmp_path):
    """同一 data/raw/ 下的其他目录不应被误拦——防线必须精确到已知合成目录。"""
    sibling = tmp_path / "another_source.csv"
    sibling.write_text("SecuCode,TrdTrdDt,TrdClsPrc\n600900,2024-01-02,30.12\n", encoding="utf-8")
    bscript._guard_against_synthetic(sibling, "--raw-file")  # 放行


def test_guard_survives_symlink_or_case_variants(tmp_path, monkeypatch):
    """大小写与冗余路径片段（..）不得绕过 resolve 后的比对。"""
    messy = PROJECT_ROOT / "data" / "raw" / "." / "backtest_paper_2024_2026_300stocks" / "market_prices.csv"
    with pytest.raises(SourceSchemaError, match="随机数生成"):
        bscript._guard_against_synthetic(messy, "--wide-price")


# ---------------------------------------------------------------------------
# 4. 宽表读取助手
# ---------------------------------------------------------------------------


def test_read_wide_price_drops_unnamed_index_residue(tmp_path):
    wide = tmp_path / "prices.csv"
    wide.write_text(
        "date,600900,000591,001258\n"
        "2024-01-02,30.12,12.04,11.88\n"
        "2024-01-03,30.40,12.31,12.02\n",
        encoding="utf-8",
    )
    frame = bscript.read_wide_price(wide)
    assert not any(str(c).startswith("Unnamed") for c in frame.columns)
    assert list(frame.columns) == ["600900", "000591", "001258"], "前导 0 列名必须保留"


def test_read_wide_price_rejects_empty_code_frame(tmp_path):
    wide = tmp_path / "empty.csv"
    wide.write_text("date,Unnamed: 0\n2024-01-02,2024-01-02\n", encoding="utf-8")
    with pytest.raises(SourceSchemaError, match="没有证券代码列"):
        bscript.read_wide_price(wide)


# ---------------------------------------------------------------------------
# 5. CLI 行为契约
# ---------------------------------------------------------------------------


def test_cli_returns_2_when_no_source_is_given():
    """无 CSMAR 源时按设计返回 2 且不写任何文件，绝不伪造数据兜底。"""
    assert bscript.main(["--quiet"]) == 2


def test_cli_forbids_synthetic_source_and_returns_2(tmp_path):
    out_dir = tmp_path / "out"
    code = bscript.main([
        "--wide-price", str(SYNTHETIC_PRICES),
        "--out-dir", str(out_dir),
        "--overwrite",
    ])
    assert code == 2
    assert not out_dir.exists(), "被拒的合成源不得产出任何文件"


def _tiny_task_file(tmp_path) -> Path:
    """2 只标的的最小任务池：含深市前导 0 代码，用于 CLI 端到端接线测试。"""
    task = tmp_path / "task_tiny.csv"
    task.write_text(
        "code,name,sector,beta,alpha,sub_industry,student_group\n"
        "600900,长江电力,defensive,0.65,0.15,绿电与清洁公用,同学B（新能源与周期资源组）\n"
        "000591,太阳能,cyclical,1.10,-0.02,黄金有色与周期资源,同学B（新能源与周期资源组）\n",
        encoding="utf-8",
    )
    return task


def _tiny_csmar_export(tmp_path) -> Path:
    """CSMAR STK_TRADE_DAYADJ 形状的 2 只 × 2 日夹具（测试夹具，非行情数据）。"""
    raw = tmp_path / "csmar_trade_dayadj.csv"
    raw.write_text(
        "SecuCode,TrdTrdDt,TrdClsPrc,TrdVol_Total_A,TrdTNRate_Total_A\n"
        "600900,2024-01-02,30.12,123450000,3.2\n"
        "600900,2024-01-03,30.40,118900000,3.1\n"
        "000591,2024-01-02,12.04,45600000,5.0\n"
        "000591,2024-01-03,12.31,44100000,4.8\n",
        encoding="utf-8",
    )
    return raw


def test_cli_accepts_real_source_and_writes_three_artifacts(tmp_path):
    out_dir = tmp_path / "out"
    code = bscript.main([
        "--raw-file", str(_tiny_csmar_export(tmp_path)),
        "--task-file", str(_tiny_task_file(tmp_path)),
        "--start-date", "2024-01-02",
        "--end-date", "2024-01-03",
        "--out-dir", str(out_dir),
        "--quiet",
    ])
    # 只喂 close/volume/turnover_rate，其余必需字段缺失 => 覆盖缺口 => 退出 1（已写出）
    assert code == 1
    assert (out_dir / "student_b_factor_panel.csv").exists()
    assert (out_dir / "student_b_factor_panel.parquet").exists()
    assert (out_dir / "student_b_factor_panel_manifest.json").exists()

    panel = pd.read_csv(out_dir / "student_b_factor_panel.csv", dtype=str, keep_default_na=False)
    assert list(panel.columns) == list(STANDARD_COLUMNS)
    assert panel.stock_code.str.fullmatch(r"\d{6}").all()
    assert panel.trade_date.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all()
    assert "000591" in set(panel.stock_code), "前导 0 在落盘 CSV 中未丢失"
    assert len(panel) == 4, "2 标的 × 2 交易日 = 4 行"
    reread_pq = pd.read_parquet(out_dir / "student_b_factor_panel.parquet")
    assert list(reread_pq.columns) == list(STANDARD_COLUMNS)
    assert reread_pq.stock_code.str.fullmatch(r"\d{6}").all()
    assert reread_pq.trade_date.dtype.kind == "M"


def test_cli_manifest_records_group_and_fabrication_contract(tmp_path):
    import json

    out_dir = tmp_path / "out"
    code = bscript.main([
        "--raw-file", str(_tiny_csmar_export(tmp_path)),
        "--task-file", str(_tiny_task_file(tmp_path)),
        "--start-date", "2024-01-02",
        "--end-date", "2024-01-03",
        "--out-dir", str(out_dir),
        "--quiet",
    ])
    assert code == 1
    manifest = json.loads(
        (out_dir / "student_b_factor_panel_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["student_group"] == bscript.STUDENT_GROUP
    assert manifest["n_stocks"] == 2
    assert set(manifest["codes"]) == {"600900", "000591"}
    assert all(len(c) == 6 and c.isdigit() for c in manifest["codes"])
    assert manifest["window"] == {"start": "2024-01-02", "end": "2024-01-03"}
    assert manifest["fill_policy"]["scope"].startswith("仅单只标的内部")
    assert manifest["fill_policy"]["cross_stock_fill"] is False
    check = manifest["fabrication_check"]
    for key in (
        "synthetic_values_generated",
        "random_data_used",
        "constant_fallback_used",
        "synthetic_backtest_artifacts_ingested",
    ):
        assert check[key] is False
    assert manifest["sources"] == ["csmar_trade_dayadj.csv"]
    assert manifest["coverage_status"] == "incomplete", "缺市值/PE/PB/ROE 不可能满覆盖"
    assert manifest["gaps"], "必须如实记录缺口"
    # 已提供字段满覆盖、缺失字段 0 覆盖，两个口径都要如实反映
    assert manifest["field_gaps"]["close"]["coverage"] == 1.0
    assert manifest["field_gaps"]["roe"]["coverage"] == 0.0


def test_cli_quarterly_anchor_requires_announce_date_column(tmp_path):
    quarterly = tmp_path / "csmar_fin_analysis.csv"
    quarterly.write_text(
        "SecuCode,ReportDate,ROE_TTM\n600900,2023-12-31,0.104\n",
        encoding="utf-8",
    )
    code = bscript.main([
        "--raw-file", str(_tiny_csmar_export(tmp_path)),
        "--quarterly-file", str(quarterly),
        "--task-file", str(_tiny_task_file(tmp_path)),
        "--start-date", "2024-01-02",
        "--end-date", "2024-01-03",
        "--out-dir", str(tmp_path / "out"),
        "--quiet",
    ])
    assert code == 2, "缺公告日列必须拒绝锚定，避免未来信息泄漏"


# ---------------------------------------------------------------------------
# 6. 数据层字段契约在 B 组口径下的稳定性
# ---------------------------------------------------------------------------


def test_standard_columns_cover_the_brief(tmp_path):
    """任务书要求的字段必须在标准列内。"""
    required = {"stock_code", "trade_date", "close", "volume", "turnover_rate",
                "market_value", "pe_ttm", "pb", "roe"}
    assert required == set(STANDARD_COLUMNS)
    assert set(FACTOR_COLUMNS) <= set(STANDARD_COLUMNS)


def test_b_task_codes_all_normalize_to_6_digits_without_loss():
    frame = read_source(TASK_FILE, source_label="task")
    for raw in frame["code"]:
        assert normalize_stock_code(raw) == str(raw).zfill(6)
        assert normalize_stock_code(raw) == normalize_stock_code(int(raw))
