# 实施计划 010：可插拔因子定价引擎与贝叶斯闭环校准系统 (Plan-Kit 010)

## 1. 模块设计与架构拓扑 (Architecture Topology)

```mermaid
flowchart TD
    subgraph Data Layer [数据摄取适配层 (Pluggable Ingestion)]
        A1[AkshareProxyFactorProvider<br/>A股代理 4 因子 + 国债 Rf] --> DB[(SQLite: factors.db)]
        A2[KennethFrenchFactorProvider<br/>美股 FF3 + MOM] --> DB
        A3[WindCSMARStubProvider<br/>校内商业终端迁移桩] -.-> DB
    end

    subgraph Econometric Core [计量与门控层 (Econometric Kernel)]
        DB -->|O(1) 索引| B1[FamaMacBethEngine<br/>滚动 252 日 OLS + Newey-West HAC]
        B1 --> B2[Alpha Gate<br/>p < 0.05 且 IR >= 0.30]
    end

    subgraph Ranking Pipeline [排行榜分析流水线 (build_ranking.py)]
        B2 --> C1[每日风险收益排行榜<br/>注入 Beta/Alpha/IR 特征]
        C2[KNN 相似形态匹配<br/>工艺节点 Process-Node 隔离] --> C1
    end

    subgraph Calibration Loop [闭环自适应调优 (Bayesian Optimizer)]
        C1 -->|实盘/模拟盘记录| D1[calibrate_weights.py<br/>Brier Score + 交叉熵损失]
        D1 -->|每周自动更新| D2[config/strategy_params.json]
    end
```

---

## 2. 实施步骤分解 (Implementation Steps)

1. **第 1 阶段**：编写 `src/analysis/factor_providers.py`，实现适配器抽象基类与三个子类，支持因子生成、SQLite 缓存与 Table 1 映射桩。
2. **第 2 阶段**：强化 `src/analysis/fama_macbeth.py`，实现 $q = \lfloor 4(T/100)^{2/9} \rfloor$ Newey-West 自适应滞后阶数与完整截面溢价提取；更新 `src/build_ranking.py` 整合因子特征。
3. **第 3 阶段**：更新 `src/analysis/similarity.py`，增加 `process_node` 工艺节点过滤支持，并在 `src/analysis/config.py` 中引入 `ENABLE_PROCESS_NODE_KNN` 开关。
4. **第 4 阶段**：编写 `src/analysis/calibrate_weights.py` 与 `.github/workflows/calibrate.yml`，实现基于模拟盘预测对决记录的贝叶斯权重调优。
5. **第 5 阶段**：编写全部单元测试并执行验证。
