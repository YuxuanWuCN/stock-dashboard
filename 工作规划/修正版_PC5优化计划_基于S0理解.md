# 修正版：S₀原生得分优化计划（基于PC5理解）

## 核心目标
优化T-NALE公式中的S₀（原生事实得分）计算，使其更具A股时效性特征

## 当前S₀的计算路径

```
原始因子 → GFCA坐标对齐 → composite_score → S₀ → T-NALE传导
          ↓
    align_gfca_coordinates():
    1. 截面Z-Score标准化
    2. tanh平滑过滤 → [-1,1]
    3. 注入Nowcasting减值惩罚
```

## 问题诊断回顾
- 命中率49.08%（低于随机）
- 前半段71.62% vs 后半段44.55%（时间失效）
- 根本原因：因子方向随市场环境变化失效

---

## ✅ 优化方案：五维增强S₀（PC5-Enhanced）

### 不是推翻重来，而是在现有GFCA基础上增强

当前GFCA只考虑：
```python
composite_score = Σ weight_k * tanh(z_k)  # 静态因子加权
```

**优化为五维时效加权**：
```python
S_0_enhanced = w1*P1_fundamental + w2*P2_sentiment*decay(t) 
             + w3*P3_momentum*exp(-λ*h) + w4*P4_sector_breadth 
             + w5*P5_macro_regime
```

### 五维定义（基于现有模块）

#### P1: 基本面稳健性（已有GFCA因子）
- 来源：现有GFCA的HML、Quality、Profitability维度
- **复用**：`raw_factor_df`中的基本面列
- 新增：财务质量评分（ROE、负债率、现金流）

#### P2: 市场情绪传导（已有部分）
- 来源：现有的`self_score`（大模型文本情感得分）
- **增强**：添加时效衰减 `decay(t)`
- 新增：新闻发布时间戳追踪

#### P3: 技术动量（已有GFCA.MOM）
- 来源：现有GFCA的Momentum因子
- **增强**：多周期动量（5日/20日/60日）
- 新增：成交量确认机制

#### P4: 板块共振（已有sector_graph_engine）
- 来源：`sector_graph_engine.py`的板块协同广度
- **复用**：涨停龙头溢出机制
- 新增：融入S₀计算而非后处理

#### P5: 宏观周期（已有市场状态机）
- 来源：现有的市场状态机（牛市/熊市/震荡）
- **复用**：Trend Gate的C浪阻断逻辑
- 新增：政策敏感度评分

---

## 👥 修正后的团队分工

### Agent 1: GFCA增强工程师（2天）
**不是从零开始，而是扩展现有模块**

#### 任务
1. **扩展`scoringv3.py`的`align_gfca_coordinates`方法**
   - 添加时效衰减参数
   - 支持动态权重调整
   
2. **实现五维特征提取器**（`src/features/pc5_extractor.py`）
   ```python
   class PC5Extractor:
       def extract_P1_fundamental(self, ticker, gfca_coords):
           # 复用现有GFCA的HML/Quality
           
       def extract_P2_sentiment(self, ticker, llm_score, timestamp):
           # 复用现有self_score + 添加衰减
           
       def extract_P3_momentum(self, ticker, gfca_coords):
           # 复用现有MOM + 多周期
           
       def extract_P4_sector(self, ticker, sector_engine):
           # 调用现有sector_graph_engine
           
       def extract_P5_macro(self, ticker, market_state):
           # 调用现有市场状态机
   ```

3. **数据接口适配**
   - 修改`build_ranking.py`调用新的S₀计算

#### 验收标准
- [ ] 五维提取器通过单元测试
- [ ] 不破坏现有GFCA接口（向后兼容）
- [ ] 生成50只股票的PC5向量样本

---

### Agent 2: 融合算法工程师（2-3天）

