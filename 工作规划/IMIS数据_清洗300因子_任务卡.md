# IMIS数据 - 清洗300支因子任务卡

## 🎯 任务
用CSMAR数据验证并清洗 factors.csv

## 📂 数据位置
- **原始数据**: `data/raw/backtest_paper_2024_2026_300stocks/factors.csv`
- **CSMAR数据**: `data/school_factors/csmar_carhart_4factors.csv`

## 🔑 关键结论
**因子值已经和CSMAR完全一致**，你只需要做格式化：
1. 把 "Unnamed: 0" 改成 "TradingDate"
2. 验证MKT←RiskPremium1、SMB←SMB1等映射
3. 保存清洗版到 `data/week1_pca/factors_clean.csv`

## 🚀 运行命令
```bash
python scripts/clean_300_factors_with_csmar.py
```

## ⏱ 预计耗时：30分钟
