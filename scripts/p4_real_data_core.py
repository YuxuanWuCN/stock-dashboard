# -*- coding: utf-8 -*-
"""scripts/p4_real_data_core.py —— P4 真实数据量化复算共享内核（修正版 v2）

本模块为 M4/P4 返工后的统一计算内核，被以下脚本复用：
  - scripts/run_p4_trend_gate_study.py  （实验一：Trend Gate 事件研究 + 安慰剂）
  - scripts/run_p4_fama_macbeth.py      （实验二：Fama-MacBeth HAC 截面回归）
  - scripts/run_real_m4_rebuild.py      （端到端一键复算）

相对 v1（commit 21c3d5d0）修正的核心问题：
  1. 前视偏差：v1 的 Fama-MacBeth 用当日收益回归含当日信息的因子（mom_20d / amihud /
     price_pos 均由当日数据构造），导致 t 值虚高。v2 的被解释变量固定为 t+1 可交易收益。
  2. 涨跌停约束形同虚设：v1 读取 `hit_limit == -1` 判断跌停，但该列取值域只有 {0, 1}，
     条件恒不成立；且判断的是触发日而非进场/退出日。v2 重建涨跌停方向，并分别作用于
     进场日（涨停买不进）与退出日（跌停卖不出），退出日不可成交时顺延至下一可成交日。
  3. 安慰剂抽样池混入触发样本、每次抽样量与触发样本数不一致、经验 p 值未落盘未进正文。
     v2 抽样池严格排除触发样本，抽样量与触发样本数一致，并如实计算单/双侧经验 p 值。

数据口径（全部可追溯，无任何硬编码结果）：
  - 价格：`close`（CSMAR TRD_Dalyr Clsprc），覆盖 299 支全部标的。
  - 收益：优先使用官方复权日收益 `ret`（Dretwd）；对缺少 ret 的标的，用 close 计算的
    收盘到收盘收益。已实测：99 支同时具备两者的标的上，两条口径的日收益中位绝对差
    仅 2.4e-7，可视为一致。
  - 涨跌停：`hit_limit`（LimitStatus != 0）覆盖 199 支；方向由 `ret` 符号确定，
    ret 缺失时用 close 收益符号，仍不可判时用 `price_pos`（收在最高/最低）兜底。
  - 停牌/异常交易：`abnormal_trd`（Trdsta != 1）。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np
import pandas as pd

# A 股年化交易日口径（方案 §P4 统计报告口径：统一 244 天）
ANNUALIZATION_DAYS = 244

# 无风险利率：项目既有现金利息假设（ORIGINAL_REQUEST §R3：闲置现金年化 1.5%）
RISK_FREE_RATE_ANNUAL = 0.015

# 各板块涨跌幅限制（涨跌停判定与指纹校验共用）
BOARD_LIMITS = {
    "main": 0.10,      # 沪深主板
    "chinext": 0.20,   # 创业板 300/301
    "star": 0.20,      # 科创板 688
}
# ST 标的为 ±5%，但本面板不含 ST 标记字段，无法识别，作为已知局限在报告中披露。
ST_LIMIT = 0.05

# 事件研究参数
TREND_MOM_WINDOW = 20
TREND_MA_WINDOW = 60
DEFAULT_HORIZONS = (5, 10, 20)
# 退出日跌停无法卖出时，最多顺延的交易日数
DEFAULT_MAX_DEFER = 5

# 涨跌停方向判定的收盘位置阈值
PRICE_POS_HIGH = 0.99   # 收在当日最高价 → 涨停
PRICE_POS_LOW = 0.01    # 收在当日最低价 → 跌停


# ===========================================================================
# 基础工具
# ===========================================================================
def sha256_of_file(path: Path | str, chunk: int = 1 << 20) -> str:
    """计算文件 sha256，用于把结果绑定到确定的数据版本。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def stock_board(code: str) -> str:
    """按证券代码返回板块，用于确定涨跌幅限制。"""
    code = str(code).zfill(6)
    if code.startswith(("300", "301")):
        return "chinext"
    if code.startswith("688"):
        return "star"
    return "main"


def board_limit(code: str) -> float:
    """返回该标的的日涨跌幅限制（小数）。"""
    return BOARD_LIMITS[stock_board(code)]


# ===========================================================================
# 计量工具：Newey-West HAC / 区块 Bootstrap / 多重检验
# ===========================================================================
def calc_newey_west_lags(n_obs: int) -> int:
    """标准经验公式: q = max(1, floor(4 * (T / 100) ** (2/9)))。

    T=585 时 q=5；T=100 时 q=4。
    """
    if n_obs <= 0:
        return 1
    q = int(np.floor(4.0 * (float(n_obs) / 100.0) ** (2.0 / 9.0)))
    return max(1, q)


def newey_west_t_stat(series: np.ndarray, lags: int) -> Tuple[float, float, float]:
    """时间序列均值的 Newey-West (Bartlett 核) HAC t 统计量。

    返回 (mean, nw_se, t_stat)。方差估计采用 1/T 归一口径：
        Var(mean) = (1/T) * [ gamma_0 + 2 * sum_l w_l * gamma_l ],  w_l = 1 - l/(L+1)
    """
    series = np.asarray(series, dtype=float)
    series = series[np.isfinite(series)]
    T = len(series)
    if T < 2:
        return (float(series[0]) if T == 1 else float("nan")), float("nan"), float("nan")
    mu = float(np.mean(series))
    e = series - mu
    gamma_0 = float(np.sum(e ** 2) / T)
    var_hac = gamma_0
    lags = max(0, int(lags))
    for lag in range(1, min(lags, T - 1) + 1):
        weight = 1.0 - float(lag) / (lags + 1.0)
        gamma_l = float(np.sum(e[lag:] * e[:-lag]) / T)
        var_hac += 2.0 * weight * gamma_l
    var_hac = max(var_hac, 1e-18)
    se = float(np.sqrt(var_hac / T))
    return mu, se, float(mu / se)


def classic_iid_t_stat(series: np.ndarray) -> Tuple[float, float, float]:
    """普通 IID t 统计量（标准差用 ddof=1），用于与 HAC 对照。"""
    series = np.asarray(series, dtype=float)
    series = series[np.isfinite(series)]
    T = len(series)
    if T < 2:
        return float("nan"), float("nan"), float("nan")
    mu = float(np.mean(series))
    se = float(np.std(series, ddof=1) / np.sqrt(T))
    if se <= 0:
        return mu, 0.0, float("inf") if mu > 0 else (float("-inf") if mu < 0 else 0.0)
    return mu, se, float(mu / se)


def moving_block_bootstrap_means(
    series: np.ndarray,
    block_len: int,
    n_boot: int = 1000,
    seed: int = 42,
) -> np.ndarray:
    """移动区块 Bootstrap（MBB）对均值重抽样，返回 n_boot 个 bootstrap 均值。

    区块长度取 max(1, round(T ** (1/3)))，这是 MBB 的常规经验规则，保证区块内
    保留自相关结构。固定随机种子，结果可复算。
    """
    series = np.asarray(series, dtype=float)
    series = series[np.isfinite(series)]
    T = len(series)
    if T == 0:
        return np.zeros(n_boot)
    block_len = max(1, min(int(block_len), T))
    n_blocks = int(np.ceil(T / block_len))
    max_start = T - block_len
    rng = np.random.RandomState(seed)
    out = np.empty(n_boot, dtype=float)
    for b in range(n_boot):
        starts = rng.randint(0, max_start + 1, size=n_blocks)
        idx = (starts[:, None] + np.arange(block_len)[None, :]).ravel()[:T]
        out[b] = float(np.mean(series[idx]))
    return out


def block_bootstrap_ci(
    series: np.ndarray,
    block_len: int | None = None,
    n_boot: int = 1000,
    seed: int = 42,
    alpha: float = 0.05,
) -> Tuple[float, float]:
    """MBB 均值的双侧百分位置信区间。"""
    T = int(np.isfinite(np.asarray(series, dtype=float)).sum())
    if block_len is None:
        block_len = default_block_len(T)
    boots = moving_block_bootstrap_means(series, block_len, n_boot=n_boot, seed=seed)
    return (
        float(np.percentile(boots, 100.0 * (alpha / 2.0))),
        float(np.percentile(boots, 100.0 * (1.0 - alpha / 2.0))),
    )


