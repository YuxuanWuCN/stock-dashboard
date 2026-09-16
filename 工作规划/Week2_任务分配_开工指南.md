# Week 2 任务分配与开工指南

**项目**: Rainbow-FinGPT 768D 因子系统优化  
**时间**: 2026-09-16（周一）至 2026-09-21（周六），共 6 天  
**分支**: `contest-2026`  
**目标**: 工程稳定性优先 + NALE 快速验证 + 可展示成果

---

## 📋 核心交付物（Week 2 结束时必须完成）

| # | 交付物 | 负责人 | 截止日期 |
|---|--------|--------|----------|
| 1 | 数据质量审计报告 | **数据组** | Day 2 (周二) |
| 2 | Bug 修复验证报告 | **测试组** | Day 2 (周二) |
| 3 | 768D 回测系统运行结果 | **算法组** | Day 3 (周三) |
| 4 | NALE 方法验证结论 | **算法组** | Day 4 (周四) |
| 5 | 技术总结报告 + PPT | **文档组** | Day 5 (周五) |

---

## 👥 角色与分工

### 角色 A：数据组（1 人，优先级最高）
**职责**: 数据质量审计，确保后续工作有可靠基础

**核心任务**:
- Day 1: 运行快速数据审计脚本
- Day 2: 输出数据质量报告

**技能要求**: Python 基础，能读写 CSV/JSON

---

### 角色 B：测试组（1 人）
**职责**: 验证 Bug 修复生效，确保代码稳定性

**核心任务**:
- Day 1: 运行测试套件，记录结果
- Day 2: 运行质量门禁，输出验证报告

**技能要求**: 能运行 pytest 和 PowerShell 脚本

---

### 角色 C：算法组（1-2 人）
**职责**: 运行回测系统，验证 NALE 方法

**核心任务**:
- Day 2-3: 运行 768D PCA 回测
- Day 3-4: NALE 快速验证

**技能要求**: 熟悉 Python，理解量化回测逻辑

---

### 角色 D：文档组（1 人，可兼任）
**职责**: 整理成果，制作答辩素材

**核心任务**:
- Day 4-5: 撰写技术报告
- Day 5: 制作 PPT 素材

**技能要求**: 文档撰写能力，PPT 制作

---

## 📅 每日任务清单

### Day 1（周一）：数据摸底 + 测试验证

#### 任务 1.1：数据组 - 快速数据审计 ⭐⭐⭐
**负责人**: [数据组成员姓名]  
**时间**: 2-3 小时  
**难度**: ⭐⭐ (简单)

**任务说明**:
运行数据审计脚本，检查 CSMAR 主表和文本因子的质量。

**操作步骤**:
```powershell
# 1. 创建审计脚本
# 复制附录 A 的代码到 scripts/week2_quick_data_audit.py

# 2. 运行脚本
python scripts/week2_quick_data_audit.py

# 3. 查看结果
cat reports/tables/week2_quick_audit.json
```

**验收标准**:
- [ ] `reports/tables/week2_quick_audit.json` 文件已生成
- [ ] 脚本输出了股票数、日期数、缺失率
- [ ] 标记了关键问题（如有）

**产出文件**:
- `reports/tables/week2_quick_audit.json`

---

#### 任务 1.2：测试组 - Bug 修复验证 ⭐⭐⭐
**负责人**: [测试组成员姓名]  
**时间**: 1-2 小时  
**难度**: ⭐ (简单)

**任务说明**:
运行测试套件，确认 2026-09-15 修复的 7 个 bug 已生效。

**操作步骤**:
```powershell
# 1. 运行 PCA 回测测试
pytest tests/test_pca_backtest.py -v --tb=short > reports/test_results_pca.txt

# 2. 运行图引擎测试
pytest tests/test_sector_graph_missing_corr.py -v --tb=short > reports/test_results_graph.txt

# 3. 运行压力测试
pytest tests/test_challenger_pca_backtest_stress.py -v --tb=short > reports/test_results_stress.txt

# 4. 运行 NALE 测试
pytest tests/test_dynamic_nale_alpha.py -v --tb=short > reports/test_results_nale.txt

# 5. 汇总结果
echo "=== 测试汇总 ===" > reports/week2_test_summary.txt
grep -E "(PASSED|FAILED)" reports/test_results_*.txt >> reports/week2_test_summary.txt
```

