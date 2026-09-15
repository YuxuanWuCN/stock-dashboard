# Week 2 开工文档包 - 使用说明

📅 **执行周期**: 2026-09-16（周一）至 2026-09-21（周六），共 6 天  
🎯 **核心目标**: 工程稳定性优先 + NALE 快速验证 + 可展示成果

---

## 📦 文档包内容

| 文件 | 用途 | 使用者 |
|------|------|--------|
| `Week2_任务分配_开工指南.md` | **主文档**：完整任务分配、每日计划、验收标准 | 全员必读 |
| `week2_quick_data_audit.py` | Day 1 脚本：快速数据审计 | 数据组 |
| `week2_run_pca_backtest.py` | Day 3 脚本：运行回测系统 | 算法组 |
| `week2_nale_quick_validation.py` | Day 4 脚本：NALE 验证 | 算法组 |
| `week2_data_audit_report_template.md` | Day 2 模板：数据审计报告 | 数据组 |
| `week2_technical_summary_template.md` | Day 5 模板：技术总结报告 | 文档组 |
| `week2_deliverable_check.py` | Day 6 脚本：检查交付物完整性 | 全员 |

---

## 🚀 快速开工（3 步）

### 第 1 步：分配角色（队长）

编辑 `Week2_任务分配_开工指南.md`，填写"联系方式"表格：

```markdown
| 角色 | 姓名 | 微信/QQ | 负责任务 |
|------|------|---------|----------|
| 队长 | [你的姓名] | [填写] | 总协调 + 决策 |
| 数据组 | [成员A] | [填写] | 任务 1.1, 2.1 |
| 测试组 | [成员B] | [填写] | 任务 1.2, 2.2 |
| 算法组 | [成员C] | [填写] | 任务 2.3, 3.1, 4.1 |
| 文档组 | [成员D] | [填写] | 任务 4.2, 5.1, 5.2 |
```

### 第 2 步：准备环境（全员）

```powershell
# 1. 拉取最新代码
git pull origin contest-2026

# 2. 检查 Python 环境
python --version  # 应为 3.13+

# 3. 检查依赖包
python -c "import pandas, numpy, matplotlib; print('✅ 依赖包正常')"
```

### 第 3 步：开工会议（15 分钟）

**议程**:
1. 队长讲解 Week 2 目标（3 分钟）
2. 确认每个人的任务和截止日期（5 分钟）
3. 明确协作流程和每日站会时间（5 分钟）
4. Q&A（2 分钟）

**会后立即**：各组开始执行 Day 1 任务

---

## 📅 每日执行清单

### Day 1（周一）

**数据组**:
```bash
python scripts/week2_quick_data_audit.py
# 产出: reports/tables/week2_quick_audit.json
```

**测试组**:
```powershell
pytest tests/test_pca_backtest.py -v --tb=short > reports/test_results_pca.txt
pytest tests/test_sector_graph_missing_corr.py -v --tb=short > reports/test_results_graph.txt
# 产出: reports/test_results_*.txt
```

---

### Day 2（周二）

**数据组**:
- 根据模板撰写 `reports/week2_data_audit_report.md`
- 从 `week2_quick_audit.json` 提取数据

**测试组**:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/run_quality.ps1 small > reports/quality_gate_small.txt
powershell -NoProfile -ExecutionPolicy Bypass -File tools/run_quality.ps1 medium --feature "week2-bug-fixes" > reports/quality_gate_medium.txt
# 产出: reports/quality_gate_*.txt
```

---

### Day 3（周三）

**算法组**:
```bash
python scripts/week2_run_pca_backtest.py
# 产出:
#   - reports/tables/ashare_pca_backtest/week2/backtest_summary.csv
#   - reports/figures/ashare_pca_backtest/week2/*.png (5 张图)
```

预计耗时：3-4 小时

---

### Day 4（周四）

**算法组**:
```bash
python scripts/week2_nale_quick_validation.py
# 产出:
#   - reports/week2_nale_validation.json
#   - reports/week2_nale_validation.md
```

**文档组**:
- 创建 `reports/week2_technical_summary.md`（根据模板）
- 填充已完成部分（数据审计、Bug 修复）

---

### Day 5（周五）

**文档组**:
- 补全技术报告的所有 `[待填入]` 项
- 制作 PPT: `PPT素材/Week2_答辩素材.pptx`（5-8 页）

---

### Day 6（周六）

**全员**:
```bash
# 检查交付物完整性
python scripts/week2_deliverable_check.py