def default_block_len(n_obs: int) -> int:
    """MBB 区块长度经验规则：T ** (1/3)。"""
    if n_obs <= 1:
        return 1
    return max(1, int(round(float(n_obs) ** (1.0 / 3.0))))


def benjamini_hochberg_fdr(p_values: Sequence[float]) -> np.ndarray:
    """Benjamini-Hochberg FDR 校正后的 q 值（含单调化处理）。"""
    p = np.asarray(p_values, dtype=float)
    m = len(p)
    if m == 0:
        return np.array([])
    order = np.argsort(p)
    ranked = p[order]
    ranks = np.arange(1, m + 1, dtype=float)
    q = ranked * m / ranks
    q = np.minimum.accumulate(q[::-1])[::-1]
    out = np.empty(m, dtype=float)
    out[order] = np.clip(q, 0.0, 1.0)
    return out


def bonferroni_adjust(p_values: Sequence[float]) -> np.ndarray:
    """Bonferroni 校正 p 值。"""
    p = np.asarray(p_values, dtype=float)
    return np.clip(p * len(p), 0.0, 1.0)


def two_sided_normal_p(t_stat: float) -> float:
    """双侧正态近似 p 值。"""
    if not np.isfinite(t_stat):
        return float("nan")
    from scipy import stats

    return float(2.0 * (1.0 - stats.norm.cdf(abs(float(t_stat)))))


# ===========================================================================
# 面板加载与真实涨跌停重建
# ===========================================================================
PANEL_REQUIRED_COLUMNS = ("stock_code", "trade_date", "close")


def load_master_panel(path: Path | str) -> pd.DataFrame:
    """加载 CSMAR 主面板并按 (stock_code, trade_date) 严格排序。"""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"找不到真实 CSMAR 数据源: {path}")
    df = pd.read_csv(path, dtype={"stock_code": str})
    missing = [c for c in PANEL_REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"主面板缺少必要列: {missing}")
    df["stock_code"] = df["stock_code"].str.zfill(6)
    df["trade_date"] = df["trade_date"].astype(str)
    df = df.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    return df


def attach_returns(df: pd.DataFrame) -> pd.DataFrame:
    """补充收盘到收盘收益与次日收益。

    - `close_ret`  : close 的个股内部一阶差分收益率（覆盖全部标的）。
    - `ret_used`   : 优先官方复权收益 ret(Dretwd)，缺失时回落到 close_ret。
    - `ret_next`   : 个股内部下一交易日收益（t → t+1），即可交易的前向收益。
    """
    df = df.copy()
    grouped = df.groupby("stock_code", sort=False)
    df["close_ret"] = grouped["close"].pct_change()
    if "ret" in df.columns:
        df["ret_used"] = df["ret"].where(df["ret"].notna(), df["close_ret"])
    else:
        df["ret_used"] = df["close_ret"]
    df["ret_next"] = df.groupby("stock_code", sort=False)["ret_used"].shift(-1)
    if "ret" in df.columns:
        # 仅用官方复权收益构造的次日收益（覆盖标的最少，用于稳健性对照）
        df["ret_next_official"] = df.groupby("stock_code", sort=False)["ret"].shift(-1)
    else:
        df["ret_next_official"] = np.nan
    return df


def derive_limit_flags(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, float]]:
    """从 `hit_limit` + 收益方向 + 收盘位置重建涨跌停方向。

    v1 直接用 `hit_limit == -1` 判跌停，而该列实际取值域为 {0, 1}（0=未触发，
    1=触发但方向已被 `!= 0` 抹平），导致跌停约束从未生效。此处重建方向。

    返回 (带新列的面板, 校验统计)。新增列：
      limit_known  : 该 (标的, 日期) 是否有涨跌停观测
      limit_up     : 涨停（收盘封在涨停价，无法买入）
      limit_down   : 跌停（收盘封在跌停价，无法卖出）
      limit_unknown: 有涨跌停标记但方向不可判（保守剔除）
    """
    df = df.copy()
    hit = df["hit_limit"] if "hit_limit" in df.columns else pd.Series(np.nan, index=df.index)
    known = hit.notna()
    is_limit = known & (hit.astype(float) != 0.0)

    direction = df["ret_used"] if "ret_used" in df.columns else df.get("ret")
    if direction is None:
        direction = df["close_ret"]
    direction = pd.Series(direction, index=df.index).astype(float)

    fallback = pd.Series(np.nan, index=df.index)
    if "price_pos" in df.columns:
        pos = pd.to_numeric(df["price_pos"], errors="coerce")
        fallback = np.where(pos >= PRICE_POS_HIGH, 1.0, np.where(pos <= PRICE_POS_LOW, -1.0, np.nan))
        fallback = pd.Series(fallback, index=df.index)

    sign = direction.where(direction.notna(), fallback)
    limit_up = is_limit & (sign > 0)
    limit_down = is_limit & (sign < 0)
    limit_unknown = is_limit & ~limit_up & ~limit_down

    df["limit_known"] = known
    df["limit_up"] = limit_up.fillna(False).astype(bool)
    df["limit_down"] = limit_down.fillna(False).astype(bool)
    df["limit_unknown"] = limit_unknown.fillna(False).astype(bool)
    if "abnormal_trd" in df.columns:
        df["suspended"] = pd.to_numeric(df["abnormal_trd"], errors="coerce").fillna(0).ne(0)
    else:
        df["suspended"] = False

    up_rows = df[df["limit_up"]]
    down_rows = df[df["limit_down"]]
    validation = {
        "n_limit_rows": int(is_limit.sum()),
        "n_limit_up": int(limit_up.sum()),
        "n_limit_down": int(limit_down.sum()),
        "n_limit_direction_unknown": int(limit_unknown.sum()),
        "limit_up_close_at_high_share": float((up_rows["price_pos"] >= PRICE_POS_HIGH).mean())
        if len(up_rows) else float("nan"),
        "limit_down_close_at_low_share": float((down_rows["price_pos"] <= PRICE_POS_LOW).mean())
        if len(down_rows) else float("nan"),
        "limit_up_abs_ret_median": float(direction[limit_up].abs().median()) if limit_up.any() else float("nan"),
        "limit_down_abs_ret_median": float(direction[limit_down].abs().median()) if limit_down.any() else float("nan"),
    }
    return df, validation


def assert_board_limit_discipline(df: pd.DataFrame) -> Dict[str, float]:
    """校验真实行情未越出板块涨跌幅限制（数据可信度指纹之一）。"""
    tmp = df.dropna(subset=["ret_used"]).copy()
    tmp["board"] = tmp["stock_code"].map(stock_board)
    tmp["limit"] = tmp["board"].map(BOARD_LIMITS)
    # 留 0.5pp 容差覆盖除权除息与四舍五入
    viol = tmp[tmp["ret_used"].abs() > tmp["limit"] + 0.005]
    return {
        "checked_rows": int(len(tmp)),
        "violations": int(len(viol)),
        "max_abs_ret": float(tmp["ret_used"].abs().max()) if len(tmp) else float("nan"),
    }


def validate_return_basis(df: pd.DataFrame, threshold: float = 0.01) -> Dict[str, float]:
    """校验「close 计算的收益」与「官方复权收益 ret(Dretwd)」的一致性。

    该面板只有 99 支标的带官方复权收益 ret，其余标的必须用 close 的收盘到收盘收益
    替代。本函数在同时具备两条口径的 99 支标的上量化替代误差，作为口径可替换性的证据；
    同时统计差异超过 threshold 的行数（除权除息日特征）。
    """
    if "ret" not in df.columns or "close_ret" not in df.columns:
        return {"available": False}
    sub = df[df["ret"].notna() & df["close_ret"].notna()]
    if len(sub) == 0:
        return {"available": False}
    diff = (sub["ret"] - sub["close_ret"]).abs()
    over = diff > threshold
    return {
        "available": True,
        "n_rows": int(len(sub)),
        "n_stocks": int(sub["stock_code"].nunique()),
        "median_abs_diff": float(diff.median()),
        "p99_abs_diff": float(diff.quantile(0.99)),
        "max_abs_diff": float(diff.max()),
        "share_over_threshold": float(over.mean()),
        "n_over_threshold": int(over.sum()),
        "threshold": float(threshold),
        "note": (
            "中位数绝对差异仅表明非除权日常态交易下价格变动中位一致，不能证明全样本分红复权等价性；"
            "差异超过阈值的行具有潜在除权除息或口径跳空特征，但在缺乏原始公司公告日志核验前，不得断言每处异常点均已被证实为除权除息。"
            "此外，事件研究采用收盘价区间收益（close price return basis），而 Fama-MacBeth 优先采用官方复权日收益（Dretwd basis），"
            "两子实验在收益底座口径上存在差异，特此如实披露。"
        ),
    }


