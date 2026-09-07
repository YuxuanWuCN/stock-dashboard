# Week 1聚焦计划：修好PC5因子（S₀增强版）

## 🎯 唯一目标
**把S₀（原生事实得分）从单一GFCA评分 → 升级为五维增强版**

---

## 📊 当前问题诊断

### 现状
```python
# 现在的S₀计算（scoringv3.py）
S_0 = GFCA.composite_score  # 单一得分，来自多因子加权
```

### 问题
1. **时效性不足**：所有因子用同一个权重，不区分时效
2. **板块信息缺失**：没有利用sector_graph_engine的板块共振数据
3. **动量单一**：只有一个Momentum维度，没有多周期

### 目标
```python
# Week 1要实现的新S₀
S_0_enhanced = PC5Fusion(
    P1=基本面稳健性,      # 从CSMAR提取
    P2=情绪传导,          # 从LLM API提取（可选）
    P3=多周期动量,        # 从CSMAR提取
    P4=板块共振强度,      # 从sector_graph_engine提取
    P5=宏观周期因子       # 从市场状态机提取
)
```

---

## 👥 Week 1任务分配（聚焦版）

### 🔵 IMIS数据（核心角色）
**任务**：对接CSMAR，提取P1和P3

#### P1：基本面稳健性（2天）
```python
# 文件：src/features/csmar_p1_fundamental.py

def extract_p1_fundamental(ticker, date):
    """从CSMAR提取基本面稳健性得分
    
    指标：
    1. ROE（净资产收益率）- 盈利能力
    2. 资产负债率 - 财务稳健
    3. 经营现金流/净利润 - 现金质量
    
    返回：[-1, 1]归一化得分
    """
    # CSMAR API调用
    roe = csmar_api.get_financial_ratio(ticker, date, "roe")
    debt_ratio = csmar_api.get_financial_ratio(ticker, date, "debt_asset_ratio")
    cash_quality = csmar_api.get_cashflow_ratio(ticker, date, "cfo_ni")
    
    # 归一化（具体公式Week 1确定）
    p1_score = normalize_fundamental(roe, debt_ratio, cash_quality)
    return p1_score
```

#### P3：多周期动量（2天）
```python
# 文件：src/features/csmar_p3_momentum.py

def extract_p3_momentum(ticker, date):
    """从CSMAR提取多周期动量得分
    
    周期：
    1. 5日动量（短期）
    2. 20日动量（中期）
    3. 60日动量（长期）
    
    成交量确认：放量上涨才算有效动量
    """
    mom_5d = csmar_api.get_return(ticker, date, window=5)
    mom_20d = csmar_api.get_return(ticker, date, window=20)
    mom_60d = csmar_api.get_return(ticker, date, window=60)
    
    vol_ratio = csmar_api.get_volume_ratio(ticker, date, window=5)
    
    # 加权：短期权重大，长期权重小
    p3_score = 0.5 * mom_5d + 0.3 * mom_20d + 0.2 * mom_60d
    p3_score *= vol_ratio  # 成交量确认
    
    return np.clip(p3_score, -1.0, 1.0)
```

**交付物**：
- [ ] `src/features/csmar_p1_fundamental.py`
- [ ] `src/features/csmar_p3_momentum.py`
- [ ] 20只股票的测试数据
- [ ] 单元测试

---

### 🟢 CS成员（核心角色）
**任务**：实现PC5融合算子 + 集成P4

#### 任务1：P4板块共振提取（1天）
```python
# 文件：src/features/sector_p4_resonance.py

def extract_p4_sector_resonance(ticker, date, sector_engine):
    """从现有sector_graph_engine提取板块共振强度
    
    指标：
    1. 板块协同广度（sector breadth）
    2. 涨停龙头加成
    3. 板块内相对强度
    """
    sector_state = sector_engine.get_sector_state_by_ticker(ticker, date)
    
    if not sector_state:
        return 0.0
    
    # 板块协同广度（0.5是中性）
    breadth = sector_state.get("breadth", 0.5)
    
    # 涨停龙头加成
    has_limit_up = sector_state.get("has_limit_up_leader", False)
    leader_boost = 0.3 if has_limit_up else 0.0
    
    # 标的在板块内的相对强度
    relative_strength = sector_state.get("ticker_rank", 0.5)
    
    # 综合得分
    p4_score = (breadth - 0.5) * 2.0 + leader_boost + (relative_strength - 0.5)
    
    return np.clip(p4_score, -1.0, 1.0)
```

