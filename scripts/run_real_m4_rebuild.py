# -*- coding: utf-8 -*-
"""scripts/run_real_m4_rebuild.py —— 真实数据重建 M4 核心量化实验执行引擎

依据《真实数据重建方案_给主Agent.md》与《AGENTS.md》：
1. 纯真实数据源：data/task_split/csmar_master/csmar_factor_panel_master.csv (299支股票, 2024-01-02至2026-08-28)
2. 实验一：Trend Gate 逐日事件研究（无前视、考虑涨跌停成交限制、未来 5/10/20 日真实收益与最大回撤、1000次真随机日期安慰剂落盘）
3. 实验二：Fama-MacBeth 真实 HAC 截面回归（Newey-West Bartlett核，滞后阶数 q=floor(4*(T/100)^(2/9))，区块Bootstrap，BH-FDR & Bonferroni校正）
4. 统计口径：A股年化244天，无任何硬编码指标，所有结果落盘至 reports/real_rebuild_20261010/
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import statsmodels.api as sm


def calc_newey_west_lags(n_obs: int) -> int:
    """标准经验公式: q = max(1, floor(4 * (T / 100)^(2/9)))"""
    if n_obs <= 0:
        return 1
    q = int(np.floor(4.0 * (float(n_obs) / 100.0) ** (2.0 / 9.0)))
    return max(1, q)


def newey_west_t_stat(series: np.ndarray, lags: int) -> Tuple[float, float, float]:
    """计算时间序列均值的 Newey-West HAC t 统计量。
    
    返回: (mean, nw_se, t_stat)
    """
    T = len(series)
    if T < 2:
        return float(np.mean(series)), 1e-9, 0.0
    mu = np.mean(series)
    e = series - mu
    # 样本方差 (gamma_0)
    gamma_0 = np.sum(e ** 2) / T
    # 自协方差求和 (Bartlett核加权)
    var_hac = gamma_0
    for l in range(1, lags + 1):
        weight = 1.0 - float(l) / (lags + 1.0)
        gamma_l = np.sum(e[l:] * e[:-l]) / T
        var_hac += 2.0 * weight * gamma_l
    
    var_mean = max(var_hac / T, 1e-12)
    se_hac = np.sqrt(var_mean)
    t_stat = mu / se_hac
    return float(mu), float(se_hac), float(t_stat)


def block_bootstrap_ci(series: np.ndarray, block_len: int = 5, n_boot: int = 1000, alpha: float = 0.05) -> Tuple[float, float]:
    """移动区块 Bootstrap (Moving Block Bootstrap) 计算均值的双侧置信区间。"""
    T = len(series)
    if T <= block_len:
        return float(np.percentile(series, 2.5)), float(np.percentile(series, 97.5))
    
    n_blocks = int(np.ceil(T / block_len))
    boot_means = np.zeros(n_boot)
    # 所有可能的区块起点
    max_start = T - block_len + 1
    
    rng = np.random.RandomState(42)  # 固定种子保证可复现性
    for b in range(n_boot):
        starts = rng.randint(0, max_start, size=n_blocks)
        sampled = []
        for s in starts:
            sampled.extend(series[s:s+block_len])
        boot_means[b] = np.mean(sampled[:T])
        
    lower = float(np.percentile(boot_means, 100.0 * (alpha / 2.0)))
    upper = float(np.percentile(boot_means, 100.0 * (1.0 - alpha / 2.0)))
    return lower, upper


def benjamini_hochberg_fdr(p_values: np.ndarray) -> np.ndarray:
    """计算 Benjamini-Hochberg FDR 调整后的 q-values。"""
    m = len(p_values)
    if m == 0:
        return np.array([])
    sorted_indices = np.argsort(p_values)
    sorted_p = p_values[sorted_indices]
    q_vals = np.zeros(m)
    
    min_q = 1.0
    for i in range(m - 1, -1, -1):
        rank = i + 1
        q = (sorted_p[i] * m) / rank
        min_q = min(min_q, q)
        q_vals[i] = min_q
        
    res = np.zeros(m)
    res[sorted_indices] = q_vals
    return np.clip(res, 0.0, 1.0)


def run_trend_gate_event_study(df: pd.DataFrame, out_dir: Path) -> Dict:
    """实验一：Trend Gate 逐日事件研究与 1000 次真实随机安慰剂检验。"""
    print("[1/2] 开始执行 Trend Gate 事件研究与安慰剂检验...")
    # 按照 stock_code 和 trade_date 严格排序
    df = df.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    
    # 构建滑动窗口与指标
    records = []
    grouped = df.groupby("stock_code")
    
    for code, group in grouped:
        if len(group) < 65:
            continue
        closes = group["close"].values
        dates = group["trade_date"].values
        hit_limits = group["hit_limit"].values if "hit_limit" in group.columns else np.zeros(len(group))
        n = len(closes)
        
        # 逐日推进 (至少有60日历史数据)
        for t in range(60, n - 20):  # 预留 20 日作为真实未来收益检验窗口
            curr_c = closes[t]
            prev_20 = closes[t - 20]
            ma60 = np.mean(closes[t - 60:t])
            
            mom_20 = (curr_c / prev_20 - 1.0) if prev_20 > 0 else 0.0
            above_ma60 = curr_c > ma60
            
            # 判定趋势状态 (Trend Gate 战术门禁)
            is_downtrend = (mom_20 <= 0.0) and (not above_ma60)
            is_uptrend = (mom_20 > 0.0) and above_ma60
            
            # 涨跌停成交限制检验 (A股真实流动性约束)
            # 若当日跌停(hit_limit == -1 or close==涨跌停价)，次日无法按市价平仓
            is_limit_down = (hit_limits[t] == -1)
            is_limit_up = (hit_limits[t] == 1)
            
            # 计算纯未来真实收益与最大回撤 (无前视偏差: t+1 至 t+k)
            ret_5d = float(closes[t + 5] / curr_c - 1.0)
            ret_10d = float(closes[t + 10] / curr_c - 1.0)
            ret_20d = float(closes[t + 20] / curr_c - 1.0)
            
            # 未来窗口期最大回撤
            window_5 = closes[t + 1:t + 6]
            window_10 = closes[t + 1:t + 11]
            window_20 = closes[t + 1:t + 21]
            
            maxdd_5d = float(np.min(window_5) / curr_c - 1.0)
            maxdd_10d = float(np.min(window_10) / curr_c - 1.0)
            maxdd_20d = float(np.min(window_20) / curr_c - 1.0)
            
            records.append({
                "stock_code": code,
                "trade_date": dates[t],
                "is_downtrend": is_downtrend,
                "is_uptrend": is_uptrend,
                "is_limit_down": is_limit_down,
                "is_limit_up": is_limit_up,
                "ret_5d": ret_5d,
                "ret_10d": ret_10d,
                "ret_20d": ret_20d,
                "maxdd_5d": maxdd_5d,
                "maxdd_10d": maxdd_10d,
                "maxdd_20d": maxdd_20d,
            })
            
    events_df = pd.DataFrame(records)
    print(f"  > 总样本事件数: {len(events_df)}")
    
    # 过滤出 Trend Gate 门禁拦截触发样本 (downtrend 且非跌停可以正常卖出平仓)
    trigger_samples = events_df[events_df["is_downtrend"] & (~events_df["is_limit_down"])].copy()
    non_trigger_samples = events_df[(~events_df["is_downtrend"])].copy()
    uptrend_samples = events_df[events_df["is_uptrend"]].copy()
    
    n_triggers = len(trigger_samples)
    print(f"  > 门禁下行拦截触发样本数: {n_triggers}, 非拦截对照样本数: {len(non_trigger_samples)}, 上行顺势样本数: {len(uptrend_samples)}")
    
    # 统计真实收益表现
    trigger_stats = {
        "count": n_triggers,
        "mean_ret_5d": float(trigger_samples["ret_5d"].mean()),
        "mean_ret_10d": float(trigger_samples["ret_10d"].mean()),
        "mean_ret_20d": float(trigger_samples["ret_20d"].mean()),
        "win_rate_5d": float((trigger_samples["ret_5d"] > 0).mean()),
        "win_rate_10d": float((trigger_samples["ret_10d"] > 0).mean()),
        "win_rate_20d": float((trigger_samples["ret_20d"] > 0).mean()),
        "mean_maxdd_5d": float(trigger_samples["maxdd_5d"].mean()),
        "mean_maxdd_10d": float(trigger_samples["maxdd_10d"].mean()),
        "mean_maxdd_20d": float(trigger_samples["maxdd_20d"].mean()),
    }
    
    uptrend_stats = {
        "count": len(uptrend_samples),
        "mean_ret_5d": float(uptrend_samples["ret_5d"].mean()),
        "mean_ret_10d": float(uptrend_samples["ret_10d"].mean()),
        "mean_ret_20d": float(uptrend_samples["ret_20d"].mean()),
        "win_rate_5d": float((uptrend_samples["ret_5d"] > 0).mean()),
        "win_rate_10d": float((uptrend_samples["ret_10d"] > 0).mean()),
        "win_rate_20d": float((uptrend_samples["ret_20d"] > 0).mean()),
        "mean_maxdd_5d": float(uptrend_samples["maxdd_5d"].mean()),
        "mean_maxdd_10d": float(uptrend_samples["maxdd_10d"].mean()),
        "mean_maxdd_20d": float(uptrend_samples["maxdd_20d"].mean()),
    }
    
    non_trigger_stats = {
        "count": len(non_trigger_samples),
        "mean_ret_5d": float(non_trigger_samples["ret_5d"].mean()),
        "mean_ret_10d": float(non_trigger_samples["ret_10d"].mean()),
        "mean_ret_20d": float(non_trigger_samples["ret_20d"].mean()),
        "win_rate_5d": float((non_trigger_samples["ret_5d"] > 0).mean()),
        "win_rate_10d": float((non_trigger_samples["ret_10d"] > 0).mean()),
        "win_rate_20d": float((non_trigger_samples["ret_20d"] > 0).mean()),
        "mean_maxdd_5d": float(non_trigger_samples["maxdd_5d"].mean()),
        "mean_maxdd_10d": float(non_trigger_samples["maxdd_10d"].mean()),
        "mean_maxdd_20d": float(non_trigger_samples["maxdd_20d"].mean()),
    }
    
    # 1000 次真实随机日期安慰剂检验 (Placebo Simulation)
    print("  > 真实执行 1000 次安慰剂随机检验并记录分布...")
    placebo_ret_5d = []
    placebo_ret_10d = []
    placebo_ret_20d = []
    placebo_maxdd_20d = []
    
    all_indices = events_df.index.values
    rng = np.random.RandomState(20261010)  # 固定种子可复算
    
    # 抽取与触发样本相同量级的随机样本 (1000 次真跑)
    sample_size = min(n_triggers, 10000)
    for i in range(1000):
        sampled_idx = rng.choice(all_indices, size=sample_size, replace=False)
        sub = events_df.loc[sampled_idx]
        placebo_ret_5d.append(float(sub["ret_5d"].mean()))
        placebo_ret_10d.append(float(sub["ret_10d"].mean()))
        placebo_ret_20d.append(float(sub["ret_20d"].mean()))
        placebo_maxdd_20d.append(float(sub["maxdd_20d"].mean()))
        
    placebo_ret_5d = np.array(placebo_ret_5d)
    placebo_ret_10d = np.array(placebo_ret_10d)
    placebo_ret_20d = np.array(placebo_ret_20d)
    placebo_maxdd_20d = np.array(placebo_maxdd_20d)
    
    # 保存 1000 次安慰剂原始抽样数据到 JSON
    placebo_file = out_dir / "trend_gate_placebo_1000.json"
    with open(placebo_file, "w", encoding="utf-8") as f:
        json.dump({
            "n_runs": 1000,
            "sample_size_per_run": sample_size,
            "actual_downtrend_mean_20d": trigger_stats["mean_ret_20d"],
            "actual_uptrend_mean_20d": uptrend_stats["mean_ret_20d"],
            "placebo_5d_means": placebo_ret_5d.tolist(),
            "placebo_10d_means": placebo_ret_10d.tolist(),
            "placebo_20d_means": placebo_ret_20d.tolist(),
            "placebo_maxdd_20d_means": placebo_maxdd_20d.tolist(),
        }, f, indent=2)
    print(f"  > 1000 次安慰剂检验结果已落盘: {placebo_file}")
    
    # 计算统计显著性 p 值 (经验 p 值: 安慰剂收益比触发下行收益还低的概率)
    p_val_avoidance_20d = float(np.mean(placebo_ret_20d <= trigger_stats["mean_ret_20d"]))
    
    return {
        "trigger_stats": trigger_stats,
        "uptrend_stats": uptrend_stats,
        "non_trigger_stats": non_trigger_stats,
        "placebo_summary": {
            "placebo_mean_20d": float(np.mean(placebo_ret_20d)),
            "placebo_std_20d": float(np.std(placebo_ret_20d)),
            "placebo_ci_95_20d": [float(np.percentile(placebo_ret_20d, 2.5)), float(np.percentile(placebo_ret_20d, 97.5))],
            "empirical_p_value_20d": p_val_avoidance_20d,
            "placebo_mean_maxdd_20d": float(np.mean(placebo_maxdd_20d)),
        }
    }


def run_fama_macbeth_regression(df: pd.DataFrame, out_dir: Path) -> Dict:
    """实验二：Fama-MacBeth HAC 截面与滚动回归 (严格按方案 q 阶滞后与多重检验校正)。"""
    print("[2/2] 开始执行 Fama-MacBeth HAC 回归与多重假设检验校正...")
    factors = ["mom_20d", "mom_60d", "vol_20d", "turnover_20d", "amihud", "price_pos"]
    available_factors = [f for f in factors if f in df.columns]
    print(f"  > 入选截面因子: {available_factors}")
    
    # 按照 trade_date 组织截面
    dates = sorted(df["trade_date"].unique())
    T_total = len(dates)
    print(f"  > 截面期数 T = {T_total}")
    
    # 存储每日回归系数 lambda_{k, t}
    daily_lambdas = {f: [] for f in available_factors}
    daily_alphas = []
    valid_dates = []
    
    for t_idx, d in enumerate(dates):
        sub = df[df["trade_date"] == d].dropna(subset=["ret"] + available_factors)
        if len(sub) < 30:  # 截面有效股票数太少则跳过
            continue
            
        y = sub["ret"].values
        X = sub[available_factors].values
        
        # 截面标准化处理 (Z-score)
        X_std = (X - np.mean(X, axis=0)) / (np.std(X, axis=0) + 1e-9)
        X_reg = sm.add_constant(X_std)
        
        try:
            model = sm.OLS(y, X_reg).fit()
            daily_alphas.append(float(model.params[0]))
            for idx, f in enumerate(available_factors):
                daily_lambdas[f].append(float(model.params[idx + 1]))
            valid_dates.append(d)
        except Exception:
            continue
            
    T_valid = len(valid_dates)
    lags_nw = calc_newey_west_lags(T_valid)
    print(f"  > 有效截面期数 T_valid = {T_valid}, 理论最优 Newey-West HAC 滞后阶数 q = {lags_nw}")
    
    factor_results = {}
    p_values_list = []
    factor_names_list = []
    
    for f in available_factors:
        series = np.array(daily_lambdas[f])
        mean_val, nw_se, nw_t = newey_west_t_stat(series, lags_nw)
        # 普通 OLS t
        classic_se = float(np.std(series, ddof=1) / np.sqrt(T_valid))
        classic_t = mean_val / max(classic_se, 1e-12)
        # 双侧 p 值 (依据正态渐近分布)
        from scipy import stats
        p_val = float(2.0 * (1.0 - stats.norm.cdf(abs(nw_t))))
        
        # 区块 Bootstrap 95% 置信区间
        ci_lower, ci_upper = block_bootstrap_ci(series, block_len=lags_nw, n_boot=1000)
        
        factor_results[f] = {
            "mean_risk_premium": mean_val,
            "annualized_premium": mean_val * 244.0,  # 统一 A 股 244 天口径
            "classic_se": classic_se,
            "classic_t": classic_t,
            "newey_west_se": nw_se,
            "newey_west_t": nw_t,
            "p_value": p_val,
            "block_bootstrap_ci_95": [ci_lower, ci_upper],
        }
        factor_names_list.append(f)
        p_values_list.append(p_val)
        
    p_vals_arr = np.array(p_values_list)
    # 多重假设检验校正: BH-FDR 与 Bonferroni
    q_vals_bh = benjamini_hochberg_fdr(p_vals_arr)
    p_vals_bonf = np.clip(p_vals_arr * len(p_vals_arr), 0.0, 1.0)
    
    for idx, f in enumerate(factor_names_list):
        factor_results[f]["fdr_q_value"] = float(q_vals_bh[idx])
        factor_results[f]["bonferroni_p_value"] = float(p_vals_bonf[idx])
        factor_results[f]["is_significant_5pct_fdr"] = bool(q_vals_bh[idx] < 0.05)
        factor_results[f]["is_significant_5pct_bonferroni"] = bool(p_vals_bonf[idx] < 0.05)
        
    return {
        "n_periods": T_valid,
        "hac_lags": lags_nw,
        "factors": factor_results
    }


def main():
    start_time = time.time()
    csmar_path = Path("data/task_split/csmar_master/csmar_factor_panel_master.csv")
    out_dir = Path("reports/real_rebuild_20261010")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    if not csmar_path.exists():
        print(f"ERROR: 找不到真实 CSMAR 数据源 {csmar_path}")
        sys.exit(1)
        
    print(f"正在加载 CSMAR 真实主面板: {csmar_path} ...")
    df = pd.read_csv(csmar_path)
    print(f"数据加载完成: {df.shape[0]} 行, {df.shape[1]} 列, 标的数: {df['stock_code'].nunique()}")
    
    # 1. Trend Gate 事件研究与安慰剂检验
    tg_results = run_trend_gate_event_study(df, out_dir)
    
    # 2. Fama-MacBeth 真实 HAC 滚动回归
    fm_results = run_fama_macbeth_regression(df, out_dir)
    
    # 汇总 results.json
    full_results = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "data_source": "data/task_split/csmar_master/csmar_factor_panel_master.csv",
        "universe_size": int(df["stock_code"].nunique()),
        "time_range": [str(df["trade_date"].min()), str(df["trade_date"].max())],
        "annualization_days": 244,
        "trend_gate_study": tg_results,
        "fama_macbeth_study": fm_results,
    }
    
    results_file = out_dir / "results.json"
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump(full_results, f, indent=2, ensure_ascii=False)
    print(f"\n[OK] 完整量化重算结果已落盘: {results_file}")
    
    elapsed = time.time() - start_time
    print(f"全流程耗时: {elapsed:.2f} 秒")


if __name__ == "__main__":
    main()
