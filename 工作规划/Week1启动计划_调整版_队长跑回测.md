# Week 1启动计划：PC5因子优化（调整版）

## 📅 时间：9/6（今天）- 9/12（周四）

---

## 👥 调整后的团队分工

### 你（队长）→ 回测验证专家
**理由**：你最熟悉整个系统，回测需要全局视角

**Week 1核心任务**：
1. 设计消融实验配置
2. 执行第一批回测（Baseline + P4）
3. Day 5检查点做决策

---

### IMIS女生 → 学术文档工程师
**理由**：论文写作需要细心和文字功底

**Week 1核心任务**：
1. 文献调研（找10篇相关论文）
2. 撰写Introduction框架
3. 准备论文模板

---

### IMIS另一位 → 数据层架构师
**Week 1核心任务**：
1. 扩展GFCA，添加P1基本面特征
2. 对接CSMAR因子库（这是关键优势！）
3. 生成50只股票的特征数据

---

### CS成员 → 算法工程师
**Week 1核心任务**：
1. 实现PC5融合算子
2. 集成P4板块共振到S₀计算
3. 单元测试与代码优化

---

## 🎯 Week 1详细时间表

### Day 1（今天，9/6周六）- Kickoff

#### 上午10:00-12:00：全员会议
**议程**：
1. 你讲解项目背景与目标（30分钟）
2. 我的计划演示（30分钟）
3. 任务分配与接口定义（30分钟）
4. Q&A与技术讨论（30分钟）

**输出**：
- 每人明确自己的Week 1任务
- 约定每天晨会时间（建议每天早9点，15分钟）
- 建立协作文档（飞书/Notion）

#### 下午14:00-18:00：搭建基础框架
**你**：
- 研究现有`backtest_engine.py`
- 设计消融实验配置文件
- 准备Baseline回测脚本

**IMIS女生**：
- 文献搜索（Google Scholar关键词："factor decay", "A-share", "temporal factor"）
- 创建论文模板（LaTeX或Markdown）
- 整理现有系统的技术文档

**IMIS数据**：
- 研究现有`scoringv3.py`的GFCA代码
- 测试CSMAR API连接
- 列出可用的因子清单

**CS**：
- 创建`src/graph/pc5_fusion.py`文件
- 设计`PC5Extractor`和`PC5Fusion`类接口
- 编写单元测试框架

---

### Day 2（9/7周日）- 核心功能原型

#### 目标：实现P1+P4的基础版本

**你**：
- 跑通Baseline回测（用现有系统）
- 记录Baseline的命中率（1日/5日）
- 准备第一个消融实验配置

**IMIS女生**：
- 完成Introduction第一稿（500字）
- 整理T-NALE公式的LaTeX代码
- 准备Related Work的论文列表

**IMIS数据**（关键角色）：
```python
# 文件：src/features/csmar_features.py

class CSMARFeatureExtractor:
    """基于CSMAR因子库的特征提取器"""
    
    def __init__(self, csmar_api):
        self.api = csmar_api
        
    def extract_p1_fundamental(self, ticker, date):
        """P1: 基本面稳健性
        
        从CSMAR提取：
        - ROE（净资产收益率）
        - 资产负债率
        - 经营现金流/净利润
        """
        roe = self.api.get_financial_indicator(ticker, date, "roe")
        leverage = self.api.get_financial_indicator(ticker, date, "debt_ratio")
        cashflow_quality = self.api.get_cashflow_quality(ticker, date)
        
        # 归一化到[-1, 1]
        p1_score = self._normalize_fundamental(roe, leverage, cashflow_quality)
        return p1_score
    
    def extract_p3_momentum(self, ticker, date, windows=[5, 20, 60]):
        """P3: 多周期动量
        
        从CSMAR提取：
        - 5日/20日/60日收益率
        - 成交量确认
        """
        momentums = {}
        for w in windows:
            ret = self.api.get_return(ticker, date, window=w)
            vol_ratio = self.api.get_volume_ratio(ticker, date, window=w)
            momentums[f"{w}d"] = ret * vol_ratio  # 成交量加权
        
        # 加权平均
        p3_score = 0.5 * momentums["5d"] + 0.3 * momentums["20d"] + 0.2 * momentums["60d"]
        return np.clip(p3_score, -1.0, 1.0)
```

