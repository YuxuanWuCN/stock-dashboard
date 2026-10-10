# 缺陷报告：第九届郑商所杯 纯碱/玻璃动态套保课题

**报告日期**：2026-09-29
**审计范围**：`src/`、`02_极星量化与实盘/`、`data/`、`reports/`（全量代码 + 产出物）
**审计方法**：静态代码审计 + 实际运行复现 + 与交易所公开真实数据交叉验证
**复现环境**：项目根目录 `D:\第九届郑商所杯_2026`，Python 3.13，akshare 1.18.64

---

## 0. 执行摘要

| 编号 | 严重度 | 缺陷 | 是否已复现 |
| :--- | :--- | :--- | :--- |
| B1 | **致命** | 基差/现货序列由随机过程**模拟**生成，却宣称是实测校准数据 | ✅ 已复现 |
| B2 | **致命** | 库存与仓单序列同为随机模拟，且直接进入 NALE 信号 | ✅ 已复现 |
| B3 | **严重** | `trend_gate` 权重在两条分支里不一致，导致同数据信号相反 | ✅ 已复现 |
| B4 | 中 | `crush_spread` 未扣燃料成本，与模型注释及 `temporal_nale` 内部定义矛盾 | ✅ 已复现 |
| B5 | 中 | `assumptions.md` 声称的参数与代码实际产出不符 | ✅ 已复现 |
| B6 | 中 | 回测存在手数未取整、平仓/移仓成本缺失 | ✅ 已复现 |
| B7 | 中 | HE 指标低于论文自设目标，且方案D 未优于基准 | ✅ 已复现 |
| B8 | 中 | 方案D 累计收益 292.55% 未做逐日归因，期权账本不闭合 | ⚠️ 待归因 |
| B9 | 轻 | 部署路径文档与实际安装不符（**已修复**） | ✅ 已修 |
| B10 | 轻 | 旧实盘策略规模换算错误（**已退役**） | ✅ 已修 |
| B11 | 轻 | 全部模型参数为手工设定，无估计与样本外冻结 | ✅ 已确认 |
| B12 | 提示 | 本次审计新增工具自身的已知近似 | — |

**核心结论**：模型的三条核心输入中，**有两条（基差、库存/仓单）是随机模拟数据**。因此 Trend Gate 的门控判定、TSMOM 期限结构动量、产业链挤压信号 NALE，都在对一个随机数序列做反应。这不是"精度不够"，是**输入与结论之间没有真实的因果关系**。

**建议顺序**：先修 B1、B2（数据真实性），再修 B3（权重一致性），然后重跑 B7、B8 相关回测。**在 B1/B2 修复前，不要基于当前信号做任何交易决策，也不要把当前回测数字写进论文。**

---

## B1【致命】基差与现货序列是随机模拟，非实测数据

### 位置
- `src/models/basis_term_structure.py:354-429` — `BasisConvergenceEngine.simulate_dynamic_basis`
- `src/data/feature_engineering.py:189-256` — `compute_calibrated_basis_and_spot`

### 证据

`basis_term_structure.py:410-416`：
```python
rng_sa = np.random.RandomState(seed)          # ← 随机数发生器
...
db = lambda_arr[i] * (mu_sa[i] - basis_sa[i-1]) + sigma_sa * rng_sa.normal(0, 1)
...
basis_sa = np.clip(basis_sa, -1400.0, 250.0)
```

`basis_term_structure.py:404-405`：
```python
cyclical_sa = 280.0 * np.sin(2.0 * np.pi * t / 120.0)   # ← 人为正弦波
mu_sa = -525.04 + cyclical_sa                            # ← 硬编码目标均值
```

`feature_engineering.py:226-243` 玻璃基差同样是纯合成：
```python
rng_fg = np.random.RandomState(random_seed + 1)
cyclical_fg = 120.0 * np.sin(2.0 * np.pi * t / 120.0 + np.pi / 4.0)
basis_fg[i] = basis_fg[i-1] + theta_fg * (mu_fg[i] - basis_fg[i-1]) + sigma_fg * rng_fg.normal(0, 1)
spot_fg = np.maximum(f_fg - basis_fg, 900.0)
```

