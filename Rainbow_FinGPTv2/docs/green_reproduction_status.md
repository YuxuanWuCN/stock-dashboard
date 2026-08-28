# 绿电复现状态与待确认项

- 日期：2026-08-28
- 目标分支：`contest-2026`
- 对照模板：存储超级周期
- 当前姿态：Draft 调查报告；未修改策略逻辑、原始数据或已提交产物

## 1. 任务理解

本次成员 C 工作按“存储超级周期”的实验结构复现绿电板块：使用物理隔离数据，执行逐日推进回测，生成三级基准指标、图表、PDF，并运行专项测试。组长同时要求通过本地环境变量提供 AI API Key。

## 2. 已完成的本地复现

在 Python 3.13 环境中执行：

```powershell
python -B -m src.analysis.green_backtest_runner
python -B tools/generate_isolated_green_dossier_pdf.py
python -B -m pytest -p no:cacheprovider tests/test_green_backtest_runner.py -q
```

结果：

- 绿电回测入口成功生成 JSON 和两张 PNG。
- PDF 命令执行完成。
- 绿电专项测试通过：`1 passed in 2.87s`。
- 存储模板专项测试通过：`2 passed in 5.62s`。
- 重新生成的 JSON 只出现浮点尾数差异；这些本机重跑产物未纳入本 Draft PR。

当前提交版指标显示：策略总收益约 4.45%，最大回撤约 21.54%；绿电 ETF 总收益约 7.59%，最大回撤约 33.05%；沪深 300 总收益约 10.85%，最大回撤约 9.82%。该结果支持“相对绿电 ETF 降低回撤”，不支持“显著跑赢宽基”的表述。

## 3. 已确认的问题

### 3.1 绿电 PDF 与回测产物契约不一致

`green_backtest_runner.py` 生成：

- `fig1_cumulative_equity_and_drawdown.png`
- `fig2_asset_allocation_and_turnover.png`

但 `generate_isolated_green_dossier_pdf.py` 读取：

- `nav_comparison.png`
- `underwater_drawdown.png`

因此 PDF 命令虽然成功退出，当前绿电图表不会按预期嵌入报告。

### 3.2 绿电 PDF 残留黄金模板内容

绿电 PDF 源码仍引用 `backtest_gold_2025q3_2026q3/`、黄金股七标的、黄金 ETF `518880.SH` 等内容。这些文案与绿电 JSON、标的池及基准不一致，交付前需要修正。

### 3.3 本地 API 环境变量不会被现有绿电命令消费

项目 LLM 层支持 `DEEPSEEK_API_KEY`、`OPENAI_API_KEY` 和 `LLM_BACKEND`，但上述三个绿电入口不调用 `src.llm`：

- 回测入口只读取本地 CSV 并计算策略净值。
- PDF 入口只读取本地 JSON/PNG。
- pytest 入口只执行离线测试。

因此“配置了 API Key”和“绿电流程实际发生 AI API 请求”是两个不同状态。若交付要求包含真实 AI 调用，需要组长指定绿电专属 AI 入口、模型、输入输出和调用凭证；不建议直接运行覆盖全项目的 `tools/daily_local.ps1` 来代替。

### 3.4 绿电实现与存储模板不是模型级等价

存储模板实际使用 GFCA、NALE、Nowcasting、供应链邻接矩阵、跨市场信号和调仓死区。绿电回测目前主要使用消纳率阈值、Trend Gate 和通用仓位分配器；已初始化的部分分析引擎与 `factors.csv` 尚未进入绿电决策路径。

需要确认“照存储模板”指：

1. 仅保持实验、图表、PDF、测试的结构一致；还是
2. 同时要求 GFCA/NALE/Nowcasting 等模型能力在绿电策略中对等落地。

### 3.5 `contest-2026` 当前无法建立全绿质量基线

该分支缺少 `.quality-gates.json`。使用上游 `main` 的同版本配置进行仅本机基线检查后，在未修改源码的情况下发现：

- 门禁默认优先选择无项目依赖的 Python 3.14；显式切换项目 Python 3.13 后可继续。
- 基线仍缺少 `flask_cors` 与 `openai` 依赖。
- `tests/test_rebalance_selection.py::test_robust_candidates_filters_and_sorts` 存在既有失败。

这些失败与本 Draft PR 无关。本 PR 不绕过或伪造全绿门禁，只报告可复现的专项测试结果。

## 4. 本 Draft PR 的唯一行为变更

仓库此前没有保护 `.env`、`api-key.txt` 和 `api_key.txt` 的 Git 忽略规则，而协作指南要求成员在本地配置 API。此 Draft PR 增加最小 `.gitignore` 规则，防止真实密钥被误加入提交。

本 PR 不包含任何 API Key、策略改动、原始数据改动或本机生成的 JSON/PNG/PDF。

## 5. 请求组长确认

请确认以下三点后再进入实现型 PR：

1. 绿电实际调用 AI 的指定入口和模型是什么？
2. “照存储模板”是报告结构等价，还是模型能力也必须等价？
3. 生成的 JSON、PNG、PDF 是否应随修复源码一并提交？

建议确认后拆分后续改动：先修复绿电 PDF 文案与图片契约并补充边界测试，再单独处理模型级对齐或全项目质量基线。