**验收标准**:
- [ ] 所有测试通过（PASSED）
- [ ] 无 FAILED 或 ERROR
- [ ] 生成了测试汇总文件

**产出文件**:
- `reports/week2_test_summary.txt`
- `reports/test_results_*.txt` (4 个测试日志)

---

### Day 2（周二）：报告产出 + 回测准备

#### 任务 2.1：数据组 - 输出审计报告 ⭐⭐
**负责人**: [数据组成员姓名]  
**时间**: 2 小时  
**难度**: ⭐⭐ (中等)

**任务说明**:
根据 Day 1 审计结果，撰写正式的数据质量报告。

**操作步骤**:
```markdown
# 创建 reports/week2_data_audit_report.md

参考模板：附录 B
```

**验收标准**:
- [ ] 报告包含 CSMAR 基本统计
- [ ] 报告包含文本因子覆盖情况
- [ ] 标记了已知问题和建议

**产出文件**:
- `reports/week2_data_audit_report.md`

---

#### 任务 2.2：测试组 - 运行质量门禁 ⭐⭐
**负责人**: [测试组成员姓名]  
**时间**: 1 小时  
**难度**: ⭐ (简单)

**任务说明**:
运行项目的质量门禁脚本，确保代码通过 small 和 medium 级别。

**操作步骤**:
```powershell
# 1. 运行 small 级别门禁
powershell -NoProfile -ExecutionPolicy Bypass -File tools/run_quality.ps1 small > reports/quality_gate_small.txt

# 2. 运行 medium 级别门禁
powershell -NoProfile -ExecutionPolicy Bypass -File tools/run_quality.ps1 medium --feature "week2-bug-fixes" > reports/quality_gate_medium.txt

# 3. 检查结果
cat reports/quality_gate_small.txt | Select-String "PASS|FAIL"
cat reports/quality_gate_medium.txt | Select-String "PASS|FAIL"
```

**验收标准**:
- [ ] Small 级别通过 (显示 `[PASS]`)
- [ ] Medium 级别通过 (显示 `[PASS]`)
- [ ] 日志文件已保存

**产出文件**:
- `reports/quality_gate_small.txt`
- `reports/quality_gate_medium.txt`

---

#### 任务 2.3：算法组 - 准备回测环境 ⭐
**负责人**: [算法组成员姓名]  
**时间**: 1 小时  
**难度**: ⭐ (简单)

**任务说明**:
检查回测所需的数据文件是否就绪，准备运行环境。

**操作步骤**:
```powershell
# 1. 检查数据文件
ls data/task_split/factors_768d_all.csv
ls data/task_split/csmar_master/csmar_factor_panel_master.csv

# 2. 检查代码模块
python -c "from src.pricing.pca_backtest import run_pca_backtest; print('✅ 模块可导入')"

# 3. 创建输出目录
mkdir reports/tables/ashare_pca_backtest/week2 -Force
mkdir reports/figures/ashare_pca_backtest/week2 -Force
```

**验收标准**:
- [ ] 数据文件存在且可读取
- [ ] Python 模块可正常导入
- [ ] 输出目录已创建

---

### Day 3（周三）：768D 回测系统运行

#### 任务 3.1：算法组 - 运行完整回测 ⭐⭐⭐⭐
**负责人**: [算法组成员姓名]  
**时间**: 3-4 小时  
**难度**: ⭐⭐⭐ (中高)

**任务说明**:
运行修复后的 PCA 回测系统，对全池和 3 个板块分别回测。

**操作步骤**:
```python
# 创建 scripts/week2_run_pca_backtest.py
# 参考附录 C 的完整代码
```

**验收标准**:
- [ ] 4 个回测（全池 + 3 板块）全部运行成功
- [ ] 生成了对比汇总表
- [ ] 生成了净值曲线图
- [ ] 所有指标（Sharpe, 回撤等）在合理范围内

**产出文件**:
- `reports/tables/ashare_pca_backtest/week2/backtest_summary.csv`
- `reports/figures/ashare_pca_backtest/week2/cumulative_pnl.png`
- `reports/figures/ashare_pca_backtest/week2/cumulative_pnl_combined.png`

---

### Day 4（周四）：NALE 验证 + 报告启动

#### 任务 4.1：算法组 - NALE 快速验证 ⭐⭐⭐
**负责人**: [算法组成员姓名]  
**时间**: 2-3 小时  
**难度**: ⭐⭐ (中等)