而 `feature_engineering.py:198` 的函数文档与 `reports/assumptions.md:14-16` 都称其为：
> "根据郑商所 2023–2026 年**实际采样数据**校准"

**期货收盘价（`close_sa` / `close_fg`）是真的**（来自 akshare `futures_main_sina`）。
**基差、现货价、仓单、库存四个字段是模拟的。**

### 实测偏差（复现命令：`python -m src.trading.audit_basis_data`）

真实数据源：`ak.futures_spot_price(date)`（交易所口径现货价与基差）。抽样 16 个交易日：

| 日期 | 真实主力基差 | 项目模拟基差 | 问题 |
| :--- | ---: | ---: | :--- |
| 2020-11-05 | −672.00 | −555.38 | 偏差 |
| 2021-04-19 | **+68.00** | −456.08 | **符号相反** |
| 2021-09-28 | **+90.00** | −578.47 | **符号相反** |
| 2022-03-16 | −397.00 | −660.74 | 偏差 |
| 2022-08-25 | −468.67 | −374.20 | 偏差 |
| 2023-02-13 | −17.33 | −189.68 | 夸大 11 倍 |
| 2023-07-26 | −41.33 | −149.22 | 夸大 3.6 倍 |
| 2024-01-05 | **−900.00** | −348.96 | 严重低估 |
| 2024-06-25 | −202.00 | −396.21 | 偏差 |
| 2024-12-05 | −252.00 | −633.35 | 夸大 2.5 倍 |
| 2025-05-23 | −209.50 | −654.72 | 夸大 3.1 倍 |
| 2025-11-04 | −14.57 | −603.96 | 夸大 41 倍 |
| 2026-04-20 | **+6.29** | −812.87 | **符号相反** |
| 2026-09-28 | −61.71 | −449.50 | 夸大 7.3 倍 |

汇总：

| 指标 | 真实 | 项目模拟 | 倍数 |
| :--- | ---: | ---: | ---: |
| 主力基差均值 | −219.42 | −490.24 | **2.23×** |
| 基差率均值 | −9.53% | −21.99% | 2.31× |
| 现货价均值 | 2138.27 | 2409.10 | — |

明细见 `reports/tables/basis_real_vs_simulated.csv`。

### 影响面
1. **论文核心前提**："纯碱期货长期深贴水 500 元/吨以上、极端 −1400" 是模拟出来的。真实情况是均值 −219、基差率 −9.5%，且历史上多次出现**升水**。"深贴水导致静态套保巨亏"这一立论缺乏真实依据。
2. **TSMOM 期限结构动量**由基差派生 → 数值不可信（当前 `tsmom_sa = −0.4762`，真实 9/28 基差率仅 −5.74%，属温和贴水）。
3. **Trend Gate 的"主动防御"机制**以 `tsmom < −0.2` 为触发 → 在对假数据做反应。
4. **回测 方案D 收益**部分来源于对假基差的反应。

### 修复方案
用交易所公开数据替换整条模拟路径：

```python
import akshare as ak          # 已验证可用，可回溯至 2020 年
real = ak.futures_spot_price("20260928")
# 返回字段：date, symbol, spot_price, near_contract, dominant_contract,
#          near_basis, dom_basis, near_basis_rate, dom_basis_rate
# SA 行示例：spot 1075.71, SA610 974.0, SA701 1014.0,
#           近月基差 -101.71, 主力基差 -61.71, 主力基差率 -5.74%
```

改造要点：
- 逐交易日拉取真实 `spot_price` / `dom_basis` / `dom_basis_rate`，缓存到 `data/raw/`
- `compute_calibrated_basis_and_spot` 改为"真实数据读取 + 缺失日插值"，删除 `RandomState` 与正弦波
- 真实基差率与论文叙述冲突的部分，**修订论文而非修订数据**

