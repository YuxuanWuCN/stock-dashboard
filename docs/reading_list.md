# 📚 Rainbow-FinGPT 核心理论与量化金融推荐书单
> Curated Reading List & Academic Reference Guide for Quantitative Asset Pricing, Trend Gating & Financial LLMs

本清单汇总了支撑 **Rainbow-FinGPT** 系统理论体系的经典量化金融、时间序列计量、技术分析及大模型金融应用教材与论文，供系统研发、答辩论证及学术引用参考。

---

## 🏛️ 一、 因子模型与横截面资产定价 (Asset Pricing & Factor Investing)

### 1. 《因子投资：方法与实践》
- **作者**: 石川、刘洋溢、连祥斌
- **出版**: 机械工业出版社 (2020)
- **对应系统模块**: `src/analysis/fama_macbeth.py`（Fama-MacBeth 两阶段回归、Newey-West HAC 标准误、Alpha 门控）
- **核心价值**:
  - 系统阐述 IC / Rank-IC 分析、因子正交化与降维。
  - 详细推导 Fama-MacBeth (1973) 横截面回归流程，并提供 Barra CNE5/CNE6 风格因子体系拆解。
  - 为实证章节提供标准的中国 A 股实证指标参考。

### 2. *Empirical Asset Pricing: The Cross Section of Stock Returns*
- **作者**: Turan G. Bali, Robert F. Engle, Scott N. Murray
- **出版**: Wiley (2016)
- **对应系统模块**: Fama-MacBeth 滚动回归、特质波动率与特质 Alpha 测算
- **核心价值**:
  - 全球金融金工界公认的横截面实证圣经。
  - 深入讲解 Fama-MacBeth 两阶段回归数学细节、Newey-West 自相关与异方差检验。

### 3. 《主动投资组合管理》(Active Portfolio Management)
- **作者**: Richard C. Grinold, Ronald N. Kahn
- **出版**: 机械工业出版社 (中译本) / McGraw-Hill
- **对应系统模块**: 组合构建与信息比率（$IR = \frac{\alpha}{\sigma_\epsilon}$）动态仓位分配
- **核心价值**:
  - 提出量化投资基础法则（Fundamental Law of Active Management）。
  - 阐明 Alpha 信号向组合权重转化的理论桥梁。

---

## 📈 二、 趋势跟踪与风险门禁 (Trend Following & Risk Gates)

### 1. 《海龟交易法则》(Way of the Turtle)
- **作者**: Curtis M. Faith
- **出版**: 中信出版社 (中译本)
- **对应系统模块**: `src/strategies/trend_gate.py`（Trend Gate 门禁系统与下行风险压制）
- **核心价值**:
  - 深刻阐述“门禁机制（Gating Mechanism）”的设计哲学——控制尾部下行风险优先于捕捉全部收益。
  - 为破位止损、均线过滤与仓位缩放提供系统化思维。

### 2. 《股市趋势技术分析》(Technical Analysis of Stock Trends)
- **作者**: Robert D. Edwards, John Magee
- **出版**: 机械工业出版社
- **对应系统模块**: MA20 趋势门禁、艾略特波浪 (Wave C) 识别、斐波那契回撤支撑区间
- **核心价值**:
  - 经典形态学与技术指标的权威定义，为指标参数选取提供文献背书。

---

## 📊 三、 金融时间序列与计量经济学 (Econometrics & Time Series)

### 1. 《金融时间序列分析》(Analysis of Financial Time Series)
- **作者**: 蔡瑞胸 (Ruey S. Tsay)
- **出版**: 人民邮电出版社 / Wiley
- **对应系统模块**: 数据清洗、滚动窗口收益率平稳性检验、GARCH 波动率
- **核心价值**:
  - 金融计量经典教材，系统推导 ARMA、GARCH 族及非线性时间序列模型。

### 2. 《计量经济学导论：现代观点》(Introductory Econometrics)
- **作者**: Jeffrey M. Wooldridge
- **出版**: 清华大学出版社
- **对应系统模块**: OLS 多元回归残差检验、多重共线性与自相关修正

---

## 🤖 四、 金融机器学习与防过拟合 (Financial ML & Robustness)

### 1. *Advances in Financial Machine Learning*
- **作者**: Marcos López de Prado
- **出版**: Wiley (2018)
- **对应系统模块**: KNN 历史形态预测、防未来信息泄露（Purged K-Fold）、样本外封箱检验
- **核心价值**:
  - 量化界防过拟合圣经。
  - 阐述为什么传统交叉验证在金融时间序列中失效，提出 Purged & Embargoed Cross-Validation。

### 2. *Machine Learning for Asset Managers*
- **作者**: Marcos López de Prado
- **出版**: Cambridge University Press (2020)
- **核心价值**: 精简版手册，适合快速掌握去噪协方差矩阵（Denoising Covariance）与特征聚类。

---

## 🧠 五、 大语言模型金融应用与智能体 (Financial LLMs & Agents)

### 1. *FinGPT: Open-Source Financial Large Language Models*
- **作者**: Hongyang Yang, Xiao-Yang Liu, Christina Dan Wang (2023)
- **论文**: arXiv:2306.06031
- **对应系统模块**: RAG 研报合成、新闻情感标注、轻量化 LoRA 微调范式
- **核心价值**: 开创金融垂直领域开源大模型流水线，定义 RAG + Sentiment Analysis 评测基准。

### 2. *FinRobot: An Open-Source AI Agent Platform for Financial Applications*
- **作者**: AI4Finance Foundation (2024)
- **论文**: arXiv:2405.14767
- **对应系统模块**: 投决会多智能体辩论（Bull vs. Bear Debate）、供应链卡位定性过滤
- **核心价值**: 提出金融 Agent 四层分层架构，证明多智能体辩论可显著降低幻觉并提升分析客观性。

---

## 🎓 论文写作与引用格式 (BibTeX 示例)

```bibtex
@book{shi2020factor,
  title={因子投资: 方法与实践},
  author={石川 and 刘洋溢 and 连祥斌},
  publisher={机械工业出版社},
  year={2020}
}

@book{bali2016empirical,
  title={Empirical Asset Pricing: The Cross Section of Stock Returns},
  author={Bali, Turan G and Engle, Robert F and Murray, Scott N},
  year={2016},
  publisher={John Wiley \& Sons}
}

@book{prado2018advances,
  title={Advances in Financial Machine Learning},
  author={L{\'o}pez de Prado, Marcos},
  year={2018},
  publisher={John Wiley \& Sons}
}

@article{yang2023fingpt,
  title={FinGPT: Open-Source Financial Large Language Models},
  author={Yang, Hongyang and Liu, Xiao-Yang and Wang, Christina Dan},
  journal={arXiv preprint arXiv:2306.06031},
  year={2023}
}
```