**任务说明**:
从 Week 1 已有结果中提取 NALE 方法的验证结论。

**操作步骤**:
```python
# 创建 scripts/week2_nale_quick_validation.py
# 参考附录 D 的代码
```

**验收标准**:
- [ ] 提取了 B0 和 V1 的 Rank IC
- [ ] 计算了 IC 提升幅度
- [ ] 给出了明确结论（有效/无效/待定）

**产出文件**:
- `reports/week2_nale_validation.json`
- `reports/week2_nale_validation.md` (简短说明)

---

#### 任务 4.2：文档组 - 启动技术报告 ⭐⭐
**负责人**: [文档组成员姓名]  
**时间**: 2 小时  
**难度**: ⭐⭐ (中等)

**任务说明**:
创建技术报告框架，填充已完成部分的内容。

**操作步骤**:
```markdown
# 创建 reports/week2_technical_summary.md
# 参考附录 E 的模板
```

**验收标准**:
- [ ] 报告框架完整（包含所有章节）
- [ ] 已完成部分（数据审计、Bug 修复）内容已填充
- [ ] 待填充部分已标记 `[待填入]`

**产出文件**:
- `reports/week2_technical_summary.md` (初稿)

---

### Day 5（周五）：报告完善 + PPT 制作

#### 任务 5.1：文档组 - 完成技术报告 ⭐⭐⭐
**负责人**: [文档组成员姓名]  
**时间**: 3-4 小时  
**难度**: ⭐⭐⭐ (中高)

**任务说明**:
补充技术报告的所有待填项，完成终稿。

**操作步骤**:
1. 从算法组获取回测结果数据
2. 填充报告中的表格和数字
3. 插入图表
4. 全文校对

**验收标准**:
- [ ] 所有 `[待填入]` 已替换为实际数据
- [ ] 所有图表已插入或链接
- [ ] 文档无明显错误

**产出文件**:
- `reports/week2_technical_summary.md` (终稿)

---

#### 任务 5.2：文档组 - 制作答辩 PPT ⭐⭐⭐
**负责人**: [文档组成员姓名]  
**时间**: 2-3 小时  
**难度**: ⭐⭐⭐ (中高)

**任务说明**:
基于技术报告，制作 5-8 页的答辩 PPT 素材。

**PPT 结构**:
```
第 1 页: 项目背景与 Week 2 目标
第 2 页: 数据质量审计结果
第 3 页: Bug 修复清单与验证
第 4 页: 768D 回测系统性能对比（表 + 图）
第 5 页: NALE 方法初步验证结论
第 6 页: Week 3 规划与展望
第 7 页: Q&A 准备
```

**验收标准**:
- [ ] PPT 页数为 5-8 页
- [ ] 每页有清晰标题和核心信息
- [ ] 包含关键图表（回测净值曲线）
- [ ] 排版美观，可直接用于答辩

**产出文件**:
- `PPT素材/Week2_答辩素材.pptx`

---

### Day 6（周六）：整合与预演

#### 任务 6.1：全员 - 文档整合 ⭐
**负责人**: 所有成员  
**时间**: 1 小时  
**难度**: ⭐ (简单)

**任务说明**:
检查所有交付物，确保完整性。

**检查清单**:
```powershell
# 运行检查脚本
python scripts/week2_deliverable_check.py
```

**验收标准**:
- [ ] 5 大交付物全部就绪
- [ ] 所有文件路径正确
- [ ] 无缺失或损坏文件

---

#### 任务 6.2：文档组 - PPT 预演 ⭐⭐
**负责人**: [文档组成员姓名]  
**时间**: 1 小时  
**难度**: ⭐⭐ (中等)

**任务说明**:
用 PPT 进行内部预演，计时 15 分钟。

**操作步骤**:
1. 给团队讲解 PPT（或自己练习）
2. 记录卡顿或不清晰的地方
3. 根据反馈调整

**验收标准**:
- [ ] 完成一次完整演练
- [ ] 时长控制在 15 分钟内
- [ ] 主要问题已优化

---

## 🔗 协作流程

### 每日站会（15 分钟）
**时间**: 每天晚上 9:00  
**形式**: 线上/线下

**议程**:
1. 每人汇报今日进度（2 分钟/人）
2. 遇到的问题和需要的帮助
3. 明天的任务确认

---

### 文件共享规范

#### 命名规范
```
reports/week2_[类型]_[日期].md
例如: reports/week2_data_audit_20260916.md
```

