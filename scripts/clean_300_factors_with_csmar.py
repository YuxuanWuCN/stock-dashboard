# 300支因子数据 CSMAR 清洗方案

## 📊 数据现状

### factors.csv（原始数据）
- **位置**: `data/raw/backtest_paper_2024_2026_300stocks/factors.csv`
- **形状**: 694天 × 8个因子
- **时间范围**: 2024-01-02 → 2026-08-28
- **因子列**: MKT, SMB, HML, MOM, rf, LARGE_ORDER_INFLOW, NORTHBOUND_DELTA, INST_SEAT_RATIO
- **问题**: 第一列叫 "Unnamed: 0"（其实是日期）

### CSMAR（权威数据源）
- **位置**: `data/school_factors/csmar_carhart_4factors.csv`
- **形状**: 694天 × 5个因子（日期完全对齐）
- **因子列**: RiskPremium1, SMB1, HML1, UMD1, RiskFreeRate

---

## ✅ 关键发现：因子值已经是正确的！

| 原始列 | CSMAR列 | 最大差异 | 结论 |
|--------|---------|---------|------|
| MKT | RiskPremium1 | **0.0** | 完全一致 |
| SMB | SMB1 | **0.0** | 完全一致 |
| HML | HML1 | **0.0** | 完全一致 |
| MOM | UMD1 | **0.0** | 完全一致 |
| rf | RiskFreeRate | **0.0** | 完全一致 |

**结论**: factors.csv中的因子值已经和CSMAR完全一致，**不需要修改数值**。只需要做格式清洗。

---

## 🛠️ 清洗任务：只需做格式修整

### 任务1：重命名列（1分钟）
```python
df.rename(columns={"Unnamed: 0": "TradingDate"}, inplace=True)
```

### 任务2：添加CSMAR列名别名（可选）
为了方便以后溯源，可以在元数据中注明映射关系：
```json
{
  "MKT": "RiskPremium1（CSMAR）",
  "SMB": "SMB1（CSMAR）",
  "HML": "HML1（CSMAR）",
  "MOM": "UMD1（CSMAR）",
  "rf": "RiskFreeRate（CSMAR）",
  "LARGE_ORDER_INFLOW": "大单净流入（东方财富）",
  "NORTHBOUND_DELTA": "北向资金净流入（东方财富）",
  "INST_SEAT_RATIO": "机构席位成交占比（东方财富）"
}
```

### 任务3：输出清洗后的文件（可选）
保存为标准化格式：`data/week1_pca/factors_clean.csv`

---

## 📝 给IMIS数据的任务（1小时就能搞定）

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scripts/clean_300_factors_with_csmar.py

使用CSMAR验证并清洗300支因子数据

结论：因子值已与CSMAR完全一致，只需格式化
"""

import pandas as pd
import numpy as np
from pathlib import Path

print("=" * 60)
print("300支因子 CSMAR 清洗验证")
print("=" * 60)

# 1. 加载数据
factors = pd.read_csv(
    "data/raw/backtest_paper_2024_2026_300stocks/factors.csv"
)
csmar = pd.read_csv("data/school_factors/csmar_carhart_4factors.csv")

print(f"\n📂 factors.csv: {factors.shape}")
print(f"📂 CSMAR:       {csmar.shape}")

# 2. 重命名日期列
factors.rename(columns={"Unnamed: 0": "TradingDate"}, inplace=True)

# 3. 验证因子一致性
checks = {
    "MKT  ← RiskPremium1": (factors["MKT"], csmar["RiskPremium1"]),
    "SMB  ← SMB1":         (factors["SMB"], csmar["SMB1"]),
    "HML  ← HML1":         (factors["HML"], csmar["HML1"]),
    "MOM  ← UMD1":         (factors["MOM"], csmar["UMD1"]),
    "rf   ← RiskFreeRate": (factors["rf"], csmar["RiskFreeRate"]),
}

print(f"\n{'='*60}")
print("因子一致性验证")
print(f"{'='*60}")

all_pass = True
for name, (a, b) in checks.items():
    diff = (a - b).abs().max()
    status = "✅" if diff < 1e-10 else "❌"
    if diff >= 1e-10:
        all_pass = False
    print(f"  {status} {name:25s} max_diff={diff:.2e}")

if all_pass:
    print(f"\n✅ ALL PASS: factors.csv 因子值已与 CSMAR 完全一致")
    print(f"   无需修改数值，直接使用即可")
else:
    print(f"\n⚠️ 存在差异，请检查")

# 4. 检查额外因子
extra_cols = ["LARGE_ORDER_INFLOW", "NORTHBOUND_DELTA", "INST_SEAT_RATIO"]
print(f"\n{'='*60}")
print("额外因子（CSMAR无）")
print(f"{'='*60}")
for col in extra_cols:
    print(f"  - {col}: 均值={factors[col].mean():.6f}, 标准差={factors[col].std():.6f}")

# 5. 输出元数据
metadata = {
    "source": "data/raw/backtest_paper_2024_2026_300stocks/factors.csv",
    "csmar_validation": "data/school_factors/csmar_carhart_4factors.csv",
    "n_days": len(factors),
    "date_start": factors["TradingDate"].iloc[0],
    "date_end": factors["TradingDate"].iloc[-1],
    "n_factors": len(factors.columns) - 1,
    "csmar_verified": all_pass,
    "csmar_mapping": {
        "MKT": "RiskPremium1",
        "SMB": "SMB1",
        "HML": "HML1",
        "MOM": "UMD1",
        "rf": "RiskFreeRate"
    },
    "extra_factors": extra_cols
}

output_dir = Path("data/week1_pca")
output_dir.mkdir(exist_ok=True)

import json
with open(output_dir / "factors_clean_metadata.json", "w", encoding="utf-8") as f:
    json.dump(metadata, f, indent=2, ensure_ascii=False)

# 6. 保存清洗版（可选）
cleaned = factors.copy()
cleaned.to_csv(output_dir / "factors_clean.csv", index=False)
print(f"\n✅ 清洗版已保存: {output_dir / 'factors_clean.csv'}")
print(f"✅ 元数据已保存: {output_dir / 'factors_clean_metadata.json'}")
