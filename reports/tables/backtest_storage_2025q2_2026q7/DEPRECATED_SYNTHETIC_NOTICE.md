# ⚠️ 废弃警告：存储全产业链回测产物全量作废 (DEPRECATED SYNTHETIC ARTIFACT)

> **目录位置**：`reports/tables/backtest_storage_2025q2_2026q7/`  
> **涉及核心文件**：`metrics_summary.md`、`data/raw/backtest_storage_2025q2_2026q7/` 及 `docs/data/quantitative/backtest_storage_2025q2_2026q7.json`  
> **作废类型**：依赖静默合成价格、Brier 硬编码及造假指标的半导体存储回测产物  
> **详细总账索引**：详见项目主作废审计文件 `reports/DEPRECATED_SYNTHETIC.md`（§二.3）

---

## 1. 作废原因与技术证据

1. **休市日与合成指纹**：底层价格数据 `data/raw/backtest_storage_2025q2_2026q7/market_prices.csv` 包含 349 天，含 14 个以上 A 股法定节假日休市日；超额峰度仅 +0.025，|r| 一阶自相关仅 +0.0036，三指纹判真完全失败。回测执行器 `src/analysis/storage_backtest_runner.py:112-132` 在缺标的时用 `np.random.seed(42)` + `np.random.normal(...)` 静默生成价格。
2. **核心指标造假与兜底常量**：
   - **Brier 分数**：`src/strategies/storage_supercycle_backtest.py:541-542` 在无预测对时硬编码兜底常量 `brier_score = 0.185`，全周期有效预测样本数为 0，0.185 从未真实计算得出；
   - **Alpha 门控假数据放行**：`storage_supercycle_backtest.py:358-362` 数据不足时注入 `alpha_val=0.0015, ir_val=0.45*sqrt(252)` 兜底伪造超额；门控判定放宽至 `p < 0.20 or alpha > 0`；
   - **Harvey t 统计量偷换概念**：`t = 3.665 (p < 0.01)` 为单策略日收益均值的普通 t 检验，既未做多重检验校正，亦未调整序列相关性，硬编码 `p < 0.01`；
   - **口径混用不可自洽**：表内几何年化收益（134.56%）与日频算术夏普比率（3.916）混用且未披露口径，读者用年化收益/年化波动复算得到 6.09，偏差高达 55.5%。
3. **衍生宣称漂移与虚构**：对外宣传的 `+490.79%`、`+159.01%` 及 `夏普 4.627` 无法溯源到任何可复现产物，系误将中间交易日净值点（如 2025-09-11 净值 1.5901）或 ETF 单点净值当成累计指标。

---

## 2. 替代指引

- 该目录指标数据已全量作废，严禁用于论文论证或产品宣传；
- 存储板块真实表现若无充分真实数据支撑，将在学术成果中坦诚披露局限，统一参考 `reports/real_rebuild_20261010/`。