def calc_peak_to_trough_drawdown(prices: Sequence[float]) -> Tuple[float, float]:
    """计算持有期内的真实峰谷最大回撤（peak-to-trough max drawdown）与入场最大不利偏移（MAE from entry）。

    - True peak-to-trough max drawdown: min(p / cummax(p) - 1.0)
    - Maximum adverse excursion from entry: min(p) / entry_price - 1.0

    例如价格序列 [100.0, 120.0, 110.0]，入场价 100.0：
      - cummax 为 [100.0, 120.0, 120.0]
      - p / cummax - 1 为 [0.0, 0.0, -10/120] = [0.0, 0.0, -1/12]
      - 峰谷最大回撤必须为 -1/12 (-0.08333...)
      - 入场最大不利偏移 (MAE) 为 100/100 - 1 = 0.0
    """
    p = np.asarray(prices, dtype=float)
    if len(p) == 0 or not np.isfinite(p[0]) or p[0] <= 0:
        return float("nan"), float("nan")
    valid = np.isfinite(p) & (p > 0)
    if not np.all(valid):
        return float("nan"), float("nan")
    cummax = np.maximum.accumulate(p)
    drawdowns = p / cummax - 1.0
    max_dd = float(np.min(drawdowns))
    mae = float(np.min(p) / p[0] - 1.0)
    return max_dd, mae


# ===========================================================================
# 实验一：Trend Gate 事件研究（无前视 + 真实流动性约束）
# ===========================================================================
def build_trend_gate_events(
    df: pd.DataFrame,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    max_defer: int = DEFAULT_MAX_DEFER,
    mom_window: int = TREND_MOM_WINDOW,
    ma_window: int = TREND_MA_WINDOW,
) -> pd.DataFrame:
    """逐日推进构造 Trend Gate 事件，并施加 A 股真实成交约束。

    时点约定（关键，消除前视）：
      - 信号在 t 日收盘后产生，只用截至 t 日的数据（mom 用 t-20..t；MA 用 t-60..t-1）。
      - 因为信号在收盘后才可知，t 日收盘价不可成交：**t+1 日收盘进场**。
      - 退出目标为进场后第 H 个交易日；若该日跌停或停牌（不能卖出），顺延至下一个
        可成交日，最多顺延 max_defer 日；仍不可成交则标记 exit_blocked。
      - 进场日若涨停（买不进）或停牌，该事件标记为不可交易并剔除出可交易样本。

    对每个 horizon 输出两组收益：
      ret_{H}d          : 受约束口径（进场受约束 + 退出顺延），不可交易时为 NaN
      ret_{H}d_free     : 无约束口径（仅要求交易日存在，不施加涨跌停/停牌约束），
                          用于与 v1 及全样本对照，并保留全部样本量
      maxdd_{H}d / maxdd_{H}d_free : 对应持有期内的最大回撤
      defer_{H}d        : 退出日实际顺延的交易日数
    """
    horizons = tuple(int(h) for h in horizons)
    max_h = max(horizons)
    records: List[Dict[str, object]] = []

    for code, group in df.groupby("stock_code", sort=False):
        closes = group["close"].to_numpy(dtype=float)
        dates = group["trade_date"].to_numpy()
        up = group["limit_up"].to_numpy(dtype=bool)
        down = group["limit_down"].to_numpy(dtype=bool)
        unk = group["limit_unknown"].to_numpy(dtype=bool)
        known = group["limit_known"].to_numpy(dtype=bool)
        susp = group["suspended"].to_numpy(dtype=bool)
        n = len(closes)

        # 需要 t+1 进场、最长 t+1+max_h+max_defer 退出
        last_t = n - 2 - max_h - max_defer
        if last_t < ma_window:
            continue

        for t in range(ma_window, last_t + 1):
            curr = closes[t]
            base = closes[t - mom_window]
            ma = float(np.mean(closes[t - ma_window:t]))
            if not np.isfinite(curr) or not np.isfinite(base) or base <= 0 or not np.isfinite(ma):
                continue
            mom = curr / base - 1.0
            is_downtrend = bool(mom <= 0.0 and curr < ma)
            is_uptrend = bool(mom > 0.0 and curr > ma)

            e = t + 1
            entry_ok = bool(known[e] and not up[e] and not unk[e] and not susp[e])
            entry_block_limit_up = bool(up[e])
            entry_block_suspension = bool(susp[e])
            entry_limit_unobserved = bool(not known[e] or unk[e])

            rec: Dict[str, object] = {
                "stock_code": code,
                "trade_date": dates[t],
                "entry_date": dates[e],
                "mom_20d": mom,
                "is_downtrend": is_downtrend,
                "is_uptrend": is_uptrend,
                "entry_tradable": entry_ok,
                "entry_block_limit_up": entry_block_limit_up,
                "entry_block_suspension": entry_block_suspension,
                "entry_limit_unobserved": entry_limit_unobserved,
            }

            entry_close = closes[e]
            for h in horizons:
                target = t + 1 + h
                # 无约束口径：直接取目标交易日
                rec[f"ret_{h}d_free"] = (
                    float(closes[target] / entry_close - 1.0) if entry_close > 0 else float("nan")
                )
                dd_free, mae_free = calc_peak_to_trough_drawdown(closes[e:target + 1])
                rec[f"maxdd_{h}d_free"] = dd_free
                rec[f"mae_{h}d_free"] = mae_free

                # 受约束口径：退出日必须可成交（非跌停、非停牌、涨跌停状态可观测）
                exit_idx = None
                for k in range(target, min(target + max_defer, n - 1) + 1):
                    if known[k] and not unk[k] and not down[k] and not susp[k]:
                        exit_idx = k
                        break
                rec[f"exit_blocked_{h}d"] = exit_idx is None
                rec[f"defer_{h}d"] = int(0 if exit_idx is None else exit_idx - target)
                if entry_ok and exit_idx is not None:
                    rec[f"ret_{h}d"] = float(closes[exit_idx] / entry_close - 1.0)
                    dd_c, mae_c = calc_peak_to_trough_drawdown(closes[e:exit_idx + 1])
                    rec[f"maxdd_{h}d"] = dd_c
                    rec[f"mae_{h}d"] = mae_c
                else:
                    rec[f"ret_{h}d"] = float("nan")
                    rec[f"maxdd_{h}d"] = float("nan")
                    rec[f"mae_{h}d"] = float("nan")

            records.append(rec)

    return pd.DataFrame.from_records(records)