#### 任务2：P5宏观周期提取（1天）
```python
# 文件：src/features/macro_p5_cycle.py

def extract_p5_macro_cycle(date, market_state_engine):
    """从现有市场状态机提取宏观周期得分
    
    市场状态：
    - 牛市（Bull）：+0.5 to +1.0
    - 震荡（Neutral）：-0.2 to +0.2
    - 熊市（Bear）：-1.0 to -0.5
    
    额外考虑：
    - Trend Gate是否触发C浪阻断（严重-1.0）
    """
    state = market_state_engine.get_current_state(date)
    
    state_score_map = {
        "bull": 0.7,
        "neutral": 0.0,
        "bear": -0.7
    }
    
    p5_score = state_score_map.get(state["phase"], 0.0)
    
    # C浪阻断惩罚
    if state.get("c_wave_blocked", False):
        p5_score = -1.0
    
    return p5_score
```

#### 任务3：PC5融合算子（2天）
```python
# 文件：src/graph/pc5_fusion.py

class PC5Fusion:
    """PC5五维融合算子
    
    核心公式：
    S_0_enhanced = Σ w_i * P_i * decay_i(h)
    
    其中：
    - w_i: 静态权重（初始等权，后续可优化）
    - P_i: 第i维得分
    - decay_i(h): 时效衰减函数
    """
    
    def __init__(self):
        # 初始权重（后续Week 2可优化）
        self.weights = {
            "P1": 0.25,  # 基本面（时效最慢）
            "P2": 0.10,  # 情绪（时效最快）
            "P3": 0.30,  # 动量（时效中等）
            "P4": 0.25,  # 板块共振（时效中等）
            "P5": 0.10   # 宏观周期（时效慢）
        }
        
        # 半衰期（天）
        self.half_lives = {
            "P1": 90,   # 基本面3个月
            "P2": 3,    # 情绪3天
            "P3": 10,   # 动量10天
            "P4": 7,    # 板块共振7天
            "P5": 60    # 宏观周期2个月
        }
    
    def fuse(self, pc5_vector, horizon_days=5.0):
        """融合五维向量为增强版S_0
        
        参数：
        - pc5_vector: dict, {"P1": 0.5, "P2": 0.3, ...}
        - horizon_days: 预测视界（天）
        
        返回：
        - s0_enhanced: float, [-1.0, 1.0]
        """
        s0_enhanced = 0.0
        
        for dim in ["P1", "P2", "P3", "P4", "P5"]:
            value = pc5_vector.get(dim, 0.0)
            weight = self.weights[dim]
            
            # 时效衰减
            decay = self._exponential_decay(
                horizon_days,
                self.half_lives[dim]
            )
            
            s0_enhanced += weight * value * decay
        
        return float(np.clip(s0_enhanced, -1.0, 1.0))
    
    def _exponential_decay(self, t, half_life):
        """指数半衰期衰减"""
        return np.exp(-np.log(2) * t / half_life)
```

**交付物**：
- [ ] `src/features/sector_p4_resonance.py`
- [ ] `src/features/macro_p5_cycle.py`
- [ ] `src/graph/pc5_fusion.py`
- [ ] 单元测试全部通过

---

### 🟡 你（队长+回测专家）
**任务**：验证PC5因子是否修好了

#### 任务1：集成PC5到build_ranking（2天）
```python
# 修改：src/build_ranking.py

# 原来的代码（第890行左右）
nale_payload = sector_engine.get_nale_network_payload(code, category, final_forecast)
r["nale_network"] = nale_payload

# 新增：计算PC5增强版S_0
from src.graph.pc5_fusion import PC5Fusion, PC5Extractor

pc5_extractor = PC5Extractor(
    csmar_api=csmar_api,
    sector_engine=sector_engine,
    market_state_engine=market_state_engine
)

pc5_fusion = PC5Fusion()

# 提取五维向量
pc5_vector = pc5_extractor.extract(code, current_date)

# 融合为S_0
s0_enhanced = pc5_fusion.fuse(pc5_vector, horizon_days=5.0)

# 替换原来的S_0
# 原来：S_0 = gfca_coords.composite_score
# 现在：S_0 = s0_enhanced

# 然后传给T-NALE引擎
nale_result = tnale_engine.calculate_temporal_nale(
    node_scores={code: s0_enhanced},  # 用新的S_0
    adjacency_matrix=W,
    ticker_list=[code],
    horizon_days=5.0
)
```