**CS**：
```python
# 文件：src/graph/pc5_fusion.py

class PC5Extractor:
    """PC5五维特征提取器"""
    
    def __init__(self, csmar_extractor, sector_engine, market_state):
        self.csmar = csmar_extractor
        self.sector_engine = sector_engine
        self.market_state = market_state
    
    def extract(self, ticker, date, horizon_days=5.0):
        """提取五维向量"""
        pc5 = {}
        
        # P1: 基本面（来自CSMAR）
        pc5["P1"] = self.csmar.extract_p1_fundamental(ticker, date)
        
        # P2: 情绪（如果LLM API可用）
        pc5["P2"] = self._extract_p2_sentiment(ticker, date)
        
        # P3: 动量（来自CSMAR）
        pc5["P3"] = self.csmar.extract_p3_momentum(ticker, date)
        
        # P4: 板块共振（复用现有sector_graph_engine）
        sector_state = self.sector_engine.get_sector_state(ticker)
        pc5["P4"] = self._extract_p4_sector(sector_state)
        
        # P5: 宏观周期（复用现有市场状态机）
        pc5["P5"] = self._extract_p5_macro(date)
        
        return pc5
    
    def _extract_p4_sector(self, sector_state):
        """P4: 板块共振强度"""
        if not sector_state:
            return 0.0
        
        # 板块协同广度
        breadth = sector_state.get("breadth", 0.5)
        
        # 涨停龙头加成
        has_leader = sector_state.get("has_limit_up_leader", False)
        leader_boost = 0.3 if has_leader else 0.0
        
        p4_score = (breadth - 0.5) * 2.0 + leader_boost  # 归一化到[-1, 1]
        return np.clip(p4_score, -1.0, 1.0)


class PC5Fusion:
    """PC5融合算子"""
    
    def __init__(self, weights=None):
        # 初始权重（后续可优化）
        self.weights = weights or {
            "P1": 0.20,  # 基本面
            "P2": 0.10,  # 情绪（如果无LLM，权重归零）
            "P3": 0.30,  # 动量
            "P4": 0.25,  # 板块共振
            "P5": 0.15   # 宏观
        }
    
    def fuse_to_s0(self, pc5_vector, horizon_days=5.0):
        """融合五维向量为增强版S_0"""
        s0_enhanced = 0.0
        
        for dim, value in pc5_vector.items():
            if dim not in self.weights:
                continue
            
            w = self.weights[dim]
            
            # 时效衰减（只对P2情绪和P3动量）
            if dim in ["P2", "P3"]:
                decay_factor = np.exp(-0.1 * horizon_days)
                value = value * decay_factor
            
            s0_enhanced += w * value
        
        # clip到[-1, 1]
        return float(np.clip(s0_enhanced, -1.0, 1.0))
```

---

### Day 3（9/8周一）- 第一次集成测试

#### 晨会（9:00-9:15）
- 每人汇报昨天进度
- 识别阻塞问题

#### 白天任务
**你**：
- 集成CS的PC5Fusion到回测流程
- 准备跑第一个增强版回测

**IMIS女生**：
- 撰写Methodology框架（1000字）
- 准备五维因子的定义表格

**IMIS数据**：
- 完成P1特征提取（至少20只股票测试）
- 完成P3动量提取
- 处理缺失值和异常值

**CS**：
- 完成PC5Fusion代码
- 通过单元测试
- 准备集成到`build_ranking.py`

---

### Day 4（9/9周二）- 第一批回测

#### 目标：完成Baseline vs +P4对比