def summarize_events(
    events: pd.DataFrame,
    mask: np.ndarray,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    mode: str = "constrained",
) -> Dict[str, object]:
    """汇总一组事件的收益/胜率/最大回撤，并给出日度截面均值序列的 NW HAC t 值。

    重叠窗口（同一标的连续触发日）与截面相关性会让朴素 t 值失真，因此显著性统一
    基于「每日截面均值」构成的时间序列再做 Newey-West HAC 校正。

    mode="constrained"：读取受流动性约束的收益列（ret_{h}d），并报告进出场拦截诊断。
    mode="free"       ：读取无约束收益列（ret_{h}d_free），覆盖全部 299 支标的，
                        用于与 v1 及全样本对照（不报告拦截诊断，因其不适用）。
    """
    if mode not in ("constrained", "free"):
        raise ValueError(f"未知汇总口径: {mode}")
    sub = events.loc[mask]
    out: Dict[str, object] = {"n_events": int(len(sub)), "mode": mode}
    if len(sub) == 0:
        return out

    out["n_stocks"] = int(sub["stock_code"].nunique())
    out["hhi_stock_share_max"] = float(sub["stock_code"].value_counts(normalize=True).max())
    if mode == "constrained":
        out["entry_blocked_limit_up_share"] = float(sub["entry_block_limit_up"].mean())
        out["entry_blocked_suspension_share"] = float(sub["entry_block_suspension"].mean())
        out["entry_limit_unobserved_share"] = float(sub["entry_limit_unobserved"].mean())

    for h in horizons:
        col = f"ret_{h}d_free" if mode == "free" else f"ret_{h}d"
        dd_col = f"maxdd_{h}d_free" if mode == "free" else f"maxdd_{h}d"
        vals = pd.to_numeric(sub[col], errors="coerce")
        valid = vals.notna()

        mae_col = f"mae_{h}d_free" if mode == "free" else f"mae_{h}d"
        block: Dict[str, object] = {
            "n_valid": int(valid.sum()),
            "coverage": float(valid.mean()),
            "mean_ret": float(vals[valid].mean()) if valid.any() else float("nan"),
            "median_ret": float(vals[valid].median()) if valid.any() else float("nan"),
            "win_rate": float((vals[valid] > 0).mean()) if valid.any() else float("nan"),
            "std_ret": float(vals[valid].std(ddof=1)) if valid.sum() > 1 else float("nan"),
            "mean_maxdd": float(pd.to_numeric(sub[dd_col], errors="coerce").mean()),
            "mean_mae": float(pd.to_numeric(sub[mae_col], errors="coerce").mean()),
        }
        if mode == "constrained":
            block["mean_defer_days"] = float(pd.to_numeric(sub[f"defer_{h}d"], errors="coerce").mean())
            block["share_any_defer"] = float(
                (pd.to_numeric(sub[f"defer_{h}d"], errors="coerce") > 0).mean()
            )
            block["exit_blocked_share"] = float(pd.to_numeric(sub[f"exit_blocked_{h}d"], errors="coerce").mean())
            block["n_exit_censored"] = int((pd.to_numeric(sub[f"exit_blocked_{h}d"], errors="coerce") == 1).sum())
            block["n_exit_deferred"] = int((pd.to_numeric(sub[f"defer_{h}d"], errors="coerce") > 0).sum())
            block["mean_ret_full_pool_free"] = float(
                pd.to_numeric(sub[f"ret_{h}d_free"], errors="coerce").mean()
            )

        # 日度截面均值 → NW HAC t
        if valid.any():
            daily = (
                pd.DataFrame({"date": sub.loc[valid, "trade_date"], "v": vals[valid]})
                .groupby("date")["v"]
                .mean()
                .sort_index()
            )
            q = calc_newey_west_lags(len(daily))
            mean_d, se_d, t_d = newey_west_t_stat(daily.to_numpy(), q)
            block.update({
                "n_days": int(len(daily)),
                "nw_lags": int(q),
                "daily_mean": mean_d,
                "daily_nw_se": se_d,
                "daily_nw_t": t_d,
                "daily_nw_p_two_sided": two_sided_normal_p(t_d),
            })
        out[f"h{h}"] = block

    return out


def run_placebo(
    events: pd.DataFrame,
    pool_mask: np.ndarray,
    target_mask: np.ndarray,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    n_runs: int = 1000,
    seed: int = 20261011,
    mode: str = "constrained",
) -> Dict[str, object]:
    """**事件级**随机抽样安慰剂（次级口径）。

    - 抽样池 = pool_mask（调用方负责排除触发样本），每次抽样量 = 目标组在该 horizon 的
      有效样本数（逐个 horizon 分别匹配，不再取各 horizon 最大值）。
    - 每个 horizon 独立按其有效样本构成抽样池（避免 NaN 稀释）。
    - 落盘 1000 次抽样的完整分布（均值、最大回撤），并据此计算经验 p 值。

    注意：事件级抽样把同一交易日的横截面相关性当作独立信息，会**低估**标准误。
    主口径请使用 `run_date_placebo`（日期级重抽样）。
    """
    horizons = tuple(int(h) for h in horizons)
    if mode not in ("constrained", "free"):
        raise ValueError(f"未知安慰剂口径: {mode}")
    rng = np.random.RandomState(seed)
    result: Dict[str, object] = {
        "mode": mode,
        "design": "event_level",
        "n_runs": n_runs,
        "seed": int(seed),
    }

    for h in horizons:
        suffix = "d_free" if mode == "free" else "d"
        ret = pd.to_numeric(events[f"ret_{h}{suffix}"], errors="coerce").to_numpy()
        dd = pd.to_numeric(events[f"maxdd_{h}{suffix}"], errors="coerce").to_numpy()
        pool_idx = np.flatnonzero(pool_mask & np.isfinite(ret))
        target_idx = np.flatnonzero(target_mask & np.isfinite(ret))
        n_draw = int(len(target_idx))
        if len(pool_idx) == 0 or n_draw <= 0:
            result[f"h{h}"] = {"error": "empty_pool"}
            continue
        draw = int(min(n_draw, len(pool_idx)))
        means = np.empty(n_runs, dtype=float)
        dds = np.empty(n_runs, dtype=float)
        for i in range(n_runs):
            idx = rng.choice(pool_idx, size=draw, replace=False)
            means[i] = float(np.mean(ret[idx]))
            dds[i] = float(np.mean(dd[idx]))
        result[f"h{h}"] = {
            "design": "event_level",
            "pool_size": int(len(pool_idx)),
            "target_size": n_draw,
            "draw_per_run": draw,
            "dist_ret_means": means.tolist(),
            "dist_maxdd_means": dds.tolist(),
            "mean": float(np.mean(means)),
            "std": float(np.std(means, ddof=1)),
            "ci_95": [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))],
            "maxdd_mean": float(np.mean(dds)),
            "maxdd_ci_95": [float(np.percentile(dds, 2.5)), float(np.percentile(dds, 97.5))],
        }
    return result


