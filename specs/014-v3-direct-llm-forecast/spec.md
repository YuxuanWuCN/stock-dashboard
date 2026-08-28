# 规范 014: v3 版本直接 LLM 预测引擎与前端呈现 (Direct LLM Forecast Engine)

## 1. 概述与背景 (Overview)
用户在网页端看板查看单股短线指标时，原有的“3日统计收益、5日统计收益、5日上涨样本比例”基于历史技术形态的纯 KNN 统计推断。在 v3 版本中，需将其全面升级为由 **Google Gemini 3.7 Flash** 大模型驱动的**直接量化预测引擎（Direct LLM Forecast Engine）**，综合多因子打分（GFCA）、均线量价形态、新闻情绪与前沿行业供需领先指标，直接输出短线（3日/5日）预期收益率、看涨置信胜率与结构化研判依据。

---

## 2. 需求规范 (Requirements)

### 2.1 大模型直接预测引擎 (`src/llm/llm_forecaster.py`)
- **REQ-014-01**: 封装 `LLMForecaster` 类，通过 OpenAI 兼容协议与配置的 `Gemini 3.7 Flash` 后端交互。
- **REQ-014-02**: 输入标准化结构体：
  - 股票基础信息（代码、名称、所属行业与题材分类）；
  - 历史行情数据（最新收盘价、MA5/MA20/MA60 均线、乖离率、RSI14、MACD 柱、ATR 波动率、近期 5 日与 20 日动量）；
  - 多因子与情绪评分（GFCA 综合评分、风险分、市场情绪标签、供需领先指标拐点）。
- **REQ-014-03**: 输出严格 JSON 结构：
  ```json
  {
    "return_3d_pct": 3.25,
    "return_5d_pct": 5.60,
    "up_probability_3d_pct": 72.0,
    "up_probability_5d_pct": 68.0,
    "confidence": "high",
    "rationale": "突破 20 日均线且量能有效放大，所属半导体题材资金净流入明显，短期多头动能强劲。",
    "risk_factors": ["短期乖离率偏高需防冲高回落", "大盘情绪处于震荡分化期"],
    "model": "gemini-3.7-flash"
  }
  ```
- **REQ-014-04**: 防爆风控限幅（Safety Bounds）：
  - 对大模型生成的 3 日预期收益率限制在 $[-15.0\%, +15.0\%]$ 区间；
  - 对 5 日预期收益率限制在 $[-20.0\%, +20.0\%]$ 区间；
  - 概率限制在 $[5.0\%, 95.0\%]$ 区间。
- **REQ-014-05**: 优雅降级（Graceful Degradation）：
  - 当 API 调用超时或解析异常时，自动安全回退至技术面与 KNN 统计估算，保证系统高可用不报错。

### 2.2 数据持久化与流水线整合 (`src/build_ranking.py`)
- **REQ-014-06**: `docs/data/analysis/{code}.json` 的 `forecast` 结构体直接写入大模型预测成果，并增加 `source: "v3_llm_direct"` 与 `model` 字段。
- **REQ-014-07**: `docs/data/analysis/ranking.json` 与 `ranking_v3.json` 全量同步大模型预测收益率与看涨胜率。

### 2.3 前端看板无缝升级 (`docs/index.html` & `docs/assets/app.js`)
- **REQ-014-08**: 卡片原位替换：
  - “3日统计收益” $\to$ **“3日 LLM 预测”**
  - “5日统计收益” $\to$ **“5日 LLM 预测”**
  - “5日上涨样本比例” $\to$ **“5日看涨置信概率”**
- **REQ-014-09**: 在详情研判区展示 Gemini 3.7 Flash 提供的核心逻辑陈述。

---

## 3. 验收标准 (Acceptance Criteria)
1. 单元测试 `tests/test_llm_forecaster.py` 覆盖率为 100%，覆盖正常解析、防爆限幅、异常回退逻辑。
2. 全量股票分析 JSON 文件包含规范的 `forecast` 结构。
3. 前端大屏点击单股能实时渲染带有“3日 LLM 预测”、“5日 LLM 预测”、“5日看涨置信概率”标签与具体数值。
4. Code-Review（规范合规与代码异味检查）双向通过。