### 验收标准
- `python -m src.trading.audit_basis_data` 输出的"模拟/真实 基差倍数"应 ≈ 1.00
- 16 个采样点中符号相反数应为 0
- `tests/` 中新增断言：`basis_sa` 与真实值相关系数 > 0.95

---

## B2【致命】库存与仓单序列同为随机模拟，且直接进入 NALE

### 位置
- `src/models/basis_term_structure.py:372-393`

### 证据
```python
if warehouse_receipts is None or inventory is None:
    rng_fund = np.random.RandomState(seed + 10)                    # ← 随机
    ...
    d_wr = 0.05 * (6000.0 + seas_wave - wr_arr[i-1]) + 150.0 * rng_fund.normal(0, 1)
    wr_arr[i] = np.clip(wr_arr[i-1] + d_wr, 1000.0, 20000.0)       # ← 仓单模拟
    ...
    d_inv = 0.04 * (75.0 - inv_arr[i-1]) + 1.2 * rng_fund.normal(0, 1)
    inv_arr[i] = np.clip(inv_arr[i-1] + d_inv, 30.0, 180.0)        # ← 库存模拟
```

### 影响面（实测）
`src/models/temporal_nale.py:414-418` 中，库存以 **40% 权重**进入 divergence：
```python
norm_inv = np.clip(-inv_diff.values / inv_std.values, -3.0, 3.0)
div = 0.6 * norm_spread + 0.4 * norm_inv
```
库存序列只要发生微小变化，NALE 就大幅摆动。实测同一个 9/28：

| 口径 | NALE 值 |
| :--- | ---: |
| 含模拟库存（项目流水线） | −0.7056 |
| 不含库存（仅价差） | −0.6439 |
| 库存顺延一日 | **−0.1179** |

**仅因库存差分变为 0，NALE 从 −0.71 跳到 −0.12。** 该信号不具备稳定性。

### 修复方案
郑商所每日公布注册仓单日报，可用 akshare 获取真实序列（如 `ak.futures_inventory_em` 或交易所公开接口）；行业库存可用第三方周度数据（隆众/卓创）或改为不使用库存项，并把 `div = norm_spread` 作为唯一口径。

### 验收标准
- 库存/仓单列与真实公布值一致（抽样核对 ≥ 20 个交易日）
- NALE 在相邻两日的变动幅度分布应显著收窄（建议：日间变动 std < 0.15）

---

## B3【严重】`trend_gate` 权重在两条分支中不一致，导致同数据信号相反

### 位置
`src/models/trend_gate.py:74-107`

### 证据
```python
if tsmom_signals is not None:
    w_price = max(0.0, 1.0 - w_ts - w_nale)     # 0.45（三信号齐全）
    composite_score = w_price*trend + w_nale*max(nale,0) + w_ts*max(tsmom,0)
    ...
else:                                            # 无 tsmom 分支
    w_price = max(0.0, 1.0 - w_ts)              # 0.65（权重凭空变化）
    composite_score = w_price*trend + w_ts*max(tsmom,0)
...
    # 再下一层（连 tsmom 都没有时）
    composite_score = (1.0 - self.nale_weight)*trend + self.nale_weight*max(nale,0)   # 0.65
```

**同一份数据、同一天、同一个模型，只因为是否传入 TSMOM，结论相反：**

| 口径 | Z | 状态 | 动作 |
| :--- | ---: | :---: | :--- |
| 带 TSMOM（项目主线） | 0.343 | 0 | **观望** |
| 不带 TSMOM | 0.650 | 1 | **做空 95%** |

复现命令：
```powershell
python -m src.trading.today_strategy --sa 1017   # 带 TSMOM → 观望
python -m src.trading.scan_sectors                # 不带 TSMOM → 做空
```

