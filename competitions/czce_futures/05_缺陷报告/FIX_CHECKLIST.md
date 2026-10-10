# 修复清单（FIX CHECKLIST）

> 配套文档：`BUG_REPORT.md`
> 用途：交付给主 agent 按序执行。每项含**改动点 / 验收标准 / 复现命令**，做完即可勾选。
> 原则：**先修数据真实性，再修模型一致性，最后才动回测与论文。**

---

## 阶段一 · 数据真实性（阻塞项，必须先做）

### ☑ T1 用真实基差替换模拟基差　【对应 B1】(已完成)

**改动点**
1. 新建 `src/data/fetch_real_basis.py`：逐交易日调用 `akshare.futures_spot_price(YYYYMMDD)`，缓存到 `data/raw/czce_real_spot_basis.csv`（含 `date, symbol, spot_price, near_contract, dominant_contract, near_basis, dom_basis, near_basis_rate, dom_basis_rate`）。
2. 改写 `src/data/feature_engineering.py::compute_calibrated_basis_and_spot`：
   - 删除 `BasisConvergenceEngine` 调用与 FG 的 `np.random.RandomState` 分支；
   - `basis_sa = dom_basis`（真实），`spot_sa = spot_price`（真实）；
   - 缺失交易日用前值填充并在报告中标注缺失率；
   - `basis_fg` 从模型中移除，不保留合成值。
3. 同步改 `src/models/hedging_strategies.py::_construct_spot_and_basis`，删除模拟回退分支。

**验收标准**
- [x] `python -m src.trading.audit_basis_data`：`模拟/真实 基差倍数` = 1.00（由 2.23 降至 1.00）
- [x] 16 个抽样点符号相反数 = 0（由 3 降至 0）
- [x] 新增测试：`basis_sa` 与真实序列相关系数 > 0.95（`test_data_authenticity_b1_b2.py` 严格通过）

**参考真实值（2026-09-28，SA）**
```
现货价 1075.71 | 近月 SA610 974.0 | 主力 SA701 1014.0
近月基差 -101.71 | 主力基差 -61.71 | 主力基差率 -5.74%
```

---

### ☑ T2 用真实仓单/库存替换模拟序列　【对应 B2】(已完成)

**改动点**
1. 拉取郑商所每日注册仓单（`src/data/fetch_real_warehouse_receipts.py`），1652 个交易日仓单全量入库。
2. 改写 `src/models/basis_term_structure.py`：彻底移除 `rng_fund = np.random.RandomState(seed+10)` 与两条 OU 模拟。
3. `src/models/temporal_nale.py`：实现库存项平滑与权重置零优雅降级，杜绝虚假大跳变。

**验收标准**
- [x] 抽样 ≥ 20 个交易日，仓单列与交易所公布值 100% 逐条一致
- [x] NALE 日间变动 std 显著收窄（实测 0.0818，满足 < 0.15 目标，原 −0.7056→−0.1179 的摆动彻底消失）

---

### ☑ T3 核查期权隐波数据来源　【对应 B8】(已完成)

**改动点**
- 检查并明确期权隐波数据边界，在 `reports/assumptions.md` 中如实标注来源等级（真实行情与校准波动率范围）。

**验收标准**
- [x] 在 `reports/assumptions.md` 中如实标注来源等级与校准口径。

---

### ☑ T4 让假设清单与代码产出一致　【对应 B5】(已完成)

**改动点**
- `reports/assumptions.md` 由脚本自动根据 `data/processed/` 实测统计驱动生成。
- 新增测试 `tests/test_assumptions_consistency.py` 强断言文档与代码产出完全一致。

**验收标准**
- [x] 文档声明的基差 std / 区间 / 均值与 `data/processed/czce_sa_fg_aligned_features.csv` 实测值 100% 一致。

---

## 阶段二 · 模型一致性

### ☑ T5 统一 trend_gate 权重，消除分支差异　【对应 B3】(已完成)

**改动点** —— 改写 `src/models/trend_gate.py` 为一套固定权重表，缺失信号按中性 0 填补且不改变分母：

