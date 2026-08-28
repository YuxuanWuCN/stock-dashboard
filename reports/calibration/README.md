# FinGPT 后训练校准系统使用指南

本文档说明如何使用 FinGPT 后训练校准系统，实现"市场反馈 → 校准报告 → 参数调整 → 验证"的闭环。

---

## 📋 系统概述

### 核心脚本

| 脚本 | 功能 | 触发时机 |
|------|------|---------|
| `tools/calibration.py` | 生成校准报告 | 每日自动检查 / 周日统一分析 |
| `tools/apply_calibration.py` | 应用调参建议 | 人工审核后执行 |
| `tools/verify_calibration.py` | 验证调参效果 | 调参后 5 天 |
| `tools/daily_local.ps1` | 每日自动任务（已集成校准检查） | 每天 18:00 |
| `tools/weekly_calibration.ps1` | 周日统一校准分析 | 每周日 20:00 |

### 工作流程

```
第 1-3 天  → 积累数据（模拟盘对决）
第 3 天    → 自动生成校准报告（daily_local.ps1）
          → 人工审核报告
          → 应用调参（apply_calibration.py）
第 4-8 天  → 继续运行（验证期）
第 8 天    → 生成验证报告（verify_calibration.py）
          → 评估调参效果
          → 决定是否保留参数
```

---

## 🚀 快速开始

### 1. 每日自动检查（已集成）

每天运行 `tools/daily_local.ps1` 时，会自动检查是否满足校准条件（≥3 个交易日）。

**满足条件时**：
- 自动生成校准报告到 `reports/calibration/calibration_report_YYYYMMDD_HHMMSS.json`
- 日志提示："⚠️  校准报告已生成，请审核后运行 python tools\apply_calibration.py"

**不满足条件时**：
- 静默跳过，继续积累数据

### 2. 周日统一分析（推荐设置定时任务）