**你（主力）**：
```python
# 文件：scripts/run_pc5_ablation_week1.py

CONFIGS = {
    "baseline": {
        "use_pc5": False,
        "description": "原始T-NALE系统"
    },
    "plus_p4": {
        "use_pc5": True,
        "enabled_dims": ["P4"],  # 只启用P4板块共振
        "description": "Baseline + P4板块共振"
    }
}

SECTORS = ["storage", "gold"]  # 先跑2个板块
TIME_WINDOW = "2025q2_2026q3"

for config_name, config in CONFIGS.items():
    for sector in SECTORS:
        result = run_backtest(
            sector=sector,
            time_window=TIME_WINDOW,
            config=config
        )
        save_result(f"results/{config_name}_{sector}.json", result)
```

**IMIS女生**：
- 准备实验结果展示模板
- 开始撰写Experiments章节

**IMIS数据**：
- 支持你的回测数据需求
- 修复可能的数据bug

**CS**：
- 优化回测性能（如果太慢）
- 准备统计检验函数

---

### Day 5（9/10周三）- 关键检查点 🚨

#### 晚上全员会议（19:00-21:00）

**议程**：
1. 你展示回测初步结果（30分钟）
2. 全员讨论：PC5方向是否正确？（60分钟）
3. 决策下周计划（30分钟）

**决策树**：

```
+P4命中率改进 ≥ 2% ?
├─ YES → 继续推进，Week 2做P1+P3+P5
├─ 0.5-2% → 调整为轻量版，只做P4+P3
└─ NO or 更差 → Pivot到Plan B（方法论论文）
```

**Plan B不是失败**：
- 重新定位："为什么板块共振在A股失效"的研究
- 论文价值："Negative Result"也是学术贡献
- 答辩角度：深度分析 > 性能提升

---

### Day 6-7（9/11-9/12周四-周五）- 根据决策推进

#### 如果继续推进（+P4有效）

**你**：
- 设计Week 2的完整消融实验矩阵
- 准备更多板块和时间窗口

**IMIS女生**：
- 完成Methodology章节初稿
- 准备Results章节模板

**IMIS数据**：
- 扩展到50只股票
- 准备P5宏观周期数据

**CS**：
- 添加P1和P3到融合算子
- 实现动态权重调整

#### 如果Pivot到Plan B（+P4无效）

**你**：
- 分析为什么P4无效
- 设计"失败原因"实验

**IMIS女生**：
- 调整论文标题和摘要
- 重写Introduction（强调"探索性研究"）

**IMIS数据+CS**：
- 深入调试数据质量
- 检查是否有实现bug

---

## 📊 Week 1预期输出

### 代码
- [ ] `src/features/csmar_features.py` - CSMAR特征提取器
- [ ] `src/graph/pc5_fusion.py` - PC5融合算子
- [ ] `scripts/run_pc5_ablation_week1.py` - 消融实验脚本
- [ ] `tests/test_pc5_fusion.py` - 单元测试

### 数据
- [ ] 20-50只股票的PC5向量样本
- [ ] Baseline回测结果（2个板块）
- [ ] +P4回测结果（2个板块）

### 文档
- [ ] 论文Introduction初稿（500-1000字）
- [ ] 论文Methodology框架
- [ ] Week 1工作日志

---

## 🔧 技术栈确认

### 数据源
- ✅ CSMAR因子库（你们有 - 这是巨大优势！）
- ✅ LLM embedding API（你们有）
- ✅ Tushare Pro（补充实时数据）

### 开发工具
- Git仓库：GitHub或Gitee
- 协作文档：飞书/Notion
- 代码编辑器：VSCode + Cursor/Copilot
- 回测环境：本地（如果算力不够，考虑租云服务器）

### Python环境
```bash
# 确保环境统一
python --version  # 应该是3.9+
pip install -r requirements.txt

# 关键依赖
numpy>=1.21
pandas>=1.3
scipy>=1.7
matplotlib>=3.4
pytest>=7.0
```

---

## 💡 CSMAR因子库的战略优势

你们有CSMAR是**巨大优势**，因为：