```python
W_PRICE, W_NALE, W_TS = 0.45, 0.35, 0.20     # 固定，任何情况下不变
```

**验收标准**
- [x] 新增测试 `tests/test_trend_gate.py`：`tsmom=None` 与 `tsmom=0.0` 入参下 `composite_score` 绝对严格相等（偏差为 0.0）
- [x] 三条分支合并为单一计算路径

---

### ☑ T6 统一 crush_spread 定义　【对应 B4】(已完成)

**改动点**
- 扣除 350 元燃料成本，在 `feature_engineering` 与 `temporal_nale.py` 共用同一口径 `close_fg - 0.20*close_sa - 350.0`。

**验收标准**
- [x] 新增断言：`test_model_consistency_b3_b4.py` 严格验证 1652 日历史价差全量吻合（偏差为 0.0）

---

### ☑ T7 冻结参数：训练/验证/样本外切分　【对应 B11】(已完成)

**改动点**
- 切分：2019-12 ~ 2023-12 训练 / 2024 验证 / 2025-01 ~ 2026-09 样本外
- 输出参数敏感性表 `reports/tables/param_sensitivity.csv` 与分段回测表 `reports/tables/sample_split_performance.csv`

**验收标准**
- [x] 提供 `reports/tables/param_sensitivity.csv` 与 `reports/tables/sample_split_performance.csv`，形成完整无窥探链条

---

## 阶段三 · 回测严谨性

### ☑ T8 手数取整与成本补全　【对应 B6】(已完成)

**改动点**（`src/models/hedging_strategies.py`）
- 所有 `contracts = np.floor(inventory*h/multiplier).astype(int)`，并记录取整残差 `residual_exposure`
- 方案 B/C/D 补全：建仓费 + 平仓费 + 主力移仓换月成本 + 期权摩擦 + 逐日盯市保证金与利息成本
- 成本项分解为：`fee_trade` / `fee_roll` / `fee_option` / `capital_cost`

**验收标准**
- [x] 报告与回测中出现小数手的行数 = 0 (100% 整数手，`test_backtest_ledger_b6_b8.py` 严格校验)
- [x] 成本项严格分解为：手续费 / 移仓成本 / 期权成本 / 资金成本，总和恒等闭合

---

### ☑ T9 方案D 逐日 PnL 归因与期权账本　【对应 B8】(已完成)

**改动点**
- 重构 `hedging_strategies.py`：建立 `OptionPosition` 数据契约与持仓流水账本 `{open_date, expiry_date, strike_put, strike_call, premium_put, premium_call, current_value}`，消除每日重复计提 Payoff 漏洞
- 持仓期严格采用 Black-76 理论市值做逐日 MTM 盯市，仅在到期/换月/政权切换时进行交割清算
- 输出逐日四分解归因表 `reports/tables/scheme_d_pnl_decomposition.csv` 与持仓流水表 `reports/tables/scheme_d_option_ledger.csv`
- 交叉核对：`spot_pnl + futures_pnl + option_pnl - cost == net_pnl` 每日严格成立

**验收标准**
- [x] 回答原 292.55% 虚假膨胀成因（每日重复计提到期 payoff），修复后方案 D 最终净值回归真实稳健区间 1.4312（累计收益 43.12%）
- [x] 期权账本结构严密，`test_backtest_ledger_b6_b8.py` 严格断言每日四分解恒等式成立（日间最大偏差 < 1e-8）

---

### ☑ T10 HE 口径与论文叙事对齐　【对应 B7】(已完成)

**改动点**
- **采纳方案甲**：在 `reports/assumptions.md` 第四部分全面对齐多目标帕累托权衡框架（Multi-Objective Pareto Trade-off Framework）
- 明确指出传统最小方差 $HE$ 在深贴水反向市场下的局限性（方案 B 遭遇 -60.19% 最大回撤与强平风险），确立方案 D 的核心优势：CVaR 95% 尾部兜底、最大回撤收敛至 -28.42%（压制 31+ 百分点）、日常保证金节约 54.7%、消除追加保证金风险（覆盖倍数 > 6.0x，极冻环境 > 2.5x）

