"""src/data/return_basis.py —— 全池统一日频总收益口径（声明式 caliber + 独立复核）.

真实缺陷（独立复核结论，取代先前"B/C 被填入伪崩盘"的错误判断）
--------------------------------------------------------------
`data/task_split/csmar_master/csmar_factor_panel_master.csv` 的 `close` 列**跨组不同口径**，
合并处不记录口径：

* **A 组 99 支 = 不复权成交价。** 生成脚本
  `data/task_split/student_a_delivery/02_脚本/build_csmar_daily_panel_factors.py:167-168`
  写明 `ret = Dretwd`、`close = Clsprc`。实测：12 行日收益越过板块涨跌停
  （−17.6%~−66.9% 的纯送转除权跳空）；159 行 ``|Dretwd − close涨幅| > 1%``；
  两者均值差 1.24bp/日 = **年化 3.13%** 的分红+除权捕获缺口。
* **B/C 组 200 支 = 前复权价。** `scripts/fetch_student_{b,c}_csmar_data.py:77-81` 与两份
  manifest 指向 CSMAR `TRD_FwardQuotation.ClosePrice`（复权行情表）。
  实测：0/64,300 行越限（若不复权，按 A 组发生率期望约 12.2 行，P(观测 0)≈5×10⁻⁶）；
  恒等式比值 A 组平坦于 1.004，B/C 从 1.062/1.080 单调收敛到**恰好 1.000**（前复权定义特征）。

所以"用 `close.pct_change()` 补 B/C"本身不是伪崩盘；**错误方向恰好相反**：凡拿 `close`
直接算前瞻收益的代码，对 A 组会把除权日读成暴跌并丢掉约 3.1%/年的分红收益 ——
这正是 `scripts/evaluate_ashare_pca_factors.py:157`（`close.shift(-5)/close-1`）在做的事。

本模块的处置
------------
1. :func:`declared_caliber`：口径以**来源证据声明**为准（静态、先验，不由收益反推）；
2. :func:`verify_caliber`：用复权恒等式 ``(market_value/close) / (volume/turnover_rate)``
   与涨跌停约束做**独立复核**，只给 ``confirmed / contradicted / inconclusive``，不参与逐行选择；
3. :func:`compute_return_basis`：按声明构造统一总收益 —— 有申报总收益优先用之；前复权 close
   用其日收益率；不复权且缺申报总收益 → 置为**不可用**（NaN），绝不把除权跳空当成交。

为什么必须由声明驱动、不能由全样本推断驱动
------------------------------------------
实测（`scratch/smoke_return_basis_v2.py`）：把 2025-06-30 之后的 `close/market_value` 扰动后
重算，**之前行的 `basis_return` 会改变** —— 全样本推断口径本身就是一条前视通道
（与 M1.4 用全样本 fit PCA 同一性质）。声明式口径先验固定后，逐行计算只依赖 ``(t-1, t)``，
时间可回放性由 `tests/test_return_basis.py` 断言。

设计约束：纯函数、无 I/O、不改入参；行序无关；6 位前导零保留；
重复键、非正价格/市值、非法代码、缺声明一律 fail-closed 抛错。
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

__all__ = [
    "BASIS_SOURCE_VALUES",
    "CALIBER_WATERMARK",
    "CLOSE_BASIS_VALUES",
    "REQUIRED_COLUMNS",
    "VERDICT_VALUES",
    "ReturnBasisConfig",
    "ReturnBasisError",
    "board_price_limit",
    "caliber_mixing_report",
    "compute_return_basis",
    "declared_caliber",
    "verify_caliber",
]

#: 产物水印：使用本口径的报表必须附带，防止被误读成"原始 close 收益"。
CALIBER_WATERMARK: Final[str] = "unified_total_return_basis_v1_declared_caliber"

#: 逐行收益计算必需列。
REQUIRED_COLUMNS: Final[tuple[str, ...]] = (
    "stock_code",
    "trade_date",
    "close",
    "volume",
    "turnover_rate",
    "market_value",
)

#: 单支股票 `close` 的复权口径取值。
CLOSE_BASIS_VALUES: Final[tuple[str, ...]] = ("forward_adjusted", "unadjusted")

#: 收益基来源取值。
BASIS_SOURCE_VALUES: Final[tuple[str, ...]] = (
    "declared_total_return",
    "forward_adjusted_close_return",
    "unavailable",
)

#: 复核判定取值。
VERDICT_VALUES: Final[tuple[str, ...]] = ("confirmed", "contradicted", "inconclusive")

#: 声明表必需列（口径必须有来源证据，空字符串视为违约）。
DECLARATION_COLUMNS: Final[tuple[str, ...]] = (
    "stock_code",
    "close_basis",
    "source_table",
    "adjustment",
    "provenance",
)


class ReturnBasisError(ValueError):
    """输入面板或口径声明违反契约（fail-closed，不静默降级）。"""


@dataclass(frozen=True)
class ReturnBasisConfig:
    """口径参数（本轮冻结；任何改动即换版本，须重跑全量审计与全量回测对比）。

    Attributes
    ----------
    limit_epsilon : float
        涨跌停判定容差，吸收四舍五入。
    drift_threshold : float
        恒等式比值样本首末相对漂移超过该值才算观察到复权证据。
    min_rows_for_verdict : int
        单支少于该行数不下复核结论（记 `inconclusive`）。
    total_return_column : str
        申报总收益列名（存在且有限时优先使用）。
    """

    limit_epsilon: float = 0.005
    drift_threshold: float = 0.01
    min_rows_for_verdict: int = 120
    total_return_column: str = "ret"

    def __post_init__(self) -> None:
        for name in ("limit_epsilon", "drift_threshold"):
            value = float(getattr(self, name))
            if not np.isfinite(value) or value <= 0.0:
                raise ReturnBasisError(f"{name} 必须为正的有限数，收到 {value!r}")
        if int(self.min_rows_for_verdict) < 2:
            raise ReturnBasisError("min_rows_for_verdict 至少为 2")
        if not str(self.total_return_column).strip():
            raise ReturnBasisError("total_return_column 不能为空")


def board_price_limit(stock_code: str, epsilon: float = 0.005) -> float:
    """返回该证券单日涨跌停幅度上限（含容差）。

    Parameters
    ----------
    stock_code : str
        6 位数字字符串代码（前导零不可丢）。
    epsilon : float, default 0.005
        舍入容差。

    Returns
    -------
    float
        单日收益绝对值上限。

    Raises
    ------
    ReturnBasisError
        代码不是 6 位数字字符串。

    Notes
    -----
    创业板 ``300/301``、科创板 ``688/689`` 为 ±20%，其余主板 ±10%。ST（±5%）与北交所
    （±30%）未出现在本轮样本；纳入前必须扩展本函数并重跑审计（见交接书 §10 D1 边界）。
    """
    code = str(stock_code)
    if len(code) != 6 or not code.isdigit():
        raise ReturnBasisError(f"证券代码必须为 6 位数字字符串，收到 {stock_code!r}")
    if code.startswith(("300", "301", "688", "689")):
        return 0.20 + epsilon
    return 0.10 + epsilon


def _validate_panel(panel: pd.DataFrame, cfg: ReturnBasisConfig) -> pd.DataFrame:
    """校验面板并按 ``(stock_code, trade_date)`` 升序返回数值化副本。"""
    if panel is None or len(panel) == 0:
        raise ReturnBasisError("输入面板为空")
    needed = list(REQUIRED_COLUMNS)
    if cfg.total_return_column in panel.columns:
        needed.append(cfg.total_return_column)
    missing = [c for c in needed if c not in panel.columns]
    if missing:
        raise ReturnBasisError(f"输入面板缺少必需列：{missing}")

    work = panel.loc[:, needed].copy()
    work["stock_code"] = work["stock_code"].astype(str).str.zfill(6)
    valid_code = work["stock_code"].str.fullmatch(r"\d{6}")
    if not bool(valid_code.all()):
        bad = work.loc[~valid_code, "stock_code"].iloc[0]
        raise ReturnBasisError(f"存在非法证券代码：{bad!r}")

    try:
        parsed = pd.to_datetime(work["trade_date"], errors="raise")
    except (TypeError, ValueError) as exc:
        raise ReturnBasisError(f"trade_date 无法解析为日期：{exc}") from exc
    work["trade_date"] = parsed.dt.strftime("%Y-%m-%d")

    dup = work.duplicated(subset=["stock_code", "trade_date"], keep=False)
    if bool(dup.any()):
        sample = work.loc[dup, ["stock_code", "trade_date"]].drop_duplicates().head(3)
        raise ReturnBasisError(f"(stock_code, trade_date) 存在重复键，样本：{sample.to_dict('records')}")

    numeric_columns = ["close", "volume", "turnover_rate", "market_value"]
    if cfg.total_return_column in needed:
        numeric_columns.append(cfg.total_return_column)
    for col in numeric_columns:
        work[col] = pd.to_numeric(work[col], errors="coerce")
    for col in ("close", "market_value"):
        if bool((work[col] <= 0).any()):
            raise ReturnBasisError(f"{col} 含非正值，无法构造口径")
        if bool(work[col].isna().any()):
            raise ReturnBasisError(f"{col} 含缺失值，口径要求先补齐或剔除该行")

    return work.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)


def _derive(work: pd.DataFrame, cfg: ReturnBasisConfig) -> pd.DataFrame:
    """派生 `r_close`、复权恒等式比值与越限标记（只使用 t-1 与 t 两行）。"""
    out = work.copy()
    grouped = out.groupby("stock_code", sort=False)
    out["r_close"] = grouped["close"].transform(lambda s: s / s.shift(1) - 1.0)

    shares_by_mv = (out["market_value"] / out["close"]).to_numpy(dtype="float64")
    volume = out["volume"].to_numpy(dtype="float64")
    turnover = out["turnover_rate"].to_numpy(dtype="float64")
    with np.errstate(divide="ignore", invalid="ignore"):
        shares_by_turnover = np.where(turnover > 0.0, volume / turnover, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        out["identity_ratio"] = shares_by_mv / shares_by_turnover

    out["price_limit"] = out["stock_code"].map(lambda c: board_price_limit(c, cfg.limit_epsilon)).astype("float64")
    out["beyond_limit"] = out["r_close"].abs().gt(out["price_limit"]).fillna(False).astype(bool)
    out["_first_day"] = grouped.cumcount().eq(0).to_numpy()
    return out


def declared_caliber(
    declarations: pd.DataFrame,
    config: ReturnBasisConfig | None = None,
) -> pd.DataFrame:
    """规范化并校验口径声明表（不看收益序列，先验固定）。

    Parameters
    ----------
    declarations : pd.DataFrame
        必含 :data:`DECLARATION_COLUMNS`；可选 ``total_return_available``（bool）。
    config : ReturnBasisConfig, optional
        仅用于登记参数版本。

    Returns
    -------
    pd.DataFrame
        规范化声明表；``stock_code`` 唯一、按代码升序。

    Raises
    ------
    ReturnBasisError
        缺列、代码非法、重复代码、`close_basis` 越界、来源证据字段为空。
    """
    cfg = config or ReturnBasisConfig()
    if declarations is None or len(declarations) == 0:
        raise ReturnBasisError("口径声明表为空：拒绝在无声明的情况下构造收益口径")
    missing = [c for c in DECLARATION_COLUMNS if c not in declarations.columns]
    if missing:
        raise ReturnBasisError(f"口径声明表缺少列：{missing}")

    table = declarations.loc[:, list(DECLARATION_COLUMNS)].copy()
    table["stock_code"] = table["stock_code"].astype(str).str.zfill(6)
    valid = table["stock_code"].str.fullmatch(r"\d{6}")
    if not bool(valid.all()):
        bad = table.loc[~valid, "stock_code"].iloc[0]
        raise ReturnBasisError(f"声明表含非法证券代码：{bad!r}")
    if bool(table["stock_code"].duplicated().any()):
        raise ReturnBasisError("声明表存在重复 stock_code")
    bad_basis = ~table["close_basis"].isin(list(CLOSE_BASIS_VALUES))
    if bool(bad_basis.any()):
        raise ReturnBasisError(f"close_basis 含非法取值：{sorted(set(table.loc[bad_basis, 'close_basis']))}")
    for col in ("source_table", "adjustment", "provenance"):
        blank = table[col].astype(str).str.strip().isin({"", "None", "nan"})
        if bool(blank.any()):
            raise ReturnBasisError(f"声明表 {col} 不允许为空（口径必须有来源证据）")

    if "total_return_available" not in table.columns:
        table["total_return_available"] = True
    table["total_return_available"] = table["total_return_available"].astype(bool)
    table["caliber_watermark"] = CALIBER_WATERMARK
    return table.sort_values("stock_code").reset_index(drop=True)


def verify_caliber(
    panel: pd.DataFrame,
    declarations: pd.DataFrame,
    config: ReturnBasisConfig | None = None,
) -> pd.DataFrame:
    """用恒等式与涨跌停约束独立复核声明（只出结论，不改逐行口径）。

    Parameters
    ----------
    panel : pd.DataFrame
        行情面板，见 :data:`REQUIRED_COLUMNS`。
    declarations : pd.DataFrame
        声明表（原始或已规范化）。
    config : ReturnBasisConfig, optional
        判据参数。

    Returns
    -------
    pd.DataFrame
        每支一行：``stock_code, declared_basis, total_return_available, n_rows,
        n_beyond_limit, identity_first, identity_last, identity_drift, identity_std,
        verdict, reason``。

    Raises
    ------
    ReturnBasisError
        面板或声明违约，或有股票缺声明。
    """
    cfg = config or ReturnBasisConfig()
    work = _derive(_validate_panel(panel, cfg), cfg)
    decl = declared_caliber(declarations, cfg)

    rows: list[dict[str, object]] = []
    for code, g in work.groupby("stock_code", sort=True):
        match = decl.loc[decl["stock_code"] == code]
        if match.empty:
            raise ReturnBasisError(f"{code} 无口径声明，拒绝处理（fail-closed）")
        declared = str(match["close_basis"].iloc[0])
        available = bool(match["total_return_available"].iloc[0])

        ident = g["identity_ratio"].dropna()
        n_rows = int(len(g))
        n_beyond = int(g["beyond_limit"].sum())
        first = float(ident.iloc[0]) if len(ident) else float("nan")
        last = float(ident.iloc[-1]) if len(ident) else float("nan")
        drift = abs(first / last - 1.0) if (len(ident) and last > 0) else float("nan")
        std = float(ident.std(ddof=1)) if len(ident) > 1 else float("nan")

        oracle_gap = float("nan")
        if cfg.total_return_column in g.columns:
            pair = g.dropna(subset=[cfg.total_return_column, "r_close"])
            if len(pair):
                oracle_gap = float((pair[cfg.total_return_column] - pair["r_close"]).abs().max())

        if n_rows < cfg.min_rows_for_verdict or len(ident) < cfg.min_rows_for_verdict:
            verdict, reason = "inconclusive", f"样本 {n_rows} 行 < {cfg.min_rows_for_verdict}，证据不足"
        elif declared == "forward_adjusted" and n_beyond > 0:
            verdict, reason = "contradicted", f"声明前复权却有 {n_beyond} 行越过涨跌停（除权跳空只出现在不复权序列）"
        elif declared == "forward_adjusted":
            if np.isfinite(drift) and drift > cfg.drift_threshold and std > cfg.drift_threshold:
                verdict, reason = "confirmed", f"恒等式比值自 {first:.4f} 收敛至 {last:.4f} 且无越限跳空"
            else:
                verdict, reason = "inconclusive", f"窗口内未发生可观察的公司行为（漂移 {drift:.4%}）"
        elif n_beyond > 0:
            verdict, reason = "confirmed", f"存在 {n_beyond} 行除权型不可能跳空"
        elif np.isfinite(oracle_gap) and oracle_gap <= 1e-9:
            verdict, reason = "contradicted", "close 日收益与申报总收益逐行全等，说明 close 已是复权价"
        elif np.isfinite(oracle_gap):
            verdict, reason = "confirmed", f"close 日收益与申报总收益最大背离 {oracle_gap:.4f}"
        else:
            # 恒等式漂移对"不复权"声明不构成反证：解禁/增发/回购同样改变流通股本。
            # 实测 36 支 A 组股票的漂移全部属此类（scratch/debug_contradicted.py），
            # 早期版本据此判 contradicted 是假阳性，已改为不下结论。
            verdict, reason = "inconclusive", "无除权事件且无总收益可比对；股本结构变动可解释恒等式漂移，不能定论"

        rows.append(
            {
                "stock_code": code,
                "declared_basis": declared,
                "total_return_available": available,
                "n_rows": n_rows,
                "n_beyond_limit": n_beyond,
                "identity_first": first,
                "identity_last": last,
                "identity_drift": drift,
                "identity_std": std,
                "verdict": verdict,
                "reason": reason,
            }
        )
    return pd.DataFrame(rows)


def compute_return_basis(
    panel: pd.DataFrame,
    declarations: pd.DataFrame,
    config: ReturnBasisConfig | None = None,
    verification: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """构造全池统一总收益面板（逐行只依赖 ``(t-1, t)``）。

    优先级：

    1. 申报总收益存在且有限 → 采用（``declared_total_return``）；
    2. 声明 ``forward_adjusted`` → 用 close 日收益率（前复权序列的日收益率即含息总收益，
       ``forward_adjusted_close_return``）；
    3. 声明 ``unadjusted`` 且无申报总收益 → ``unavailable``（NaN）；
    4. 复核结论 ``contradicted`` 的股票整支 ``unavailable``。

    Parameters
    ----------
    panel : pd.DataFrame
        行情面板。
    declarations : pd.DataFrame
        口径声明表。
    config : ReturnBasisConfig, optional
        参数。
    verification : pd.DataFrame, optional
        预先算好的 :func:`verify_caliber` 结果（走步复用时避免重复扫描）。

    Returns
    -------
    pd.DataFrame
        列见模块文档；``basis_return`` 为 NaN 时 ``basis_source == 'unavailable'``，
        绝不填 0.0。

    Raises
    ------
    ReturnBasisError
        面板/声明违约、有股票缺声明、复核结论取值非法。
    """
    cfg = config or ReturnBasisConfig()
    work = _derive(_validate_panel(panel, cfg), cfg)
    decl = declared_caliber(declarations, cfg)

    if verification is None:
        warnings.warn(
            "compute_return_basis 未收到冻结的 verify_caliber 结果，将按全样本重算复核结论；"
            "全样本统计不是点时信息，走步/回测必须显式传入 training 期算出的 verification，"
            "否则会把未来信息灌进历史行。",
            UserWarning,
            stacklevel=2,
        )
        verify_table = verify_caliber(panel, decl, cfg)
    else:
        verify_table = verification.copy()
    verify_table["stock_code"] = verify_table["stock_code"].astype(str).str.zfill(6)
    bad_verdict = set(verify_table["verdict"]) - set(VERDICT_VALUES)
    if bad_verdict:
        raise ReturnBasisError(f"复核结论含未知取值：{sorted(bad_verdict)}")
    contradicted = set(verify_table.loc[verify_table["verdict"] == "contradicted", "stock_code"])

    merged = work.merge(
        decl[["stock_code", "close_basis", "total_return_available"]],
        on="stock_code",
        how="left",
        validate="many_to_one",
    )
    if bool(merged["close_basis"].isna().any()):
        raise ReturnBasisError("存在无口径声明的股票，拒绝构造收益（fail-closed）")

    declared_ret = (
        merged[cfg.total_return_column].to_numpy(dtype="float64")
        if cfg.total_return_column in merged.columns
        else np.full(len(merged), np.nan)
    )
    close_ret = merged["r_close"].to_numpy(dtype="float64")
    chosen_basis = merged["close_basis"].to_numpy(dtype=object)
    first_day = merged["_first_day"].to_numpy()
    blocked = (
        np.isin(merged["stock_code"].to_numpy(), list(contradicted))
        if contradicted
        else np.zeros(len(merged), dtype=bool)
    )

    basis = np.full(len(merged), np.nan)
    source = np.array(["unavailable"] * len(merged), dtype=object)

    stock_codes = merged["stock_code"].to_numpy()
    code_is_blocked = np.zeros(len(merged), dtype=bool)
    if contradicted:
        code_is_blocked = np.isin(stock_codes, list(contradicted))

    # 有申报总收益的行以申报值为准，与该支 close 口径判定是否矛盾无关；
    # 只有"必须依赖 close 取收益"的行才因复核矛盾而不可用。
    use_declared = np.isfinite(declared_ret)
    source[use_declared] = "declared_total_return"
    basis[use_declared] = declared_ret[use_declared]

    forward = (
        ~use_declared
        & ~code_is_blocked
        & (chosen_basis == "forward_adjusted")
        & np.isfinite(close_ret)
        & ~first_day
    )
    source[forward] = "forward_adjusted_close_return"
    basis[forward] = close_ret[forward]

    merged["basis_return"] = basis
    merged["basis_source"] = pd.Categorical(source, categories=list(BASIS_SOURCE_VALUES), ordered=False)
    merged["caliber_watermark"] = CALIBER_WATERMARK

    columns = [
        "stock_code",
        "trade_date",
        "close",
        "market_value",
        "r_close",
        "identity_ratio",
        "price_limit",
        "close_basis",
        "beyond_limit",
        "basis_return",
        "basis_source",
        "caliber_watermark",
    ]
    if cfg.total_return_column in merged.columns:
        columns.insert(4, cfg.total_return_column)
    out = merged.loc[:, columns].copy()
    if cfg.total_return_column in out.columns:
        out = out.rename(columns={cfg.total_return_column: "declared_total_return"})
    return out.reset_index(drop=True)


def caliber_mixing_report(
    basis_panel: pd.DataFrame,
    declared_column: str = "declared_total_return",
) -> dict[str, float]:
    """量化"误用 close 当日收益"的系统代价（仅在两口径同时可得的行上可比）。

    Parameters
    ----------
    basis_panel : pd.DataFrame
        :func:`compute_return_basis` 的输出。
    declared_column : str, default 'declared_total_return'
        申报总收益列名。

    Returns
    -------
    dict[str, float]
        ``n_compared``、``mean_daily_gap``、``annualized_gap``、``max_abs_daily_gap``、
        ``share_gap_gt_1pct``、``coverage``、``rows_basis_unavailable``。

    Raises
    ------
    ReturnBasisError
        缺列或无可比行。
    """
    if declared_column not in basis_panel.columns:
        raise ReturnBasisError(f"面板缺少 {declared_column!r} 列，无法评估口径混用后果")
    sub = basis_panel.dropna(subset=[declared_column, "r_close"])
    if sub.empty:
        raise ReturnBasisError("无同时具备申报总收益与 close 日收益的行")
    gap = sub[declared_column] - sub["r_close"]
    return {
        "n_compared": float(len(sub)),
        "mean_daily_gap": float(gap.mean()),
        "annualized_gap": float(gap.mean() * 252.0),
        "max_abs_daily_gap": float(gap.abs().max()),
        "share_gap_gt_1pct": float((gap.abs() > 0.01).mean()),
        "coverage": float(basis_panel["basis_return"].notna().mean()),
        "rows_basis_unavailable": float(int(basis_panel["basis_return"].isna().sum())),
    }
