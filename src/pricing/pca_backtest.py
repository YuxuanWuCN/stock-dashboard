# -*- coding: utf-8 -*-
"""src/pricing/pca_backtest.py —— A 股 PCA 复合因子多空投资组合周度回测与绩效评价流水线

功能契约：
1. load_and_align_datasets: 安全加载 768 维语义因子大表与 CSMAR 交易面板，完成 6 位代码规范化与收益率安全对齐；
2. compute_alpha_composite_nale: 基于 768 维特征矩阵提取 PC1~PC5，调用 ASharePCAFactorPipeline
   完成 3xMAD 去极值、行业与流通市值 OLS 中性化与 Z-score 标准化，输出全池有效静态 Alpha 打分；
3. run_weekly_long_short_backtest: 执行周度（5 交易日）多空再平衡回测（全池 299 标的及 A/B/C 三大子板块），
   按照前 20% 等权做多、后 20% 等权做空，日度收益按 0.5 * Long - 0.5 * Short 结算，并追踪组合换手率；
4. compute_performance_metrics: 计算年化收益率、年化波动率、夏普比率、最大回撤、年化换手率与 Calmar 比率；
5. decompose_annual_alpha_beta: 针对 2024、2025、2026 分年度执行相对同宇宙等权基准的 OLS 计量回归分解；
6. generate_pnl_charts: 生成满足国赛金奖出版级要求（>=200 DPI，中文字体渲染，清晰图例）的 5 张净值走势图表；
7. run_pipeline: 端到端串联生成所有指定 CSV 报表与 PNG 图表产物。
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
import statsmodels.api as sm

from src.pricing.factor_neutralization import ASharePCAFactorPipeline


logger = logging.getLogger(__name__)

# 配置 Matplotlib 中文字体支持与负号显示
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "SimSun", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class BacktestResult:
    """周度多空组合回测结果容器。"""

    universe: str
    daily_returns: pd.Series
    cumulative_returns: pd.Series
    cumulative_log_returns: pd.Series
    long_leg_returns: pd.Series
    short_leg_returns: pd.Series
    turnover_series: pd.Series
    long_holdings: Mapping[str, Sequence[str]]
    short_holdings: Mapping[str, Sequence[str]]
    rebalance_dates: Sequence[str]


def load_and_align_datasets(
    data_dir: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    """加载 768 维因子大表与 CSMAR 交易面板，并执行收益率安全对齐与市值提取。

    Parameters
    ----------
    data_dir : Path, optional
        数据根目录（默认为 project_root / 'data' / 'task_split'）

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame, pd.Series]
        (factors_df, csmar_panel, latest_market_value)
    """
    base_dir = data_dir or (PROJECT_ROOT / "data" / "task_split")
    factors_path = base_dir / "factors_768d_all.csv"
    csmar_path = base_dir / "csmar_master" / "csmar_factor_panel_master.csv"

    if not factors_path.exists():
        raise FileNotFoundError(f"768D 因子文件不存在: {factors_path}")
    if not csmar_path.exists():
        raise FileNotFoundError(f"CSMAR 面板文件不存在: {csmar_path}")

    factors_df = pd.read_csv(factors_path, dtype={"code": str})
    factors_df["code"] = factors_df["code"].astype(str).str.zfill(6)
    factors_df = factors_df.set_index("code")

    csmar_df = pd.read_csv(
        csmar_path,
        dtype={"stock_code": str, "trade_date": str},
    )
    csmar_df["stock_code"] = csmar_df["stock_code"].astype(str).str.zfill(6)
    csmar_df = csmar_df.sort_values(["trade_date", "stock_code"]).reset_index(drop=True)

    # 收益率安全修复：B 组与 C 组历史缺失 ret，采用 close.pct_change() 补齐，首日缺失置 0.0
    calc_ret = csmar_df.groupby("stock_code")["close"].pct_change()
    if "ret" in csmar_df.columns:
        csmar_df["eff_ret"] = csmar_df["ret"].fillna(calc_ret).fillna(0.0)
    else:
        csmar_df["eff_ret"] = calc_ret.fillna(0.0)

    # 提取每只股票最新有效交易日的流通市值
    latest_mv = (
        csmar_df.sort_values("trade_date")
        .groupby("stock_code")["market_value"]
        .last()
    )

    return factors_df, csmar_df, latest_mv


def compute_alpha_composite_nale(
    factors_df: pd.DataFrame,
    csmar_panel: pd.DataFrame,
    n_components: int = 5,
    random_state: int = 42,
) -> tuple[pd.Series, pd.DataFrame]:
    """基于 768 维嵌入特征与最新市值计算标准化综合因子 alpha_composite_nale。

    Parameters
    ----------
    factors_df : pd.DataFrame
        768 维因子特征大表，index 为 6 位证券代码
    csmar_panel : pd.DataFrame
        CSMAR 交易面板，包含 stock_code, trade_date, eff_ret 等列
    n_components : int, default 5
        PCA 降维目标成分数
    random_state : int, default 42
        PCA 随机种子

    Returns
    -------
    tuple[pd.Series, pd.DataFrame]
        (composite_alpha, daily_returns_matrix)
        其中 composite_alpha 为截面标准化因子评分，
        daily_returns_matrix 为 index=trade_date, columns=stock_code 的收益率透视表
    """
    dim_cols = [c for c in factors_df.columns if c.startswith("dim_")]
    if len(dim_cols) != 768:
        raise ValueError(f"预期 768 个特征维度，实际发现 {len(dim_cols)} 列")

    # 1. 768 维特征矩阵标准化与全截面 PCA 拟合
    scaler = StandardScaler()
    scaled_features = scaler.fit_transform(factors_df[dim_cols].values)

    pca = PCA(n_components=n_components, svd_solver="full", random_state=random_state)
    pca_scores = pca.fit_transform(scaled_features)

    pca_df = pd.DataFrame(
        pca_scores,
        index=factors_df.index,
        columns=[f"PC{k}" for k in range(1, n_components + 1)],
    )

    # 2. 提取截面最新流通市值并调用 ASharePCAFactorPipeline
    latest_mv = (
        csmar_panel.sort_values("trade_date")
        .groupby("stock_code")["market_value"]
        .last()
    )

    pipeline = ASharePCAFactorPipeline(winsorize=True, standardize=True)
    bundle = pipeline.transform_cross_section(
        pca_factors=pca_df,
        industries=factors_df["sector"],
        market_caps=latest_mv,
    )

    composite_alpha = bundle.composite_alpha.dropna()

    # 3. 构造对齐的日收益率矩阵
    returns_matrix = csmar_panel.pivot(
        index="trade_date",
        columns="stock_code",
        values="eff_ret",
    ).fillna(0.0)

    return composite_alpha, returns_matrix


def run_weekly_long_short_backtest(
    alpha_series: pd.Series,
    returns_df: pd.DataFrame,
    stock_metadata: pd.DataFrame,
    cohort: str | None = None,
    rebalance_freq: int = 5,
    top_pct: float = 0.2,
    bot_pct: float = 0.2,
    volume_df: pd.DataFrame | None = None,
    transaction_cost: float = 0.0,
) -> BacktestResult:
    """执行 5 交易日周度再平衡多空策略回测。

    Parameters
    ----------
    alpha_series : pd.Series
        静态复合因子评分，index 为 6 位证券代码
    returns_df : pd.DataFrame
        日度收益率矩阵，index 为 trade_date，columns 为 6 位证券代码
    stock_metadata : pd.DataFrame
        股票元数据表，必须包含 cohort_key 列，index 为 6 位证券代码
    cohort : str, optional
        回测子板块标识（'student_A', 'student_B', 'student_C' 或 None/'full'）
    rebalance_freq : int, default 5
        调仓周期（交易日数）
    top_pct : float, default 0.2
        多头腿选股分位数比例（默认前 20%）
    bot_pct : float, default 0.2
        空头腿选股分位数比例（默认后 20%）
    volume_df : pd.DataFrame, optional
        交易量矩阵，用于在调仓日剔除停牌无成交量的标的
    transaction_cost : float, default 0.0
        单边交易成本比率（基准设定为 0.0）

    Returns
    -------
    BacktestResult
        包含策略收益、腿收益、换手率和持仓明细的结果对象
    """
    universe_name = cohort if cohort and cohort != "full" else "full"

    # 确定当前回测股票池
    if universe_name == "full":
        target_universe = [
            s for s in alpha_series.index if s in returns_df.columns
        ]
    else:
        cohort_stocks = stock_metadata[
            stock_metadata["cohort_key"] == universe_name
        ].index
        target_universe = [
            s
            for s in cohort_stocks
            if s in alpha_series.index and s in returns_df.columns
        ]

    if not target_universe:
        raise ValueError(f"股票池 {universe_name} 为空，无法执行回测")

    dates = sorted(returns_df.index.tolist())
    reb_indices = set(range(0, len(dates), rebalance_freq))

    daily_p_ret: list[float] = []
    daily_l_ret: list[float] = []
    daily_s_ret: list[float] = []
    turnover_list: list[float] = []
    rebalance_dates_list: list[str] = []

    long_holdings: dict[str, list[str]] = {}
    short_holdings: dict[str, list[str]] = {}

    curr_long: list[str] = []
    curr_short: list[str] = []
    prev_long: set[str] | None = None
    prev_short: set[str] | None = None

    for idx, d in enumerate(dates):
        if idx in reb_indices:
            rebalance_dates_list.append(d)

            # 筛选调仓日有效可交易标的（若提供了 volume_df，要求 volume > 0）
            if volume_df is not None and d in volume_df.index:
                valid_stocks = [
                    s
                    for s in target_universe
                    if s in volume_df.columns and volume_df.loc[d, s] > 0
                ]
            else:
                valid_stocks = list(target_universe)

            if not valid_stocks:
                valid_stocks = list(target_universe)

            # 依据因子打分降序排列
            u_alpha = alpha_series.loc[valid_stocks].sort_values(ascending=False)
            k = max(1, int(round(len(valid_stocks) * top_pct)))

            curr_long = u_alpha.index[:k].tolist()
            curr_short = u_alpha.index[-k:].tolist()

            long_holdings[d] = list(curr_long)
            short_holdings[d] = list(curr_short)

            # 计算换手率：多头腿与空头腿换仓股票比例的算术平均值
            curr_long_set = set(curr_long)
            curr_short_set = set(curr_short)

            if prev_long is not None and prev_short is not None:
                to_long = len(curr_long_set - prev_long) / max(len(curr_long_set), 1)
                to_short = len(curr_short_set - prev_short) / max(len(curr_short_set), 1)
                to_step = 0.5 * (to_long + to_short)
            else:
                to_step = 0.0

            turnover_list.append(to_step)
            prev_long = curr_long_set
            prev_short = curr_short_set

        # 计算当日多头与空头平均收益率
        long_series = returns_df.loc[d, curr_long].dropna() if curr_long else pd.Series(dtype=float)
        short_series = returns_df.loc[d, curr_short].dropna() if curr_short else pd.Series(dtype=float)

        r_l = float(long_series.mean()) if len(long_series) > 0 else 0.0
        r_s = float(short_series.mean()) if len(short_series) > 0 else 0.0

        # 多空对冲日收益率：0.5 * Long - 0.5 * Short
        r_p = 0.5 * r_l - 0.5 * r_s

        daily_l_ret.append(r_l)
        daily_s_ret.append(r_s)
        daily_p_ret.append(r_p)

    s_ret = pd.Series(daily_p_ret, index=dates, name="daily_returns")
    s_long = pd.Series(daily_l_ret, index=dates, name="long_leg_returns")
    s_short = pd.Series(daily_s_ret, index=dates, name="short_leg_returns")
    s_turnover = pd.Series(
        turnover_list, index=rebalance_dates_list, name="turnover_series"
    )

    cum_ret = (1.0 + s_ret).cumprod().rename("cumulative_returns")
    cum_log_ret = np.log1p(s_ret).cumsum().rename("cumulative_log_returns")

    return BacktestResult(
        universe=universe_name,
        daily_returns=s_ret,
        cumulative_returns=cum_ret,
        cumulative_log_returns=cum_log_ret,
        long_leg_returns=s_long,
        short_leg_returns=s_short,
        turnover_series=s_turnover,
        long_holdings=long_holdings,
        short_holdings=short_holdings,
        rebalance_dates=rebalance_dates_list,
    )


def compute_performance_metrics(result: BacktestResult) -> dict[str, Any]:
    """计算回测核心绩效指标。

    Parameters
    ----------
    result : BacktestResult
        回测结果对象

    Returns
    -------
    dict[str, Any]
        包含 universe, annualized_return, annualized_volatility,
        sharpe_ratio, max_drawdown, annualized_turnover, calmar_ratio
    """
    s_ret = result.daily_returns
    t_len = len(s_ret)
    if t_len == 0:
        return {
            "universe": result.universe,
            "annualized_return": 0.0,
            "annualized_volatility": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "annualized_turnover": 0.0,
            "calmar_ratio": 0.0,
        }

    # 复合年化收益率
    cum_total = (1.0 + s_ret).prod()
    if cum_total > 0:
        ann_ret = float(cum_total ** (252.0 / t_len) - 1.0)
    else:
        ann_ret = float(s_ret.mean() * 252.0)

    # 年化波动率
    daily_std = float(s_ret.std(ddof=1)) if t_len > 1 else 0.0
    ann_vol = daily_std * np.sqrt(252.0)

    # 夏普比率 (无风险利率假设为 0.0)
    if daily_std > 1e-12:
        sharpe = float((s_ret.mean() / daily_std) * np.sqrt(252.0))
    else:
        sharpe = 0.0

    # 最大回撤 (MDD)
    cum = (1.0 + s_ret).cumprod()
    peak = cum.cummax()
    drawdown = (peak - cum) / peak
    mdd = float(drawdown.max()) if len(drawdown) > 0 else 0.0

    # 年化换手率
    if len(result.turnover_series) > 0:
        ann_to = float(result.turnover_series.mean() * (252.0 / 5.0))
    else:
        ann_to = 0.0

    # Calmar 比率
    calmar = float(ann_ret / mdd) if mdd > 1e-12 else 0.0

    return {
        "universe": result.universe,
        "annualized_return": ann_ret,
        "annualized_volatility": ann_vol,
        "sharpe_ratio": sharpe,
        "max_drawdown": mdd,
        "annualized_turnover": ann_to,
        "calmar_ratio": calmar,
    }


def decompose_annual_alpha_beta(
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series,
) -> pd.DataFrame:
    """分年度执行相对于宇宙等权基准的 OLS 计量回归分解。

    回归设定：
        R_{p, t} = alpha_{daily} + beta * R_{m, t} + epsilon_t
        alpha_{annual} = alpha_{daily} * 252

    Parameters
    ----------
    portfolio_returns : pd.Series
        策略日收益率序列，index 为 trade_date ('YYYY-MM-DD')
    benchmark_returns : pd.Series
        同宇宙等权市场基准日收益率序列，index 为 trade_date ('YYYY-MM-DD')

    Returns
    -------
    pd.DataFrame
        包含 year, annual_alpha, beta, r_squared, t_stat 的 DataFrame
    """
    df = pd.DataFrame({
        "portfolio": portfolio_returns,
        "benchmark": benchmark_returns,
    }).dropna()

    df["year"] = pd.to_datetime(df.index).year

    records = []
    for yr, group in df.groupby("year"):
        if len(group) < 3:
            continue

        X = sm.add_constant(group["benchmark"])
        y = group["portfolio"]

        model = sm.OLS(y, X).fit()

        alpha_daily = float(model.params.iloc[0])
        annual_alpha = alpha_daily * 252.0
        beta = float(model.params.iloc[1])
        r_squared = float(model.rsquared)
        t_stat = float(model.tvalues.iloc[0])

        records.append({
            "year": int(yr),
            "annual_alpha": annual_alpha,
            "beta": beta,
            "r_squared": r_squared,
            "t_stat": t_stat,
        })

    return pd.DataFrame(records)


def generate_pnl_charts(
    results: Mapping[str, BacktestResult],
    output_dir: Path,
) -> list[Path]:
    """生成满足出版级（>=200 DPI）的 5 张净值与多空对比走势图。

    Parameters
    ----------
    results : Mapping[str, BacktestResult]
        包含 'full', 'student_A', 'student_B', 'student_C' 的回测结果映射
    output_dir : Path
        图表保存目录

    Returns
    -------
    list[Path]
        生成的所有图表路径列表
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_paths: list[Path] = []

    universe_titles = {
        "full": "全市场全池标的 (299 支)",
        "student_A": "同学 A — 硬科技与高端制造板块 (99 支)",
        "student_B": "同学 B — 新能源与周期资源板块 (100 支)",
        "student_C": "同学 C — 大金融与核心消费板块 (100 支)",
    }

    # 1. 生成 4 张单体多空净值走势图
    for u_key, title in universe_titles.items():
        if u_key not in results:
            continue

        res = results[u_key]
        dates = pd.to_datetime(res.daily_returns.index)

        # 累计对数收益率
        cum_long = np.log1p(res.long_leg_returns).cumsum()
        cum_short = np.log1p(res.short_leg_returns).cumsum()
        cum_spread = np.log1p(res.daily_returns).cumsum()

        fig, ax = plt.subplots(figsize=(10, 5.5), dpi=300)

        ax.plot(dates, cum_long, label="多头组合 (Top 20% 等权)", color="#d62728", linewidth=1.8)
        ax.plot(dates, cum_short, label="空头组合 (Bottom 20% 等权)", color="#1f77b4", linewidth=1.8)
        ax.plot(dates, cum_spread, label="多空对冲组合 (0.5L - 0.5S)", color="#2ca02c", linewidth=2.2, linestyle="--")

        ax.set_title(f"A 股 PCA 复合因子周度多空净值曲线 — {title}", fontsize=13, fontweight="bold", pad=12)
        ax.set_xlabel("交易日期", fontsize=11, labelpad=8)
        ax.set_ylabel("累计对数收益率 (Cumulative Log-Return)", fontsize=11, labelpad=8)
        ax.grid(True, linestyle=":", alpha=0.6)
        ax.legend(loc="best", frameon=True, framealpha=0.9, fontsize=10)

        plt.tight_layout()

        target_file = output_dir / f"{u_key.lower()}_pnl.png"
        fig.savefig(target_file, dpi=300)
        plt.close(fig)
        generated_paths.append(target_file)

        # 同时也保存别名以兼顾各种命名习惯
        alias_file = output_dir / f"pnl_{u_key.lower()}.png"
        if alias_file != target_file:
            fig_alias, ax_alias = plt.subplots(figsize=(10, 5.5), dpi=300)
            ax_alias.plot(dates, cum_long, label="多头组合 (Top 20% 等权)", color="#d62728", linewidth=1.8)
            ax_alias.plot(dates, cum_short, label="空头组合 (Bottom 20% 等权)", color="#1f77b4", linewidth=1.8)
            ax_alias.plot(dates, cum_spread, label="多空对冲组合 (0.5L - 0.5S)", color="#2ca02c", linewidth=2.2, linestyle="--")
            ax_alias.set_title(f"A 股 PCA 复合因子周度多空净值曲线 — {title}", fontsize=13, fontweight="bold", pad=12)
            ax_alias.set_xlabel("交易日期", fontsize=11, labelpad=8)
            ax_alias.set_ylabel("累计对数收益率 (Cumulative Log-Return)", fontsize=11, labelpad=8)
            ax_alias.grid(True, linestyle=":", alpha=0.6)
            ax_alias.legend(loc="best", frameon=True, framealpha=0.9, fontsize=10)
            plt.tight_layout()
            fig_alias.savefig(alias_file, dpi=300)
            plt.close(fig_alias)

    # 2. 生成 1 张多宇宙对比图
    fig, ax = plt.subplots(figsize=(11, 6), dpi=300)
    colors = {
        "full": "#2ca02c",
        "student_A": "#d62728",
        "student_B": "#ff7f0e",
        "student_C": "#1f77b4",
    }
    line_styles = {
        "full": "-",
        "student_A": "--",
        "student_B": "-.",
        "student_C": ":",
    }

    for u_key in ["full", "student_A", "student_B", "student_C"]:
        if u_key not in results:
            continue
        res = results[u_key]
        dates = pd.to_datetime(res.daily_returns.index)
        cum_spread = np.log1p(res.daily_returns).cumsum()
        ax.plot(
            dates,
            cum_spread,
            label=universe_titles.get(u_key, u_key),
            color=colors.get(u_key, "#333333"),
            linestyle=line_styles.get(u_key, "-"),
            linewidth=2.0,
        )

    ax.set_title("A 股 PCA 复合因子周度多空组合跨板块绩效对比 (2024–2026)", fontsize=14, fontweight="bold", pad=14)
    ax.set_xlabel("交易日期", fontsize=11, labelpad=8)
    ax.set_ylabel("累计对数收益率 (Cumulative Log-Return)", fontsize=11, labelpad=8)
    ax.grid(True, linestyle=":", alpha=0.6)
    ax.legend(loc="best", frameon=True, framealpha=0.9, fontsize=10)

    plt.tight_layout()
    comb_target = output_dir / "combined_pnl.png"
    fig.savefig(comb_target, dpi=300)
    plt.close(fig)
    generated_paths.append(comb_target)

    comb_alias = output_dir / "pnl_combined.png"
    if comb_alias != comb_target:
        fig_c, ax_c = plt.subplots(figsize=(11, 6), dpi=300)
        for u_key in ["full", "student_A", "student_B", "student_C"]:
            if u_key not in results:
                continue
            res = results[u_key]
            dates = pd.to_datetime(res.daily_returns.index)
            cum_spread = np.log1p(res.daily_returns).cumsum()
            ax_c.plot(
                dates,
                cum_spread,
                label=universe_titles.get(u_key, u_key),
                color=colors.get(u_key, "#333333"),
                linestyle=line_styles.get(u_key, "-"),
                linewidth=2.0,
            )
        ax_c.set_title("A 股 PCA 复合因子周度多空组合跨板块绩效对比 (2024–2026)", fontsize=14, fontweight="bold", pad=14)
        ax_c.set_xlabel("交易日期", fontsize=11, labelpad=8)
        ax_c.set_ylabel("累计对数收益率 (Cumulative Log-Return)", fontsize=11, labelpad=8)
        ax_c.grid(True, linestyle=":", alpha=0.6)
        ax_c.legend(loc="best", frameon=True, framealpha=0.9, fontsize=10)
        plt.tight_layout()
        fig_c.savefig(comb_alias, dpi=300)
        plt.close(fig_c)

    return generated_paths