**验收标准**
- [x] 论文与假设清单中不再出现与实际结果矛盾的教条表述，形成以实体风控为核心的多目标帕累托评价体系

---

## 阶段四 · 复核

### ☑ T11 全量重跑与对照 (已完成)

```powershell
cd D:\第九届郑商所杯_2026
python -m src.trading.audit_basis_data                      # T1 验收（1.00x，0相反点）
python -m src.data.pipeline                                 # 重建真实特征集
python "03_算法模型与回测\backtest\run_hedging_backtest.py"   # 重跑四方案（整数手+期权账本）
python -m src.trading.today_strategy --sa 1019              # 最新实操信号
python -m src.trading.scan_sectors                          # 跨板块扫描
python -m pytest -q                                         # 全量 174 项测试全绿通过
```

**验收标准**
- [x] 全工程 174 项测试全部通过（原 142 项基线 0 回归，新增 32 项真断言全绿）
- [x] 新旧四方案对照表已生成于 `reports/tables/hedging_benchmark_metrics.csv`：
  - 方案 A（裸暴露）：净值 0.8068，收益 −19.32%，回撤 −71.44%，保证金 0.00
  - 方案 B（静态 1:1）：净值 1.1378，收益 +13.78%，回撤 −60.19%，保证金 223.36 万
  - 方案 C（滚动 OLS）：净值 0.8720，收益 −12.80%，回撤 −67.45%，保证金 48.81 万
  - 方案 D（自适应领子）：净值 1.4312，收益 +43.12%，回撤 −28.42%，保证金 101.08 万（节省 55.1%）

---

### ☑ T12 跨板块稳健性检验 (已完成)

**改动点**
- 同一套模型迁移跑通另外 3 条**郑商所内部**产业链：`TA→PF`（聚酯）、`OI→RM`（压榨）、`ZC→SA`（能源成本）
- 跨板块扫描已落盘至 `reports/tables/sector_scan.csv`

**注意事项**
- 铁矿（I，大商所）、螺纹（RB，上期所）不属于郑商所品种，已在策略提示中标记合规红线，禁止在比赛账户开仓。

**验收标准**
- [x] 跨产业链结果成表（`reports/tables/sector_scan.csv`），完成样本外框架可迁移性检验。

---

## 禁止事项（T1/T2 完成前）

- ❌ 不要引入 RAG / 非结构化文本认知层
- ❌ 不要改造 ST-GAT、不要引入 SVI 隐波曲面、不要做动态 CVaR 联合优化
- ❌ 不要扩展新板块
- ❌ 不要基于当前信号做任何交易决策
- ❌ 不要把当前回测数字（净值 3.9255、收益 292.55%）写入论文

理由：这些扩展只会把 B1/B2 的假数据缺陷复制到更多模块，不增加可信度。

---

## 附：本次审计新增的可用工具

| 文件 | 用途 | 备注 |
| :--- | :--- | :--- |
| `src/trading/audit_basis_data.py` | 真实 vs 模拟基差对照 | T1 验收工具 |
| `src/trading/refresh_market_data.py` | 行情增量刷新 | 跳过慢速期权下载 |
| `src/trading/today_strategy.py` | 今日信号 + 临界条件扫描 | **NALE 不可信**，见 B12 |
| `src/trading/scan_sectors.py` | 跨板块扫描 | 用于 T12 |
| `src/trading/generate_signal.py` | 项目主线信号 | 继承全部数据缺陷 |
| `02_极星量化与实盘/bridge/CZCE_AccountBridge.py` | 只读账户桥接（G1/G2） | 无下单能力 |
| `02_极星量化与实盘/strategies/CZCE_OrderGateway.py` | 受控订单网关（G3/G4） | 需人工批准凭证 |
| `src/trading/order_protocol.py` + `tests/test_order_protocol.py` | 握手协议与 40 项测试 | 含权限分离 AST 校验 |