#### 任务2：快速验证（2天）
```python
# 文件：scripts/quick_test_pc5.py

# 不跑完整回测，只验证PC5因子本身

# 测试1：数值合理性
for ticker in sample_tickers[:10]:
    pc5 = extractor.extract(ticker, date)
    s0_new = fusion.fuse(pc5, horizon_days=5.0)
    s0_old = gfca.get_composite_score(ticker, date)
    
    print(f"{ticker}: S0_old={s0_old:.3f}, S0_new={s0_new:.3f}")
    
    # 检查：
    # 1. 新S0是否在[-1, 1]
    # 2. 新S0和旧S0的相关性（应该>0.5，但不是1.0）
    # 3. 新S0是否有更高的区分度（标准差更大）

# 测试2：时效性检查
for h in [1, 5, 10, 20]:
    s0_h = fusion.fuse(pc5, horizon_days=h)
    print(f"horizon={h}d: S0={s0_h:.3f}")
    
    # 检查：S0应该随h增大而衰减（如果动量和情绪为正）

# 测试3：板块共振验证
# 找一个有涨停龙头的板块（如存储板块，德明利涨停那天）
date_limit_up = "2026-08-15"  # 假设这天德明利涨停
for ticker in storage_sector_tickers:
    pc5 = extractor.extract(ticker, date_limit_up)
    print(f"{ticker}: P4={pc5['P4']:.3f}")
    
    # 检查：同板块股票的P4都应该>0，且德明利最高
```

**交付物**：
- [ ] PC5集成到`build_ranking.py`
- [ ] 快速验证脚本通过
- [ ] 验证报告（数值合理性+时效性+板块共振）

---

### 🔴 IMIS女生（支援角色）
**任务**：Week 1不写论文，先做文献调研+数据支持

#### 任务1：文献调研（2天）
搜索关键词：
- "factor decay" + "China A-share"
- "temporal factor" + "stock prediction"
- "multi-factor model" + "time-varying"

目标：找到5-10篇相关论文，整理成文献综述表格

#### 任务2：数据支持（2-3天）
协助IMIS数据：
- 处理CSMAR返回的缺失值
- 整理测试用的股票清单（20-50只）
- 制作数据质量报告

**交付物**：
- [ ] 文献综述表格（10篇论文）
- [ ] 测试股票清单（Excel）
- [ ] 数据质量报告（Markdown）

---

## 📅 Week 1时间表（简化版）

### Day 1-2（周六-周日）：框架搭建
- IMIS数据：CSMAR API测试，P1原型
- CS：P4+P5提取器原型，PC5Fusion框架
- 你：研究现有代码，设计集成方案
- IMIS女生：文献搜索，股票清单

**里程碑**：5个文件创建完成，接口定义清晰

### Day 3-4（周一-周二）：功能实现
- IMIS数据：完成P1+P3，测试20只股票
- CS：完成P4+P5+PC5Fusion，单元测试通过
- 你：集成到build_ranking.py
- IMIS女生：处理数据缺失值

**里程碑**：可以生成10只股票的新S₀

### Day 5（周三）：验证与决策 🚨
- 你：运行quick_test_pc5.py
- 全员：晚上开会评估结果

**关键问题**：
1. 新S₀数值合理吗？（[-1,1]，区分度高）
2. 时效性体现了吗？（horizon越大，衰减越明显）
3. P4板块共振有效吗？（涨停日P4确实>0）

**决策**：
- ✅ 3个问题都YES → Week 2跑完整回测
- ⚠️ 部分YES → 调整有问题的维度
- ❌ 都NO → 回到原GFCA，分析失败原因

### Day 6-7（周四-周五）：调试与优化
- 根据Day 5结果调整
- 修复bug
- 准备Week 2的完整回测

---

## ✅ Week 1成功标准

### 最低标准（Must Have）
- [ ] 5个特征提取器代码完成（P1-P5）
- [ ] PC5Fusion算子实现并通过测试
- [ ] 可以为任意股票生成新的S₀
- [ ] 数值验证通过（合理性+时效性+板块共振）

### 期望标准（Should Have）
- [ ] 新S₀和旧S₀相关性在0.5-0.8（有改进但不是完全不同）
- [ ] 新S₀的标准差>旧S₀（区分度更高）
- [ ] P4在涨停日确实>0.5（板块共振有效）
- [ ] 单元测试覆盖率>70%

