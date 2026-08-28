# 计划 014: v3 版本直接 LLM 预测引擎架构与实施计划 (Implementation Plan)

## 1. 架构流图 (Architecture Diagram)

```mermaid
flowchart TD
    subgraph DataInput ["输入特征层"]
        A1["K线行情 & 均线指标 (MA/RSI/MACD/ATR)"]
        A2["多因子评分 (GFCA / Fama-MacBeth)"]
        A3["新闻情绪与行业领先指标"]
    end

    subgraph LLMEngine ["v3 LLM 预测核心 (src/llm/llm_forecaster.py)"]
        B1["Prompt 结构化组装"]
        B2["Gemini 3.7 Flash API 调用"]
        B3["JSON 严格提取与字段校验"]
        B4["防爆截断器 ([-15%, +15%] / [-20%, +20%])"]
        B5["异常安全降级器 (Fallback to KNN)"]
    end

    subgraph OutputLayer ["落盘与前端展现"]
        C1["docs/data/analysis/{code}.json"]
        C2["docs/data/analysis/ranking.json"]
        C3["docs/index.html & docs/assets/app.js"]
    end

    DataInput --> B1 --> B2 --> B3 --> B4 --> C1 & C2
    B2 -.->|超时/异常| B5 --> C1 & C2
    C1 & C2 --> C3
```

---

## 2. 详细技术实现方案

1. **核心预测类 `src/llm/llm_forecaster.py`**：
   - 继承项目统一的 `LLMClient`；
   - 编写专门的量化直接推断 Prompt，要求必须只输出合规 JSON；
   - 编写数值安全清洗器 `_clamp_values`；
2. **流水线适配 `src/build_ranking.py`**：
   - 在 `analyze_single` 或 `build_stock_detail` 中调用 `LLMForecaster.forecast_single(item, df, scores, leading)`；
3. **前端呈现 `docs/index.html` & `docs/assets/app.js`**：
   - 更新 HTML 指标网格中的文案标签；
   - 优化 JS 渲染器 `renderAnalysisDetail`。