每周日晚上 20:00 自动运行完整校准分析：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\weekly_calibration.ps1
```

**Windows 任务计划程序设置**：
1. 打开"任务计划程序" → 创建任务
2. 触发器：每周日 20:00
3. 操作：启动程序
   - 程序：`powershell.exe`
   - 参数：`-NoProfile -ExecutionPolicy Bypass -File "D:\股票分析项目\2.0版\tools\weekly_calibration.ps1"`
   - 起始于：`D:\股票分析项目\2.0版`

---

## 📊 使用详解

### 步骤 1: 生成校准报告

**手动运行**（可选）：
```bash
python tools/calibration.py
```

**输出**：
- `reports/calibration/calibration_report_YYYYMMDD_HHMMSS.json`
- 控制台打印报告摘要

**报告内容**：
- 累计交易日数
- 市场反馈对齐率
- 组合绩效对比（稳健/激进/等权）
- 单只股票准确率分析
- 分行业/分市场表现
- 调参建议（优先级 + 实施方法）

**触发条件**：
- ≥3 个交易日的模拟盘数据
- 或 market_feedback 样本数 ≥ 200

---

### 步骤 2: 审核校准报告

打开最新的校准报告 JSON 文件，重点查看：

1. **`market_feedback_summary.alignment_rate`**
   - 当前对齐率是否 < 50%？（存在乐观偏差）
   - 正向惊喜 vs 负向惊喜比例

2. **`portfolio_performance`**
   - 激进组合是否跑赢稳健组合？
   - 最大回撤是否过大（> 10%）？
   - 波动率是否在可接受范围内？

3. **`calibration_suggestions`**
   - 每条建议的 `priority`（high/medium/low）
   - 每条建议的 `reason` 和 `implementation`
   - 判断是否合理

---

### 步骤 3: 应用调参建议

**交互式应用**（推荐）：
```bash
python tools/apply_calibration.py
```

会逐条显示建议，询问是否应用（y/n）。

**自动应用所有建议**（谨慎）：
```bash
python tools/apply_calibration.py --auto
```

**指定报告文件**：
```bash
python tools/apply_calibration.py --report reports/calibration/calibration_report_20260812_180000.json
```

**脚本会自动**：
1. 备份当前参数文件到 `reports/calibration/backups/`
2. 修改相关配置文件（如 `daily_brief.py`, `aggressive_scan.py`）
3. 记录调参日志到 `项目规划/05-FinGPT后训练计划.md`

**调参后**：
- 继续运行 5 个交易日作为验证期
- **不要**立即再次调参

---

### 步骤 4: 验证调参效果

调参后 5 天（或更多），运行验证脚本：

```bash
python tools/verify_calibration.py
```

**输出**：
- `reports/calibration/verification_report_YYYYMMDD_HHMMSS.json`
- 控制台打印验证摘要

**验证内容**：
- 对齐率是否提升？
- 组合收益是否改善？
- 风险指标（波动率、回撤）是否在可控范围？
- 结论：调参是否有效

**根据结论决定**：
- ✅ 有效 → 保持当前参数，继续监控
- ⚠️  无效 → 考虑回滚或进一步调参

---

## 🔄 回滚参数（如需要）

如果调参效果不佳，可以回滚到之前的参数：

1. 查看备份目录：`reports/calibration/backups/`
2. 找到对应时间戳的备份文件
3. 手动复制回原位置，覆盖当前文件

**示例**：
```bash
# 回滚 daily_brief.py
cp reports/calibration/backups/daily_brief_20260812_180000.py src/strategies/daily_brief.py
```

---

## 📈 调参建议类型

### 1. 概率阈值调整

**触发条件**：对齐率 < 50%，存在乐观偏差

**调整内容**：
- `daily_brief.py` 中的候选股票概率阈值（50% → 60%）
- `aggressive_scan.py` 中的同样阈值

**目标**：提高预测准确率，减少假阳性

### 2. 组合策略调整

**触发条件**：
- 激进组合大幅跑赢稳健组合（增加动量权重）
- 激进组合回撤过大（加入止损纪律）

**调整内容**：
- `aggressive_scan.py` 中的因子权重
- 添加止损规则（单日跌幅 > 5% 或累计回撤 > 8%）

### 3. 评分权重调整

**触发条件**：交易日数 ≥ 10 天，可分析各因子贡献

**调整内容**：
- `src/analysis/scoring.py` 中的 `TECHNICAL_WEIGHT` / `FUNDAMENTAL_WEIGHT`
- KNN 特征权重

**目标**：优化多因子模型

---

## 🛠️ 故障排查

### 问题 1: 校准脚本报错"未找到数据文件"

**原因**：模拟盘数据未生成

**解决**：
1. 确认 `docs/data/paper/performance.json` 存在
2. 确认 `docs/data/llm/market_feedback.json` 存在
3. 运行 `python tools/paper_portfolio.py report` 生成数据

### 问题 2: 提示"交易日数不足"

**原因**：累计交易日 < 3 天

**解决**：继续运行每日任务，等待数据积累

### 问题 3: 应用调参后系统报错

**原因**：参数修改导致代码错误

**解决**：
1. 回滚参数（见上文）
2. 检查 `.quality-state/daily_local.log` 错误信息
3. 手动修正代码

### 问题 4: 验证脚本报错"数据不足"

**原因**：调参后未满 5 个交易日

**解决**：继续运行，等待验证期数据积累

---

## 📝 最佳实践

### 1. 调参频率

- ✅ **推荐**：每 5-10 个交易日调参一次
- ❌ **不推荐**：每天调参（过拟合风险）

### 2. 调参幅度

- ✅ **推荐**：每次只调整 1-2 个参数
- ❌ **不推荐**：一次性大幅修改所有参数

### 3. 数据积累

- 第 1 轮调参：≥ 3 天基线数据
- 第 2 轮调参：≥ 10 天历史数据
- 稳定期：≥ 30 天数据后再做大调整

### 4. 风险控制

- 始终保留参数备份
- 验证期不满意立即回滚
- 重大调参前手动测试

---

## 📚 相关文档

- 项目规划：`项目规划/05-FinGPT后训练计划.md`
- 每日任务：`tools/daily_local.ps1`
- 模拟盘系统：`tools/paper_portfolio.py`
- FinGPT 管线：`src/llm/`

---

## 💡 常见问题

**Q: 为什么不自动应用调参？**  
A: 金融模型调参有风险，需要人工审核确保合理性。

**Q: 对齐率多少算正常？**  
A: 50-60% 是合理水平（随机猜测是 50%），>70% 需警惕过拟合。

**Q: 调参后收益下降怎么办？**  
A: 立即回滚参数，分析原因，考虑是否市场环境变化。

**Q: 可以直接修改代码而不用这套系统吗？**  
A: 可以，但这套系统提供了备份、日志、验证等保障机制。

---

**最后更新**: 2026-08-11  
**作者**: 吴宇轩  
**版本**: 2.0
