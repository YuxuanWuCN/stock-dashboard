# 阶段 0 研究报告：NALE 时效动态连续卷积与事件感知双波峰原型 (research.md)

**功能**：`022-refined-temporal-nale`  
**日期**：2026-10-23  

---

## 1. 核心技术决策与调研结果

### 研究项 1：点时因果事件催化年龄（Node Age）追踪架构

- **决策**：构建因果点时状态机 `EventAgeTracker`，按交易日单向滚动推进。
  - **触发重置（Age = 0）**：
    1. 触及或封死涨停板（`hit_limit > 0` 且收盘在最高价，或主板 $\ge 9.8\%$ / 双创 $\ge 19.8\%$）；
    2. 量价异动脉冲（当日成交额 $\ge 2.0 \times \text{MA20}$ 且日收益率 $\ge +4.0\%$）。
  - **自然流逝推进**：无催化日，历史年龄递增 $t_{\text{age}, \tau} = t_{\text{age}, \tau-1} + 1.0$，上限截断至 60 天（超过 60 天视为进入长效稳态）。
- **理由**：
  1. 彻底解决过去“未传 node_ages 导致截面归一化完全对消”的严重缺陷；
  2. 保证每个截面上各股票的 age 呈现自然的离散分布（新突破股为 0-1 天，老题材股为 15-30 天），使半衰期衰减因子 $2^{-t_{\text{age}} / H}$ 真正起到“区分新旧动能”的截面选股作用；
  3. 严格遵循点时因果性（Point-in-Time），只用 $t-1$ 日及之前的已实现数据。
- **考虑的替代方案**：
  - *方案 A（既有实现：过去 20 日单日最大涨幅所在天数）*：被拒绝。当全市场普跌时，强行抓一个伪极值作为催化点，容易给下行阴跌股票赋予错误的虚假年轻年龄。
  - *方案 B（大模型研报时间戳）*：被拒绝。历史 CSMAR 面板并非所有股票在所有交易日都有研报，会导致大量缺失值引发前视补齐漏洞。

---

### 研究项 2：连续时变参数学习算法与优化目标

- **决策**：采用 `scipy.optimize.minimize` 的 `L-BFGS-B` 算法在滚动 Walk-Forward 窗口（126 个交易日）内自适应寻优。
  - **待优化参数向量**：
    $$\boldsymbol{\theta} = [\tau, \sigma, \alpha_{\text{sentiment}}, \alpha_{\text{physical}}]$$
  - **参数有界空间（Bounded Convexity）**：
    - $\tau \in [6.0, 25.0]$（产业链物理传导时滞下限 6 天，上限 25 天）；
    - $\sigma \in [2.0, 8.0]$（高斯脉冲波动带宽）；
    - $\alpha_{\text{sentiment}} \in [0.10, 0.45]$；
    - $\alpha_{\text{physical}} \in [0.10, 0.45]$；
    - $\alpha_{\text{base}} = 0.15$（无事件常态底仓背景耦合）。
  - **损失函数**：
    $$\mathcal{L}(\boldsymbol{\theta}) = - \text{Corr}\left( S_{\text{T-NALE}}(\boldsymbol{\theta}), R_{t \to t+5} \right) + \lambda_{\text{reg}} \|\boldsymbol{\theta} - \boldsymbol{\theta}_0\|_2^2$$
    以负截面相关系数为主目标，加入先验正则项防止参数在低信噪比截面剧烈漂移。
- **理由**：
  1. 参数维度仅 4-6 维，L-BFGS-B 每次寻优耗时 $<0.5$ 秒，全样本 2.5 年走步重估可在 15 秒内跑完；
  2. 纯 CPU 运算，无需任何 PyTorch/PyG 庞大依赖，不挑显卡，在 Windows 和 Linux CI 上 100% 稳定可复现。
- **考虑的替代方案**：
  - *深度时态图网络（TGN / TGAT）*：被拒绝。引入 PyTorch-Geometric 会使 `render.yaml` 和 Docker 体积膨胀数倍，且 AMD 9060XT 在 Windows 下对动态图显存算子容易出现兼容性崩溃，违背轻量可复现原则。

---

### 研究项 3：验证与消融实验设计（四个基准对决）

- **决策**：在同一份 CSMAR 299 标的真实行情上，并列对比四个版本：
  1. **Version A (Static NALE)**：经典静态 NALE（固定 $\alpha=0.40$）；
  2. **Version B (Hardcoded T-NALE)**：硬编码时空 NALE（固定 $\tau=14, \sigma=5$）；
  3. **Version C (Heuristic Dynamic-Alpha)**：启发式动态 Alpha（固定参数 0.25/0.45/0.45）；
  4. **Version D (Learned Event-Aware T-NALE)**：本规范实现的事件感知因果学习内核。
- **统计门禁**：
  - 5 日与 10 日 Rank IC 均值及提升百分比；
  - Newey-West HAC $t$ 统计量（滞后阶数 $q = \lfloor 4(T/100)^{2/9} \rfloor$）；
  - Deflated Sharpe Ratio (DSR) 校验过拟合概率。