def run_date_placebo(
    events: pd.DataFrame,
    pool_mask: np.ndarray,
    target_mask: np.ndarray,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    n_runs: int = 1000,
    seed: int = 20261011,
    mode: str = "constrained",
) -> Dict[str, object]:
    """**随机日期**安慰剂（主口径，对应方案 §P4.1「随机日期安慰剂」）。

    设计：每次从抽样池覆盖的交易日中以**有放回**方式抽取与目标组相同数量的交易日，
    取出这些日期上抽样池内的全部事件，计算均值。这样同一天内几百只股票的横截面共同
    波动被完整保留，不会像事件级抽样那样把「同一天同涨同跌」误当作独立信息，
    因此标准误不会被低估。

    为什么必须有放回：触发事件几乎覆盖了全部交易日期（557 天中约 557 天），
    若按不放回抽同样多的日期，等价于每次取整个抽样池，分布会退化为一个点。
    有放回抽样得到的是日度均值的 bootstrap 分布，其标准差近似 std(日度均值)/sqrt(天数)。
    """
    horizons = tuple(int(h) for h in horizons)
    if mode not in ("constrained", "free"):
        raise ValueError(f"未知安慰剂口径: {mode}")
    rng = np.random.RandomState(seed)
    dates_all = events["trade_date"].to_numpy()
    result: Dict[str, object] = {
        "mode": mode,
        "design": "date_level",
        "n_runs": n_runs,
        "seed": int(seed),
        "note": "每次有放回抽取与目标组相同数量的交易日，取该日期上抽样池内的全部事件",
    }

    for h in horizons:
        suffix = "d_free" if mode == "free" else "d"
        ret = pd.to_numeric(events[f"ret_{h}{suffix}"], errors="coerce").to_numpy()
        dd = pd.to_numeric(events[f"maxdd_{h}{suffix}"], errors="coerce").to_numpy()
        valid = np.isfinite(ret)
        in_pool = pool_mask & valid
        in_target = target_mask & valid

        n_target_dates = int(pd.unique(dates_all[in_target]).size)
        target_size = int(in_target.sum())
        if n_target_dates == 0 or not in_pool.any():
            result[f"h{h}"] = {"error": "empty_pool"}
            continue

        agg = (
            pd.DataFrame({"date": dates_all[in_pool], "v": ret[in_pool], "dd": dd[in_pool]})
            .groupby("date")
            .agg(v_sum=("v", "sum"), dd_sum=("dd", "sum"), n=("v", "size"))
            .sort_index()
        )
        v_sum = agg["v_sum"].to_numpy(dtype=float)
        dd_sum = agg["dd_sum"].to_numpy(dtype=float)
        cnt = agg["n"].to_numpy(dtype=float)
        date_means = v_sum / np.where(cnt > 0, cnt, 1.0)
        date_dds = dd_sum / np.where(cnt > 0, cnt, 1.0)
        m = len(v_sum)
        draw_dates = int(n_target_dates)

        means = np.empty(n_runs, dtype=float)
        dds = np.empty(n_runs, dtype=float)
        date_equal_means = np.empty(n_runs, dtype=float)
        date_equal_dds = np.empty(n_runs, dtype=float)
        sizes = np.empty(n_runs, dtype=int)
        for i in range(n_runs):
            picked = rng.randint(0, m, size=draw_dates)
            total_n = float(cnt[picked].sum())
            means[i] = float(v_sum[picked].sum() / total_n)
            dds[i] = float(dd_sum[picked].sum() / total_n)
            date_equal_means[i] = float(np.mean(date_means[picked]))
            date_equal_dds[i] = float(np.mean(date_dds[picked]))
            sizes[i] = int(total_n)
        result[f"h{h}"] = {
            "design": "date_level",
            "pool_size": int(in_pool.sum()),
            "pool_dates": int(m),
            "target_size": target_size,
            "target_dates": n_target_dates,
            "dates_per_run": draw_dates,
            "resample_with_replacement": True,
            "events_per_run_mean": float(np.mean(sizes)),
            "events_per_run_min": int(np.min(sizes)),
            "events_per_run_max": int(np.max(sizes)),
            "dist_ret_means": means.tolist(),
            "dist_maxdd_means": dds.tolist(),
            "dist_date_equal_ret_means": date_equal_means.tolist(),
            "dist_date_equal_maxdd_means": date_equal_dds.tolist(),
            "mean": float(np.mean(means)),
            "std": float(np.std(means, ddof=1)),
            "ci_95": [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))],
            "date_equal_mean": float(np.mean(date_equal_means)),
            "date_equal_std": float(np.std(date_equal_means, ddof=1)),
            "date_equal_ci_95": [float(np.percentile(date_equal_means, 2.5)), float(np.percentile(date_equal_means, 97.5))],
            "maxdd_mean": float(np.mean(dds)),
            "maxdd_ci_95": [float(np.percentile(dds, 2.5)), float(np.percentile(dds, 97.5))],
        }
    return result


def run_date_matched_placebo(
    events: pd.DataFrame,
    pool_mask: np.ndarray,
    target_mask: np.ndarray,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    n_runs: int = 1000,
    seed: int = 20261011,
    mode: str = "constrained",
) -> Dict[str, object]:
    """**同日匹配**安慰剂（把「日期加权」与「样本量」同时固定住的对照）。

    随机日期安慰剂按日期均匀抽样，但触发事件在各交易日的分布并不均匀；若触发日集中在
    少数日期，触发组的均值方差会与安慰剂分布不匹配，可能夸大显著性。本设计对每个交易日
    分别从该日的抽样池中不放回抽取与该日触发数相同的样本，从而：
      - 完全复刻触发组的日期分布与逐日样本量；
      - 抽样池仍严格排除触发样本；
      - 交易日内横截面相关性被完整保留。
    """
    horizons = tuple(int(h) for h in horizons)
    if mode not in ("constrained", "free"):
        raise ValueError(f"未知安慰剂口径: {mode}")
    rng = np.random.RandomState(seed)
    dates_all = events["trade_date"].to_numpy()
    result: Dict[str, object] = {
        "mode": mode,
        "design": "date_matched",
        "n_runs": n_runs,
        "seed": int(seed),
        "note": "逐日从抽样池中抽取与该日目标组样本数相同的事件",
    }

    for h in horizons:
        suffix = "d_free" if mode == "free" else "d"
        ret = pd.to_numeric(events[f"ret_{h}{suffix}"], errors="coerce").to_numpy()
        dd = pd.to_numeric(events[f"maxdd_{h}{suffix}"], errors="coerce").to_numpy()
        valid = np.isfinite(ret)
        in_pool = pool_mask & valid
        in_target = target_mask & valid
        if not in_target.any() or not in_pool.any():
            result[f"h{h}"] = {
                "error": "empty_pool",
                "status": "invalid_insufficient_control",
                "match_status": "invalid_insufficient_control",
                "is_valid_inference": False,
            }
            continue

        target_counts = (
            pd.Series(dates_all[in_target]).value_counts().sort_index()
        )
        pool_frame = pd.DataFrame({
            "date": dates_all[in_pool],
            "idx": np.flatnonzero(in_pool),
        })
        pool_by_date = {d: g["idx"].to_numpy() for d, g in pool_frame.groupby("date")}
        capped = 0
        tasks = []
        for d, n_d in target_counts.items():
            arr = pool_by_date.get(d)
            if arr is None or len(arr) == 0:
                capped += 1
                continue
            k = int(min(int(n_d), len(arr)))
            if k < int(n_d):
                capped += 1
            tasks.append((d, arr, int(n_d), k))

        # 被检验统计量必须与基线同权重：按该设计自身的（被截断的）日权重重算目标组均值
        tgt_mean_by_date = (
            pd.DataFrame({"date": dates_all[in_target], "v": ret[in_target]})
            .groupby("date")["v"].mean()
        )
        w_total = float(sum(k for _d, _arr, _n_d, k in tasks))
        target_mean_matched = (
            float(sum(k * float(tgt_mean_by_date.loc[d]) for d, _arr, _n_d, k in tasks) / w_total)
            if w_total > 0
            else float("nan")
        )

        means = np.empty(n_runs, dtype=float)
        dds = np.empty(n_runs, dtype=float)
        sizes = np.empty(n_runs, dtype=int)
        for i in range(n_runs):
            total = 0
            s = 0.0
            sd = 0.0
            for _d, arr, _n_d, k in tasks:
                idx = rng.choice(arr, size=k, replace=False)
                s += float(ret[idx].sum())
                sd += float(dd[idx].sum())
                total += k
            means[i] = s / total
            dds[i] = sd / total
            sizes[i] = total
        is_insufficient = bool(capped > 0)
        status_code = "invalid_insufficient_control" if is_insufficient else "valid_matched"
        result[f"h{h}"] = {
            "design": "date_matched",
            "status": status_code,
            "match_status": status_code,
            "is_valid_inference": not is_insufficient,
            "pool_size": int(in_pool.sum()),
            "target_size": int(in_target.sum()),
            "dates_matched": int(len(tasks)),
            "dates_capped_or_missing": int(capped),
            "events_target_requested": int(in_target.sum()),
            "events_matched": int(w_total),
            "control_insufficient": is_insufficient,
            "sample_equality_claimed": False if is_insufficient else True,
            "events_per_run_mean": float(np.mean(sizes)),
            "target_mean_full_sample": float(np.mean(ret[in_target])),
            "target_mean_under_matched_weights": target_mean_matched,
            "dist_ret_means": means.tolist(),
            "dist_maxdd_means": dds.tolist(),
            "mean": float(np.mean(means)),
            "std": float(np.std(means, ddof=1)),
            "ci_95": [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))],
            "maxdd_mean": float(np.mean(dds)),
            "maxdd_ci_95": [float(np.percentile(dds, 2.5)), float(np.percentile(dds, 97.5))],
        }
    return result


def safe_corrcoef(x: np.ndarray, y: np.ndarray) -> float:
    """计算两序列的 Pearson 相关系数，遇到常数序列或方差极小序列时返回 nan，避免 RuntimeWarning。"""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(x) < 3 or len(y) < 3 or len(x) != len(y):
        return float("nan")
    valid = np.isfinite(x) & np.isfinite(y)
    if valid.sum() < 3:
        return float("nan")
    xv = x[valid]
    yv = y[valid]
    sx = float(np.std(xv))
    sy = float(np.std(yv))
    if sx < 1e-12 or sy < 1e-12:
        return float("nan")
    val = float(np.corrcoef(xv, yv)[0, 1])
    return val if np.isfinite(val) else float("nan")