### 修复方案
统一权重表，缺失信号按"中性 = 0"处理，**不允许改变分母**：
```python
W_PRICE, W_NALE, W_TS = 0.45, 0.35, 0.20     # 固定表
trend = ...                                   # 价格项
nale  = 0.0 if nale_signals is None else clip(nale, -1, 1)
ts    = 0.0 if tsmom_signals is None else clip(ts, -1, 1)
raw = W_PRICE*trend + W_NALE*max(nale,0) + W_TS*max(ts,0)
```

### 验收标准
- 新增单元测试：传入 `tsmom=None` 与传入 `tsmom=0.0`，得到的 `composite_score` 必须完全相等
- 三个分支合并为一条计算路径

---

## B4【中】`crush_spread` 未扣燃料成本，与模型内部定义矛盾

### 位置
- 流水线定义：`src/data/feature_engineering.py:133-158`（`compute_commodity_spreads`）
- 模型定义：`src/models/temporal_nale.py:453`
- 取值优先级：`src/models/temporal_nale.py:405-408`

### 证据
CSV 实际产出（2026-09-28）：`crush_spread = 690.2`
按模型注释应为：`893 − 0.20×1014 − 350 = 340.2`

`temporal_nale.py:405-408` 优先使用 df 中已存在的列：
```python
if "crush_spread" in df.columns:
    spread = df["crush_spread"].values        # ← 用的是流水线版本（未减燃料）
else:
    spread = p_fg - 0.20 * p_sa - fuel        # ← 模型自身定义（减了 350）
```
因此实际运行使用的是"未减燃料"版本，与 `temporal_nale.py:453` 的 `crush_spread = p_fg - 0.20*p_sa - fuel` 不一致。

### 修复方案
明确唯一口径并在两侧共用同一函数；在 `tests/` 中加断言，确保 CSV 列与模型内部计算一致。

---

## B5【中】`assumptions.md` 与代码实际产出不符

### 证据
| 项 | `reports/assumptions.md:16` 声称 | 代码实际产出 |
| :--- | ---: | ---: |
| 基差标准差 | 486.90 | **171.38** |
| 基差区间 | [−1434.3, +238.7] | **[−935.82, −9.16]** |
| 基差均值 | −525.04 | −492.95 |

代码 clip 边界为 `[-1400.0, 250.0]`（`basis_term_structure.py:416`），与文档声称的极值也对不上。**假设文件与自己产出的数据自相矛盾。**

### 修复方案
把假设清单改为**由代码产出自动生成**（如 `reports/tables/` 输出实测统计），或在测试中断言文档与产出一致。人工维护的假设表必须有校验。

---

## B6【中】回测手数未取整、平仓与移仓成本缺失

### 位置
`src/models/hedging_strategies.py`

### 证据
```python
# 方案B（L106）
contracts = (self.inventory_tons * h) / self.multiplier        # 10000*1/20 = 500.0，恰好整数
# 方案C（L144）
contracts = (self.inventory_tons * h_star) / self.multiplier   # h_star 连续 → 出现小数手
# 方案D（L201）
contracts = (self.inventory_tons * dynamic_h) / self.multiplier # 10000*0.25/20 = 125，整数；
                                                                # 但 h 非 0.25/0.95 时会出小数
```
真实期货无法交易 0.35 手。

```python
# 方案B（L114-116）手续费仅在首日计一次
cost = pd.Series(0.0, index=res.index)
cost.iloc[0] = contracts * self.multiplier * p_fut.iloc[0] * self.commission_rate
cost += capital_cost
```
无平仓手续费、无移仓换月成本、无期权交易成本。

### 修复方案
1. 手数 `np.floor()` 取整，并记录取整导致的敞口残差；
2. 补平仓手续费与移仓成本（主力换月时）；
3. 保证金按日盯市重算。

---

## B7【中】HE 指标低于论文自设目标

### 证据
`reports/tables/hedging_benchmark_metrics.csv`：

