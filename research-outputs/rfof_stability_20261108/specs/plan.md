# 实现计划:FOF 防守层稳定性与期货腿现实性

**分支**:`022-fof-stability-futures-realism`(R-FOF 无 Git,仅作特性标识) | **日期**:2026-11-08 | **规格**:[spec.md](spec.md)
**输入**:`specs/022-fof-stability-futures-realism/spec.md`

## 概要

在不改动棘轮、驼峰参数与期货品种的前提下,(1) 用 2012–2026 长历史 ETF 做滚动前向验证,比较现有防守规则 A0 与 Ledoit-Wolf 最小方差 A1、HRP A2、波动率目标 A3;(2) 对期货腿做展期成本、保证金、均线窗口、节假日对齐的敏感性分析。结论由预先写好的三条验收标准自动判定,不达标就如实标"无显著改善"。

## 技术背景

**语言/版本**:Python 3.13.14
**主要依赖项**:pandas 3.0.3、numpy 2.5.1、scipy 1.18.0(层次聚类)、scikit-learn 1.9.0(`LedoitWolf`)、matplotlib
**存储**:文件。输入只读:`scratch/etf_hist/*.json`、`Rainbow_FinGPTv2/data/raw/` 下的期货 CSV 与 `R-FOF/reports/personal_lifecycle_backtest/precomputed_core_returns.csv`;输出 CSV/PNG/MD
**测试**:pytest(沿用 `R-FOF/tests/`)
**目标平台**:本地 Windows,命令行运行
**项目类型**:单体研究脚本,沿用 `R-FOF/tools/` 约定
**性能目标**:全流程在个人电脑上 5 分钟内跑完(10 只 ETF × 约 3500 日 × 4 方法 × 参数网格)
**约束条件**:无前视;不覆盖原始数据与已提交材料;不加杠杆;不引入网络依赖
**规模/范围**:10 只 ETF、4 个防守方法、3 条期货腿、4 类期货敏感性;4 个熊市窗口

**待核实事实(非代码阻塞)**:主力合约真实换月日与换月价差缺失,第一轮用假设网格,见 research.md D9。

## 宪章检查

*关卡:研究前通过;设计后复核。*

| 原则 | 判定 | 说明 |
|---|---|---|
| I 事实与用户价值 | 通过 | 每张表标注"回测/价格收益,不含分红"与样本区间;进攻核与防守层分开列示;文案不承诺收益(FR-008) |
| II 隐私与凭据保护 | 不适用 | 本特性不处理账号、密钥、个人资产数据 |
| III 显式外部调用 | 不适用 | 零网络依赖,不调用第三方模型 |
| IV 可验证交互 | 通过(适配) | 无页面;以自动化测试覆盖正常、空数据、坏数据(跳变 ETF)、判定失败路径 |
| V 范围与质量门 | **有一项需说明** | 先写验收再实现、测试先行,符合。但已将研究文档推送到 `Rainbow_FinGPTv2` 的 `main`,与"只修改 R-FOF"不一致,见复杂度跟踪 |

**设计后复核**:见文末"设计后复核"。

## 项目结构

### 文档(此功能)

```text
specs/022-fof-stability-futures-realism/
├── spec.md
├── plan.md              # 本文件
├── research.md          # 阶段 0
├── data-model.md        # 阶段 1
├── quickstart.md        # 阶段 1
├── contracts/
│   └── stability_outputs.md   # 阶段 1:模块接口与输出表契约
└── tasks.md             # 由 /speckit-tasks 生成,本命令不创建
```

### 源代码

```text
R-FOF/
├── tools/
│   ├── stability_etf_audit.py      # 已完成:数据审计
│   ├── stability_universe.py       # 加载、清洗、候选池
│   ├── stability_methods.py        # A0–A3 权重方法
│   ├── stability_walkforward.py    # 滚动前向与指标、熊市窗口
│   ├── stability_futures.py        # B0–B4 期货腿敏感性
│   ├── stability_verdict.py        # 三条验收判定
│   └── run_stability_study.py      # 一键入口
├── tests/
│   └── test_stability_*.py         # 冒烟与专项测试
└── reports/stability_YYYYMMDD/     # 每次运行写入带日期的新目录
    ├── tables/  figures/
    └── 结果报告.md
```

**结构决策**:沿用 R-FOF 现有 `tools/` + `tests/` 约定,不新建 `src/` 以保持与规格 020 一致。所有模块只依赖 `stability_universe.py` 的加载接口,便于独立测试。

## 复杂度跟踪

| 违规情况 | 为何需要 | 被拒绝的更简单替代方案原因 |
|---|---|---|
| 向 `Rainbow_FinGPTv2` 的 `main` 推送了 `research-outputs/rfof_stability_20261108/`（仅包含脱敏的纯学术研究计划、数据审计表与审计脚本） | 用户明确要求同步到 GitHub 并指定提交 main；R-FOF 本身不是独立 Git 仓库 | 在 R-FOF 初始化 Git 与章程“当前阶段不初始化 Git”冲突。**用户已裁决**：正式确立章程原则 VI——“只允许同步纯学术研究文档，严禁提交任何比赛申报书/参赛作品表/个人档案”。合规红线已正式写入章程并得到严格执行。 |

## 设计后复核

- 数据契约与接口见 data-model.md、contracts/，均无网络与凭据。
- 原则 I、IV、V、VI 全部通过；外部代码仓库中严格仅存脱敏量化研究成果，零比赛申报文件。