def block_bootstrap_ratio_diff(
    ts: np.ndarray,
    tn: np.ndarray,
    ps: np.ndarray,
    pn: np.ndarray,
    block_len: int,
    n_boot: int = 1000,
    seed: int = 42,
) -> np.ndarray:
    """移动区块 Bootstrap（MBB）对配对日度汇总四元组 (ts, tn, ps, pn) 重抽样比率差。
    直接计算每一轮重抽样下的全样本比率之差：
        theta^* = sum(ts^*) / sum(tn^*) - sum(ps^*) / sum(pn^*)
    严格保持时序依赖、横截面配对以及两组各日样本量权重的联合分布。
    """
    ts = np.asarray(ts, dtype=float)
    tn = np.asarray(tn, dtype=float)
    ps = np.asarray(ps, dtype=float)
    pn = np.asarray(pn, dtype=float)
    T = len(ts)
    if T == 0:
        return np.zeros(n_boot)
    block_len = max(1, min(int(block_len), T))
    n_blocks = int(np.ceil(T / block_len))
    max_start = T - block_len
    rng = np.random.RandomState(seed)
    out = np.empty(n_boot, dtype=float)
    for b in range(n_boot):
        starts = rng.randint(0, max_start + 1, size=n_blocks)
        idx = (starts[:, None] + np.arange(block_len)[None, :]).ravel()[:T]
        sum_ts = float(ts[idx].sum())
        sum_tn = float(tn[idx].sum())
        sum_ps = float(ps[idx].sum())
        sum_pn = float(pn[idx].sum())
        if sum_tn > 0 and sum_pn > 0:
            out[b] = sum_ts / sum_tn - sum_ps / sum_pn
        else:
            out[b] = np.nan
    return out


def date_cluster_bootstrap_diff(
    events: pd.DataFrame,
    target_mask: np.ndarray,
    pool_mask: np.ndarray,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    n_runs: int = 1000,
    seed: int = 20261011,
    mode: str = "constrained",
) -> Dict[str, object]:
    """**日期级 cluster bootstrap 的组间配对差**——本实验的正式显著性检验。

    为什么必须有它：`run_date_placebo` / `run_date_matched_placebo` 给出的是**抽样池均值
    的零分布**，只含池子一侧的方差；用它去比较目标组均值，会漏掉目标组自身的抽样方差
    以及两侧的协方差（同一天两组同涨同跌，协方差为正），从而系统性低估标准误。

    本函数把统计量直接定义为「目标组均值 − 池均值」，并在**日期维度**上有放回重抽样
    （同一天的两组事件一起进出），因此同时包含两侧方差与协方差：
      - event_weighted：按事件汇总（等于两组各自的全样本均值之差，即策略实际体验到的口径）
      - date_equal   ：先算每日差值再等权平均（回答「典型一天里两组差多少」）
    """
    horizons = tuple(int(h) for h in horizons)
    if mode not in ("constrained", "free"):
        raise ValueError(f"未知对照口径: {mode}")
    rng = np.random.RandomState(seed)
    dates_all = events["trade_date"].to_numpy()
    out: Dict[str, object] = {"mode": mode, "design": "date_cluster_bootstrap_diff", "n_runs": n_runs, "seed": seed}

    for h in horizons:
        suffix = "d_free" if mode == "free" else "d"
        vals = pd.to_numeric(events[f"ret_{h}{suffix}"], errors="coerce").to_numpy()
        valid = np.isfinite(vals)
        tgt = target_mask & valid
        pool = pool_mask & valid
        if not tgt.any() or not pool.any():
            out[f"h{h}"] = {"error": "empty_side"}
            continue

        g_t = pd.DataFrame({"date": dates_all[tgt], "v": vals[tgt]}).groupby("date")["v"].agg(["sum", "size"])
        g_p = pd.DataFrame({"date": dates_all[pool], "v": vals[pool]}).groupby("date")["v"].agg(["sum", "size"])
        joined = g_t.join(g_p, how="inner", lsuffix="_t", rsuffix="_p").sort_index()
        ts = joined["sum_t"].to_numpy(dtype=float)
        tn = joined["size_t"].to_numpy(dtype=float)
        ps = joined["sum_p"].to_numpy(dtype=float)
        pn = joined["size_p"].to_numpy(dtype=float)
        m = len(ts)
        if m < 2:
            out[f"h{h}"] = {"error": "insufficient_days"}
            continue

        mu_x = float(ts.sum() / tn.sum())
        mu_y = float(ps.sum() / pn.sum())
        obs_event = float(mu_x - mu_y)
        obs_date = float(np.mean(ts / tn - ps / pn))

        boot_event = np.empty(n_runs, dtype=float)
        boot_date = np.empty(n_runs, dtype=float)
        for i in range(n_runs):
            idx = rng.randint(0, m, size=m)
            boot_event[i] = float(ts[idx].sum() / tn[idx].sum() - ps[idx].sum() / pn[idx].sum())
            boot_date[i] = float(np.mean((ts / tn - ps / pn)[idx]))

        def _block(
            obs: float,
            boot: np.ndarray,
            series: np.ndarray,
            paired_tuples: tuple | None = None,
        ) -> Dict[str, object]:
            """给出 i.i.d. 日 bootstrap、Newey-West HAC（含自动、H-1、扩展阶数敏感性）及区块 Bootstrap。"""
            se_iid = float(np.std(boot, ddof=1))
            t_iid = obs / se_iid if se_iid > 0 else float("inf")

            q_auto = calc_newey_west_lags(len(series))
            q_h1 = max(1, h - 1)
            q_ext = max(int(q_auto + 5), int(h + 4), 20)

            _, se_hac, t_hac = newey_west_t_stat(series, q_auto)
            _, se_h1, t_h1 = newey_west_t_stat(series, q_h1)
            _, se_ext, t_ext = newey_west_t_stat(series, q_ext)

            out_blk: Dict[str, object] = {
                "observed_diff": obs,
                "boot_iid_se": se_iid,
                "boot_iid_t": t_iid,
                "boot_iid_p_two_sided": two_sided_normal_p(t_iid),
                "hac_lags": int(q_auto),
                "hac_se": se_hac,
                "hac_t": t_hac,
                "hac_p_two_sided": two_sided_normal_p(t_hac),
                "hac_h_minus_1_lags": int(q_h1),
                "hac_h_minus_1_se": se_h1,
                "hac_h_minus_1_t": t_h1,
                "hac_h_minus_1_p_two_sided": two_sided_normal_p(t_h1),
                "hac_ext_lags": int(q_ext),
                "hac_ext_se": se_ext,
                "hac_ext_t": t_ext,
                "hac_ext_p_two_sided": two_sided_normal_p(t_ext),
                "boot_ci_95_iid": [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))],
            }
            # 区块 Bootstrap：block2, block5, block_h, block20
            block_lengths = [("block2", 2), ("block5", 5), (f"block_h{h}", h), ("block20", 20)]
            for label, blen in block_lengths:
                if paired_tuples is not None:
                    ts_arr, tn_arr, ps_arr, pn_arr = paired_tuples
                    blk = block_bootstrap_ratio_diff(ts_arr, tn_arr, ps_arr, pn_arr, blen, n_boot=n_runs, seed=seed)
                else:
                    blk = moving_block_bootstrap_means(series, blen, n_boot=n_runs, seed=seed)
                se_blk = float(np.nanstd(blk, ddof=1))
                t_blk = obs / se_blk if se_blk > 0 else float("inf")
                out_blk[f"{label}_len"] = int(min(blen, len(series)))
                out_blk[f"{label}_se"] = se_blk
                out_blk[f"{label}_t"] = t_blk
                out_blk[f"{label}_p_two_sided"] = two_sided_normal_p(t_blk)
            return out_blk

        def _pct_rank(dist: np.ndarray) -> float:
            """观测值在分布自身上尾/下尾的经验位置（描述性，不作推断）。"""
            return float(min(np.mean(dist <= 0.0), np.mean(dist >= 0.0)))

        # 事件加权：中心化比率估计量影响函数分数
        # psi_t = (S_t - mu_x * N_t) / sum(N) - (R_t - mu_y * M_t) / sum(M)
        # z_t = T * psi_t + obs_event
        # 其样本均值严格等于 obs_event，且对 z_t 做 HAC 得到的方差与比率估计量 delta 方法在时序依赖下的渐近方差严格吻合。
        psi = (ts - mu_x * tn) / float(tn.sum()) - (ps - mu_y * pn) / float(pn.sum())
        z = m * psi + obs_event
        # 等权日：d_t = 当日目标均值 − 当日池均值，mean(d) 已经等于等权日差
        d = ts / tn - ps / pn

        corr_means = safe_corrcoef(ts / tn, ps / pn)
        autocorr_z = safe_corrcoef(z[:-1], z[1:])

        block: Dict[str, object] = {
            "design": "date_cluster_bootstrap_diff",
            "n_days_target": int(len(g_t)),
            "n_days_pool": int(len(g_p)),
            "n_days_joined": int(m),
            "n_days_target_only": int(len(g_t) - m),
            "n_days_pool_only": int(len(g_p) - m),
            "events_target": int(tn.sum()),
            "events_pool": int(pn.sum()),
            "corr_of_date_means": corr_means,
            "autocorr_of_event_weighted_contrib_lag1": autocorr_z,
            "note": "推断以 hac_*（序列相关稳健）为准；boot_iid_* 按日独立重抽样，会低估标准误，仅作对照。",
            "event_weighted": _block(obs_event, boot_event, z, paired_tuples=(ts, tn, ps, pn)),
            "date_equal": _block(obs_date, boot_date, d, paired_tuples=None),
        }
        block["event_weighted"]["dist_tail_rank"] = _pct_rank(boot_event)
        block["date_equal"]["dist_tail_rank"] = _pct_rank(boot_date)
        out[f"h{h}"] = block
    return out


