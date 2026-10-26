# 规范 022：NALE 时效动态连续卷积与事件感知双波峰原型系统 (Refined Temporal NALE & Event-Aware Dynamic Alpha Prototype)

**功能标识**：`022-refined-temporal-nale`  
**关联分支**：`022-refined-temporal-nale`  
**对应工件目录**：`specs/022-refined-temporal-nale/`  

---

## 1. 概述与核心动机 (Overview & Motivation)

在 Rainbow-FinGPT v4.0 的理论卡片（Card 2: Temporal NALE）中，时空连续图卷积算子与双波峰动态耦合参数 $\alpha(t; \tau, \sigma, H)$ 是全系统的核心理论创新点：
$$S_i(t, h) = (1 - \alpha_i(t)) \cdot \left[ S_{0, i}(t) \cdot \exp\left( -\frac{\ln 2}{H_i} \cdot h \right) \right] + \alpha_i(t) \cdot \sum_{j} W_{ji} \cdot K_{\text{lag}}(h - \tau_{ji}, \sigma_{ji}) \cdot \left[ S_{0, j}(t_j) \cdot \exp\left( -\frac{\ln 2}{H_j} \cdot (t - t_j) \right) \right]$$

然而在既有实现中存在三项关键缺陷：
1. **事件催化年龄（Node Ages）粗暴或缺失**：部分接口未传 `node_ages` 或简单用 20 日收益极值近似，导致横截面衰减因子退化为常数标量并在截面排名（Rank Standardize）中被完全约去；
2. **双波峰时滞与衰减参数硬编码**：情绪半衰期 $H=3\text{d}$、物理时滞 $\tau=14\text{d}$、高斯带宽 $\sigma=5\text{d}$ 以及动态权重均为人工常量，未在真实 A 股数据上自适应学习；
3. **缺乏独立的原型评估底座**：需要一个在 `scratch/` 隔离运行、连接 CSMAR 真实 299 标的面板的闭环原型，验证时效动态调整是否能显著提升未来 5d/10d 截面 Rank IC 与多头超额。

---

## 2. 需求规范 (Functional Requirements)

### 2.1 事件感知节点年龄跟踪器 (Event-Aware Node Aging Tracker)
- **REQ-022-01 [点时因果年龄]**：输入每日量价截面，当标的出现关键催化（涨停封板、放量突破 $\text{Volume} > 2.0 \times \text{MA20}$ 且涨幅 $>4.0\%$，或财报/研报事件）时，将该节点的事件年龄重置为 $t_{\text{age}} = 0.0$；
- **REQ-022-02 [连续时间衰减推进]**：无新催化事件时，节点年龄按真实交易日步长递增：$t_{\text{age}, \tau} = t_{\text{age}, \tau-1} + 1.0$；
- **REQ-022-03 [截面异质分化保证]**：在任何评估截面 $T$，标的池内的 $t_{\text{age}}$ 必须存在截面离散度（$\text{std}(t_{\text{age}}) > 1.0$），保证信息衰减因子 $2^{-t_{\text{age}} / H}$ 在截面上不会被除法或排序对消。

### 2.2 学习型双波峰动态 Alpha 耦合引擎 (Learned Dynamic Temporal Alpha)
- **REQ-022-04 [连续时变公式]**：动态耦合强度遵循有界凸组合：
  $$\alpha(t) = \text{clip}\left( \alpha_{\text{base}} + \alpha_{\text{sentiment}} \cdot 2^{-t / H_{\text{sentiment}}} + \alpha_{\text{physical}} \cdot \exp\left( -\frac{(t - \tau)^2}{2\sigma^2} \right), \alpha_{\text{min}}, \alpha_{\text{max}} \right)$$
- **REQ-022-05 [滚动 Walk-Forward 拟合]**：在训练窗口（126 交易日）内，以最大化向前 5 日截面 Rank IC（或最小化残差均方误差 MSE）为目标，使用 L-BFGS-B 或网格寻优，自适应学习产业链内部与跨链的最佳时滞均值 $\tau^*$、带宽 $\sigma^*$ 和情绪分量权重；
- **REQ-022-06 [防前视与隔离期]**：学习过程必须严格施加 6 交易日的 Purged 隔离窗，禁止使用未来收益信息。

### 2.3 双轨消融对比与统计显著性检验 (Empirical Ablation & Significance)
- **REQ-022-07 [四基准并列对照]**：在真实 CSMAR 299 标的主面板上并行输出：
  1. Base-0: 经典静态 NALE ($\alpha=0.4$ 固定)；
  2. Base-1: 硬编码参数 T-NALE (固定 $\tau=14, \sigma=5$)；
  3. Base-2: 启发式动态 Alpha T-NALE；
  4. Model-Learned: 本规范实现的事件感知学习型 T-NALE。
- **REQ-022-08 [计量与统计门禁]**：计算截面 Rank IC、ICIR、Newey-West HAC $t$ 统计量、Top 10% 多头年化超额收益与 Deflated Sharpe Ratio (DSR)。

### 2.4 可解释性可视化与冲激响应曲面 (Impulse Response Gallery)
- **REQ-022-09 [动态曲线生成]**：输出标准双波峰 $\alpha(t)$ 动力学轨迹图（情绪峰 $t \le 2\text{d}$、验证谷底 $t \in [3, 10]\text{d}$、物理到货共振峰 $t \approx \tau$）；
- **REQ-022-10 [学术图谱落盘]**：将高清可视化图表生成至 `reports/figures/refined_temporal_nale/`。

---

## 3. 验收标准 (Acceptance Criteria)

1. **截面离散性验证**：在任意抽样截面上，$t_{\text{age}}$ 保持异质，衰减后得分与静态原始得分的相关系数 $\rho < 0.98$（证明时效衰减未被截面约去）；
2. **真实样本外 IC 提升**：在 2024–2026 CSMAR 真实面板测试折上，`Model-Learned` 的 5 日 Rank IC 均值高于经典静态 NALE，且 Newey-West $t > 1.96$；
3. **零生产污染**：原型验证代码与中间矩阵全部存放于 `scratch/refined_temporal_nale/`，不修改既有 `src/` 生产模块，直到验收达标。
