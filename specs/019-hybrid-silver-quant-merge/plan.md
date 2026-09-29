# 实现计划：019-hybrid-silver-quant-merge
# 银发普惠与学术量化投研双核融合终端 (Hybrid Silver-Care & Academic Quant Terminal)

**分支**：`main` | **日期**：2026-09-29 | **规格**：`specs/019-hybrid-silver-quant-merge/spec.md`  
**输入**：来自 `specs/019-hybrid-silver-quant-merge/spec.md` 的功能规格  

---

## 1. 概要 (Summary)

将组员在 `大创赛第一版.zip` 中开发的现代 React 18 + TS + Tailwind 适老化银发理财前端，与主仓现有的业内级学术量化投研资产（Fama-MacBeth 滚动截面回归实证模型、CSMAR/Wind 权威因子映射、BibTeX 引用、双向模式穿透）进行深度无缝融合。
前端以温馨适老的“银发安心理财助手”为顶层门面，在底部机构研报折叠层中无缝注入硬核学术计量面板；构建层面产出单文件离线化自愈产品（`docs/index_wealth.html`）与构建产物（`docs/home/`）；后端打通双模式路由，最终通过自动化契约测试并推送至 GitHub 远端。

---

## 2. 技术背景 (Technical Context)

- **前端技术栈**：React 18 + TypeScript + Vite + Tailwind CSS 3 + Lucide Icons + 纯数学原生 SVG 矢量图表
- **图表渲染策略**：摒弃笨重的外部 CDN ECharts，核心曲线（收益走势、配置环图、半圆温度仪表盘）全部采用纯数学原生 SVG 绘制，保证 0 外部网络依赖、毫秒级秒开
- **后端服务栈**：Python 3.10+ / Flask / OpenAPI 3.0 数据网关（`src/server.py`, `src/homepage_api.py`, `src/dataset_api.py`）
- **数据与存储**：静态同构 JSON 快照（`docs/data/` 约 18MB）+ CSMAR 因子库映射 + Fama-MacBeth 滚动两阶段回归参数
- **目标运行环境**：
  1. 现代浏览器在线模式（Edge / Chrome / Safari）
  2. 离线演示模式（双击单文件 HTML 离线秒开，支持飞机/赛场弱网断网环境）
- **性能指标**：首屏加载时间 < 1.0s；离线单文件体积 < 500KB；零外部 CDN 阻塞
- **测试框架**：pytest + 静态契约断言（`tests/test_wealth_terminal_contract.py`）

---

## 3. 宪章检查与质量门禁 (Constitution Check)

- [x] **库优先与职责清晰**：数据展示、图表计算、接口调用分离为独立组件与模块；
- [x] **离线自愈与防白屏**：网络不可用时自动回退到同构静态学术快照，确保任何评审现场绝不发生白屏；
- [x] **规范契约先行**：明确数据模型（`data-model.md`）与接口契约（`contracts/`）；
- [x] **零破坏性污染**：不破坏既有 A 股量化看板 `index.html` 的独立性，通过双向安全路由互通。

---

## 4. 项目结构与目录映射 (Project Structure)

### 规格与设计文档
```text
specs/019-hybrid-silver-quant-merge/
├── spec.md               # 需求规格与验收标准
├── plan.md               # 本实施计划
├── research.md           # 技术选型与融合决策
├── data-model.md         # 领域数据实体与模型契约
├── quickstart.md         # 本地启动与验证指南
└── contracts/
    └── homepage-api.json # OpenAPI 接口契约
```

### 源代码合并与产物路径
```text
Rainbow_FinGPTv2/
├── rainbow-fingpt-web/               # 前端源码工程（React 18 + TS + Tailwind）
│   ├── src/
│   │   ├── sections/
│   │   │   ├── HeroSection.tsx       # 适老摄影 Hero 横幅 + 核心评级
│   │   │   ├── EquityCurvePanel.tsx  # 安心增长绝对收益曲线 (SVG)
│   │   │   ├── AllocationPanel.tsx   # 资产配置环图 + 现金释义 (SVG)
│   │   │   ├── RiskRadarSection.tsx  # 产业链避险小卫士动态卡片
│   │   │   └── ExpertModeSection.tsx # ★ 机构研报模式（注入学术计量与回测）
│   │   ├── components/
│   │   │   └── academic/             # ★ 新增：学术计量经济学组件 (Fama-MacBeth / CSMAR)
│   │   ├── data/
│   │   │   └── mock.ts               # 同构保底数据（含学术计量数据集）
│   │   └── types/
│   │       └── index.ts              # 扩展学术因子类型定义
│   └── scripts/
│       └── build-offline.py          # 离线单文件封箱打包脚本
│
├── docs/
│   ├── index.html                    # 既有 A 股专业量化投研看板（挂载 /）
│   ├── index_wealth.html             # ★ 融合打包后的单文件离线终端（双击即看）
│   └── home/                         # Flask 托管构建产物（挂载 /home）
│
├── src/
│   ├── server.py                     # Flask 主入口（双页面托管与 API 网关）
│   └── homepage_api.py               # 首页聚合 BFF 接口
│
└── tests/
    └── test_wealth_terminal_contract.py # 静态与集成验收测试
```

---

## 5. 实施阶段拆解 (Implementation Phases)

### 阶段 0：大纲与研究（完成 `research.md`）
- 确定学术计量面板在 `ExpertModeSection.tsx` 中的组件交互形态（Tabs 分页：策略 vs 计量）；
- 确立 Fama-MacBeth 和 CSMAR 映射表的数据契约与样式规范（等宽数字、金融级 Slate 主题）；
- 确立单文件打包工具链的资源内联方案。

### 阶段 1：契约与设计工件（完成 `data-model.md`、`contracts/`、`quickstart.md`）
- 定义 `AcademicEconometrics`、`FamaMacBethFactor`、`CsmarMapping` 数据模型；
- 生成 OpenAPI 契约；
- 编写快速启动验证指南。

### 阶段 2：代码合并与工程落地
- 步骤 2.1：从 `大创赛第一版.zip` 中安全引入 `rainbow-fingpt-web` 前端源码与部署支撑文件；
- 步骤 2.2：在 `rainbow-fingpt-web/src/sections/ExpertModeSection.tsx` 中注入学术计量模块（Fama-MacBeth 滚动两阶段回归 $\beta$、t 值、CSMAR 映射表与 BibTeX 引用）；
- 步骤 2.3：更新 `mock.ts` 与 `types/index.ts`，确保全类型安全与静态兜底；
- 步骤 2.4：执行打包与离线封箱，更新 `docs/index_wealth.html` 与 `docs/home/`；
- 步骤 2.5：打通原量化看板 `docs/index.html` 的双向返回入口。

### 阶段 3：测试、质量门禁与 GitHub 同步
- 步骤 3.1：更新并执行 pytest 静态契约与功能测试；
- 步骤 3.2：验证在 Edge 浏览器中本地离线与 HTTP 服务的加载效果；
- 步骤 3.3：执行 `git add`, `git commit` 并推送至 GitHub 远端仓库。