# 如果显示 ✅ 核心交付物全部完成
# 则进行 Week 2 验收和 Week 3 规划
```

**文档组**:
- PPT 预演（15 分钟）
- 根据反馈调整

---

## ✅ Week 2 最小验收标准

### 必须完成（6 项）
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

## 🔧 常见问题速查

### Q1: 脚本运行报错 "ModuleNotFoundError"
```bash
# 检查是否在项目根目录
pwd  # 或 Get-Location (PowerShell)

# 如果不是，切换到项目根目录
cd /d/R-FinGPTv2（国创版本）
```

### Q2: 数据文件找不到
```bash
# 检查文件是否存在
ls data/task_split/factors_768d_all.csv
ls data/task_split/csmar_master/csmar_factor_panel_master.csv

# 如果缺失，联系队长
```

### Q3: 测试失败怎么办
1. 不要慌，记录失败的测试名称
2. 查看详细错误信息
3. 在群里反馈，决定是否需要修复

### Q4: 回测结果看起来不对
- Sharpe < 0: 可能正常（市场环境差）
- Sharpe > 5: 可能有 bug
- NaN/Inf: 一定有 bug，联系算法组

---

## 📞 协作规范

### 每日站会（15 分钟）
**时间**: 每天晚上 9:00  
**形式**: 线上/线下

**议程**:
1. 每人汇报今日进度（2 分钟/人）
2. 遇到的问题和需要的帮助
3. 明天的任务确认

### Git 提交规范
```bash
# 每完成一个任务就提交
git add [相关文件]
git commit -m "Week2 Day1: 完成数据审计 - [你的姓名]"
git push origin contest-2026
```

### 文件交接
- **数据组 → 算法组**: 完成后在群里 @算法组
- **算法组 → 文档组**: 提供数据和图表路径
- **测试组 → 文档组**: 提供测试报告路径

---

## 📊 进度追踪（队长填写）

| 日期 | 数据组 | 测试组 | 算法组 | 文档组 | 备注 |
|------|--------|--------|--------|--------|------|
| 9/16 周一 | ☐ | ☐ | ☐ | - | Day 1 |
| 9/17 周二 | ☐ | ☐ | ☐ | - | Day 2 |
| 9/18 周三 | - | - | ☐ | - | Day 3 |
| 9/19 周四 | - | - | ☐ | ☐ | Day 4 |
| 9/20 周五 | - | - | - | ☐ | Day 5 |
| 9/21 周六 | ☐ 全员 | - | - | ☐ | Day 6 |

**图例**: ☐ 待完成 / ☑ 已完成 / ⚠️ 有问题

---

## 🎯 Week 2 成功标准

如果在 9/21（周六）晚上，`week2_deliverable_check.py` 显示：

```
✅ 核心交付物全部完成！
   可以进行 Week 2 验收和 Week 3 规划。
```

**恭喜！Week 2 圆满完成！** 🎉

下一步：
1. 召开 Week 2 复盘会议（30 分钟）
2. 根据 NALE 验证结果决定 Week 3 方向
3. 编写 Week 3 执行计划

---

## 📚 参考资料

- **主任务书**: `specs/contest-2026/week1-recovery-plan.md`
- **12 周路线图**: `specs/011-12week-joint-research-roadmap/plan.md`
- **项目总体规划**: `PROJECT.md`
- **NALE 方法说明**: `specs/contest-2026/week1-nale-alpha-handoff.md`

---

**文档版本**: v1.0  
**创建日期**: 2026-09-15  
**维护人**: [你的姓名]

---

## 💡 最后提醒

1. **沟通胜过一切**：有问题立即在群里问，不要憋着
2. **进度透明**：每日站会诚实汇报，延期不可怕，隐瞒才可怕
3. **质量优先**：宁可少做一点，也要保证质量
4. **保持节奏**：Week 2 是马拉松的一站，不要过度透支

**祝 Week 2 顺利！加油！💪**