| 方案 | 最终净值 | 累计收益 | HE | 最大回撤 | 年化波动 | 平均保证金 |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| A 裸暴露 | 0.7003 | −29.97% | 0 | −71.33% | 41.25% | 0 |
| B 静态 1:1 | 0.9459 | −5.41% | 67.46% | −37.92% | 28.23% | 223.42 |
| C 滚动 OLS | 1.0385 | 3.85% | **68.15%** | −40.00% | 27.26% | 227.96 |
| D 门控+领子 | 3.9255 | **292.55%** | **58.30%** | −21.22% | 15.60% | 112.62 |

`01_研究计划与论文/郑商所杯_研究计划书_申报稿.md:127` 声称：
> 目标：使动态套保组合方差较未对冲头寸降低 **70% 以上**，显著超越传统 OLS 静态套保

实际：方案D 的 HE（58.30%）**低于**方案B（67.46%）与方案C（68.15%），且未达 70%。

### 修复方案（二选一）
- **改叙事**：明确方案D 的目标是多目标权衡（尾部风险 + 保证金占用 + 交易成本），不以 HE 单独排序；补充 CVaR、强平次数、保证金峰值等指标支撑这一说法。
- **改模型**：若坚持 HE 目标，需重新设计权重与状态切换。

---

## B8【中】方案D 收益未归因，期权账本不闭合

### 证据
方案D 累计收益 292.55%（净值 3.9255），对一个"套期保值"策略异常偏高。`src/models/hedging_strategies.py:220-248` 的期权部分实现方式为：

```python
for i in range(len(self.df)):
    if tg_vals[i] == 0:
        col_res = self.collar_engine.compute_adaptive_collar(spot_price=s_prev, iv=iv_vals[i], skew=skew_vals[i])
        payoff_ton = self.collar_engine.compute_collar_payoff(s_curr, col_res.strike_put, col_res.strike_call)
        collar_ton_pnl[i] = unh_frac * payoff_ton
```

**每个交易日都按当日价重新计算一次 payoff**，没有开仓日 / 持有期 / 到期日账本。需要核实：
1. 是否存在逐日重复计提期权收益；
2. `iv_atm_sa` / `collar_skew_sa` 是否也是合成数据（`feature_engineering.py:259` 的 `extract_or_synthesize_option_iv` 名称中的 "synthesize" 提示需核查）；
3. 期权权利金是否计入成本（当前 `cost` 只含期货手续费与资金成本）。

### 修复方案
建立逐日账本：`{开仓日, 到期日, 行权价, 权利金支出, 每日盯市价值, 到期结算}`，并输出 PnL 四分解（现货 / 期货 / 期权 / 成本）表。

**在归因完成前，292.55% 这个数字不应出现在论文中。**

---

## B9【轻，已修复】部署路径与文档不符

`EPOLESTAR_LIVE_MANUAL.md:24` 称部署在 `%APPDATA%\Epolestar000450v9.5\...`（该路径不存在）。
实际机器上有**两个安装**：

