# Agent 4 任务卡：质量门禁与文档工程师

## 角色定位
负责代码质量、测试覆盖率和学术文档包装

## 本周目标
确保交付物达到学术发表标准

## 详细任务

### 任务1: 测试金字塔构建
```
tests/
├── unit/
│   ├── test_pc5_features.py      # Agent 1
│   ├── test_pc5_nale_fusion.py   # Agent 2
│   └── test_temporal_decay.py
├── integration/
│   ├── test_feature_to_score_pipeline.py
│   └── test_score_to_backtest_pipeline.py
└── e2e/
    └── test_full_pipeline.py
```

目标覆盖率：
- 单元测试：≥ 90%
- 集成测试：≥ 80%
- 端到端：1个完整场景

### 任务2: 质量门禁执行
按顺序运行：
```powershell
# 1. 前置检查
.\tools\run_quality.ps1 begin-unit

# 2. 分级测试
pytest tests/unit -v          # small
pytest tests/integration -v   # medium  
pytest tests/e2e -v          # heavy

# 3. 覆盖率报告
pytest --cov=src --cov-report=html
```

### 任务3: 学术论文级文档
**文件**: `docs/papers/pc5_temporal_nale.md`

结构（IEEE/ACM风格）：
```markdown
# PC5-Temporal NALE: A Time-Aware Composite Factor Framework for A-Share Markets

## Abstract (200字)
## 1. Introduction (2页)
   1.1 Motivation: A股市场的时效性特征
   1.2 Challenges: 因子失效与过拟合
   1.3 Contributions: PC5五维复合向量
   
## 2. Related Work (1页)
   2.1 NALE与图神经网络
   2.2 时序因子衰减研究
   
## 3. Methodology (3页)
   3.1 PC5向量定义
   3.2 融合算子设计
   3.3 滚动方向校准机制
   
## 4. Experiments (2页)
   4.1 数据集与设置
   4.2 基准对比
   4.3 消融实验
   
## 5. Results & Discussion (1页)
   5.1 性能提升
   5.2 局限性分析
   
## 6. Conclusion & Future Work
## References (≥10篇)
```

### 任务4: 代码审查协调
运行code-review技能：
```bash
/code-review HEAD~5  # 检查最近5次提交
```

审查维度：
- Standards: 是否符合 `AGENTS.md` 规范
- Spec: 是否忠实实现设计文档

## 验收清单
- [ ] 覆盖率报告显示 ≥ 85%
- [ ] 所有质量门禁通过
- [ ] 学术文档 ≥ 8页，5张图表
- [ ] 代码审查问题100%修复
- [ ] 生成最终交付检查清单

## 技术提示
- 使用 `pytest-cov` 生成覆盖率
- 使用 `matplotlib` 生成学术图表
- 参考现有论文 `paper/` 目录风格
- 引用Menzly & Ozbas (2010)等经典文献

## 时间安排
- Day 1-2: 测试框架搭建
- Day 3-4: 单元测试 + 集成测试
- Day 5-6: 学术文档撰写
- Day 7: 最终验收 + 交付

## 协作接口
- 向所有Agent提供：测试框架
- 向主管提供：质量报告
- 协调：代码审查会议