#### 任务
1. **实现加权融合策略**（`src/graph/pc5_fusion.py`）
   ```python
   class PC5Fusion:
       def fuse_to_s0(self, pc5_vector, horizon_days):
           """将五维向量融合为增强版S_0"""
           # 核心：动态权重 + 时效调整
   ```

2. **集成滚动方向校准**
   - 修改`rolling_direction_calibration.py`
   - 对PC5的每个维度独立校准方向
   - 如果某维度失效，动态降权

3. **消融实验设计**
   - Baseline: 原GFCA
   - +P4: 原GFCA + 板块共振
   - +P4+P3: 再加动量增强
   - Full PC5: 五维完整

#### 验收标准
- [ ] 融合算子通过边界测试
- [ ] 消融实验代码就绪
- [ ] 权重优化策略文档

---

### Agent 3: 回测验证专家（3天）

#### 任务（调整为更现实的规模）
1. **基准对比实验**（12个，不是60个）
   - 3个板块 × 4个配置 = 12个实验
   - 配置：Baseline, +P4, +P4+P3, Full PC5

2. **关键指标追踪**
   - 命中率（1日/5日）
   - 分段稳定性（前后半段对比）
   - 夏普比率、最大回撤

3. **统计显著性检验**
   - 配对t检验（Baseline vs PC5）
   - 不做多重检验的p-hacking

#### 验收标准
- [ ] 12个回测全部完成
- [ ] 至少1个配置显著优于Baseline
- [ ] 诚实记录失败案例

---

### Agent 4: 学术文档工程师（贯穿全周）

#### 任务（聚焦学术输出）
1. **学术论文撰写**（`docs/papers/pc5_enhanced_s0.md`）
   ```markdown
   # PC5-Enhanced S₀: A Time-Aware Composite Factor for A-Share Forecasting
   
   ## Abstract
   We propose PC5-Enhanced S₀, a five-dimensional composite factor 
   that improves the raw score calculation in Temporal-NALE framework...
   
   ## 1. Introduction
   ### 1.1 A股市场的因子时效性挑战
   ### 1.2 现有GFCA的局限性
   ### 1.3 本文贡献
   
   ## 2. Methodology
   ### 2.1 五维因子定义
   ### 2.2 时效衰减机制
   ### 2.3 融合算子设计
   
   ## 3. Experiments
   ### 3.1 数据与设置
   ### 3.2 消融实验
   ### 3.3 统计检验
   
   ## 4. Results
   [诚实展示，即使改进有限]
   
   ## 5. Discussion
   ### 5.1 成功案例分析
   ### 5.2 失败案例剖析
   ### 5.3 局限性
   
   ## 6. Conclusion
   ```

2. **质量检查**
   - 代码覆盖率 ≥ 80%（不强求85%）
   - 所有单元测试通过
   - 代码审查记录

3. **可视化图表**
   - 五维向量热力图
   - 命中率时序对比
   - 消融实验结果图

#### 验收标准
- [ ] 学术论文 ≥ 6页（不强求8页）
- [ ] 包含至少3张原创图表
- [ ] 诚实讨论局限性
- [ ] 引用文献 ≥ 8篇

---

## 📅 修正后的时间线

### Day 1-2: 基础扩展
- Agent 1: 扩展GFCA，实现五维提取器
- Agent 2: 设计融合算子原型
- Agent 3: 搭建回测框架
- Agent 4: 开始文献调研

**里程碑**: 可以生成10只股票的PC5-Enhanced S₀

### Day 3-4: 核心验证
- Agent 1: 完成50只股票数据
- Agent 2: 完成融合算子 + 消融实验设计
- Agent 3: 完成前6个回测（Baseline vs +P4 vs +P4+P3）
- Agent 4: 完成论文Introduction和Methodology初稿

**里程碑**: 消融实验揭示哪些维度有效

### Day 5-6: 全面回测与撰写
- Agent 1: 支持调试与数据修复
- Agent 2: 根据结果调优权重
- Agent 3: 完成全部12个回测
- Agent 4: 完成Results和Discussion

