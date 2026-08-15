# Implementation Plan: Fama-MacBeth 多因子引擎（Phase 1）

**Branch**: 003-fama-macbeth-engine | **Date**: 2026-08-15 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from specs/003-fama-macbeth-engine/spec.md

## Summary

在 build_ranking.py 中集成 Fama-MacBeth 两阶段回归（Carhart 4 因子 MKT/SMB/HML/MOM）作为 Engine 2 的核心：新建 SQLite 因子库与 CSV 加载器（用户手工提供 CSMAR/RESSET 导出，开发期用合成夹具），阶段一时间序列回归输出每标的 alpha/p 值/IR（HAC 标准误），阶段二横截面 FM 作为信息性输出，双重硬门控（p<0.05 且 IR>=0.3）决定激进组合候选，未通过降级 Watchlist；模块 100% 测试覆盖 + 无前视泄漏专项测试 + 独立手算复核（详见 research.md）。

## Technical Context

**Language/Version**: Python（项目 venv，numpy 2.5.2 / pandas 2.3.3；需新增 statsmodels，见 R1）

**Primary Dependencies**: statsmodels（OLS + HAC/Newey-West + VIF）、标准库 sqlite3；沿用 pandas/numpy 体系。不引入 linearmodels/sklearn（research.md R1）

**Storage**: SQLite（docs/data/factors/factors.db，新建）；个股 K 线沿用 docs/data/kline/*.json（akshare 缓存）

**Testing**: pytest 9.1.1 + 项目质量门禁（small/medium/heavy）；全部离线合成夹具，零外部请求

**Target Platform**: Windows 本地开发机 + 项目 GitHub Pages 看板（输出 JSON 被前端消费）

**Project Type**: 数据流水线（pipeline）模块，集成进现有 src.build_ranking 主流水线

**Performance Goals**: 全池（约 202 只 × 5 年日线）回归 < 15 分钟（SC-005；预估 < 1 分钟，R9）

**Constraints**: 无前视（锚定 5 年窗口，泄漏注入测试必失败）；不伪造数据（数据不足 → null + 原因）；离线可复现（夹具/mock）；quality-gate 100% 覆盖率

**Scale/Scope**: 单项目模块；202 只标的 × 1250 交易日 × 4 因子

## Constitution Check

> 注：.specify/memory/constitution.md 仍为未填充模板（无已批准章程条款可核对）。以项目现行约束文件 AGENTS.md（含 2.0版/AGENTS.md 协作规则）作为等效依据执行门禁检查。

| 章程/规则项 | 本计划合规性 | 依据 |
|---|---|---|
| 可复现性（AGENTS.md 1） | 通过 | 全部测试离线夹具；因子导入事务性；质量报告可审计 |
| 数据诚实（AGENTS.md 2） | 通过 | 数据不足 → null 不伪造；真实/夹具数据区分；无前视泄漏专项测试 |
| 质量工作流（AGENTS.md 1） | 通过 | 实施前 begin-unit；small → medium → heavy；bug 合集阅读；本计划把新测试注册进 .quality-gates.json 批次 |
| 独立复核（AGENTS.md 3） | 通过 | SC-006 手算复核 3 只；合成样本注入已知 alpha 还原校验 |
| 时间序列不乱序（AGENTS.md 2） | 通过 | 因子/收益按日期对齐，无随机打乱 |

*门禁结论：无违规，无需复杂度豁免。*

## Project Structure

### Documentation (this feature)

    specs/003-fama-macbeth-engine/
    ├── plan.md              # 本文件
    ├── research.md          # 阶段 0：9 项研究决策
    ├── data-model.md        # 阶段 1：5 个实体模型
    ├── quickstart.md        # 阶段 1：快速上手
    ├── contracts/           # 阶段 1：数据契约
    │   ├── factors-csv.md       # 因子 CSV 输入契约 + SQLite 输出
    │   └── alpha-gate-output.md # 排行榜 JSON 扩展契约
    ├── checklists/requirements.md  # 规范质量清单（14/14 通过）
    └── tasks.md             # 阶段 2 输出（speckit-tasks，本命令不生成）

### Source Code (repository root)

    src/analysis/
    ├── factor_db.py         # 新增：CSV 加载/校验 + SQLite 入库/查询 + 质量报告（US1, FR-001~003/012）
    ├── fama_macbeth.py      # 新增：两阶段回归 + HAC + VIF + IR（US2, FR-004~006/008/009）
    ├── alpha_gate.py        # 新增：门控判定 + 降级策略（US3, FR-006/007/011）
    ├── config.py            # 扩展：门控阈值/窗口/rf/缺口率参数
    └── schema.py            # 扩展：alpha_gate 字段校验（FR-007）

    src/build_ranking.py     # 修改：机会分后插入门控调用点（US3）

    tests/
    ├── test_fama_macbeth.py            # 新增：单元（加载器/校验/回归/门控/泄漏注入）
    └── test_fama_macbeth_integration.py # 新增：集成（mock 行情跑 build_ranking 门控全链路）

    docs/data/factors/       # 新建：factors.db + 夹具 CSV + 质量报告

    .quality-gates.json      # 扩展：small/medium 批次注册新测试文件
    requirements.txt         # 更新：statsmodels 依赖

**Structure Decision**: 沿用项目现有 src/analysis 分层（与 similarity.py/fundamental.py 同构），门控作为 build_ranking 主流水线的插入点；不新建独立服务或包，保持单项目结构。

## Complexity Tracking

> 无违规，本表不适用。
