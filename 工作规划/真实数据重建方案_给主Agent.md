# 真实数据重建方案（交主 Agent 执行）

> 起草：2026-10-10。依据：人工核查 + A2 审计（`D:\股票分析项目\scratch\audit_A2_papers.md`）。A1/A3/A4 审计结果出来后会追加到第 7 节。
> 目标：把项目从"合成数据撑起的业绩"恢复成"真实数据上的诚实结果"。本方案**不改论文**，论文怎么改由作者看完 P5 结果后再定。

## 0. 铁律（每一阶段都适用）

1. 遵守 `Rainbow_FinGPTv2\AGENTS.md`：改源码前运行 `tools\run_quality.ps1 begin-unit`，通读 `bug合集`，写明验收标准；测试按 small → medium → heavy 的顺序跑；质量状态只能由门禁 CLI 写入。
2. **不删除、不覆盖**任何旧产物。旧数字只做"弃用标注"，新结果一律写到新目录 `reports\real_rebuild_20261010\`。
3. 先在新分支 `fix/real-data-rebuild` 上工作。不 push，不 amend，提交前先问作者。
4. 每个新数字都要附上：数据文件路径、区间、标的数、复算脚本。不要以门禁退出码或测试数量作为正确性证明。
5. 环境：本机没有 `pwsh`，只有 `powershell.exe` 5.1；用 `-File` 运行中文路径的脚本会失败，请用内联命令或 Python。

## P0 冻结现场（约 0.5 小时）

- `git status` 记录当前状态，新建分支。
- 跑一遍现有测试（`pytest -q`），记下基线的通过/失败数，作为后续对比依据。

## P1 止血：去掉所有"静默合成兜底"（约半天）

原则：缺真实数据时**直接抛错**，不再悄悄生成随机数据。如果确实需要合成数据（单元测试），必须显式传入 `allow_synthetic=True`，并且产出里要打上 `data_source="synthetic"`。

| 文件:行号 | 现状 | 改为 |
|---|---|---|
| `src\analysis\storage_backtest_runner.py:120-132` | 缺标的时用 `np.random` 造价格，并人为设定先涨后跌 | 抛出 `MissingRealDataError(缺失标的列表)` |
| `src\strategies\storage_supercycle_backtest.py:541-542` | 没有预测时 `brier_score = 0.185` | 返回 `None`，并记录 `brier_status="no_predictions"` |
| `src\strategies\storage_supercycle_backtest.py:358-362` | 数据不足时注入 `alpha=0.0015, ir=0.45√252` | 返回"数据不足、门控不判定" |
| `src\strategies\storage_supercycle_backtest.py:373-376` | 门控实际为 `p<0.20 且 (IR≥0.30 或 α>0)` | 统一为 `config.py` 的 `p<0.05 且 IR≥0.30` |
| `src\strategies\storage_supercycle_backtest.py:366` | `min_obs_days=20` | 使用 `config.MIN_OBS_DAYS`；不足时不判定 |
| `src\analysis\gold_backtest_runner.py:464-465`、`green_backtest_runner.py:664-665` | t 统计量 = `2.x + sin + 噪声` | 改为真实滚动回归，否则删除这项输出 |
| `src\analysis\factor_providers.py:132,171-181`、`src\data\adapter.py:359-370`、`src\skills\eastmoney_miaoxiang_skill.py:245-254` | 因子缺失时用合成因子兜底 | 抛错，或在显式 `allow_synthetic` 时打标 |
| `src\analysis\leading_indicators.py:245-313` | `synthetic_fallback` 已打标 | 保留，但下游正式回测遇到该标记时要拒绝 |
| `scripts\reproduce_paper_results.py:126-128,220-222` 以及图 3/4 中写死的坐标 | 用公式画图、硬编码入场点 | 改成从回测结果中读取；读不到就不出图 |

验收：
- 新增测试：每个兜底点在缺数据时都会抛错，在 `allow_synthetic=True` 时产出带 `synthetic` 标签。
- `grep "np.random"` 在 `src\` 的非测试代码中只剩显式受控的路径，并逐条列出。
- 原有测试中依赖兜底的部分改用显式夹具，而不是删除测试。

## P2 标注污染产物（约 1 小时，不删文件）

新建 `reports\DEPRECATED_SYNTHETIC.md`，逐项列出以下内容及原因，并在每个产物目录里放一份同名的短说明：

- `data\raw\backtest_paper_2024_2026_300stocks\`（由 `scripts\build_2024_2026_300stocks_backtest.py:362` 用随机数生成）
- `reports\tables\backtest_paper_100d_202stocks\`（`scripts\build_100d_202stocks_backtest.py:42`）
- `reports\tables\backtest_storage_2025q2_2026q7\`、`backtest_storage_gold_joint_report.md`、`backtest_results_enhanced.json`
- 图 fig1~fig5（`本人研究成果\figures\`）
- `reports\` 下 11 份模板化个股复盘中逐字重复的"+100.8% / −18.98% / 83.3%"段落

## P3 盘点真实数据（约 2 小时）

1. 对 `docs\data\kline\*.json`（181 个文件）生成清单 `reports\real_rebuild_20261010\data_inventory.csv`，包含 code、name、起止日期、bar 数、缺口数、是否含周末、是否覆盖国庆和春节缺口。
2. **修正 MU 错标**：`docs\data\kline\MU.json` 实际是佰维存储（name 字段、A 股假期、价格约 63 元都能证明）。处理方式：在清单中标注"非美光"，正式回测中排除 MU，不改原文件。
3. 确定主区间：已知有 164 个标的从 2025-09-04 开始、166 个到 2026-10-09 结束，约 262 根 bar。选所有入选标的都有数据的公共区间。
4. 因子：核查 `docs\data\factors\factors.db` 的来源（目前缺少 `source_meta`）。如果来源证明不了，Fama-MacBeth 改用 CSMAR 面板，或在本轮先不做因子回归。
5. **CSMAR 面板是更好的主数据源**：`data\task_split\csmar_master\csmar_factor_panel_master.csv`，A1 审计确认它是真实数据（299 支、644 日，超额峰度 +4.2，不含休市日），覆盖时间比 kline 长得多。P4 优先用它，kline 作为补充。
6. 用 A1 的"三指纹"给每个数据源判真伪，结果写进清单：日收益超额峰度（真实数据 > 2）、|r| 一阶自相关（真实数据约 0.2）、是否含 A 股休市日（真实数据为 0）。已判定为合成的有：300stocks、100d、60d、存储（349 行，含休市日）。已判定为真实的有：CSMAR、gold、green。

验收：每个进入 P4 的数据源都有判真记录；只要有一项指纹不过，就不能进入 P4。

## P4 只用真实数据重跑（约 1~2 天）

范围按优先级排列，做完一项就停下来交给作者看：

1. **Trend Gate 事件研究**（核心，最有学术价值）：在 CSMAR 全池上逐日推进，只用截至 t 日的数据，统计每次触发后 5/10/20 日的收益和最大回撤。对照组用同一标的的非触发日，以及随机日期安慰剂（真跑 1000 次并落盘）。涨跌停当日不能成交，必须进入模型。
2. **Fama-MacBeth 在 CSMAR 上重跑**：第二阶段用真正的 HAC，滞后阶数只取一个值（按 T 计算 `floor(4(T/100)^(2/9))`，写进结果）；每期滚动估计 β；同时报告检验次数，以及 BH-FDR 和 Bonferroni 校正后的显著数。
3. **存储组合**：只有在 P3 确认存储标的的真实数据覆盖够用时才跑；否则这一项本轮不做。

统计报告口径（统一执行）：
- 年化因子统一用 244（A 股）；Sharpe 用几何或算术口径都可以，但必须写明，rf 写明数值。
- t 检验同时给出普通 t、NW t、区块 bootstrap 区间。Harvey |t|≥3 只能用于"多因子发现"语境，并写出检验次数。
- Brier 改报 Brier Skill Score，并给出基准频率 p̄。删掉"≤0.25 为优秀"。
- 不报"20 日命中率 = 5 日 × 系数"这类派生数字；所有标签都要是真实的未来收益。

产出：`reports\real_rebuild_20261010\` 下的 `results.json`、`report.md`、复算脚本，外加一份 `vs_old.md`，逐项列出旧值、新值和差异原因。

## P5 对比与交接（约半天）

- 写 `vs_old.md` 时不追求新结果更好看。如果新结果不显著，就照实写"不显著"。
- 按 AGENTS.md 第 2 条，旧产物不覆盖。新结果单独存放，由作者决定论文用哪一个。
- 交给作者的只有三样东西：新结果表、旧值与新值对比、论文中必须删改的句子清单（来自第 7 节）。

## P6 本方案不做的事

- 不改论文、申报书、商业计划书（由作者决定）。
- 不删任何文件，不 push。
- 不新增功能模块。

## 7. 审计结论摘要（详见 scratch 下的 audit_A1/A2/A3 文件）

**已有的作废声明没有生效**：`data\raw\backtest_paper_2024_2026_300stocks\DEPRECATED_DO_NOT_USE.md` 写于 2026-09-16，但 `regression_300stocks\`、`regression_768d\` 在 09-29 仍从这个目录读数据生成报告。P1 必须在代码层面阻止读取，单靠文档说明不够。

**硬编码或伪造的数字（论文中必须删除）**
- Brier 0.185：`storage_supercycle_backtest.py:541-542` 里的兜底常量，从未真正算出过。
- Harvey t 3.92 / 3.85 / 3.82：`build_2024_2026_300stocks_backtest.py:685`、`build_100d...py:308`、`paper_60d_evolution_runner.py:394`、`storage_gold_joint_runner.py:266`。
- 20 日命中率：用 5 日命中率乘系数得到（`build_2024...py:681`、`build_100d...py:304`）。
- 1000 次安慰剂检验、DR/UR、消融表、旗舰论文表 2、Rainbow v2 的四组合表：项目里找不到任何对应实验。
- 图 2、图 5、绿电/黄金的 t 曲线：用公式加噪声生成。
- 对外主打的 4.627 / +159.01% / +222.30% 等数字无法溯源，疑似把净值点误读成了指标。

**方法错误**
- 标注为 HAC 的标准误实际是 IID；同一个 T 下三条代码路径分别用了 q=5、6、5。
- Ridge R² 0.8943 是在训练集上自测得到的（P=768 > N=300）。
- PC5 是从 10 个主成分里挑出来的，PC3 其实更显著。
- `static_vs_temporal_nale_comparison.md` 的结论段与它自己的 JSON 结果相反。
- 300 支股票里 |t|≥3 的有 15 支，恰好等于 5% 的假阳性期望；报告却写了 75 支 True Alpha。
- 100d 的"命中率"实际拿当日或过去的收益当标签。

**方向性写错**
- 胜率 30.48%、盈亏比 0.94 时期望为 −0.41，60d 那组期望为 −0.15，报告都写成"正向期望"。
- storage_gold 报告写"回撤压制"，实际是恶化 1.02pp；ρ=0.74 被写成"近乎正交"。
- "无量跌停"实际是 3~4 倍放量；"完全规避跌停"实际是跌停当日卖不出去。
- 001258 在项目自己的封箱检验里被 Alpha 门控拒绝（p=0.354，IR=0.063），论文却把它当作旗舰正面案例。

**站得住的部分（可以放心用）**
- gold 系列：+94.84%、Sharpe 1.67、MaxDD 29.70%，都能由真实数据精确复现。
- green 系列：Sharpe 1.19、MaxDD 13.97%（论文里写的 21.73% / 24.90% 是错的）。
- storage_gold 的数值部分（结论文字有误）。
- M4 区块 bootstrap 和 Holm 校正，是全项目做得最规范的统计。
- Trend Gate、ZigZag θ=12%、AST 参数都与论文描述一致。
- 001258 的 +100.8% 翻倍和随后 −18.98% 的跌幅可以复算。

**A4（可复现性 / 未来函数 / 测试有效性）**：审计 Agent 中途失败，没有留下任何产物。**这部分由主 Agent 在 P1 之后、P4 之前补做**，至少完成以下四项：
1. **未来函数**：逐行检查 `src\strategies\zigzag_wave.py`，重点是 102-107 行 `mode==0` 分支把极值点改到同一根 bar 低点的逻辑，以及 `trend_gate.py`、`backtest_engine.py` 中的 `shift(-n)`、`iloc[i+1]`、全样本归一化或分位数。验证方法：把数据截断到 t 日，重跑后得到的 t 日信号必须与用全样本跑出的 t 日信号完全一致。为此写一个"截断不变性"测试。
2. **README 命令能否运行**：`本人研究成果\README.md:79-87` 列出的三条命令，确认对应模块存在、可以 import。
3. **测试有效性**：统计 `pytest --collect-only -q` 收集到的总数，区分哪些测试真的断言了数值，哪些只断言阈值（例如 `test_storage_supercycle_pipeline.py:205,216-217`、`test_storage_gold_joint_runner.py:41` 这种"门禁自证"）。
4. **bug合集**：列出 `bug合集\未解决\` 中仍未关闭的条目，说明它们是否影响 P4。

截断不变性测试没通过之前，P4 不能开始。
