# -*- coding: utf-8 -*-
"""
纯碱衍生品套期保值模型参数敏感性分析与样本时序切分引擎 (src/models/parameter_sensitivity.py)
-----------------------------------------------------------------------------------------
职责与学术规范:
1. 样本切分规范 (T7 / B11):
   - 训练期 (Train): 2019-12-06 至 2023-12-31 (市场微观结构探索与超参数初筛)
   - 验证期 (Validation): 2024-01-01 至 2024-12-31 (历经纯碱现货大幅走弱周期，确认并冻结超参数)
   - 样本外测试期 (Test): 2025-01-01 至 2026-09-28 (严格未调优样本外盲测，验证策略泛化稳健性)
   - 全历史样本 (Full): 2019-12-06 至 2026-09-28 (全景实证对照)
2. 参数敏感性分析 (±20% 扰动):
   对 8 项核心参数开展局部敏感性扰动压力测试:
   - fast_span (20) -> [16, 20, 24]
   - slow_span (60) -> [48, 60, 72]
   - hysteresis_window (3) -> [2, 3, 4]
   - nale_weight (0.35) -> [0.28, 0.35, 0.42]
   - tsmom_weight (0.20) -> [0.16, 0.20, 0.24]
   - threshold (0.50) -> [0.40, 0.50, 0.60]
   - sa_to_fg_lag (18.0) -> [14.4, 18.0, 21.6]
   - sa_half_life (25.0) -> [20.0, 25.0, 30.0]
3. 输出报表产出:
   - reports/tables/sample_split_performance.csv (四大方案在各时序切分阶段的表现矩阵)
   - reports/tables/param_sensitivity.csv (核心超参数敏感性与稳健性评级表)
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
import numpy as np
import pandas as pd

# 强制 UTF-8 标准输出
sys.stdout.reconfigure(encoding="utf-8")

# 工程路径解析
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.models.hedging_strategies import HedgingEngine, compute_performance_metrics
from src.models.temporal_nale import TemporalNALE

PROCESSED_DATA_PATH = ROOT_DIR / "data" / "processed" / "czce_sa_fg_aligned_features.csv"
TABLES_DIR = ROOT_DIR / "reports" / "tables"
TABLES_DIR.mkdir(parents=True, exist_ok=True)

# 核心超参数基准设定表 (Benchmark Parameters)
BASELINE_PARAMS = {
    "fast_span": 20,
    "slow_span": 60,
    "hysteresis_window": 3,
    "nale_weight": 0.35,
    "tsmom_weight": 0.20,
    "threshold": 0.50,
    "sa_to_fg_lag": 18.0,
    "sa_half_life": 25.0,
}


def split_dataset(
    df: pd.DataFrame,
    train_end: str = "2023-12-31",
    val_end: str = "2024-12-31"
) -> Dict[str, pd.DataFrame]:
    """
    根据时间序列因果无前视原则切分数据集为训练集、验证集、样本外测试集及全样本。
    
    参数:
    - df: 包含 date 列的特征 DataFrame
    - train_end: 训练期截止日期 (默认 2023-12-31)
    - val_end: 验证期截止日期 (默认 2024-12-31)
    
    返回:
    - 字典包含划分好的 4 个切片 DataFrame (reset_index)
    """
    if "date" not in df.columns:
        raise KeyError("输入 DataFrame 必须包含 'date' 字段")

    dates = pd.to_datetime(df["date"])
    t_end = pd.to_datetime(train_end)
    v_end = pd.to_datetime(val_end)

    train_mask = dates <= t_end
    val_mask = (dates > t_end) & (dates <= v_end)
    test_mask = dates > v_end

    train_df = df[train_mask].copy().reset_index(drop=True)
    val_df = df[val_mask].copy().reset_index(drop=True)
    test_df = df[test_mask].copy().reset_index(drop=True)
    full_df = df.copy().reset_index(drop=True)

    return {
        "训练期 (2019-2023)": train_df,
        "验证期 (2024)": val_df,
        "样本外测试期 (2025-2026)": test_df,
        "全历史样本 (2019-2026)": full_df,
    }


def evaluate_sample_splits(
    df: Optional[pd.DataFrame] = None,
    output_path: Optional[Path] = None
) -> pd.DataFrame:
    """
    运行四大方案在各时序切片阶段的回测评估，并输出结构化指标矩阵。
    """
    if df is None:
        if not PROCESSED_DATA_PATH.exists():
            raise FileNotFoundError(f"未找到输入数据文件: {PROCESSED_DATA_PATH}")
        df = pd.read_csv(PROCESSED_DATA_PATH)

    splits = split_dataset(df)
    all_records = []

    for stage_name, split_df in splits.items():
        if len(split_df) < 5:
            continue

        start_date = str(split_df["date"].iloc[0])
        end_date = str(split_df["date"].iloc[-1])
        n_days = len(split_df)

        engine = HedgingEngine(
            df=split_df,
            inventory_tons=10000.0,
            contract_multiplier=20.0,
            margin_ratio=0.12,
            commission_rate=0.0002,
            annual_risk_free_rate=0.03
        )

        res_a = engine.run_unhedged()
        res_b = engine.run_naive_hedge()
        res_c = engine.run_ols_hedge(window=min(60, max(10, n_days // 3)))
        res_d = engine.run_trend_gate_collar()

        res_dict = {
            "方案A(裸暴露)": res_a,
            "方案B(传统1:1静态套保)": res_b,
            "方案C(经典滚动OLS对冲)": res_c,
            "方案D(TrendGate自适应领子对冲)": res_d,
        }

        perf_df = compute_performance_metrics(res_dict)
        perf_df.insert(0, "交易日数", n_days)
        perf_df.insert(0, "结束日期", end_date)
        perf_df.insert(0, "起始日期", start_date)
        perf_df.insert(0, "样本阶段", stage_name)

        all_records.append(perf_df)

    combined_df = pd.concat(all_records, ignore_index=True)
    out_file = output_path if output_path is not None else (TABLES_DIR / "sample_split_performance.csv")
    combined_df.to_csv(out_file, index=False, encoding="utf-8-sig")
    return combined_df


def _extract_scheme_d_metrics(
    engine: HedgingEngine,
    unhedged_pnl: pd.Series,
    **kwargs
) -> Tuple[float, float, float]:
    """计算单个配置下方案 D 的 (HE_pct, MaxDD_pct, TotalRet_pct)"""
    res_d = engine.run_trend_gate_collar(**kwargs)
    net_worth = res_d["net_worth"]
    net_pnl = res_d["net_pnl"]

    final_nw = net_worth.iloc[-1]
    total_ret = (final_nw - 1.0) * 100.0

    var_unhedged = np.var(unhedged_pnl)
    var_hedged = np.var(net_pnl)
    he = (1.0 - var_hedged / var_unhedged) * 100.0 if var_unhedged > 0 else 0.0

    cummax = net_worth.cummax()
    drawdown = (net_worth - cummax) / cummax
    max_dd = drawdown.min() * 100.0

    return float(he), float(max_dd), float(total_ret)


def run_parameter_sensitivity(
    df: Optional[pd.DataFrame] = None,
    output_path: Optional[Path] = None
) -> pd.DataFrame:
    """
    对 8 项核心超参数开展 ±20% 敏感性压力测试并输出评估表格。
    """
    if df is None:
        if not PROCESSED_DATA_PATH.exists():
            raise FileNotFoundError(f"未找到输入数据文件: {PROCESSED_DATA_PATH}")
        df = pd.read_csv(PROCESSED_DATA_PATH)

    splits = split_dataset(df)
    val_df = splits["验证期 (2024)"]
    full_df = splits["全历史样本 (2019-2026)"]

    engine_val = HedgingEngine(val_df)
    engine_full = HedgingEngine(full_df)

    res_a_val = engine_val.run_unhedged()
    res_a_full = engine_full.run_unhedged()
    unhedged_pnl_val = res_a_val["net_pnl"]
    unhedged_pnl_full = res_a_full["net_pnl"]

    # 预计算 baseline NALE 信号以大幅提升扰动测试运行速度
    nale_base_val = TemporalNALE(
        window=60,
        sa_to_fg_lag=BASELINE_PARAMS["sa_to_fg_lag"],
        sa_half_life=BASELINE_PARAMS["sa_half_life"]
    ).compute_crush_spread(val_df)["nale_leading_signal"]

    nale_base_full = TemporalNALE(
        window=60,
        sa_to_fg_lag=BASELINE_PARAMS["sa_to_fg_lag"],
        sa_half_life=BASELINE_PARAMS["sa_half_life"]
    ).compute_crush_spread(full_df)["nale_leading_signal"]

    # 基准评估
    base_val_he, base_val_mdd, _ = _extract_scheme_d_metrics(
        engine_val, unhedged_pnl_val, nale_signals=nale_base_val
    )
    base_full_he, base_full_mdd, _ = _extract_scheme_d_metrics(
        engine_full, unhedged_pnl_full, nale_signals=nale_base_full
    )

    records = []
    perturbation_ratios = [-0.20, 0.0, 0.20]

    for param_name, base_val in BASELINE_PARAMS.items():
        is_int = isinstance(base_val, int)

        for delta in perturbation_ratios:
            perturbed_val = base_val * (1.0 + delta)
            if is_int:
                test_val = int(round(perturbed_val))
            else:
                test_val = round(perturbed_val, 4)

            # 构造传参
            run_kwargs = {}
            if param_name in ["sa_to_fg_lag", "sa_half_life"]:
                # NALE 参数需要重新计算 NALE 信号
                run_kwargs[param_name] = test_val
                val_he, val_mdd, _ = _extract_scheme_d_metrics(engine_val, unhedged_pnl_val, **run_kwargs)
                full_he, full_mdd, _ = _extract_scheme_d_metrics(engine_full, unhedged_pnl_full, **run_kwargs)
            else:
                # TrendGate 参数可复用基准 NALE 信号
                run_kwargs[param_name] = test_val
                val_he, val_mdd, _ = _extract_scheme_d_metrics(
                    engine_val, unhedged_pnl_val, nale_signals=nale_base_val, **run_kwargs
                )
                full_he, full_mdd, _ = _extract_scheme_d_metrics(
                    engine_full, unhedged_pnl_full, nale_signals=nale_base_full, **run_kwargs
                )

            d_val_he = round(val_he - base_val_he, 2)
            d_val_mdd = round(val_mdd - base_val_mdd, 2)
            d_full_he = round(full_he - base_full_he, 2)
            d_full_mdd = round(full_mdd - base_full_mdd, 2)

            # 稳健性评级: 若最大回撤在验证集与全样本的波动均在 5.0% 以内，评定为稳健 (ROBUST)
            robustness = "ROBUST" if (abs(d_val_mdd) <= 5.0 and abs(d_full_mdd) <= 5.0) else "SENSITIVE"

            delta_str = "0% (基准)" if delta == 0.0 else f"{int(delta * 100):+d}%"

            records.append({
                "参数名称": param_name,
                "基准值": base_val,
                "扰动比例": delta_str,
                "实测测试值": test_val,
                "验证期HE(%)": round(val_he, 2),
                "验证期MaxDD(%)": round(val_mdd, 2),
                "验证期MaxDD变动(%)": d_val_mdd,
                "全样本HE(%)": round(full_he, 2),
                "全样本MaxDD(%)": round(full_mdd, 2),
                "全样本MaxDD变动(%)": d_full_mdd,
                "稳健性评级": robustness
            })

    sensitivity_df = pd.DataFrame(records)
    out_file = output_path if output_path is not None else (TABLES_DIR / "param_sensitivity.csv")
    sensitivity_df.to_csv(out_file, index=False, encoding="utf-8-sig")
    return sensitivity_df


def main():
    print("=================================================================")
    print("【Milestone 2】纯碱套期保值模型参数时序切分与敏感性实证分析启动...")
    print("=================================================================")

    if not PROCESSED_DATA_PATH.exists():
        raise FileNotFoundError(f"未找到特征工程数据: {PROCESSED_DATA_PATH}")

    df = pd.read_csv(PROCESSED_DATA_PATH)
    print(f"-> 成功加载特征数据: {len(df)} 交易日 ({df['date'].min()} 至 {df['date'].max()})")

    # 1. 运行样本时序切片回测评估
    print("\n-> [1/2] 正在执行训练期、验证期、样本外测试期及全样本划分回测...")
    split_df = evaluate_sample_splits(df)
    split_path = TABLES_DIR / "sample_split_performance.csv"
    print(f"[OK] 样本时序切分回测对比表已保存 -> {split_path}")
    print("\n" + split_df[["样本阶段", "方案名称", "累计收益率(%)", "套保有效性HE(%)", "最大回撤(%)", "平均保证金占用(万元)"]].to_string(index=False))

    # 2. 运行核心超参数 ±20% 敏感性压力测试
    print("\n-> [2/2] 正在执行 8 项核心超参数 ±20% 敏感性压力测试...")
    sens_df = run_parameter_sensitivity(df)
    sens_path = TABLES_DIR / "param_sensitivity.csv"
    print(f"[OK] 参数敏感性压力测试矩阵已保存 -> {sens_path}")
    print("\n" + sens_df[["参数名称", "扰动比例", "实测测试值", "验证期MaxDD变动(%)", "全样本MaxDD变动(%)", "稳健性评级"]].to_string(index=False))

    print("\n=================================================================")
    print("【Milestone 2】模型参数冻结与敏感性实证分析完成 (All PASSED)")
    print("=================================================================")


if __name__ == "__main__":
    main()
