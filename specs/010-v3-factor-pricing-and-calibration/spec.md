# 规范 010：可插拔因子定价引擎与贝叶斯闭环校准系统 (Spec-Kit 010)

> **版本**：v3.0 Production Blueprint  
> **依据文档**：《Rainbow-FinGPT v3.0: Pluggable Factor Pricing Spec》与《StockDashboard v3.0 Blueprint》  
> **作者**：吴宇轩（华南师范大学阿伯丁数据科学与人工智能学院）

---

## 1. 概述与核心目标 (Overview & Objectives)

本规范旨在实现 StockDashboard 从 v2.5.2 到 v3.0 的核心架构跨越，彻底解决六大结构性缺陷中的：
1. **未剔除系统性 Beta 漂移**：通过可插拔双市场两阶段 Fama-MacBeth 回归模型提取纯特质 Alpha。
2. **校外开源与校内商业数据库平滑迁移**：通过适配器模式隔离数据摄取层与计量核，支持由 AkShare/French 免费数据无损切换至 Wind/CSMAR 数据库。
3. **KNN 产业链工艺节点空间硬约束**：预留 `ENABLE_PROCESS_NODE_KNN` 开关与工艺节点硬隔离接口。
4. **每周自动化贝叶斯闭环参数优化**：建立基于真实交叉熵与 Brier Score 的自动化参数校准流。

---

## 2. 功能需求规范 (Functional Requirements)

- **FR-001 (可插拔因子数据适配器)**：定义 `BaseFactorProvider` 抽象基类，实现 `AkshareProxyFactorProvider`、`KennethFrenchFactorProvider` 与 `WindCSMARStubProvider`。
- **FR-002 (本地 SQLite 因子缓存)**：A 股 4 因子（$MKT, SMB, HML, MOM, R_f$）支持基于 `docs/data/factors/factors.db` 的 $O(1)$ 快速索引与增量更新。
- **FR-003 (Newey-West HAC 异方差稳健估计)**：时序 OLS 回归自适应滞后阶数计算：
  $$q = \left\lfloor 4 \times (T / 100)^{2/9} \right\rfloor$$
- **FR-004 (Alpha Gate 统计与经济显著性硬门控)**：$p(\alpha_i) < 0.05$ 且特质信息比率 $IR_i = \alpha_i / \sigma(\epsilon_i) \ge 0.30$。
- **FR-005 (工艺节点 KNN 隔离接口)**：在 `similarity.py` 中增加 `process_node` 分组过滤接口。
- **FR-006 (每周贝叶斯闭环校准)**：在 `calibrate_weights.py` 中实现交叉熵与 Brier Score 损失函数优化，自动微调并更新 `config/strategy_params.json`。
- **FR-007 (GitHub Actions 定时工作流)**：创建 `.github/workflows/calibrate.yml`，每周日自动触发权重优化并提交。

---

## 3. 验收标准与测试矩阵 (Verification Matrix)

| 检验项 | 模块 / 接口 | 目标阈值 / 验收标准 | 验证测试文件 |
| :--- | :--- | :--- | :--- |
| **A股代理因子生成与缓存** | `AkshareProxyFactorProvider` | 支持按区间查询 DataFrame，包含 MKT, SMB, HML, MOM, rf | `tests/test_factor_providers.py` |
| **美股因子下载与解析** | `KennethFrenchFactorProvider` | 成功解析 CSV 并返回一致时序结构 | `tests/test_factor_providers.py` |
| **Fama-MacBeth HAC滞后计算** | `FamaMacBethEngine` | $T=252$ 时 $q=4$；输出有效 Alpha 与载荷 | `tests/test_fama_macbeth.py` |
| **贝叶斯权重校准闭环** | `calibrate_weights.py` | 优化后交叉熵损失单调不增，权重归一化和为 1.0 | `tests/test_calibration_loop.py` |
| **全量回归测试** | 全仓库测试套件 | 100% 测试通过 | `python -m pytest tests/` |