### 优势1：数据质量高
- CSMAR是学术界认可的权威数据源
- 评委看到"CSMAR"会加分（专业性）
- 数据清洗工作量大幅减少

### 优势2：因子丰富
CSMAR有现成的：
- 财务因子（ROE、ROA、负债率...）
- 市场因子（动量、反转、波动率...）
- 估值因子（PE、PB、PS...）

这意味着**P1和P3可以直接从CSMAR提取**，不需要从零计算！

### 优势3：学术背书
- 论文里写"数据来源：CSMAR"
- 评委会认为你们的研究更严谨
- 比自己爬的数据可信度高

### 建议的CSMAR使用策略
```python
# P1基本面：直接用CSMAR的Quality因子
p1_score = csmar.get_quality_factor(ticker, date)

# P3动量：直接用CSMAR的Momentum因子
p3_score = csmar.get_momentum_factor(ticker, date)

# 然后你们的创新在于：
# 1. 五维融合算子
# 2. 时效衰减机制
# 3. 与T-NALE的集成
```

---

## 🎯 今天（Day 1）的具体行动

### 立即做（接下来2小时）

#### 你：
1. 召集团队开会（线上/线下）
2. 讲解这个Week 1计划
3. 分配任务，明确接口

#### IMIS数据：
1. 测试CSMAR API连接
2. 列出可用因子清单
3. 提取1-2只股票的样本数据

#### IMIS女生：
1. 搜索3-5篇相关论文
2. 阅读现有系统的README
3. 创建论文模板文件

#### CS：
1. 创建`pc5_fusion.py`文件
2. 写出类接口定义（先不实现）
3. 创建测试文件

### 晚上做（18:00-22:00）

所有人：
- 根据下午的任务继续推进
- 遇到问题立即群里讨论
- 22:00前提交今天的代码/文档

---

## 📞 沟通机制

### 每天晨会（15分钟）
**时间**：每天早上9:00（建议）
**形式**：线上语音/视频
**内容**：
- 每人1分钟汇报昨天完成+今天计划
- 识别阻塞问题
- 你做技术决策

### 随时沟通（群聊）
**原则**：
- 遇到技术问题立即问
- 不要憋着超过1小时
- 相互帮助，不要单打独斗

### 关键节点会议
- Day 1（今天）：Kickoff，2小时
- Day 5（9/10）：检查点决策会，2小时
- Day 7（9/12）：Week 1总结会，1小时

---

## ✅ 启动检查清单

在今天会议结束前，确认：

- [ ] 每人明确自己的Week 1任务
- [ ] 代码仓库创建完成，每人有权限
- [ ] 协作文档建立（任务看板）
- [ ] CSMAR API测试通过
- [ ] 每人的开发环境配置完成
- [ ] 约定好每天晨会时间
- [ ] 建立微信/飞书群，保持沟通

---

## 🔥 最后的话

### 给你（队长）
1. **你的角色是指挥官**：不要陷入具体代码细节，关注全局
2. **Day 5是最关键节点**：如果P4无效，立即pivot，不要硬扛
3. **回测是你的主战场**：你最熟悉系统，这个任务只能你做

### 给团队
1. **不要怕失败**：如果PC5无效，"为什么无效"也是好论文
2. **频繁沟通**：遇到问题立即说，不要等到卡住才说
3. **Vibe Coding**：大胆用AI辅助，但要理解AI生成的代码

### 给IMIS女生（论文负责人）
1. **你的输出是最终交付物**：论文和PPT决定比赛成绩
2. **Week 1可以慢一点**：先做文献调研和框架，不急着写
3. **Week 2-3是你的主场**：需要快速产出6-8页论文

---

## 现在，告诉我

1. **你认可这个Week 1计划吗？**
2. **今天能召集团队开会吗？**（几点？）
3. **需要我现在帮你生成什么？**
   - A. 4个人的详细任务卡（每人5-10页）
   - B. CSMAR特征提取器的代码模板
   - C. 消融实验配置文件
   - D. 全部都要
   - E. 其他

**告诉我你的决定，我们立即开工！** 🚀
