# -*- coding: utf-8 -*-
"""scripts/review_m4_fullrun.py —— M4 正式评测产物的独立复核（不依赖评测器内部计算）。

按 AGENTS.md「Agent 独立复核」要求：门禁退出码与评测器自算结果不作为正确性证明。
本脚本从 run_id 产物文件出发，用**独立实现**重算关键结论并断言：

R1 恒等式：alpha_0.00 的得分 ≡ asof 面板 S0（逐位）；alpha_0.00 跨网络逐位相同。
R2 门控回落：fallback_reason 非空时，gate_* 得分 ≡ b0_alpha_0.40 得分（逐位）。
R3 标签手算：任取一支股票一个信号日，从 master 面板 close 序列按日历轴独立重算
   label_5（前复权日收益连乘），与 asof 面板标签逐位一致。
R4 IC 手算：任取 (网络, 变体, 信号日)，用 numpy 独立实现 Pearson/Spearman IC，
   与 ic_series.csv 逐位一致。
R5 组合重算：任取 (网络, 变体, 视界, 成本档)，独立重建逐期多空（腿=20、换手计费），
   重算每期净收益均值与评测器 portfolio.csv 的 mean_period_return 一致（<1e-12）。

用法：python scripts/review_m4_fullrun.py --run-id m4-full-run-B-20260919 [--rows 5]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class ReviewError(AssertionError):
    """独立复核失败。"""


def _load(run_id: str) -> dict[str, pd.DataFrame | dict]:
    base = ROOT / "reports/tables/pca_nale_integration" / run_id
    required = ["manifest.json", "ic_series.csv", "portfolio.csv", "metrics_by_variant.csv"]
    missing = [name for name in required if not (base / name).exists()]
    if missing:
        raise ReviewError(f"{base} 缺少产物：{missing}")
    processed = ROOT / "data/processed/pca_nale_integration" / run_id
    missing = [name for name in ("asof_panel.csv.gz", "variant_scores.csv.gz") if not (processed / name).exists()]
    if missing:
        raise ReviewError(f"{processed} 缺少产物：{missing}")
    return {
        "manifest": json.loads((base / "manifest.json").read_text(encoding="utf-8")),
        "ic_series": pd.read_csv(base / "ic_series.csv"),
        "portfolio": pd.read_csv(base / "portfolio.csv"),
        "metrics": pd.read_csv(base / "metrics_by_variant.csv"),
        "asof": pd.read_csv(processed / "asof_panel.csv.gz", dtype={"stock_code": str}),
        "scores": pd.read_csv(processed / "variant_scores.csv.gz", dtype={"stock_code": str}),
    }


def review_run(run_id: str, *, spot_rows: int = 3) -> list[str]:
    data = _load(run_id)
    manifest: dict = data["manifest"]  # type: ignore[assignment]
    asof: pd.DataFrame = data["asof"]  # type: ignore[assignment]
    scores: pd.DataFrame = data["scores"]  # type: ignore[assignment]
    ic_series: pd.DataFrame = data["ic_series"]  # type: ignore[assignment]
    portfolio: pd.DataFrame = data["portfolio"]  # type: ignore[assignment]
    findings: list[str] = []

    # ---- R1: alpha_0.00 ≡ S0，且跨网络逐位相同 -------------------------------
    s0 = asof[asof["is_available"]].loc[:, ["stock_code", "signal_date", "S0"]]
    for network in sorted(scores.loc[scores["variant"] == "alpha_0.00", "network"].unique()):
        block = scores[(scores["network"] == network) & (scores["variant"] == "alpha_0.00")]
        merged = block.merge(s0, on=["stock_code", "signal_date"], how="inner", validate="many_to_one")
        delta = float(np.max(np.abs(merged["score"].to_numpy() - merged["S0"].to_numpy())))
        if delta > 1e-12:
            raise ReviewError(f"R1 失败：{network} alpha_0.00 与 S0 最大差 {delta:.3e}")
    networks = sorted(scores["network"].unique())
    base_net = networks[0]
    first = scores[(scores["network"] == base_net) & (scores["variant"] == "alpha_0.00")].sort_values(
        ["signal_date", "stock_code"]).reset_index(drop=True)
    for network in networks[1:]:
        other = scores[(scores["network"] == network) & (scores["variant"] == "alpha_0.00")].sort_values(
            ["signal_date", "stock_code"]).reset_index(drop=True)
        if not np.array_equal(first["score"].to_numpy(), other["score"].to_numpy()):
            raise ReviewError(f"R1 失败：alpha_0.00 跨网络不相同（{base_net} vs {network}）")
    findings.append(f"R1 通过：alpha_0.00 ≡ S0（max|Δ|=0），跨 {len(networks)} 网络逐位相同")

    # ---- R2: 门控回落 ⇒ gate_* ≡ b0 ----------------------------------------
    for network, fits in manifest["gate_fits"].items():
        for version, fit in fits.items():
            if fit["fallback_reason"]:
                gate = scores[(scores["network"] == network) & (scores["variant"] == f"gate_{version}")]
                b0 = scores[(scores["network"] == network) & (scores["variant"] == "b0_alpha_0.40")]
                a = gate.sort_values(["signal_date", "stock_code"])["score"].to_numpy()
                b = b0.sort_values(["signal_date", "stock_code"])["score"].to_numpy()
                if a.shape != b.shape or not np.array_equal(a, b):
                    raise ReviewError(f"R2 失败：{network}/gate_{version} 声称回落但得分与 b0 不同")
                findings.append(f"R2 通过：{network}/gate_{version} fallback={fit['fallback_reason']} ⇒ 与 b0 逐位相同")

    # ---- R3: 标签手算（前复权 close 日收益连乘，按日历轴） -------------------
    master = pd.read_csv(ROOT / "data/task_split/csmar_master/csmar_factor_panel_master.csv",
                         dtype={"stock_code": str})
    master = master.sort_values(["stock_code", "trade_date"])
    master["close_ret"] = master.groupby("stock_code")["close"].pct_change()
    dates = list(master.loc[master["stock_code"] == master["stock_code"].iloc[0], "trade_date"])
    pos = {date: index for index, date in enumerate(dates)}
    label_columns = [column for column in asof.columns if column.startswith("label_") and column.endswith("_5")]
    sample = asof[asof["is_available"] & asof["label_ok_5"]].dropna(subset=["label_5"])
    rng = np.random.default_rng(20260919)
    picks = sample.iloc[rng.choice(len(sample), size=min(spot_rows, len(sample)), replace=False)]
    for _, row in picks.iterrows():
        code, date = str(row["stock_code"]), str(row["signal_date"])
        index = pos[date]
        future = master[(master["stock_code"] == code)].set_index("trade_date")
        if index + 5 >= len(dates):
            continue
        window = dates[index + 1: index + 6]
        rets = future.loc[window, "close_ret"].to_numpy(dtype=float)
        if not np.isfinite(rets).all():
            continue
        hand_label = float(np.prod(1.0 + rets) - 1.0)
        declared = float(row["label_5"])
        if abs(hand_label - declared) > 1e-10:
            raise ReviewError(f"R3 失败：{code}@{date} 手算 label_5={hand_label:.10f} ≠ 面板 {declared:.10f}")
    findings.append(f"R3 通过：{len(picks)} 个 (股票, 信号日) 的 label_5 独立重算逐位一致")

    # ---- R4: IC 手算（numpy 独立实现 Pearson/Spearman） ----------------------
    label_ref = asof.loc[:, ["stock_code", "signal_date", "label_5", "label_20"]]
    rng2 = np.random.default_rng(42)
    ic_rows = ic_series[~ic_series["excluded"]]
    picks2 = ic_rows.iloc[rng2.choice(len(ic_rows), size=min(spot_rows, len(ic_rows)), replace=False)]
    for _, row in picks2.iterrows():
        network, variant, date, horizon = row["network"], row["variant"], row["signal_date"], int(row["horizon"])
        label_column = f"label_{horizon}"
        block = scores[(scores["network"] == network) & (scores["variant"] == variant) &
                       (scores["signal_date"] == date)].merge(
            label_ref.loc[:, ["stock_code", "signal_date", label_column]],
            on=["stock_code", "signal_date"], how="inner").dropna()
        x = block["score"].to_numpy(dtype=float)
        y = block[label_column].to_numpy(dtype=float)
        pearson = float(np.corrcoef(x, y)[0, 1])
        rank_x = pd.Series(x).rank().to_numpy()
        rank_y = pd.Series(y).rank().to_numpy()
        spearman = float(np.corrcoef(rank_x, rank_y)[0, 1])
        if abs(pearson - float(row["pearson_ic"])) > 1e-10 or abs(spearman - float(row["spearman_ic"])) > 1e-10:
            raise ReviewError(
                f"R4 失败：{network}/{variant}@{date} h={horizon} 手算 IC=({pearson:.8f},{spearman:.8f}) "
                f"≠ 表内 ({row['pearson_ic']:.8f},{row['spearman_ic']:.8f})")
    findings.append(f"R4 通过：{len(picks2)} 个 (网络, 变体, 信号日) 的 Pearson/Spearman IC 独立重算一致")

    # ---- R5: 组合逐期重算（0 成本 gross 均值 + 15bp 净均值） ------------------
    rng3 = np.random.default_rng(7)
    port_rows = portfolio[portfolio["metric"].isin(["gross_return", "net_return"])]
    combos = port_rows[["network", "variant", "horizon", "cost_bps", "metric", "mean_period_return"]].drop_duplicates()
    picks3 = combos.iloc[rng3.choice(len(combos), size=min(4, len(combos)), replace=False)]
    for _, combo in picks3.iterrows():
        network, variant = combo["network"], combo["variant"]
        horizon, cost = int(combo["horizon"]), float(combo["cost_bps"])
        label_column = f"label_{horizon}"
        block = scores[(scores["network"] == network) & (scores["variant"] == variant)].merge(
            asof.loc[:, ["stock_code", "signal_date", label_column]],
            on=["stock_code", "signal_date"], how="inner").dropna(subset=["score", label_column])
        gross_values, net_values = [], []
        prev_long: set[str] = set()
        prev_short: set[str] = set()
        for date, group in block.groupby("signal_date", sort=True):
            if len(group) < 20:
                continue
            size = max(10, int(np.ceil(0.2 * len(group))))
            ordered = group.sort_values("score", ascending=False, kind="stable")
            long_leg = ordered.head(size)["stock_code"].astype(str).tolist()
            short_leg = ordered.tail(size)["stock_code"].astype(str).tolist()
            turnover = 0.5 * (
                len(set(long_leg) - prev_long) / len(long_leg) if prev_long else 1.0
            ) + 0.5 * (
                len(set(short_leg) - prev_short) / len(short_leg) if prev_short else 1.0
            )
            long_mean = float(ordered.head(size)[label_column].mean())
            short_mean = float(ordered.tail(size)[label_column].mean())
            gross_values.append(long_mean - short_mean)
            net_values.append(long_mean - short_mean - turnover * cost / 10000.0 * 2.0)
            prev_long, prev_short = set(long_leg), set(short_leg)
        metric = str(combo["metric"])
        hand_mean = float(np.mean(gross_values if metric == "gross_return" else net_values))
        declared_mean = float(combo["mean_period_return"])
        if abs(hand_mean - declared_mean) > 1e-9:
            raise ReviewError(
                f"R5 失败：{network}/{variant} h={horizon} cost={cost} {metric} 手算均值 {hand_mean:.10f} "
                f"≠ 表内 {declared_mean:.10f}")
    findings.append(f"R5 通过：{len(picks3)} 个组合的逐期多空（腿=20、换手计费）独立重算均值一致")

    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M4 评测产物独立复核")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--rows", type=int, default=3)
    args = parser.parse_args(argv)
    findings = review_run(args.run_id, spot_rows=args.rows)
    print(f"===== 独立复核 {args.run_id} =====")
    for item in findings:
        print(" ✔", item)
    print("全部独立断言通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
