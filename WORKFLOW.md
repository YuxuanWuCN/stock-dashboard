# 股票分析项目质量工作流

本项目采用 `D:\数学建模作品` 中的分层质量门禁，并针对股票看板的 Python、JavaScript、离线分析和可复现性测试做了配置适配。质量门禁本身也由独立测试覆盖，不能只看 pytest 数量或退出码判断业务正确性。

## 工作顺序

```text
需求与验收标准
    -> begin-unit（完整阅读 bug 合集）
    -> 编写最小代码单元
    -> small（单元测试，成功后关闭单元）
    -> medium --feature（综合流程，依赖有效 small 凭证）
    -> heavy --version vX.Y.Z（版本级检查，依赖有效 medium 凭证）
    -> release vX.Y.Z（仅在证据已提交后创建标签）
```

首次迁移、克隆或人工恢复后，先建立可信基线：

```powershell
powershell -ExecutionPolicy Bypass -File tools/install_hooks.ps1
powershell -ExecutionPolicy Bypass -File tools/run_quality.ps1 bootstrap `
  --reason "股票分析项目质量系统迁移" `
  --acceptance "源码、控制文件和完整 bug 合集已审阅，股票单元测试通过"
```

开始新的最小代码单元：

```powershell
powershell -ExecutionPolicy Bypass -File tools/run_quality.ps1 begin-unit `
  --name "修改内容" `
  --acceptance "可观察的验收标准"
powershell -ExecutionPolicy Bypass -File tools/run_quality.ps1 small
```

完成一组功能后按顺序执行：

```powershell
powershell -ExecutionPolicy Bypass -File tools/run_quality.ps1 medium `
  --feature "功能名称"
powershell -ExecutionPolicy Bypass -File tools/run_quality.ps1 heavy --version v2.1.0
```

只有明确需要发布时才执行：

```powershell
powershell -ExecutionPolicy Bypass -File tools/run_quality.ps1 release v2.1.0
```

## 三层测试内容

- `small`：Python/Notebook/JSON 语法、质量系统自测、股票业务单元测试和依赖声明检查。
- `medium`：以上检查，加上离线综合分析流程测试；必须存在有效的 small 凭证。
- `heavy`：以上检查，加上可复现性测试、全量回归、秘密扫描和依赖一致性检查；必须存在有效的 medium 凭证。

每次测试都会在 `.quality-state/reports/` 写入 JSON/Markdown 回执。失败会通过质量门禁自动登记到 `bug合集/`，包括功能、数据安全、范围、概率、恢复成本和回归风险共 22 分，历史记录不能直接删除或手改。

## 保护范围

`.quality-state/`、`bug合集/`、版本证据和 Git Hook 由门禁 CLI 管理；Git 提交和推送会验证对应凭证。新克隆后必须执行 `tools/install_hooks.ps1`，本地 Hook 不能替代远端仓库的最终保护。

## 独立复核

对关键股票名称解析、指标计算、评分边界、缺失数据和可复现结果，必须使用独立断言或可手算的小样本复核。测试通过只能证明已执行的断言成立，不能替代对业务含义、数据来源和失败路径的审查。