def daily_paired_test(
    events: pd.DataFrame,
    target_mask: np.ndarray,
    pool_mask: np.ndarray,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    mode: str = "constrained",
) -> Dict[str, object]:
    """逐日配对检验：同一天上「目标组截面均值 − 抽样池截面均值」构成时间序列，再做 NW HAC。

    这是本实验统计上最干净的口径：配对消掉了市场共同的时序波动（也顺带吸收了大盘
    因子与同期宏观冲击），只保留「同一天同一池子里，被门禁拦下的标的与没被拦下的标的
    差多少」。它比安慰剂抽样更有效力，但**不替代**方案要求的随机日期安慰剂。
    """
    horizons = tuple(int(h) for h in horizons)
    if mode not in ("constrained", "free"):
        raise ValueError(f"未知对照口径: {mode}")
    out: Dict[str, object] = {"mode": mode, "design": "daily_paired"}
    dates_all = events["trade_date"].to_numpy()
    for h in horizons:
        suffix = "d_free" if mode == "free" else "d"
        vals = pd.to_numeric(events[f"ret_{h}{suffix}"], errors="coerce").to_numpy()
        valid = np.isfinite(vals)
        tgt = target_mask & valid
        pool = pool_mask & valid
        if not tgt.any() or not pool.any():
            out[f"h{h}"] = {"error": "empty_side"}
            continue
        s_t = pd.DataFrame({"date": dates_all[tgt], "v": vals[tgt]}).groupby("date")["v"].agg(["mean", "size"])
        s_p = pd.DataFrame({"date": dates_all[pool], "v": vals[pool]}).groupby("date")["v"].agg(["mean", "size"])
        joined = s_t.join(s_p, how="inner", lsuffix="_t", rsuffix="_p").sort_index()
        diff = (joined["mean_t"] - joined["mean_p"]).to_numpy(dtype=float)
        weights = joined["size_t"].to_numpy(dtype=float)
        q = calc_newey_west_lags(len(diff))
        mean_d, se, t_stat = newey_west_t_stat(diff, q)
        q_h1 = max(1, h - 1)
        _, se_h1, t_h1 = newey_west_t_stat(diff, q_h1)
        # 等权日口径与事件加权口径的差异，用于定位「优势集中在少数高触发日」这类结构性效应
        weighted_mean_d = float(np.average(diff, weights=weights)) if weights.sum() > 0 else float("nan")
        median_size = float(np.median(weights))
        heavy = weights >= np.percentile(weights, 90)
        if not heavy.any() or heavy.all():
            heavy = weights >= median_size
        heavy_diff = (
            float(np.average(diff[heavy], weights=weights[heavy])) if heavy.any() else float("nan")
        )
        light_diff = (
            float(np.average(diff[~heavy], weights=weights[~heavy])) if (~heavy).any() else float("nan")
        )
        out[f"h{h}"] = {
            "n_days": int(len(diff)),
            "mean_diff": mean_d,
            "weighted_mean_diff": weighted_mean_d,
            "nw_se": se,
            "nw_t": t_stat,
            "nw_p_two_sided": two_sided_normal_p(t_stat),
            "hac_lags": int(q),
            "nw_h_minus_1_lags": int(q_h1),
            "nw_h_minus_1_se": se_h1,
            "nw_h_minus_1_t": t_h1,
            "nw_h_minus_1_p_two_sided": two_sided_normal_p(t_h1),
            "share_days_target_lower": float(np.mean(diff < 0)),
            "target_mean_on_paired_days": float(joined["mean_t"].mean()),
            "pool_mean_on_paired_days": float(joined["mean_p"].mean()),
            "mean_events_target": float(joined["size_t"].mean()),
            "mean_events_pool": float(joined["size_p"].mean()),
            "diff_on_heavy_trigger_days": heavy_diff,
            "diff_on_light_trigger_days": light_diff,
            "heavy_trigger_day_share_of_events": float(weights[heavy].sum() / weights.sum()),
            "median_events_per_day": median_size,
        }
    return out