| 路径 | 状态 |
| :--- | :--- |
| `C:\Users\ASUS\AppData\Roaming\Epolestar000450v9.5\` | **桌面快捷方式指向、实际运行中**（`class SSLForm`，标题"郑商杯 v19.5"） |
| `D:\Epolestar000450v9.5\` | 另一份副本，最后运行 2026-09-25 |

两处 `Quant\Editor\api\base_api.py` SHA256 相同，API 结论不受影响。

**已修复**：新策略已部署到真实运行的安装；该文档已由 `LOAD_STRATEGY_GUIDE.md` 取代。

---

## B10【轻，已退役】旧实盘策略规模换算错误

`strategies/_deprecated/CZCE_TemporalTrendGate_LiveStrategy.py`：
```python
full_exposure_lots = int(round(g_params['PhysicalInventoryTons'] / g_params['ContractMultiplier']))  # 10000/20 = 500 手
target_short_lots = int(round(target_hedge_ratio * full_exposure_lots))    # 25%→125手, 95%→475手
...
SellShort(lots_diff, current_price)     # 官方签名为 7 个参数，此处缺 5 个
```

按纯碱 1500 元/吨、20 吨/手、保证金 12% 估算：125 手需约 **45 万元**保证金，475 手约 **171 万元**。比赛模拟账户极可能直接触发追保。

官方签名（`base_api.py:1428`）：
```python
def SellShort(self, orderQty, orderPrice, contractNo, userNo, coverFlag, hedge):
```

**已处理**：该文件已从**两个**客户端安装的策略目录移出至 `strategies/_deprecated/`，并由只读桥接 `CZCE_AccountBridge.py` + 受控网关 `CZCE_OrderGateway.py` 取代。

---

## B11【轻】全部模型参数为手工设定

以下参数无估计过程、无样本外选择（`src/models/trend_gate.py`、`src/models/temporal_nale.py`）：

| 参数 | 值 | 来源 |
| :--- | :--- | :--- |
| `fast_span` / `slow_span` | 20 / 60 | 手工 |
| `hysteresis_window` | 3 | 手工 |
| `nale_weight` / `tsmom_weight` | 0.35 / 0.20 | 手工 |
| 触发阈值 | 0.50 | 手工 |
| 对冲比例 | 0.25 / 0.95 | 手工 |
| `sa_to_fg_lag` / `sa_half_life` | 18.0 / 25.0 | 手工 |
| 不对称核 `tau_up/tau_down/...` | 10/28/14/35 | 手工 |

答辩风险：评委必问"这些数怎么来的"。修复方式：训练期网格搜索 + 验证期冻结 + 样本外测试，并在论文中报告敏感性。

---

## B12【提示】本次审计新增工具的已知近似

以下为本报告作者新增的工具，本身存在已知局限，**不应用于决策**，列出以免误用：

| 文件 | 已知限制 |
| :--- | :--- |
| `src/trading/today_strategy.py` | 把实时价追加为"今日行"时，库存/仓单/基差等非价格特征只能顺延，会显著扰动 NALE（实测 −0.7056 → −0.1179）。**该脚本输出的 NALE 不可信**，仅价格项与均线可用。 |
| `src/trading/scan_sectors.py` | 统一禁用 TSMOM 以便横向比较，故与项目主线口径不同（这正是发现 B3 的方式）。`菜油→菜粕` 的加工系数为经验近似。 |
| `src/trading/audit_basis_data.py` | 抽样 16 个交易日，为抽样对照而非全样本比对。 |
| `src/trading/generate_signal.py` | 直接读取现有 CSV，继承 B1–B5 全部缺陷。 |

---

## 附：复现命令清单

```powershell
cd D:\第九届郑商所杯_2026

# 1. 真实 vs 模拟基差对照（B1）
python -m src.trading.audit_basis_data
# 产出：reports/tables/basis_real_vs_simulated.csv

# 2. 行情增量刷新（含 9/28 之前缺口）
python -m src.trading.refresh_market_data

# 3. 重建特征数据集
python -m src.data.pipeline

# 4. 今日信号（注意 B12：NALE 不可信）
python -m src.trading.today_strategy --sa 1017

# 5. 跨板块扫描（B3 的复现路径）
python -m src.trading.scan_sectors
# 产出：reports/tables/sector_scan.csv

# 6. 四方案回测（B6/B7/B8）
python "03_算法模型与回测\backtest\run_hedging_backtest.py"
# 产出：reports/tables/hedging_benchmark_metrics.csv

# 7. 全量测试
python -m pytest -q
```

---

## 附：不要做的事

在 B1/B2 修复前，**不建议**继续扩展以下内容 —— 它们只会把同一批假数据缺陷复制到更多地方，不增加任何可信度：

- ❌ 引入 RAG / 非结构化文本认知层
- ❌ 把静态规则式图注意力改造成真正训练的 ST-GAT
- ❌ 引入 SVI 隐波曲面与动态 CVaR 联合优化
- ❌ 扩展到更多板块（可先记录方案，修复后再执行）

**修复数据真实性 → 重跑回测 → 再谈模型升级**，这个顺序不能颠倒。