### 卓越标准（Nice to Have）
- [ ] 完成50只股票的数据生成
- [ ] 代码重构完成，注释清晰
- [ ] 文档完整（每个函数有docstring）

---

## 🚨 Week 1风险控制

### 风险1：CSMAR API限流
**症状**：请求过多被限制

**应对**：
- 添加缓存机制（本地保存已请求的数据）
- 降低测试股票数量（从50只降到20只）
- 分批请求（每次请求间隔1秒）

### 风险2：P4/P5集成困难
**症状**：现有sector_graph_engine接口不兼容

**应对**：
- 先跳过P4/P5，只做P1+P3
- Week 2再补P4/P5
- 降级为"三维PC3"系统

### 风险3：Day 5验证失败
**症状**：新S₀数值不合理或没有改进

**应对**：
- 不要硬扛，立即分析原因
- 可能是权重不对 → 调整weights
- 可能是半衰期不对 → 调整half_lives
- 可能是某个维度有bug → 单独调试该维度

---

## 🔧 技术细节：如何修改现有代码

### 修改点1：scoringv3.py
```python
# 原来（第106行左右）
comp_score = float(np.clip(weighted_sum, -1.0, 1.0))
results[ticker] = GFCACoordinates(
    ticker=ticker,
    coordinates=coords,
    composite_score=comp_score,  # 这是旧S₀
    raw_loadings=raw_vals
)

# 改为
comp_score_old = float(np.clip(weighted_sum, -1.0, 1.0))

# 新增：计算PC5增强版S₀
pc5_vector = pc5_extractor.extract(ticker, current_date)
comp_score_new = pc5_fusion.fuse(pc5_vector, horizon_days=5.0)

results[ticker] = GFCACoordinates(
    ticker=ticker,
    coordinates=coords,
    composite_score=comp_score_new,  # 用新S₀替换
    composite_score_old=comp_score_old,  # 保留旧S₀用于对比
    pc5_vector=pc5_vector,  # 保存五维向量
    raw_loadings=raw_vals
)
```

### 修改点2：build_ranking.py
```python
# 原来（第890行左右）
# 直接用GFCA的composite_score作为S_0传给T-NALE

# 改为
# 已经在scoringv3.py里替换了，这里不需要改
# 但要确保传给T-NALE的node_scores用的是新S₀
```

---

## 🎯 今天（Day 1）立即做的事

### 1. 召集团队会议（1小时）
**时间**：今天晚上（建议19:00-20:00）

**议程**：
1. 你讲解：为什么Week 1只修PC5因子（10分钟）
2. 分配任务：每人明确自己的角色（30分钟）
3. 技术讨论：CSMAR API怎么用、接口怎么定义（20分钟）

### 2. 测试CSMAR连接（30分钟）
```python
# 让IMIS数据现在就测试
import csmar_api

# 测试1：能否连接
client = csmar_api.connect(api_key="你的key")

# 测试2：能否获取数据
roe = client.get_financial_ratio("000001.SZ", "2026-08-01", "roe")
print(f"ROE: {roe}")

# 测试3：查看可用因子
available_factors = client.list_factors()
print(f"可用因子：{available_factors}")
```

### 3. 创建代码框架（1小时）
所有人：
- 创建自己负责的.py文件
- 写出函数签名（先不实现）
- 写出单元测试的框架

---

## 💡 为什么Week 1只修PC5因子？

### 聚焦的好处
1. **降低复杂度**：不考虑回测、论文、PPT，只聚焦技术
2. **快速验证**：Day 5就能知道PC5是否有效
3. **容易调试**：如果有问题，马上能定位
4. **团队协作简单**：每人的任务清晰，接口明确

### Week 2再做什么？
如果PC5修好了：
- 你：跑完整回测（12-30个实验）
- IMIS女生：写论文
- IMIS数据：扩展到更多股票
- CS：优化性能

如果PC5没修好：
- 全员：分析原因，调整方案
- 可能降级为"PC3"（只做P1+P3+P4）
- 或pivot到Plan B（方法论论文）

---

## 现在告诉我

1. **你认可这个"Week 1只修PC5因子"的计划吗？**

2. **今天晚上能开会吗？**（几点？）

3. **IMIS数据现在能测试CSMAR连接吗？**

4. **你需要我现在生成什么代码模板？**
   - A. CSMAR特征提取器（P1+P3）
   - B. PC5Fusion算子
   - C. 快速验证脚本
   - D. 全部都要

**告诉我，我立即帮你生成！** 🚀
