<div align="center">

# 🌈 Rainbow-FinGPT v2.0
### *半导体存储超级周期中的资产定价与战术执行：解耦三引擎量化框架与实证检验*

[![arXiv](https://img.shields.io/badge/arXiv-2606.29290v1-b31b1b.svg?style=for-the-badge)](papers/2606.29290v1.pdf)
[![Python 3.12](https://img.shields.io/badge/Python-3.12%2B-blue.svg?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![LLM Backend](https://img.shields.io/badge/LLM-DeepSeek--V4--Flash-6366f1.svg?style=for-the-badge&logo=openai&logoColor=white)](https://deepseek.com/)
[![在线看板](https://img.shields.io/badge/在线看板-已上线-10b981.svg?style=for-the-badge&logo=vercel&logoColor=white)](https://yuxuanwucn.github.io/stock-dashboard/)
[![License](https://img.shields.io/badge/License-MIT-amber.svg?style=for-the-badge)](LICENSE)

**吴宇轩 (Wu Yuxuan)**  
*华南师范大学阿伯丁数据科学与人工智能学院 / Rainbow-FinGPT 量化投研实验室*  
联系邮箱: `wuyuxuan@m.scnu.edu.cn` · **预印本编号**: `arXiv:2606.29290v1 [q-fin.PM]`

[🚀 在线体验 Web 看板](https://yuxuanwucn.github.io/stock-dashboard/) · [📖 English Documentation (README)](README.md) · [📄 论文全文 (PDF)](papers/2606.29290v1.pdf) · [📑 LaTeX 源码](papers/storage_supercycle_paper.tex) · [🌐 网页版论文 (HTML)](papers/Rainbow_FinGPT_v2_Paper.html) · [⚡ 快速上手](#-快速上手) · [🔬 一键学术复现](#-一键学术复现)

---

<img src="docs/assets/figures/fig0_triple_engine_framework.jpg" alt="Rainbow-FinGPT 三层解耦量化架构全景拓扑" width="95%">

</div>

> [!TIP]
> 🏆 **2026 中国国际大学生创新大赛（达观数据产业命题）专项归档**：  
> 大赛官方申报材料、18页金牌路演 PPT 逐字稿、答辩专家攻防 QA 靶向演练手册以及三大出版级实证研报已独立封闭归档，请访问 [**contest-2026 分支**](https://github.com/YuxuanWuCN/stock-dashboard/tree/contest-2026)。

---

## 📖 学术摘要 (Abstract)

在半导体行业超级周期（特别是 2025–2026 年存储超级周期）中，传统量化投资模型常面临非结构化文本情绪噪声干扰、产业链上下游非线性时滞传导失真以及主跌浪中回撤失控的耦合瓶颈。针对上述挑战，本研究提出了 **Rainbow-FinGPT v2.0** 工业级解耦三引擎量化投研与战术执行系统：

1. **SCNU-RAG 定性语义认知层**：构建基于事实-观点-推论（FOI）三元分离的财报与卖方研报精准抽取引擎，结合供应链卡位打分（$CS \ge 12$）与 100% 坐标级段落证据溯源；
2. **现代经典资产定价核心层**：实现 Fama-MacBeth 两阶段横截面 OLS 滚动回归模型，引入 Newey-West (1987) 异方差自相关稳健协方差估计（HAC，最优滞后阶数 $q=4$），执行 Harvey (2016) $|t| \ge 3.0$ 与特质信息比率 $IR \ge 0.30$ 强门禁筛选；
3. **Temporal NALE 时空图卷积扩散层**：基于高斯脉冲核与信息半衰期指数衰减建立产业链时滞卷积算子，通过动态有界凸 Alpha 组合因子 $\alpha(t) \in [0.05, 0.75]$ 动态融合短期舆情突发脉冲与中期实体库存周转共振；
4. **Trend Gate™ 战术执行与风险防御层**：设计布尔趋势门控方程与严格因果无前视 ZigZag 状态机（反转阈值 $\theta = 12\%$），精准定位 3 浪主升后的斐波那契 $[0.500, 0.618]$ 缩量企稳买点，并在判定 C 浪下跌时强制清仓避险。

**实证结论**：在 2025 年 7 月 21 日至 2026 年 8 月 24 日（267 个交易日）的 A 股/美股全真回测检验中（严格扣除印花税、佣金、过户费及滑点，遵循 T+1 制度），Trend Gate 成功拦截行业 ASP 崩塌主跌，将佰维存储（688525）最大回撤压制至 **11.75%**（同期基准最大回撤 -46.30%），并捕捉美光科技（MU）主升浪取得 **1.72**（分段 2.26）夏普比率，KNN 5 日方向预测 Brier 分数达 **0.185**（$\le 0.25$）。

**关键词**：*资产定价, Fama-MacBeth 回归, Newey-West HAC, 时空图神经网络, 艾略特波浪理论, 半导体存储超级周期, SCNU-RAG, 战术风险控制*

---

## 📐 核心数学公式卡片 (Mathematical Cards)

### 卡片 1：Fama-MacBeth 两阶段截面回归与 Newey-West HAC 稳健估计

**阶段一（时序 OLS 滚动估计载荷）**：  
在 252 交易日滚动时间窗口内，对标的资产 $i$ 估计 Carhart 四因子风险载荷：
$$R_{i, \tau} - R_{f, \tau} = \alpha_i + \beta_{i,1} MKT_\tau + \beta_{i,2} SMB_\tau + \beta_{i,3} HML_\tau + \beta_{i,4} MOM_\tau + \epsilon_{i, \tau}, \quad \tau \in [t - T, t]$$

**阶段二（截面回归求因子风险溢价）**：  
在每个截面 $t$ 上进行 OLS 回归提取因子瞬时溢价 $\gamma_{k,t}$：
$$R_{i,t} - R_{f,t} = \gamma_{0,t} + \sum_{k=1}^4 \gamma_{k,t} \hat{\beta}_{i,k} + \eta_{i,t}, \quad \bar{\boldsymbol{\gamma}} = \frac{1}{T}\sum_{t=1}^T \boldsymbol{\gamma}_t$$

**Newey-West (1987) HAC 协方差估计量与 Bartlett 核权重**：
$$\hat{\mathbf{V}}_{NW} = \frac{1}{T}\left[ \hat{\mathbf{\Gamma}}_0 + \sum_{j=1}^q \left(1 - \frac{j}{q+1}\right) \left(\hat{\mathbf{\Gamma}}_j + \hat{\mathbf{\Gamma}}_j^T\right) \right], \quad q = \left\lfloor 4 \cdot \left(\frac{T}{100}\right)^{2/9} \right\rfloor$$
当 $T=252$ 时，最优自适应滞后阶数精确满足 $q=4$。标的通过 **Alpha Gate** 的充要条件为：
$$|t(\bar{\alpha}_i)| \ge 1.96 \text{ (或遵循 Harvey et al. 2016 强门禁 } |t| \ge 3.0) \quad \land \quad IR_i = \frac{\alpha_i}{\sigma(\epsilon_i)} \ge 0.30$$

---

### 卡片 2：Temporal NALE 时空图卷积算子与动态有界凸 Alpha $\alpha(t)$

为准确捕捉跨行业领先后发动力学，连续时间时空产业链图卷积算子定义为：
$$S_i(t, h) = (1 - \alpha_i(t)) \cdot \left[ S_{0, i}(t) \cdot \exp\left( -\frac{\ln 2}{H_i} \cdot h \right) \right] + \alpha_i(t) \cdot \sum_{j} W_{ji} \cdot K_{\text{lag}}(h - \tau_{ji}, \sigma_{ji}) \cdot \left[ S_{0, j}(t_j) \cdot \exp\left( -\frac{\ln 2}{H_j} \cdot (t - t_j) \right) \right]$$

物理产业链时滞采用高斯脉冲核建模：
$$K_{\text{lag}}(h - \tau, \sigma) = \eta \cdot \exp\left( -\frac{(h - \tau)^2}{2\sigma^2} \right)$$

动态时序耦合系数 $\alpha(t)$ 遵循有界凸组合机制：
$$\alpha(t) = \text{clip}\left( \alpha_{\text{base}} + \alpha_{\text{sentiment}} \cdot 2^{-t / H_{\text{sentiment}}} + \alpha_{\text{physical}} \cdot \exp\left( -\frac{(t - \tau)^2}{2\sigma^2} \right), \alpha_{\text{min}}, \alpha_{\text{max}} \right)$$
*参数先验*：$\alpha_{\text{base}} = 0.20$, $\alpha_{\text{sentiment}} = 0.35$, $\alpha_{\text{physical}} = 0.35$, $H_{\text{sentiment}} = 3.0\text{d}$, $[\alpha_{\text{min}}, \alpha_{\text{max}}] = [0.05, 0.75]$。

---

### 卡片 3：Wave-C Trend Gate™ 布尔执行方程与因果 ZigZag 无前视定理

战术资金调配由确定性布尔门控方程驱动：
$$\text{GatePass}_{i,t} = \mathbb{I}(P_{i,t} > \text{MA20}_{i,t}) \times \mathbb{I}(\text{MACD\_DIF}_{i,t} > \text{MACD\_DEA}_{i,t}) \times (1 - \mathbb{I}(\text{WavePhase}_{i,t} == \text{Phase\_C}))$$

**定理（因果 ZigZag 滤波器的无前视不变性）**：  
设价格历史自然信息滤子为 $\mathcal{F}_t = \sigma(P_\tau, \tau \le t)$。任意波段极值 $E_k$ 在时刻 $t_k$ 锁定的充要条件为存在确认时刻 $t_c > t_k$ 使得：
$$\frac{P_{t_k} - P_{t_c}}{P_{t_k}} \ge \theta, \quad \theta = 12\%$$
对任意 $t < t_c$，$E_k$ 决不参与决策，杜绝未来信息回溯：
$$\mathbb{E}[\text{GatePass}_t \mid \mathcal{F}_t] = \mathbb{E}[\text{GatePass}_t \mid \mathcal{F}_t \vee \sigma(P_{\tau > t})]$$

- **斐波那契狩猎场买点**：跟踪 3 浪区间 $[W3_{\text{low}}, W3_{\text{high}}]$，当 4 浪回调且 $P_{i,t} \in [F_{0.618}, F_{0.500}]$ 伴随 $\text{成交量} \le 0.80 \cdot \text{MA20均量}$ 时触发买入。
- **C 浪杀跌清仓避险**：当价格跌破 3 浪起涨支撑确立 Lower High + Lower Low 时，置 $\text{WavePhase} \leftarrow \text{Phase\_C} \implies \text{GatePass} = 0 \implies$ 100% 强制清仓避险。

---

## 📊 实证消融与基准对照表

### 表 1：开源免费数据与校内学术终端 (Wind / CSMAR) 迁移映射矩阵
确保科研成果在开源环境与高校专业商业数据库之间无缝迁移：

| 计量经济学变量 | 开源免费方案 (AkShare / Kenneth French) | Wind API 终端代码 | CSMAR 国泰安数据库 |
|:--------------|:---------------------------------------|:------------------|:------------------|
| 无风险利率 ($R_f$) | 中国 1 年期国债日度收益率 | `cn_bond_1y` | `sz_rf_rate` |
| 市场因子 ($MKT$) | 沪深 300 日度超额收益率 | `index_daily_300` | `FF_MKT_Daily` |
| 规模因子 ($SMB$) | 小市值 30% 减大市值 30% 收益差 | `stock_daily_mv` | `FF_SMB_Daily` |
| 价值因子 ($HML$) | 高账面市值比 30% 减低账面市值比 30% 收益差 | `stock_daily_pb` | `FF_HML_Daily` |
| 动量因子 ($MOM$) | 过去 252 日涨幅前 30% 减后 30% 收益差 | `stock_daily_momentum` | `FF_MOM_Daily` |
| 个股日收益率 ($R_{i,t}$) | 前复权收盘价日收益率序列 | `stock_daily_adjclose` | `TRD_Dret` |

---

### 表 2：规范文档 Table 2 标杆参考用例实测对比
在严格的 T+1 撮合与真实交易摩擦（印花税、佣金、过户费、滑点）下的回测实证表现：

| 标的名称 / 指标 | 关键检验阶段 | 规范文档约束门槛 | 实测达成指标 | 判定结论 |
|:---------------|:------------|:-----------------|:------------|:--------:|
| **佰维存储 (688525)** | 2026-Q2 至 2026-Q4 | $\text{MaxDD} < 17.0\%$ (C 浪清仓避险) | $\mathbf{11.75\%}$ | **PASS (通过)** |
| **美光科技 (MU)** | 2025-H2 至 2026-Q1 | $\text{Sharpe} > 1.70$ ($0.618$ 斐波那契加仓) | $\mathbf{1.72}$ | **PASS (通过)** |
| **KNN 方向预测校准** | 2025 至 2026 全周期 | $\text{Brier Score} \le 0.25$ | $\mathbf{0.185}$ | **PASS (通过)** |

---

### 表 3：300 标的 2 年全周期双版本拟真消融对决 (2024-03-26 至 2026-08-28)
样本池：300 只 A 股全真样本 | 初始资金：100 万元 | 最大持仓：15 只 | 严格 T+1 | 扣除所有摩擦费用：

| 模型架构版本 | 累积收益率 | 年化复合收益 (CAGR) | 年化波动率 | 夏普比率 (Sharpe) | 最大回撤 (MaxDD) | 卡玛比率 (Calmar) | 相比沪深300超额 |
|:------------|:----------:|:-------------------:|:----------:|:-----------------:|:----------------:|:-----------------:|:---------------:|
| **Version A: 静态 NALE (基准)** | +157.32% | 45.68% | 19.46% | 1.905 | 15.18% | 3.01 | +100.41% |
| **Version B: 固定时滞 T-NALE** | +147.83% | 43.52% | 19.94% | 1.788 | 19.32% | 2.25 | +90.91% |
| **Version C: 动态 Alpha T-NALE** | **+169.16%** | **48.32%** | **19.43%** | **1.999** | **13.98%** | **3.46** | **+112.24%** |
| *基准：沪深 300 指数* | +56.91% | 20.48% | 18.20% | 0.812 | 24.30% | 0.84 | 0.00% |

---

## 🔬 出版级实证图表集 (Figure Gallery)

<div align="center">
  <table>
    <tr>
      <td align="center"><b>图 1：策略累积净值与动态水下回撤对比图</b><br><img src="docs/assets/figures/fig1_cumulative_equity_and_drawdown.png" width="98%"></td>
      <td align="center"><b>图 2：滚动 Fama-MacBeth Alpha 与 IR 门控</b><br><img src="docs/assets/figures/fig2_fama_macbeth_rolling_alpha.png" width="98%"></td>
    </tr>
    <tr>
      <td align="center"><b>图 3：佰维存储 (688525) Trend Gate C 浪防御</b><br><img src="docs/assets/figures/fig3_zigzag_trend_gate_biwin_defense.png" width="98%"></td>
      <td align="center"><b>图 4：美光科技 (MU) 0.618 斐波那契狩猎场买点</b><br><img src="docs/assets/figures/fig4_micron_hunting_ground_fibonacci.png" width="98%"></td>
    </tr>
    <tr>
      <td align="center"><b>图 5：KNN 预测概率 Brier Score 校准曲线</b><br><img src="docs/assets/figures/fig5_brier_score_calibration_curve.png" width="90%"></td>
      <td align="center"><b>真实封箱回测验证 (001258 德明利 / MU 美光)</b><br><img src="docs/assets/figures/001258_sealed_box.png" width="48%"><img src="docs/assets/figures/MU_sealed_box.png" width="48%"></td>
    </tr>
  </table>
</div>

---

## ⚡ 一键学术复现 (One-Click Reproduction)

系统内置了全自动化学术复现脚本，可一键完成回测计算、生成全套 300 DPI 图表并运行 pytest 单元验证：

```bash
# 1. 克隆代码仓库
git clone https://github.com/YuxuanWuCN/stock-dashboard.git
cd stock-dashboard/Rainbow_FinGPTv2

# 2. 创建并激活虚拟环境 (Python 3.12+ 推荐)
python -m venv .venv
.venv\Scripts\Activate.ps1  # Linux / macOS: source .venv/bin/activate

# 3. 安装依赖库
pip install -r requirements.txt

# 4. 一键复现全部论文图表、验证矩阵与核心单元测试
python scripts/reproduce_paper_results.py
```

### 运行量化核心模块独立测试

```bash
# 验证 4 大量化核心模块（36 项测试 100% 通过）
python -m pytest tests/test_storage_supercycle_pipeline.py tests/test_temporal_nale.py tests/test_dynamic_temporal_alpha.py tests/test_fama_macbeth_integration.py -v

# 运行工程质量全量测试（807 项测试）
python -m pytest tests/
```

---

## 🚀 本地交互看板启动与离线演示模式

系统具备**零报错离线演示（Zero-Crash Offline Fallback）**架构，即便在未配置任何 API 密钥的本地克隆环境下，亦可通过预缓存的 166 只标的数据完整体验各项功能：

```powershell
# 方案 A：启动具备离线自动降级的交互服务端
python src/server.py

# 方案 B：启动轻量化静态 Web 看板
python -m http.server 8080 --directory docs
```
打开浏览器访问 **`http://127.0.0.1:8080/index.html`** 即可浏览完整看板 🎉。

---

## 🤝 学术引用 (BibTeX)

如果您在学术论文、课题研究或量化交易开发中参考了本项目的方法论或代码，请引用：

```bibtex
@article{wu2026storage,
  title={Asset Pricing and Tactical Execution in the 2025--2026 Semiconductor Storage Supercycle: A Decoupled Triple-Engine Quantitative Framework and Empirical Validation},
  author={Wu, Yuxuan},
  journal={arXiv preprint arXiv:2606.29290},
  year={2026},
  institution={Aberdeen Institute of Data Science and AI, South China Normal University}
}

@software{RainbowFinGPT2026,
  author = {Wu, Yuxuan},
  title = {Rainbow-FinGPT: Automated Quantitative Research Platform with Multi-Factor Trend Gate and SCNU-RAG},
  year = {2026},
  publisher = {GitHub},
  url = {https://github.com/YuxuanWuCN/stock-dashboard}
}
```

---

## 📄 开源许可与学术免责声明

- **开源协议**：本项目基于 [MIT License](LICENSE) 开源。
- **免责声明**：*本项目产出的所有模型评分、量化信号与模拟组合均仅供学术研究、教学研讨与量化算法探索使用，绝不构成任何实质性投资建议或操盘指令。金融市场有风险，投资需谨慎。*
