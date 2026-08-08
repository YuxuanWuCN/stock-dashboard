# 质量工作流入口

完整的分层质量门禁规则已经统一记录在 [WORKFLOW.md](WORKFLOW.md)。

```powershell
powershell -ExecutionPolicy Bypass -File tools/run_quality.ps1 begin-unit --name "修改内容" --acceptance "验收标准"
powershell -ExecutionPolicy Bypass -File tools/run_quality.ps1 small
powershell -ExecutionPolicy Bypass -File tools/run_quality.ps1 medium --feature "功能名称"
powershell -ExecutionPolicy Bypass -File tools/run_quality.ps1 heavy --version v2.1.0
```
