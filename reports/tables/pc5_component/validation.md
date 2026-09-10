# PC5 第五主成分交付验证

日期：2026-09-10。上游输入固定为 `YuxuanWuCN/stock-dashboard` 的 `contest-2026 @ 7d63bb4f22821549efa20c23e9ffb28ee35cbcd4`。交付范围为负责人指定的第5主成分，不是 P1-P5 人工融合或整个 NALE 门控模型。

## 数据和结果

| 核对项 | GitHub 768维截面 | 旧绿色能源日期因子 |
|---|---:|---:|
| 行数 / 特征数 | 300 / 768 | 258 / 8 |
| 保留的主成分数 | 10 | 5 |
| 实际选取列 | PC05 | PC05 |
| PC5 方差解释率 | 3.726987527943334% | 13.291410139628604% |
| 基底正交性最大误差 | 1.9984e-15 | 1.3323e-15 |
| 与旧 PC5 符号对齐后的最大误差 | 不适用：旧报告没有同口径逐股得分 | 4.9743e-14 |

300个股票代码及名称逐项核对仓库的 `universe_300_assigned.csv`；六位代码前导零保留。主输入300行均标记为 `local_semantic`，没有把它们声明为已核实的历史 LLM embedding。

旧768维报告的 PC5 解释率与本次差值为 `-3.2839e-08`；旧实现的 auto 求解器和加 `1e-8` 的缩放与本次完整 SVD、标准缩放不同。本次保存冻结的完整10维载荷、特征均值/尺度、PC均值/尺度、基底版本及输入哈希，避免跨基底误用。

## 独立验证

专项命令：`python -m pytest -q tests/test_pc5_component.py tests/test_factor_orthogonalization.py`，22项通过。断言包括：

- 可手算的五组相关因子对：总体特征值为 `1.9,1.8,1.7,1.6,1.5,0.5,0.4,0.3,0.2,0.1`，故 PC5 为最后一对之和除以 `sqrt(2)`，总体方差1.5、解释率15%；不会误选 PC10。
- 独立协方差特征分解，以及 scikit-learn `StandardScaler + PCA(svd_solver="full")` 对300股的 PC5 交叉核对。
- 旧 Day2 入口即使保留6维也选择第5维，不再把最后一个主成分重命名为 PC5。
- 常量 `0.1` 列不能因浮点误差虚增有效秩；不足5维、保留数超过有效秩、非有限值、重复样本键及不匹配特征均拒绝。
- 调换输入行列顺序不改变拟合基底；冻结训练截止日后，扰动未来样本不改变训练结果或早期得分。
- 基底哈希损坏拒绝载入或变换；已存在的输出目录拒绝覆盖。
- 端到端检查原始/标准化得分、20个产物哈希、输入来源和描述性状态；CSV/JSON/Markdown 明确使用 LF。

上传前另对 Git 暂存区实际字节检查20个产物及3个实现文件的 SHA-256，不仅检查工作目录文件；全部与 `run_manifest.json` 一致。两张220dpi图已目视检查，图表内容为解释率、得分分布和载荷，没有伪造收益曲线。

## 工程检查

- Python 3.13.9；numpy 2.3.5；pandas 2.3.3；scikit-learn 1.7.2；matplotlib 3.10.6。
- Ruff、Black 检查本次4个 Python 文件通过，`pip check` 通过。
- `small` 通过；新增上游失败记录后重新阅读并刷新回执为 `20260910145151-small-424a46`。
- `medium` 通过；绑定最新 Bug 记录的最终回执为 `20260910145415-medium-6e6529`。
- `heavy` 未通过，回执 `20260910144819-heavy-50cc58`：全量 pytest 为 **810 passed / 6 failed**，另有1条 error 级弱断言。秘密扫描、依赖一致性、可复现性测试均通过。[门禁原始报告](../../../测试记录/版本/v0.0.0-pc5-20260910.md) / [JSON证据](../../../测试记录/版本/v0.0.0-pc5-20260910.json)。
- 质量门禁源码哈希：`ce95dad625c7aa1f4e7a753893b5ea29981fe8a80d3b17a1041b2987660625bd`。本次脚本、配置和产物另由专项测试及清单哈希覆盖。
- 本次代码、产物和说明的 `git diff --check` 通过；唯一例外是 CLI 原样保存的 heavy Markdown 日志中6处行尾空白。它们来自旧失败测试的 traceback，保留原始证据，不手改门禁生成文件。

### 上游基线复核

在独立、干净的 detached worktree `D:\stock-dashboard-pc5-baseline` 中，HEAD 固定为上游 `7d63bb4f22821549efa20c23e9ffb28ee35cbcd4`，使用相同 Python 环境单独运行以下6个失败节点。结果 **6 failed in 5.43s**，报错与本次全量检查逐项一致；复核前后 `git status --porcelain` 均为空。本次没有在原始基线上重跑其余全部测试。

| 失败位置 | 原始基线上复现的原因 |
|---|---|
| `test_factor_providers.py::test_scnu_strict_mode_requires_explicit_trading_calendar` | 缺失显式交易日历时未抛出预期异常 |
| `test_git_push_with_fallback.py::test_both_daily_jobs_use_the_shared_push_helper` | `daily_local.ps1` 已改为调用 `daily_routine.py`，与测试要求的共享推送入口不一致 |
| `test_storage_supercycle_pipeline.py::test_table2_biwin_maxdd_suppression_and_micron_sharpe` | 本地因子数据库缺少 `factors` 表 |
| `test_storage_supercycle_pipeline.py::test_full_storage_supercycle_backtest_pipeline` | 同样缺少 `factors` 表 |
| `test_validate_teacher_framework.py::test_three_actions_windows` | 20日持有收益实际为 -3.46%，与测试硬编码正收益断言冲突 |
| `test_validate_teacher_framework.py::test_limit_up_clustering` | 现有数据得到7簇，而测试硬编码6簇 |

原始基线的 `python tools/quality_gate.py scan-asserts --json` 还复现 `tests/test_dynamic_position_sizer.py:326` 的 `no-assert` error；合计13条 warn、1条 error。此命令的 JSON 结果才是判断依据，不能以扫描 CLI 的零退出码宣称通过。

以上失败保持未解决，不跳过、不改断言或范围外业务逻辑，不宣称全仓通过。交付采用 Draft PR 等待负责人审阅；不创建发布标签、不合并分支。重读新增 Bug 记录后重新运行 small / medium，确保提交凭证绑定最新记录。

## 未验证事项与边界

本次未进行收益、IC、样本外策略优劣或显著性评价。768维数据是当前截面，缺少日期、`available_at` 和历史版本；旧日期因子上游又有 `forward_backward_fill` 记录。不能把当前截面复制进历史，也不能把全样本PCA复核当作样本外预测。

因此保留稳定量化产物，所有新数据写入独立目录；`performance_evaluation=NOT_RUN_NO_POINT_IN_TIME_PANEL`，`stable_output_replacement=false`，`system_did_not_order=true`。PC5载荷不是持仓权重，解释率不是收益率，匿名 embedding 维度也没有被强行赋予经济语义。

[结果与复现说明](../../../specs/contest-2026/pc5-component-handoff.md) · [产物目录](../../../data/processed/pc5_component/github-7d63bb4/README.md)