def run_pipeline(
    project_root: Path | None = None,
    output_tables_dir: Path | None = None,
    output_figures_dir: Path | None = None,
) -> dict[str, Any]:
    """执行端到端 PCA 因子回测流水线，输出所有报告与图表。

    Parameters
    ----------
    project_root : Path, optional
        项目根目录
    output_tables_dir : Path, optional
        CSV 报表输出目录（默认 reports/tables/ashare_pca_backtest/）
    output_figures_dir : Path, optional
        PNG 图表输出目录（默认 reports/figures/ashare_pca_backtest/）

    Returns
    -------
    dict[str, Any]
        包含 metrics_summary, annual_alpha_dfs, output_files 等的执行结果字典
    """
    root = project_root or PROJECT_ROOT
    data_dir = root / "data" / "task_split"
    tables_dir = output_tables_dir or (root / "reports" / "tables" / "ashare_pca_backtest")
    figures_dir = output_figures_dir or (root / "reports" / "figures" / "ashare_pca_backtest")

    tables_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)

    logger.info("1. 加载并对齐数据集...")
    factors_df, csmar_panel, latest_mv = load_and_align_datasets(data_dir=data_dir)

    logger.info("2. 计算截面综合因子打分...")
    composite_alpha, returns_matrix = compute_alpha_composite_nale(
        factors_df=factors_df,
        csmar_panel=csmar_panel,
    )

    volume_matrix = csmar_panel.pivot(
        index="trade_date",
        columns="stock_code",
        values="volume",
    ).fillna(0.0)

    # 3. 运行 4 大宇宙回测
    universes = ["full", "student_A", "student_B", "student_C"]
    results: dict[str, BacktestResult] = {}
    metrics_list: list[dict[str, Any]] = []

    logger.info("3. 执行 4 个多空投资组合周度回测...")
    for u in universes:
        res = run_weekly_long_short_backtest(
            alpha_series=composite_alpha,
            returns_df=returns_matrix,
            stock_metadata=factors_df,
            cohort=u,
            rebalance_freq=5,
            top_pct=0.2,
            bot_pct=0.2,
            volume_df=volume_matrix,
            transaction_cost=0.0,
        )
        results[u] = res
        m = compute_performance_metrics(res)
        metrics_list.append(m)

    # 保存绩效汇总表
    summary_df = pd.DataFrame(metrics_list)
    summary_path = tables_dir / "backtest_summary.csv"
    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")

    # 4. 历年 Alpha/Beta 分解
    logger.info("4. 执行分年度市场基准回归分解...")
    annual_alpha_dfs: dict[str, pd.DataFrame] = {}
    for u in universes:
        if u == "full":
            u_stocks = [s for s in composite_alpha.index if s in returns_matrix.columns]
        else:
            u_stocks = [
                s
                for s in factors_df[factors_df["cohort_key"] == u].index
                if s in composite_alpha.index and s in returns_matrix.columns
            ]

        # 宇宙等权基准
        bench_series = returns_matrix[u_stocks].mean(axis=1)
        decomp_df = decompose_annual_alpha_beta(
            portfolio_returns=results[u].daily_returns,
            benchmark_returns=bench_series,
        )
        annual_alpha_dfs[u] = decomp_df

        # 保存分解 CSV（支持小写文件名）
        out_name = f"annual_alpha_{u.lower()}.csv"
        decomp_df.to_csv(tables_dir / out_name, index=False, encoding="utf-8-sig")

    # 5. 生成 5 张图表
    logger.info("5. 生成出版级图表矩阵...")
    fig_paths = generate_pnl_charts(results=results, output_dir=figures_dir)

    return {
        "composite_alpha": composite_alpha,
        "results": results,
        "summary_df": summary_df,
        "annual_alpha_dfs": annual_alpha_dfs,
        "summary_path": summary_path,
        "figure_paths": fig_paths,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print("Running PCA Backtest Pipeline...")
    output = run_pipeline()
    print("Pipeline finished successfully!")
    print(output["summary_df"].to_string(index=False))
