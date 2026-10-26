# 实现计划：NALE 时效动态连续卷积与事件感知双波峰原型系统

**分支**：`022-refined-temporal-nale` | **日期**：2026-10-23 | **规格**：[spec.md](spec.md)  
**输入**：来自 `specs/022-refined-temporal-nale/spec.md` 的功能规格  

---

## 概要

精修 Rainbow-FinGPT 核心创新点——Temporal NALE 时空连续卷积网络。
解决早期实现中“事件催化年龄缺失粗暴导致截面衰减对消”以及“双波峰参数人工拍脑袋”的硬伤。
通过构建点时因果 `EventAgeTracker`，并在真实 CSMAR 299 标的面板上使用 L-BFGS-B 进行连续参数自适应学习，输出真实样本外 Rank IC 显著提升及学术级双波峰冲激响应图谱。

---

## 技术背景

- **语言/环境**：Python 3.10+
- **主要依赖**：`numpy`, `pandas`, `scipy.optimize`, `scipy.sparse`, `matplotlib`（零新增依赖，纯 CPU 秒级求解）
- **数据底座**：`data/task_split/csmar_master/csmar_factor_panel_master.parquet`（299 标的 × 644 交易日真实行情）
- **测试框架**：`pytest`
- **运行隔离**：实验代码与中间矩阵完整隔离于 `scratch/refined_temporal_nale/`，不污染既有 `src/`

---

## 章程检查 (Constitution Check - 基于 AGENTS.md)

1. **学术真实性与数据纯度**：
   - [x] 100% 运行于三指纹审计通过的真实 CSMAR 面板，坚决不读取 `data/raw/backtest_paper_2024_2026_300stocks/` 作废合成数据。
2. **防前视函数原则**：
   - [x] 年龄追踪仅依赖 $t-1$ 日及之前的已实现量价；参数拟合严格执行 Walk-Forward 与 6 交易日 Purged 隔离。
3. **独立复核原则**：
   - [x] 统计显著性必须通过 Newey-West HAC 检验，严禁用 IID 普通 t 检验代替。
4. **零根目录污染**：
   - [x] 遵守系统纪律，所有临时脚本和验证工件仅落盘在 `scratch/refined_temporal_nale/` 和 `specs/022-refined-temporal-nale/`。

---

## 项目结构与工件布局

```text
specs/022-refined-temporal-nale/
├── spec.md                  # 功能规范
├── plan.md                  # 本文件（实现计划）
├── research.md              # 第 0 阶段研究报告
├── data-model.md            # 第 1 阶段数据模型
├── quickstart.md            # 第 1 阶段快速指引
└── contracts/
    └── api_contract.md      # 第 1 阶段契约规范

scratch/refined_temporal_nale/
├── event_tracker.py         # 点时因果事件催化年龄跟踪器
├── temporal_optimizer.py    # 双波峰时空核 L-BFGS-B 学习器
├── run_prototype.py         # 一键原型运行与消融评测主脚本
└── test_prototype.py        # 独立轻量单元回归测试
```

---

## 阶段规划

### 阶段 0: 调研与决策（已完成，见 [research.md](research.md)）
- 确立 `EventAgeTracker` 双触发重置机制；
- 确立 L-BFGS-B 连续有界优化参数空间；
- 确立 4 版本并行消融评测基线。

### 阶段 1: 规格设计与契约（已完成）
- 完成 `data-model.md`、`contracts/api_contract.md`、`quickstart.md`。

### 阶段 2: 原型构建与实证验证
1. 在 `scratch/refined_temporal_nale/` 编写核心模块代码；
2. 运行四版本真实回测，收集 Rank IC、ICIR、Newey-West t 统计量；
3. 生成冲激响应曲线高清图表；
4. 汇总实验结果并向用户汇报。