#### Git 提交规范
```bash
# 每完成一个任务就提交
git add [相关文件]
git commit -m "Week2 Day1: 完成数据审计 - [你的姓名]"
git push origin contest-2026
```

#### 文件交接
- 数据组 → 算法组: 完成后在群里 @算法组
- 算法组 → 文档组: 完成后提供数据和图表链接
- 测试组 → 文档组: 提供测试报告路径

---

## ❓ 常见问题 FAQ

### Q1: 脚本运行报错怎么办？
**A**: 
1. 先检查 Python 环境和依赖包
2. 查看错误信息，检查文件路径
3. 在群里贴出完整错误信息求助

### Q2: 数据文件找不到怎么办？
**A**: 
1. 确认当前工作目录：`pwd` (Bash) 或 `Get-Location` (PowerShell)
2. 检查文件是否存在：`ls data/task_split/factors_768d_all.csv`
3. 如果真的缺失，联系队长

### Q3: 测试失败怎么办？
**A**: 
1. 不要慌，先记录失败的测试名称
2. 查看测试日志的详细错误信息
3. 在群里反馈，决定是否需要修复

### Q4: 回测结果不合理怎么办？
**A**: 
- Sharpe < 0: 可能正常（市场环境差）
- Sharpe > 5: 可能有 bug，检查数据
- NaN/Inf: 一定有 bug，联系算法组

### Q5: PPT 不知道怎么写？
**A**: 
1. 参考技术报告，每章提取 2-3 个要点
2. 每页只放一张图或一个表
3. 用简短的句子，不要大段文字

---

## 📞 联系方式

| 角色 | 姓名 | 微信/QQ | 负责任务 |
|------|------|---------|----------|
| 队长 | [你的姓名] | [联系方式] | 总协调 + 决策 |
| 数据组 | [成员姓名] | [联系方式] | 任务 1.1, 2.1 |
| 测试组 | [成员姓名] | [联系方式] | 任务 1.2, 2.2 |
| 算法组 | [成员姓名] | [联系方式] | 任务 2.3, 3.1, 4.1 |
| 文档组 | [成员姓名] | [联系方式] | 任务 4.2, 5.1, 5.2 |

---

## ✅ Week 2 最终验收清单

### 必须完成（Hard Requirements）
- [ ] `reports/week2_data_audit_report.md` - 数据审计报告
- [ ] `reports/week2_test_summary.txt` - 测试验证报告
- [ ] `reports/tables/ashare_pca_backtest/week2/backtest_summary.csv` - 回测结果
- [ ] `reports/week2_nale_validation.json` - NALE 验证结论
- [ ] `reports/week2_technical_summary.md` - 技术总结报告
- [ ] `PPT素材/Week2_答辩素材.pptx` - 答辩 PPT

### 质量标准
- [ ] 所有 pytest 测试通过
- [ ] 质量门禁 small 和 medium 通过
- [ ] 回测系统 4 个宇宙运行成功
- [ ] 技术报告无明显错误
- [ ] PPT 可流畅讲述 15 分钟

---

## 📎 附录：代码模板

### 附录 A：数据审计脚本

见下一个文件：`scripts/week2_quick_data_audit.py`

### 附录 B：数据审计报告模板

见下一个文件：`reports/week2_data_audit_report_template.md`

### 附录 C：PCA 回测脚本

见下一个文件：`scripts/week2_run_pca_backtest.py`

### 附录 D：NALE 验证脚本

见下一个文件：`scripts/week2_nale_quick_validation.py`

### 附录 E：技术报告模板

见下一个文件：`reports/week2_technical_summary_template.md`

---

**文档版本**: v1.0  
**创建日期**: 2026-09-15  
**最后更新**: 2026-09-15  
**维护人**: [你的姓名]

---

## 🚀 开工准备

### 今晚必做（准备工作）
1. **队长**: 分配角色，填写"联系方式"表格
2. **所有人**: 拉取最新代码 `git pull origin contest-2026`
3. **所有人**: 检查 Python 环境 `python --version` (应为 3.13+)
4. **所有人**: 阅读自己负责的任务（标记 ⭐⭐⭐ 的部分）

### 明天开工（Day 1）
- 9:00 AM: 开工会议（15 分钟）
- 9:30 AM: 开始执行各自任务
- 9:00 PM: 第一次每日站会

---

**祝 Week 2 顺利！有问题随时在群里沟通。**