def empirical_p_value(dist: Sequence[float], observed: float, tail: str = "lower") -> float:
    """经验（蒙特卡洛）p 值，采用标准的 (count + 1) / (n + 1) 口径。

    tail="lower": P(安慰剂 <= 观测)  —— 检验「该组收益显著低于随机基线」
    tail="upper": P(安慰剂 >= 观测)  —— 检验「该组收益显著高于随机基线」
    tail="two"  : min(1, 2 * min(单侧))，上限 1.0

    采用 +1 校正（Phipson & Smyth 2010）：它同时给出有限抽样下的无偏下界，
    避免出现「p = 0」或「托底后乘 2 失效」的不一致结果。
    例：1000 次抽样中全部 placebo <= observed、且全部 placebo < observed 时，
    单侧上尾 p = 1/1001，双侧 = 2/1001 ≈ 0.002。
    """
    arr = np.asarray(dist, dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0 or not np.isfinite(observed):
        return float("nan")
    n = len(arr)
    lower = float((np.sum(arr <= observed) + 1.0) / (n + 1.0))
    upper = float((np.sum(arr >= observed) + 1.0) / (n + 1.0))
    if tail == "lower":
        return lower
    if tail == "upper":
        return upper
    return float(min(1.0, 2.0 * min(lower, upper)))


# ===========================================================================
# 实验二：Fama-MacBeth 截面回归（t+1 可交易收益）
# ===========================================================================
DEFAULT_FACTORS = ("mom_20d", "mom_60d", "vol_20d", "turnover_20d", "amihud", "price_pos")


def run_fama_macbeth(
    df: pd.DataFrame,
    factors: Sequence[str] = DEFAULT_FACTORS,
    dependent: str = "ret_next",
    min_stocks: int = 30,
    bootstrap_runs: int = 1000,
    bootstrap_seed: int = 42,
    drop_limit_up_at_t: bool = False,
    limit_up_definition: str = "reconstructed",
) -> Dict[str, object]:
    """Fama-MacBeth 两阶段回归（第一阶段逐期截面 OLS，第二阶段 HAC 时序检验）。

    `dependent` 默认 `ret_next`（t → t+1 的可交易收益）。**严禁**改用同期收益：
    面板中的 mom_20d / amihud / price_pos 都含当日信息，用同期收益回归会得到
    机械虚高的 t 值（v1 的 mom_20d t=14.09、price_pos t=33.92 即源于此）。

    `drop_limit_up_at_t=True` 时剔除 t 日涨停（无法在收盘价建仓）的观测：
      - limit_up_definition="reconstructed"（默认）：用重建后的涨停标志（含 close 收益
        推断方向、price_pos 兜底的样本）
      - limit_up_definition="literal"：只用字面口径 hit_limit == 1 且 ret > 0
    两种口径剔除的行数不同，显著性对定义可能敏感，故均需报告。
    """
    if limit_up_definition not in ("reconstructed", "literal"):
        raise ValueError(f"未知涨停口径: {limit_up_definition}")
    factors = [f for f in factors if f in df.columns]
    missing = [f for f in factors if f not in df.columns]
    if not factors:
        raise ValueError("没有任何可用因子列")
    work = df.dropna(subset=[dependent] + factors).copy()
    n_before = len(work)
    if drop_limit_up_at_t:
        if limit_up_definition == "literal" and "hit_limit" in work.columns and "ret" in work.columns:
            keep = ~(
                pd.to_numeric(work["hit_limit"], errors="coerce").fillna(0).eq(1)
                & pd.to_numeric(work["ret"], errors="coerce").gt(0)
            )
            work = work[keep]
        else:
            work = work[~work["limit_up"].fillna(False)]
    n_excluded = n_before - len(work)

    dates = sorted(work["trade_date"].unique())
    lambdas: Dict[str, List[float]] = {f: [] for f in factors}
    alphas: List[float] = []
    valid_dates: List[str] = []
    r2_list: List[float] = []
    n_obs_list: List[int] = []
    skipped = 0

    for d in dates:
        sub = work[work["trade_date"] == d]
        if len(sub) < min_stocks:
            skipped += 1
            continue
        y = sub[dependent].to_numpy(dtype=float)
        X = sub[list(factors)].to_numpy(dtype=float)
        sd = X.std(axis=0)
        sd[sd == 0] = 1.0
        Xs = (X - X.mean(axis=0)) / sd
        design = np.column_stack([np.ones(len(Xs)), Xs])
        coef, *_ = np.linalg.lstsq(design, y, rcond=None)
        resid = y - design @ coef
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r2 = 1.0 - float(np.sum(resid ** 2)) / ss_tot if ss_tot > 0 else float("nan")
        alphas.append(float(coef[0]))
        for i, f in enumerate(factors):
            lambdas[f].append(float(coef[i + 1]))
        valid_dates.append(str(d))
        r2_list.append(r2)
        n_obs_list.append(int(len(sub)))

    T = len(valid_dates)
    lags = calc_newey_west_lags(T)
    block_len = default_block_len(T)

    factors_out: Dict[str, object] = {}
    p_list: List[float] = []
    for f in factors:
        series = np.asarray(lambdas[f], dtype=float)
        mean_v, nw_se, nw_t = newey_west_t_stat(series, lags)
        _, classic_se, classic_t = classic_iid_t_stat(series)
        p_val = two_sided_normal_p(nw_t)
        ci_low, ci_high = block_bootstrap_ci(series, block_len=block_len, n_boot=bootstrap_runs, seed=bootstrap_seed)
        rf_daily = RISK_FREE_RATE_ANNUAL / ANNUALIZATION_DAYS
        # 计量说明：因因子在截面已完成 z-score 标准化且回归含截距项，各因子斜率 λ_t 对应零净投资、
        # 资金中性的多空因子组合收益，自身即为超额收益，无需也不应扣除无风险利率 Rf。
        # 扣除 Rf 仅平移截距项 α_t（对应全截面等权基准），对因子溢价斜率与 t 值无任何影响。
        # 字段 annualized_premium_excess_244d 维持与 annualized_premium_244d 一致以保障 schema 兼容。
        factors_out[f] = {
            "mean_risk_premium_daily": mean_v,
            "annualized_premium_244d": mean_v * ANNUALIZATION_DAYS,
            "annualized_premium_excess_244d": mean_v * ANNUALIZATION_DAYS,
            "std_daily": float(np.std(series, ddof=1)) if T > 1 else float("nan"),
            "classic_se": classic_se,
            "classic_t": classic_t,
            "newey_west_se": nw_se,
            "newey_west_t": nw_t,
            "p_value_two_sided": p_val,
            "block_bootstrap_ci_95": [ci_low, ci_high],
            "harvey_abs_t_ge_3": bool(np.isfinite(nw_t) and abs(nw_t) >= 3.0),
        }
        p_list.append(p_val)

    p_arr = np.asarray(p_list, dtype=float)
    q_arr = benjamini_hochberg_fdr(p_arr)
    b_arr = bonferroni_adjust(p_arr)
    for i, f in enumerate(factors):
        factors_out[f]["fdr_q_value"] = float(q_arr[i])
        factors_out[f]["bonferroni_p_value"] = float(b_arr[i])
        factors_out[f]["significant_5pct_raw"] = bool(p_arr[i] < 0.05)
        factors_out[f]["significant_5pct_fdr"] = bool(q_arr[i] < 0.05)
        factors_out[f]["significant_5pct_bonferroni"] = bool(b_arr[i] < 0.05)

    rolling = {}
    for f in factors:
        s = pd.Series(lambdas[f], dtype=float)
        if len(s) >= 60:
            rm = s.rolling(60).mean().dropna()
            rolling[f] = {
                "window": 60,
                "min": float(rm.min()),
                "max": float(rm.max()),
                "mean": float(rm.mean()),
                "last": float(rm.iloc[-1]),
            }

    alpha_arr = np.asarray(alphas, dtype=float)
    mean_alpha = float(np.mean(alpha_arr)) if len(alpha_arr) else float("nan")
    alpha_nw_mean, alpha_nw_se, alpha_nw_t = (
        newey_west_t_stat(alpha_arr, lags) if len(alpha_arr) else (float("nan"), float("nan"), float("nan"))
    )

    return {
        "dependent_variable": dependent,
        "factors": list(factors),
        "unused_factor_columns": missing,
        "n_periods": T,
        "n_dates_available": len(dates),
        "n_dates_skipped_insufficient_cross_section": int(skipped),
        "min_stocks_per_period": int(min_stocks),
        "cross_section_size": {
            "min": int(np.min(n_obs_list)) if n_obs_list else 0,
            "max": int(np.max(n_obs_list)) if n_obs_list else 0,
            "mean": float(np.mean(n_obs_list)) if n_obs_list else float("nan"),
        },
        "n_stocks": int(work["stock_code"].nunique()),
        "n_observations": int(len(work)),
        "mean_cross_section_r2": float(np.mean(r2_list)) if r2_list else float("nan"),
        "hac_lags": int(lags),
        "hac_kernel": "bartlett",
        "block_bootstrap": {"block_len": int(block_len), "n_boot": bootstrap_runs, "seed": bootstrap_seed},
        "n_tests": int(len(factors)),
        "risk_free_rate_annual": RISK_FREE_RATE_ANNUAL,
        "annualization_days": ANNUALIZATION_DAYS,
        "mean_alpha_daily": mean_alpha,
        "annualized_alpha_244d": mean_alpha * ANNUALIZATION_DAYS if np.isfinite(mean_alpha) else float("nan"),
        "annualized_alpha_excess_244d": (mean_alpha - rf_daily) * ANNUALIZATION_DAYS if np.isfinite(mean_alpha) else float("nan"),
        "alpha_newey_west_t": alpha_nw_t,
        "excluded_limit_up_at_t": bool(drop_limit_up_at_t),
        "limit_up_definition": limit_up_definition if drop_limit_up_at_t else None,
        "n_rows_excluded": int(n_excluded),
        "factors_stats": factors_out,
        "rolling_60_beta_summary": rolling,
        "per_period_dates": valid_dates,
        "per_period_lambdas": {f: lambdas[f] for f in factors},
        "per_period_alpha": alphas,
    }


def load_json(path: Path | str) -> dict:
    """读取 UTF-8 JSON。"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def dump_json(obj: object, path: Path | str) -> Path:
    """写出缩进 UTF-8 JSON。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False, default=_json_default)
    return path


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"不可序列化类型: {type(o)}")
