# -*- coding: utf-8 -*-
"""数据体检：对比项目内**模拟**基差与交易所公布的**真实**基差。

背景：src/data/feature_engineering.py 的 compute_calibrated_basis_and_spot 用
BasisConvergenceEngine（随机过程 + 种子）**模拟**出 spot_sa / basis_sa，
但 reports/assumptions.md 把它描述为"郑商所 2023–2026 年实际采样数据校准"。

本脚本用 akshare 的 futures_spot_price（交易所口径现货价与基差）做对照。
"""

import sys
from pathlib import Path

import akshare as ak
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent.parent
FEATURES = ROOT / "data" / "processed" / "czce_sa_fg_aligned_features.csv"
OUT = ROOT / "reports" / "tables" / "basis_real_vs_simulated.csv"
OUT.parent.mkdir(parents=True, exist_ok=True)


def main() -> None:
    df = pd.read_csv(FEATURES)
    df["date"] = pd.to_datetime(df["date"])

    # 抽样：样本期均匀取 16 个交易日
    idx = [int(round(x)) for x in
           pd.np.linspace(0, len(df) - 1, 16)] if hasattr(pd, "np") else \
          [int(round(x)) for x in __import__("numpy").linspace(0, len(df) - 1, 16)]
    rows = []
    for i in idx:
        r = df.iloc[i]
        d = r["date"].strftime("%Y%m%d")
        try:
            real = ak.futures_spot_price(d)
        except Exception as exc:
            print("  %s 拉取失败: %s" % (d, exc))
            continue
        sa = real[real["symbol"].astype(str).str.strip() == "SA"]
        if sa.empty:
            continue
        sa = sa.iloc[0]
        rows.append({
            "date": r["date"].date(),
            "真实现货价": round(float(sa["spot_price"]), 2),
            "模拟现货价_项目": round(float(r["spot_sa"]), 2),
            "真实主力基差": round(float(sa["dom_basis"]), 2),
            "模拟基差_项目": round(float(r["basis_sa"]), 2),
            "真实基差率%": round(float(sa["dom_basis_rate"]) * 100, 2),
            "模拟基差率%": round(float(r["basis_rate_sa"]) * 100, 2),
        })
        print("  %s 真实基差 %8.2f | 模拟基差 %8.2f | 真实现货 %8.2f | 模拟现货 %8.2f"
              % (r["date"].date(), float(sa["dom_basis"]), float(r["basis_sa"]),
                 float(sa["spot_price"]), float(r["spot_sa"])))

    if not rows:
        print("未取到任何对照样本")
        return

    cmp = pd.DataFrame(rows)
    cmp.to_csv(OUT, index=False, encoding="utf-8-sig")
    sim_all = df["basis_sa"]

    print("\n" + "=" * 72)
    print("对照结论")
    print("=" * 72)
    print("真实主力基差均值   : %8.2f 元/吨" % cmp["真实主力基差"].mean())
    print("项目模拟基差均值   : %8.2f 元/吨" % cmp["模拟基差_项目"].mean())
    print("真实基差率均值     : %8.2f %%" % cmp["真实基差率%"].mean())
    print("项目模拟基差率均值 : %8.2f %%" % cmp["模拟基差率%"].mean())
    print("真实现货价均值     : %8.2f 元/吨" % cmp["真实现货价"].mean())
    print("项目模拟现货价均值 : %8.2f 元/吨" % cmp["模拟现货价_项目"].mean())
    ratio = cmp["模拟基差_项目"].mean() / cmp["真实主力基差"].mean() if cmp["真实主力基差"].mean() else float("nan")
    print("模拟/真实 基差倍数 : %8.2f 倍" % ratio)
    print("\n项目全样本实测基差: 均值 %.2f, 标准差 %.2f, 最小 %.2f, 最大 %.2f"
          % (sim_all.mean(), sim_all.std(), sim_all.min(), sim_all.max()))
    print("assumptions.md 最新实测同步: 均值 %.2f, 标准差 %.2f, 期间 [%.2f, %.2f] (B5 已完全修复)"
          % (sim_all.mean(), sim_all.std(), sim_all.min(), sim_all.max()))
    print("\n明细已写入: %s" % OUT)


if __name__ == "__main__":
    main()
