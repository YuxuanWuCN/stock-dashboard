# -*- coding: utf-8 -*-
"""src/data/pca_nale_asof_panel.py —— as-of S0 面板工厂（M2）。

为什么必须有这个模块
--------------------
M1.4 的"日频信号"实际是把一张 **无日期** 的 300×780 静态截面复制到 2024–2026 每一天
（`factors_768d_all.csv` 全部 300 个 `retrieved_at_utc` 落在 2026-09-07T15:47Z~09-09T02:17Z），
并在**全样本**上 fit `StandardScaler+PCA`、取每支**最后**一天市值做中性化。这是前视。

本模块把 S0 重建成**逐信号日**截面，且每条可用性规则都写成可复核的显式声明：

1. **训练期定标**：`StandardScaler` 与 `PCA` 只用 ``signal_date`` **之前**训练窗内的行拟合；
   未来行被改动**不得**改变过去任何输出（`tests/test_pca_nale_asof_panel.py` 有往返测试）。
2. **当日截面处理**：MAD 去极值 → 行业哑变量 + **当日**对数市值 OLS 残差 → 截面 Z-score，
   全部只看 ``signal_date`` 当天截面（截面标准化不是前视，全样本拟合才是）。
3. **交易日历对齐**：面板缺行是**整行缺失**（F10 实测 357 行：`601989` 退市 264 行 + 12 支停牌 93 行），
   所以先把 (code × 完整交易日历) 铺满并标注 `status ∈ {trading, suspended, delisted, not_listed}`，
   再**沿日历轴**计 h 日前瞻收益；严禁 `groupby(code).shift(-h)` 那种"按可用行偏移"的写法
   （实测会把"5 日"标签拉成约 19 个交易日）。跨停牌/退市不足 h 日的标签**记拒绝原因**，不静默丢整支。
4. **缺失即不可用，绝不填 0**：任一声明特征缺失 → 整行 `is_available=False` 并计入 `counters`。
5. **特征族按组可用性是事实**（本轮实测）：面板的技术类因子 `mom_*/vol_*/turnover_20d/amihud/
   price_pos/amplitude/gap/hit_limit/abnormal_trd` **只有 A 组 99 支**有值；基本面
   `pe_ttm/pb/roe` **只有 B/C 组 200 支**有值；`ret` 只有 A 组有值。故特征族与股票池必须显式匹配，
   不匹配一律 fail-closed 抛错，而不是产出全 NaN 的假面板。
6. **静态 768 维嵌入标 NOT_ASOF**：其 `retrieved_at_utc` 全部晚于 2026-09-07，且本机
   **没有**任何可用的嵌入模型缓存（fastembed 缓存目录为空、huggingface 缓存无模型），
   因此**无法**在离线条件下把语料重新嵌入成 as-of 向量；该族只登记、不产出，禁止进入真实实验组。
   文本侧真正 as-of 可用的是**逐条 `publish_time`**（语料 77,254 条公告 + 1,971 条新闻，200 支）。

语义与版本
----------
* `S0`（主口径，`s0_version = pca10_equal_signaligned_v1`）：PC01~PC10 各自先做截面 Z-score，
  PCA 分量符号按训练期载荷最大绝对值项**取正**对齐（PCA 符号本身任意，不对齐会让不同训练窗的
  S0 随机翻号）→ 等权平均 → MAD 去极值 → 中性化 → 截面 Z-score。
* `S0_pc5_prior`（基线列，不覆盖主口径）：M1.4 的历史固定权重 `+0.15/−0.15/+0.35/+0.20/−0.35`
  施加于前五个 PC。其权重来自**全样本回归证据 ⇒ 属前视**，故只作为"历史固定先验基线"并列报告，
  不得宣称与十维口径等价（裁决 D3）。

设计约束：清洗原语复用 `src/pricing/factor_neutralization.py`；本模块纯函数、不写盘、不改入参；
所有日期为 `YYYY-MM-DD` 字符串。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

from src.pricing.factor_neutralization import (
    neutralize_cross_section,
    standardize_zscore,
    winsorize_mad,
)

__all__ = [
    "ASOF_PANEL_VERSION",
    "DEFAULT_HORIZONS",
    "DEFAULT_TEXT_WINDOWS",
    "DECLARED_BIAS_WARNING",
    "FEATURE_FAMILIES",
    "NOT_ASOF_FAMILIES",
    "PCA_VERSION",
    "NEUTRALIZATION_VERSION",
    "S0_VERSION",
    "S0_PC5_PRIOR_VERSION",
    "STATIC_EMBEDDING_FAMILY",
    "AsofPanelConfig",
    "AsofPanelError",
    "AsofPanelResult",
    "align_pca_signs",
    "align_to_calendar",
    "build_asof_panel",
    "feature_family_columns",
    "forward_return_labels",
    "load_corpus_records",
    "text_flow_features",
    "trading_calendar_from_panel",
]

#: 面板契约版本（列语义、可用性规则一变即换版本）。
ASOF_PANEL_VERSION = "pca_nale_asof_panel_v1"

#: S0 主口径版本。
S0_VERSION = "pca10_equal_signaligned_v1"

#: 历史固定先验基线版本（前视权重，仅作对照）。
S0_PC5_PRIOR_VERSION = "pc5_fixed_prior_v1_lookahead_derived"

#: PCA 定标方式版本。
PCA_VERSION = "trainfit_full_svd_pca10_v1"

#: 中性化版本。
NEUTRALIZATION_VERSION = "industry_dummies_plus_log_float_mv_ols_v1"

#: 必须在所有产物中携带的偏差声明。
DECLARED_BIAS_WARNING = (
    "S0_pc5_prior 的权重来自 M1.4 全样本回归证据，属前视，仅作历史固定先验基线；"
    "主口径 S0 不使用任何标签拟合。静态 768 维嵌入族为 NOT_ASOF，不得进入真实实验组。"
)

#: 默认前瞻标签视界（交易日）。
DEFAULT_HORIZONS: tuple[int, ...] = (1, 5, 10, 20)

#: 默认文本流量窗口（交易日）。
DEFAULT_TEXT_WINDOWS: tuple[int, ...] = (5, 20, 60)

#: 静态嵌入族代号（登记但拒绝产出）。
STATIC_EMBEDDING_FAMILY = "static_embedding_768_jina_v2"

#: 特征族 → 面板列（**按组可用性实测结论**，见模块文档第 5 条）。
FEATURE_FAMILIES: dict[str, tuple[str, ...]] = {
    "price_technical_v1": (
        "mom_5d",
        "mom_20d",
        "mom_60d",
        "vol_20d",
        "vol_60d",
        "turnover_20d",
        "amihud",
        "price_pos",
        "amplitude",
        "gap",
        "hit_limit",
        "abnormal_trd",
    ),
    "fundamental_v1": ("pe_ttm", "pb", "roe"),
    STATIC_EMBEDDING_FAMILY: (),
}

#: 各族嵌入的最长回看（交易日），用于 `feature_window_start` 与最小预热。
FAMILY_LOOKBACK_DAYS: dict[str, int] = {
    "price_technical_v1": 60,
    "fundamental_v1": 0,
    "text_flow_v1": 60,
    STATIC_EMBEDDING_FAMILY: 0,
}

#: 明确禁止进入真实实验组的族（登记 + 拒绝）。
NOT_ASOF_FAMILIES: dict[str, str] = {
    STATIC_EMBEDDING_FAMILY: (
        "768 维嵌入的 retrieved_at_utc 全部晚于 2026-09-07，且本机无嵌入模型缓存（fastembed 缓存为空、"
        "huggingface 缓存无模型），无法离线重建 as-of 向量：该族为事后证据，任何早于 2026-09-07 的信号"
        "使用它都构成前视。"
    ),
}

#: 文本记录可用性滞后（自然日）：第 d 日发布的记录最早在第 d+lag 个交易日可用于信号。
DEFAULT_TEXT_LAG_DAYS = 1

#: 面板中标识股票代码 / 交易日 / 市值 / 行业的列名。
CODE_COLUMN = "stock_code"
DATE_COLUMN = "trade_date"
MARKET_VALUE_COLUMN = "market_value"
PRICE_COLUMN = "close"


class AsofPanelError(ValueError):
    """输入违反 as-of 契约（fail-closed，不静默降级、不填 0）。"""


@dataclass(frozen=True)
class AsofPanelConfig:
    """as-of 面板参数（冻结；任何改动即换版本并重跑全量对比）。

    Attributes
    ----------
    feature_family : str
        :data:`FEATURE_FAMILIES` 或 ``"text_flow_v1"`` 中的键。
    n_components : int
        PCA 分量数（裁决 D3 冻结为 10）。
    train_window_days : int
        训练窗长度（交易日，只取 ``signal_date`` **之前**的交易日）。
    min_train_rows : int
        训练窗最小可用行数；不足则该信号日不产出。
    min_cross_section : int
        当日截面最小可用股票数；不足则该日整日不可用。
    winsor_n / mad_scale : float
        MAD 去极值参数（复用 `factor_neutralization.winsorize_mad`）。
    horizons : tuple[int, ...]
        前瞻标签视界（交易日，沿完整日历计数）。
    text_windows : tuple[int, ...]
        文本流量特征窗口（交易日）。
    text_lag_days : int
        文本记录可用性滞后（自然日）。
    signal_dates : tuple[str, ...] | None
        指定信号日；None 表示用完整日历中满足预热与训练窗要求的全部交易日。
    industry_column : str
        截面行业列（中性化用行业哑变量）。
    min_signal_index : int
        信号日最早可用的日历下标（默认由训练窗与最长回看推出）。
    """

    feature_family: str = "price_technical_v1"
    n_components: int = 10
    train_window_days: int = 120
    min_train_rows: int = 200
    min_cross_section: int = 20
    winsor_n: float = 3.0
    mad_scale: float = 1.4826
    horizons: tuple[int, ...] = DEFAULT_HORIZONS
    text_windows: tuple[int, ...] = DEFAULT_TEXT_WINDOWS
    text_lag_days: int = DEFAULT_TEXT_LAG_DAYS
    signal_dates: tuple[str, ...] | None = None
    industry_column: str = "sub_industry"
    min_signal_index: int | None = None

    def __post_init__(self) -> None:
        if self.feature_family in NOT_ASOF_FAMILIES:
            raise AsofPanelError(
                f"特征族 {self.feature_family!r} 已标 NOT_ASOF，禁止构造 as-of 面板："
                f"{NOT_ASOF_FAMILIES[self.feature_family]}"
            )
        if self.feature_family not in FEATURE_FAMILIES and self.feature_family != "text_flow_v1":
            raise AsofPanelError(
                f"未声明的特征族 {self.feature_family!r}；合法取值："
                f"{sorted([*FEATURE_FAMILIES, 'text_flow_v1'])}"
            )
        if int(self.n_components) < 1:
            raise AsofPanelError("n_components 至少为 1")
        if int(self.train_window_days) < 2:
            raise AsofPanelError("train_window_days 至少为 2")
        if int(self.min_train_rows) < int(self.n_components) + 1:
            raise AsofPanelError("min_train_rows 必须大于 n_components")
        if int(self.min_cross_section) < 5:
            raise AsofPanelError("min_cross_section 至少为 5（中性化回归需要足够样本）")
        for h in self.horizons:
            if int(h) < 1:
                raise AsofPanelError(f"前瞻视界必须为正整数，收到 {h!r}")
        for w in self.text_windows:
            if int(w) < 1:
                raise AsofPanelError(f"文本窗口必须为正整数，收到 {w!r}")
        if int(self.text_lag_days) < 0:
            raise AsofPanelError("text_lag_days 不能为负（当日发布的记录不得当日使用）")
        if self.min_signal_index is not None and int(self.min_signal_index) < 1:
            raise AsofPanelError("min_signal_index 至少为 1")

    @property
    def is_text_family(self) -> bool:
        """是否使用文本流量族。"""
        return self.feature_family == "text_flow_v1"

    def required_columns(self) -> tuple[str, ...]:
        """该族需要的面板列。"""
        if self.is_text_family:
            return ()
        return FEATURE_FAMILIES[self.feature_family]

    def lookback_days(self) -> int:
        """该族最长回看（交易日）。"""
        if self.is_text_family:
            return max(self.text_windows) if self.text_windows else 0
        return FAMILY_LOOKBACK_DAYS[self.feature_family]


@dataclass
class AsofPanelResult:
    """as-of 面板产物 + 逐信号日拟合报告 + 可用性计数。"""

    panel: pd.DataFrame
    fit_report: pd.DataFrame
    counters: dict[str, int] = field(default_factory=dict)
    config: AsofPanelConfig | None = None

    def summary(self) -> dict[str, Any]:
        """供 CLI/报表使用的最小摘要（不含完整面板）。"""
        panel = self.panel
        return {
            "asof_panel_version": ASOF_PANEL_VERSION,
            "feature_family": self.config.feature_family if self.config else None,
            "rows": int(len(panel)),
            "available_rows": int(panel["is_available"].sum()) if "is_available" in panel else 0,
            "codes": int(panel[CODE_COLUMN].nunique()) if len(panel) else 0,
            "signal_dates": int(panel["signal_date"].nunique()) if len(panel) else 0,
            "counters": dict(self.counters),
        }


# ---------------------------------------------------------------------------
# 1. 交易日历与占位行
# ---------------------------------------------------------------------------

def trading_calendar_from_panel(panel: pd.DataFrame) -> tuple[str, ...]:
    """从主面板提取完整交易日历（全池并集，升序、去重、字符串）。"""
    if DATE_COLUMN not in panel.columns:
        raise AsofPanelError(f"面板缺少 {DATE_COLUMN} 列")
    values = panel[DATE_COLUMN].astype(str)
    if not bool(values.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all()):
        raise AsofPanelError("trade_date 必须是 YYYY-MM-DD 字符串")
    calendar = tuple(sorted(values.unique()))
    if len(calendar) < 2:
        raise AsofPanelError("交易日历少于 2 天，无法构造面板")
    return calendar


def align_to_calendar(
    panel: pd.DataFrame,
    calendar: Sequence[str],
    codes: Sequence[str],
) -> pd.DataFrame:
    """把 (code × 完整交易日历) 铺满，缺行位置标占位状态。

    Parameters
    ----------
    panel : pd.DataFrame
        至少含 ``stock_code`` / ``trade_date``。
    calendar : Sequence[str]
        完整交易日历（升序）。
    codes : Sequence[str]
        研究域。

    返回
    ----
    pd.DataFrame
        ``stock_code, trade_date, row_present, status``；``status`` 取值：
        ``trading``（面板有该行）、``not_listed``（早于该支首个可用日）、
        ``delisted``（晚于该支末个可用日且该支末日晚于全池末日 ⇒ 退市/被吸并）、
        ``suspended``（两头都有行、中间缺失 ⇒ 停牌）。
    """
    codes = [str(c).zfill(6) for c in codes]
    if len(set(codes)) != len(codes):
        raise AsofPanelError("研究域存在重复股票代码")
    calendar = list(calendar)
    if not calendar:
        raise AsofPanelError("交易日历为空")
    work = panel.loc[:, [CODE_COLUMN, DATE_COLUMN]].copy()
    work[CODE_COLUMN] = work[CODE_COLUMN].astype(str).str.zfill(6)
    work[DATE_COLUMN] = work[DATE_COLUMN].astype(str)
    work = work[work[CODE_COLUMN].isin(codes)]
    work["row_present"] = True

    grid = pd.MultiIndex.from_product([codes, calendar], names=[CODE_COLUMN, DATE_COLUMN]).to_frame(index=False)
    merged = grid.merge(work, on=[CODE_COLUMN, DATE_COLUMN], how="left")
    merged["row_present"] = merged["row_present"].fillna(False).astype(bool)

    span = (
        work.groupby(CODE_COLUMN)[DATE_COLUMN]
        .agg(first="min", last="max")
        .reindex(codes)
    )
    calendar_last = calendar[-1]
    status = np.empty(len(merged), dtype=object)
    date_values = merged[DATE_COLUMN].to_numpy()
    code_values = merged[CODE_COLUMN].to_numpy()
    present = merged["row_present"].to_numpy()
    first_map = span["first"].to_dict()
    last_map = span["last"].to_dict()
    for i in range(len(merged)):
        if present[i]:
            status[i] = "trading"
            continue
        code = code_values[i]
        date = date_values[i]
        first = first_map.get(code)
        last = last_map.get(code)
        if first is None or last is None or (isinstance(first, float) and np.isnan(first)):
            status[i] = "not_listed"
            continue
        if date < first:
            status[i] = "not_listed"
        elif date > last:
            status[i] = "delisted" if last < calendar_last else "suspended"
        else:
            status[i] = "suspended"
    merged["status"] = status
    return merged


# ---------------------------------------------------------------------------
# 2. 前瞻标签（按交易日历计数，F10）
# ---------------------------------------------------------------------------

def forward_return_labels(
    basis_panel: pd.DataFrame,
    calendar: Sequence[str],
    codes: Sequence[str],
    horizons: Sequence[int] = DEFAULT_HORIZONS,
) -> pd.DataFrame:
    """按**完整交易日历**计数的 h 日前瞻收益。

    标签 = 沿日历轴连续 h 个交易日、该支**每日都有行且收益有限**时的复利总收益：

    ``label_h(t) = prod_{k=1..h} (1 + basis_return(t+k)) - 1``

    任一中间日缺行（停牌）/ 越过末个可用日（退市）/ 收益不可用（``basis_source='unavailable'``）
    → 标签为 NaN，并写 ``label_reason_h``，**不静默丢弃整支**（F10 契约）。

    Parameters
    ----------
    basis_panel : pd.DataFrame
        :func:`src.data.return_basis.compute_return_basis` 的输出（含 ``basis_return``）。
    calendar, codes : Sequence
        交易日历与研究域。
    horizons : Sequence[int]
        视界（交易日），正整数。

    Returns
    -------
    pd.DataFrame
        ``stock_code, signal_date, status, label_{h}, label_ok_{h}, label_reason_{h}``（宽表，每行一个
        code×日期），``status`` 来自 :func:`align_to_calendar`。
    """
    required = {CODE_COLUMN, DATE_COLUMN, "basis_return"}
    missing = required - set(basis_panel.columns)
    if missing:
        raise AsofPanelError(f"收益面板缺少列：{sorted(missing)}")
    horizons = [int(h) for h in horizons]
    if not horizons or any(h < 1 for h in horizons):
        raise AsofPanelError("horizons 必须为正整数序列")

    aligned = align_to_calendar(basis_panel, calendar, codes)
    work = basis_panel.loc[:, [CODE_COLUMN, DATE_COLUMN, "basis_return"]].copy()
    work[CODE_COLUMN] = work[CODE_COLUMN].astype(str).str.zfill(6)
    work[DATE_COLUMN] = work[DATE_COLUMN].astype(str)
    calendar_index = {date: i for i, date in enumerate(calendar)}
    work["cal_index"] = work[DATE_COLUMN].map(calendar_index)
    if work["cal_index"].isna().any():
        raise AsofPanelError("收益面板含不在交易日历中的日期")

    wide = work.pivot_table(index=CODE_COLUMN, columns="cal_index", values="basis_return", aggfunc="first")
    wide = wide.reindex(index=sorted(set(aligned[CODE_COLUMN])), columns=range(len(calendar)))
    values = wide.to_numpy(dtype=float)
    n_dates = len(calendar)
    statuses = aligned.set_index([CODE_COLUMN, DATE_COLUMN])["status"].reindex(
        pd.MultiIndex.from_product([wide.index, calendar], names=[CODE_COLUMN, DATE_COLUMN])
    ).to_numpy(dtype=object).reshape(values.shape)

    result = aligned.copy()
    codes_array = result[CODE_COLUMN].to_numpy()
    dates_array = result[DATE_COLUMN].to_numpy()
    for h in horizons:
        label = np.full(values.shape, np.nan)
        for k in range(n_dates - h):
            window = values[:, k + 1 : k + 1 + h]
            ok = np.isfinite(window).all(axis=1)
            if ok.any():
                label[ok, k] = np.prod(1.0 + window[ok], axis=1) - 1.0
        label_long = pd.DataFrame(
            {
                CODE_COLUMN: np.repeat(np.asarray(wide.index), n_dates),
                DATE_COLUMN: np.tile(np.asarray(calendar), len(wide.index)),
                f"label_{h}": label.reshape(-1),
            }
        )
        result = result.merge(
            label_long,
            on=[CODE_COLUMN, DATE_COLUMN],
            how="left",
            validate="one_to_one",
        )

        ok_mask = result[f"label_{h}"].notna().to_numpy()
        after_end = np.array(
            [calendar_index[d] + h >= n_dates for d in dates_array], dtype=bool
        )
        own_status = result["status"].to_numpy(dtype=object)
        reasons = np.full(len(result), "ok", dtype=object)
        for row_index in range(len(result)):
            if ok_mask[row_index]:
                continue
            if own_status[row_index] != "trading":
                reasons[row_index] = f"{own_status[row_index]}_on_signal_date"
                continue
            if after_end[row_index]:
                reasons[row_index] = "insufficient_calendar_after"
                continue
            position = calendar_index[dates_array[row_index]]
            code_position = wide.index.get_loc(codes_array[row_index])
            forward = statuses[code_position, position + 1 : position + 1 + h]
            offending = [s for s in forward if s != "trading"]
            if offending:
                reasons[row_index] = f"{offending[0]}_inside_horizon"
            else:
                reasons[row_index] = "return_unavailable_inside_horizon"
        result[f"label_ok_{h}"] = ok_mask
        result[f"label_reason_{h}"] = reasons
    return result


# ---------------------------------------------------------------------------
# 3. 文本流量特征（逐条 publish_time ⇒ 真正 as-of）
# ---------------------------------------------------------------------------

def load_corpus_records(corpus_dir: str | Path) -> pd.DataFrame:
    """读取盘上语料，产出 ``stock_code, publish_date, item_type`` 记录表。

    只读；不推断、不补抓。缺文件的股票不会出现在结果中（由调用方对照覆盖率）。
    """
    directory = Path(corpus_dir)
    if not directory.exists():
        raise AsofPanelError(f"语料目录不存在：{directory}")
    rows: list[dict[str, str]] = []
    for path in sorted(directory.glob("*.jsonl")):
        code = path.stem
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise AsofPanelError(f"{path.name} 含非法 JSON 行：{exc}") from exc
                published = str(record.get("publish_time") or "").strip()
                if len(published) < 10:
                    raise AsofPanelError(f"{path.name} 存在缺失 publish_time 的记录")
                rows.append(
                    {
                        CODE_COLUMN: code,
                        "publish_date": published[:10],
                        "item_type": str(record.get("item_type") or "unknown"),
                    }
                )
    if not rows:
        raise AsofPanelError(f"语料目录 {directory} 未读到任何记录")
    return pd.DataFrame(rows, columns=[CODE_COLUMN, "publish_date", "item_type"])


def text_flow_features(
    records: pd.DataFrame,
    calendar: Sequence[str],
    codes: Sequence[str],
    windows: Sequence[int] = DEFAULT_TEXT_WINDOWS,
    lag_days: int = DEFAULT_TEXT_LAG_DAYS,
) -> pd.DataFrame:
    """把逐条语料聚合成**逐信号日 as-of** 文本流量特征（纯函数）。

    可用性规则：第 ``d`` 日发布的记录，最早在第 ``d + lag_days`` 个自然日**当日或之后**的第一个
    交易日可用于信号（默认 ``lag_days=1``，即当日发布当日不可用）。

    特征（全部对"零记录"也有定义，故不存在"填 0 掩盖缺失"的问题）：

    * ``flow_total_w{w}`` = ``log1p(窗口内可用记录数)``
    * ``flow_news_w{w}`` = ``log1p(窗口内可用新闻数)``
    * ``flow_recency`` = ``min(自最后一条可用记录以来的交易日数, 60) / 60``（窗口内无记录时为 1.0）

    Parameters
    ----------
    records : pd.DataFrame
        ``stock_code, publish_date, item_type``。
    calendar : Sequence[str]
        交易日历。
    codes : Sequence[str]
        研究域。
    windows : Sequence[int]
        交易日窗口。
    lag_days : int
        可用性滞后（自然日）。

    Returns
    -------
    pd.DataFrame
        ``stock_code, trade_date`` + 上述特征列（覆盖全部 code × 日历）。
    """
    needed = {CODE_COLUMN, "publish_date", "item_type"}
    missing = needed - set(records.columns)
    if missing:
        raise AsofPanelError(f"语料记录表缺少列：{sorted(missing)}")
    if int(lag_days) < 0:
        raise AsofPanelError("lag_days 不能为负")
    windows = [int(w) for w in windows]
    if not windows or any(w < 1 for w in windows):
        raise AsofPanelError("windows 必须为正整数序列")

    calendar = list(calendar)
    index_of = {date: i for i, date in enumerate(calendar)}
    codes = [str(c).zfill(6) for c in codes]

    work = records.copy()
    work[CODE_COLUMN] = work[CODE_COLUMN].astype(str).str.zfill(6)
    work["publish_date"] = work["publish_date"].astype(str)
    unusable = ~work[CODE_COLUMN].isin(codes)
    work = work[~unusable]

    calendar_dates = pd.to_datetime(pd.Series(calendar), format="%Y-%m-%d")
    published = pd.to_datetime(work["publish_date"], format="%Y-%m-%d", errors="coerce")
    if published.isna().any():
        bad = work.loc[published.isna(), "publish_date"].iloc[0]
        raise AsofPanelError(f"语料含非法发布日期：{bad!r}")
    earliest = published + pd.Timedelta(days=int(lag_days))
    usable_from = np.searchsorted(calendar_dates.to_numpy(), earliest.to_numpy(), side="left")
    work = work.assign(usable_index=usable_from)
    work = work[work["usable_index"] < len(calendar)]

    n_codes, n_dates = len(codes), len(calendar)
    code_pos = {code: i for i, code in enumerate(codes)}
    totals = np.zeros((n_codes, n_dates))
    news = np.zeros((n_codes, n_dates))
    for code, usable_index, item_type in zip(work[CODE_COLUMN], work["usable_index"], work["item_type"]):
        pos = code_pos.get(code)
        if pos is None:
            continue
        totals[pos, usable_index] += 1.0
        if str(item_type) == "news":
            news[pos, usable_index] += 1.0

    features: dict[str, np.ndarray] = {}
    cumulative_total = np.cumsum(totals, axis=1)
    cumulative_news = np.cumsum(news, axis=1)
    for w in windows:
        if w >= n_dates:
            # 窗口长于可用日历：整段历史都在窗口内（不得越界拼接）
            in_window_total = cumulative_total
            in_window_news = cumulative_news
        else:
            shifted_total = np.concatenate(
                [np.zeros((n_codes, w)), cumulative_total[:, :-w]], axis=1
            )
            shifted_news = np.concatenate([np.zeros((n_codes, w)), cumulative_news[:, :-w]], axis=1)
            in_window_total = cumulative_total - shifted_total
            in_window_news = cumulative_news - shifted_news
        features[f"flow_total_w{w}"] = np.log1p(in_window_total)
        features[f"flow_news_w{w}"] = np.log1p(in_window_news)

    max_window = max(windows)
    last_seen = np.full((n_codes, n_dates), -1)
    running = np.full(n_codes, -1.0)
    for j in range(n_dates):
        seen_today = totals[:, j] > 0
        running = np.where(seen_today, float(j), running)
        last_seen[:, j] = running
    column_index = np.arange(n_dates, dtype=float)[None, :]
    age = column_index - last_seen
    below = np.where(last_seen < 0, np.inf, age)
    features["flow_recency"] = np.clip(below, 0.0, float(max_window)) / float(max_window)

    frame = pd.DataFrame(
        {
            CODE_COLUMN: np.repeat(codes, n_dates),
            DATE_COLUMN: np.tile(calendar, n_codes),
        }
    )
    for name, matrix in features.items():
        frame[name] = matrix.reshape(-1)
    return frame


def feature_family_columns(config: AsofPanelConfig) -> tuple[str, ...]:
    """该配置实际需要的特征列（文本族按窗口展开）。"""
    if config.is_text_family:
        columns: list[str] = []
        for w in config.text_windows:
            columns.extend([f"flow_total_w{w}", f"flow_news_w{w}"])
        columns.append("flow_recency")
        return tuple(columns)
    return config.required_columns()


# ---------------------------------------------------------------------------
# 4. 训练期定标 + 逐信号日截面
# ---------------------------------------------------------------------------

def align_pca_signs(loadings: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """把 PCA 载荷按"最大绝对载荷项为正"逐分量翻号，返回 (对齐后载荷, 符号向量)。

    PCA 分量的符号本身任意（不同训练窗可能整体翻号，会让 S0 随机变号）。公务规则：
    每个分量的最大 ``|loading|`` 项必须为正，符号由其决定。该规则**只看训练期载荷**，
    不使用任何标签，故不引入前视。

    Examples
    --------
    >>> align_pca_signs(np.array([[-3.0, 1.0, 0.5]]))[0].tolist()
    [[3.0, -1.0, -0.5]]
    """
    matrix = np.asarray(loadings, dtype=float)
    if matrix.ndim != 2:
        raise AsofPanelError("PCA 载荷必须是二维矩阵")
    reference = np.argmax(np.abs(matrix), axis=1)
    signs = np.sign(matrix[np.arange(matrix.shape[0]), reference])
    signs[signs == 0] = 1.0
    return matrix * signs[:, None], signs


def _build_pca_engine(train_values: np.ndarray, config: AsofPanelConfig) -> tuple[StandardScaler, PCA, np.ndarray]:
    """在训练窗上拟合 StandardScaler + full-SVD PCA，并把分量符号对齐（确定性）。"""
    scaler = StandardScaler()
    scaled = scaler.fit_transform(train_values)
    pca = PCA(n_components=int(config.n_components), svd_solver="full", random_state=0)
    pca.fit(scaled)
    aligned, signs = align_pca_signs(pca.components_)
    pca.components_ = aligned
    return scaler, pca, signs


def _cross_section_pipeline(
    scores: pd.Series,
    industries: pd.Series,
    market_values: pd.Series,
    config: AsofPanelConfig,
) -> pd.Series:
    """当日截面：MAD 去极值 → 行业+对数市值 OLS 残差 → 截面 Z-score。"""
    winsorized = winsorize_mad(scores, n=config.winsor_n, scale=config.mad_scale)
    residual = neutralize_cross_section(winsorized, industries, market_values)
    return standardize_zscore(residual)


def build_asof_panel(
    feature_frame: pd.DataFrame,
    panel: pd.DataFrame,
    basis_panel: pd.DataFrame,
    calendar: Sequence[str],
    codes: Sequence[str],
    config: AsofPanelConfig,
    *,
    industries: Mapping[str, str] | None = None,
    corpus_version: str = "unavailable",
    embedding_model_version: str = "unavailable",
    embedding_truncation_date: str = "unavailable",
) -> AsofPanelResult:
    """构造 as-of S0 面板（纯函数，不写盘）。

    Parameters
    ----------
    feature_frame : pd.DataFrame
        ``stock_code, trade_date`` + 声明特征列（技术族来自主面板，文本族来自
        :func:`text_flow_features`）。
    panel : pd.DataFrame
        主面板（提供 ``close`` / ``market_value`` / 行业列）。
    basis_panel : pd.DataFrame
        统一口径收益面板（构造标签）。
    calendar, codes : Sequence
        交易日历与研究域。
    config : AsofPanelConfig
        参数。
    industries : Mapping[str, str] | None
        代码 → 行业；None 时取 ``panel`` 的 ``config.industry_column``。
    corpus_version, embedding_model_version, embedding_truncation_date : str
        数据契约要求的版本字段（缺省显式写 ``unavailable``，不假装有版本）。

    Returns
    -------
    AsofPanelResult
        ``panel`` 满足 §3 契约列；``fit_report`` 逐信号日记录训练窗、PC 符号与解释方差；
        ``counters`` 记录各类不可用原因（不静默）。

    Raises
    ------
    AsofPanelError
        特征列缺失、行业映射缺失、训练窗/截面不足且无法产出任何信号日等违约情形。
    """
    feature_columns = feature_family_columns(config)
    required = {CODE_COLUMN, DATE_COLUMN, *feature_columns}
    missing = required - set(feature_frame.columns)
    if missing:
        raise AsofPanelError(f"特征表缺少列：{sorted(missing)}")
    if DATE_COLUMN not in panel.columns or PRICE_COLUMN not in panel.columns:
        raise AsofPanelError(f"主面板缺少 {PRICE_COLUMN} 列")
    if MARKET_VALUE_COLUMN not in panel.columns:
        raise AsofPanelError(f"主面板缺少 {MARKET_VALUE_COLUMN} 列")

    calendar = list(calendar)
    codes = [str(c).zfill(6) for c in codes]
    index_of = {date: i for i, date in enumerate(calendar)}

    features = feature_frame.copy()
    features[CODE_COLUMN] = features[CODE_COLUMN].astype(str).str.zfill(6)
    features[DATE_COLUMN] = features[DATE_COLUMN].astype(str)
    features = features[features[CODE_COLUMN].isin(codes)]
    if features.duplicated([CODE_COLUMN, DATE_COLUMN]).any():
        raise AsofPanelError("特征表存在重复 (stock_code, trade_date) 键")
    # 统计"整列全缺"的族，fail-closed（防止产出全 NaN 的假面板）
    for column in feature_columns:
        if features[column].notna().sum() == 0:
            raise AsofPanelError(
                f"特征列 {column!r} 在给定研究域上全部缺失：该特征族与本股票池不匹配"
                "（A 组只有技术类因子、B/C 组只有基本面因子），拒绝产出假面板"
            )

    price = panel.loc[:, [CODE_COLUMN, DATE_COLUMN, PRICE_COLUMN, MARKET_VALUE_COLUMN]].copy()
    price[CODE_COLUMN] = price[CODE_COLUMN].astype(str).str.zfill(6)
    price[DATE_COLUMN] = price[DATE_COLUMN].astype(str)
    price = price[price[CODE_COLUMN].isin(codes)]
    price = price.drop_duplicates([CODE_COLUMN, DATE_COLUMN])

    if industries is None:
        if config.industry_column not in panel.columns:
            raise AsofPanelError(f"主面板缺少行业列 {config.industry_column!r}，无法做行业中性化")
        industry_map = (
            panel.loc[:, [CODE_COLUMN, config.industry_column]]
            .dropna()
            .drop_duplicates(CODE_COLUMN)
            .set_index(CODE_COLUMN)[config.industry_column]
            .astype(str)
            .to_dict()
        )
    else:
        industry_map = {str(k).zfill(6): str(v) for k, v in industries.items()}

    merged = features.merge(price, on=[CODE_COLUMN, DATE_COLUMN], how="left", validate="one_to_one")
    merged["cal_index"] = merged[DATE_COLUMN].map(index_of)
    merged = merged[merged["cal_index"].notna()]
    merged["cal_index"] = merged["cal_index"].astype(int)
    merged["industry"] = merged[CODE_COLUMN].map(industry_map)

    labels = forward_return_labels(basis_panel, calendar, codes, config.horizons)
    counters: dict[str, int] = {
        "rows_total_all_dates": int(len(merged)),
        "feature_missing_rows_all_dates": int(merged[list(feature_columns)].isna().any(axis=1).sum()),
        "industry_missing_rows_all_dates": int(merged["industry"].isna().sum()),
        "price_missing_rows_all_dates": int(merged[PRICE_COLUMN].isna().sum()),
        "market_value_missing_rows_all_dates": int(merged[MARKET_VALUE_COLUMN].isna().sum()),
        "signal_dates_considered": 0,
        "signal_dates_skipped_insufficient_train": 0,
        "signal_dates_skipped_insufficient_cross_section": 0,
        "rows_emitted": 0,
        "rows_unavailable": 0,
        "rows_feature_missing": 0,
        "rows_market_value_missing": 0,
        "rows_industry_missing": 0,
    }

    lookback = config.lookback_days()
    min_index = config.min_signal_index
    if min_index is None:
        min_index = max(int(config.train_window_days), lookback) + 1

    if config.signal_dates is None:
        candidate_dates = [date for date in calendar if index_of[date] >= min_index]
    else:
        unknown = [d for d in config.signal_dates if d not in index_of]
        if unknown:
            raise AsofPanelError(f"signal_dates 含不在交易日历中的日期：{unknown[:3]}")
        candidate_dates = sorted(config.signal_dates)

    by_date = {date: group for date, group in merged.groupby(DATE_COLUMN, sort=False)}
    fit_rows: list[dict[str, Any]] = []
    panel_rows: list[pd.DataFrame] = []

    for signal_date in candidate_dates:
        counters["signal_dates_considered"] += 1
        signal_index = index_of[signal_date]
        train_start = max(0, signal_index - int(config.train_window_days))
        train_dates = calendar[train_start:signal_index]
        if len(train_dates) < 2:
            counters["signal_dates_skipped_insufficient_train"] += 1
            continue

        today = by_date.get(signal_date)
        if today is None or len(today) < int(config.min_cross_section):
            counters["signal_dates_skipped_insufficient_cross_section"] += 1
            continue

        train = merged[merged[DATE_COLUMN].isin(train_dates)]
        train_complete = train.dropna(subset=[*feature_columns, "industry", MARKET_VALUE_COLUMN])
        if len(train_complete) < int(config.min_train_rows):
            counters["signal_dates_skipped_insufficient_train"] += 1
            continue

        scaler, pca, signs = _build_pca_engine(
            train_complete.loc[:, list(feature_columns)].to_numpy(dtype=float), config
        )

        usable = today.dropna(subset=[*feature_columns]).copy()
        usable = usable[usable[MARKET_VALUE_COLUMN].notna() & (usable[MARKET_VALUE_COLUMN] > 0)]
        usable = usable[usable["industry"].notna()]
        if len(usable) < int(config.min_cross_section):
            counters["signal_dates_skipped_insufficient_cross_section"] += 1
            continue

        scores = pca.transform(scaler.transform(usable.loc[:, list(feature_columns)].to_numpy(dtype=float)))
        pc_frame = pd.DataFrame(
            scores,
            columns=[f"PC{i:02d}" for i in range(1, int(config.n_components) + 1)],
            index=usable.index,
        )
        z_frame = pc_frame.apply(standardize_zscore)

        composite = standardize_zscore(z_frame.mean(axis=1))
        composite = _cross_section_pipeline(
            composite,
            usable["industry"],
            usable[MARKET_VALUE_COLUMN],
            config,
        )

        prior_weights = np.array([0.15, -0.15, 0.35, 0.20, -0.35])
        prior = pd.Series(np.nan, index=z_frame.index, dtype=float)
        if int(config.n_components) >= len(prior_weights):
            prior_raw = pd.Series(
                z_frame.iloc[:, : len(prior_weights)].to_numpy(dtype=float) @ prior_weights,
                index=z_frame.index,
            )
            prior = _cross_section_pipeline(
                prior_raw, usable["industry"], usable[MARKET_VALUE_COLUMN], config
            )

        # 不可用行必须**保留在面板里**并写明原因，不得静默丢弃（审计要求）。
        emitted = today.copy()
        missing_features = today[list(feature_columns)].isna()
        no_feature = missing_features.any(axis=1)
        no_cap = today[MARKET_VALUE_COLUMN].isna() | ~(today[MARKET_VALUE_COLUMN] > 0)
        no_industry = today["industry"].isna()
        available = ~(no_feature | no_cap | no_industry)
        counters["rows_unavailable"] += int((~available).sum())
        counters["rows_feature_missing"] = counters.get("rows_feature_missing", 0) + int(no_feature.sum())
        counters["rows_market_value_missing"] = counters.get("rows_market_value_missing", 0) + int(no_cap.sum())
        counters["rows_industry_missing"] = counters.get("rows_industry_missing", 0) + int(no_industry.sum())

        reason_names = (
            missing_features.apply(
                lambda row: ",".join(list(row.index[row.to_numpy()])[:3]), axis=1
            )
        )
        emitted["is_available"] = available.to_numpy()
        emitted["unavailable_reason"] = np.select(
            [
                no_feature.to_numpy(),
                no_cap.to_numpy(),
                no_industry.to_numpy(),
            ],
            [
                "feature_missing:" + reason_names.to_numpy(),
                "market_value_missing_or_nonpositive",
                "industry_missing",
            ],
            default="",
        )
        for column in z_frame.columns:
            emitted[f"{column}_z"] = z_frame[column].reindex(emitted.index)
        emitted["S0"] = composite.reindex(emitted.index)
        emitted["S0_pc5_prior"] = prior.reindex(emitted.index)
        emitted["s0_pc5_prior_version"] = (
            S0_PC5_PRIOR_VERSION
            if int(config.n_components) >= len(prior_weights)
            else "not_applied_n_components_below_5"
        )

        emitted = emitted.loc[
            :,
            [
                CODE_COLUMN,
                DATE_COLUMN,
                "S0",
                PRICE_COLUMN,
                MARKET_VALUE_COLUMN,
                "industry",
                "is_available",
                "unavailable_reason",
                *[f"{name}_z" for name in z_frame.columns],
                "S0_pc5_prior",
                "s0_pc5_prior_version",
                *list(feature_columns),
            ],
        ].copy()
        emitted["signal_date"] = signal_date
        emitted["signal_cal_index"] = signal_index
        emitted = emitted.merge(
            labels[[CODE_COLUMN, DATE_COLUMN, "status", *[c for c in labels.columns if c.startswith(("label_",))]]].rename(
                columns={DATE_COLUMN: "signal_date"}
            ),
            on=[CODE_COLUMN, "signal_date"],
            how="left",
            validate="one_to_one",
        )
        panel_rows.append(emitted)
        counters["rows_emitted"] += int(len(emitted))

        aligned_loadings = pca.components_
        reference_index = np.argmax(np.abs(aligned_loadings), axis=1)
        top_loading_positive = bool(
            (aligned_loadings[np.arange(len(reference_index)), reference_index] > 0).all()
        )
        fit_rows.append(
            {
                "signal_date": signal_date,
                "train_start": train_dates[0],
                "train_end": train_dates[-1],
                "train_rows": int(len(train_complete)),
                "cross_section_rows": int(len(usable)),
                "pc_signs": "".join("+" if s > 0 else "-" for s in signs),
                "pc_top_features": ",".join(str(feature_columns[i]) for i in reference_index),
                "pc_top_loadings_positive": top_loading_positive,
                "explained_variance_ratio_sum": float(np.sum(pca.explained_variance_ratio_)),
                "scaler_mean_norm": float(np.linalg.norm(scaler.mean_)),
            }
        )

    if not panel_rows:
        raise AsofPanelError(
            "没有任何信号日满足训练窗与截面要求：拒绝返回空面板（请检查交易日历起点、"
            "train_window_days / min_train_rows / min_cross_section 与特征族是否匹配股票池）"
        )

    panel_out = pd.concat(panel_rows, ignore_index=True)
    panel_out = panel_out.rename(columns={DATE_COLUMN: "trade_date"})
    panel_out["available_at"] = panel_out["signal_date"]
    panel_out["raw_corpus_version"] = corpus_version
    panel_out["embedding_model_version"] = embedding_model_version
    panel_out["embedding_truncation_date"] = embedding_truncation_date
    panel_out["feature_window_start"] = panel_out["signal_cal_index"].map(
        lambda i: calendar[max(0, i - lookback)]
    )
    panel_out["s0_version"] = S0_VERSION
    panel_out["pca_version"] = PCA_VERSION
    panel_out["neutralization_version"] = NEUTRALIZATION_VERSION
    panel_out["feature_family"] = config.feature_family
    panel_out["asof_panel_version"] = ASOF_PANEL_VERSION
    panel_out["declared_bias_warning"] = DECLARED_BIAS_WARNING
    panel_out["available_flags"] = np.where(
        panel_out["is_available"].to_numpy(),
        "features_ok|text_publish_time_asof|static_embedding_NOT_ASOF",
        "features_missing|static_embedding_NOT_ASOF",
    )
    counters["rows_unavailable"] = int((~panel_out["is_available"]).sum())

    ordered = [
        CODE_COLUMN,
        "signal_date",
        "available_at",
        "feature_window_start",
        "raw_corpus_version",
        "embedding_model_version",
        "embedding_truncation_date",
        "s0_version",
        "pca_version",
        "neutralization_version",
        "feature_family",
        "asof_panel_version",
        "S0",
        PRICE_COLUMN,
        MARKET_VALUE_COLUMN,
        "industry",
        "is_available",
        "unavailable_reason",
        "available_flags",
        "declared_bias_warning",
        "s0_pc5_prior_version",
        *[c for c in panel_out.columns if c.startswith(("PC", "label_", "S0_pc5", "flow_"))],
        "status",
        "signal_cal_index",
    ]
    panel_out = panel_out.loc[:, [c for c in ordered if c in panel_out.columns]]
    return AsofPanelResult(
        panel=panel_out,
        fit_report=pd.DataFrame(fit_rows),
        counters=counters,
        config=config,
    )