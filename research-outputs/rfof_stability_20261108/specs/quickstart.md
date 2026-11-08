# 快速开始

## 前置
- Python 3.13、pandas、numpy、scipy、scikit-learn、matplotlib、pytest。
- 输入数据只读:`scratch/etf_hist/`、`Rainbow_FinGPTv2/data/raw/`。

## 已可运行(第 1 步)
```powershell
python R-FOF/tools/stability_etf_audit.py
```
预期:打印 17 只 ETF 审计表;`n_outlier_ret` 为 0 的品种可进入候选池。

## 完整研究(实现后)
```powershell
python R-FOF/tools/run_stability_study.py --out R-FOF/reports/stability_20261110
python -m pytest R-FOF/tests -k stability -q
```

## 验收场景
1. 审计表中 512010、510500、512100 的异常日被识别,候选池拒绝加载并报出日期。
2. B0 与 `precomputed_core_returns.csv` 的 `r_futures_hedge` 逐日一致。
3. 追加一段未来数据,历史再平衡权重不变。
4. HRP 在 3 资产小样本上与手算结果一致;LW 最小方差权重非负且和为 1。
5. 构造一个在所有窗口都更差的方法,判定输出 `no_significant_improvement`。
6. 输出目录已存在时,程序报错退出且不修改任何文件。