**里程碑**: 确定最佳配置，完成学术文档

### Day 7: 交付与总结
- 所有Agent：代码审查与文档润色
- Agent 4: 生成最终学术PDF

**里程碑**: 交付学术论文 + 代码实现

---

## 🎯 成功标准（现实版）

### 最低标准（Must Have）
- [ ] PC5五维提取器实现完整
- [ ] 至少在1个消融实验中看到改进信号（哪怕+2%）
- [ ] 学术论文完整（≥6页，包含诚实的失败讨论）
- [ ] 代码通过基础测试

### 期望标准（Should Have）
- [ ] 命中率提升到53-55%
- [ ] 前后半段稳定性改善（差异<10%）
- [ ] 学术论文达到会议投稿质量
- [ ] 消融实验清晰展示各维度贡献

### 卓越标准（Nice to Have）
- [ ] 命中率提升到58%+
- [ ] 通过统计显著性检验
- [ ] 论文可直接投稿学术会议

---

## 🚨 风险控制（诚实版）

### 预设场景应对

**场景A：PC5改进明显（概率30%）**
- 命中率提升到55%+
- 行动：深入挖掘成功原因，准备答辩材料

**场景B：PC5改进微弱（概率50%）**
- 命中率提升到51-53%
- 行动：
  - 诚实在论文Discussion中说明局限性
  - 强调"方法论贡献"而非"性能提升"
  - 展示消融实验的洞察（哪些维度有效）

**场景C：PC5无改进或更差（概率20%）**
- 命中率仍在49-51%
- 行动：
  - **不隐瞒结果**，在论文中诚实报告
  - 分析失败原因（共线性？过拟合？数据质量？）
  - 提出"Negative Result"论文投稿
  - 保留原系统，将PC5作为"探索性尝试"记录

### 底线原则
1. **不伪造数据**：宁可承认失败，不编造数字
2. **不刷p值**：不在12个实验里cherry-pick最好的报告
3. **诚实归因**：如果改进来自bug修复而非PC5，明确说明

---

## 💡 为什么这个方案更可行？

### 对比原方案的改进

| 维度 | 原方案 | 修正方案 |
|------|--------|----------|
| **概念清晰度** | PC5未定义 | PC5=S₀，明确指向 |
| **工作量** | 从零构建五维系统 | 扩展现有GFCA模块 |
| **实验规模** | 60个回测（不现实） | 12个回测（可行） |
| **成功概率** | 10%大获成功 | 30%明显改进 |
| **失败应对** | 无Plan B | 有Negative Result策略 |
| **学术价值** | 依赖性能提升 | 方法论+消融实验 |

### 核心优势
1. **复用现有代码**：80%的功能已实现
2. **消融实验清晰**：可以精确归因哪个维度有效
3. **学术输出保底**：即使性能无改进，方法论也有价值
4. **时间可控**：不依赖60个回测的赌博

---

## 🔥 回答你的三个关键点

### 1. "PC5是数学公式中占据最重要部分，时效性最低"
✅ **理解正确**：PC5 = S₀，权重(1-α)=0.6，是T-NALE的基础输入

### 2. "诊断已经跑完了"
✅ **接受**：那我们直接进入优化阶段，不重复诊断

### 3. "至少保证能产出一个比现在更好的学术文档"
✅ **可承诺**：
- 即使命中率无改进，消融实验本身就是学术贡献
- Negative Result也可以发表（ICML有专门的track）
- 方法论创新（五维+时效）可以单独讨论

---

## 最终建议

**启动修正版计划，但加入两个保险**：

1. **Day 3检查点**：如果消融实验显示所有维度都无效，立即pivot到"方法论论文"而非"性能提升论文"

2. **学术输出双轨**：
   - Track A: 性能提升论文（如果PC5有效）
   - Track B: 方法论探索论文（如果PC5无效但有洞察）

**这样无论结果如何，都有学术产出。**
