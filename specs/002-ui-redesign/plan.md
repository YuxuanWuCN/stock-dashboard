# Implementation Plan: 股票研究看板整体 UI 重新设计与体验提升

**Branch**: `002-ui-redesign` | **Date**: 2026-08-14 | **Spec**: [specs/002-ui-redesign/spec.md](spec.md)

**Input**: 规范文档 `specs/002-ui-redesign/spec.md` 中的全部需求与验收标准

## Summary

本计划旨在全面重构和重构优化 `股票研究看板 2.5`（包括 `index.html`, `portfolio.html` 及其相关样式和脚本）。
通过引入原生 CSS Design Tokens 变量体系、响应式 App-Shell 双模式布局（Desktop 侧边栏/Mobile 抽屉）、ECharts 缩放与深浅调色联动、骨架屏/微动画组件，打造现代化、金融级极简风的高性能股票看板应用。

## Technical Context

**Language/Version**: HTML5, Vanilla CSS3 (Custom Properties / Flexbox / Grid), JavaScript (ES6+)

**Primary Dependencies**: ECharts 5.5.1 CDN (`https://fastly.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js`)

**Storage**: LocalStorage / SessionStorage (管理用户偏好与自选股缓存)，后端 JSON 数据接口

**Testing**: Pytest (关联前端 Manifest/UI 契约测试 `tests/test_frontend_*.py`) + 浏览器响应式人工审查

**Target Platform**: Desktop (Chrome, Edge, Safari, Firefox) & Mobile Browsers (iOS Safari, Android Chrome)

**Project Type**: Front-end Web Dashboard Application (Vanilla SPA Pattern)

**Performance Goals**: 页面可交互时间 (TTI) <= 1.5s，窗口 Resize 耗时 <= 100ms，页面无刷新切换延迟 <= 50ms

**Constraints**: 不引入第三方重型打包框架（React/Vue），保留现有部署拓扑（Static Hosting / Python Server API），保留原有全量业务数据绑定逻辑

**Scale/Scope**: 核心页面 2 个 (`index.html`, `portfolio.html`)，模块视图 6 个 (今日关注、自选股、排行榜、单股查询、个股研究、模拟盘)

## Constitution Check

- [x] **架构符合原则**: 无破坏性 API 变更，基于已有无损 UI 升级模式。
- [x] **数据合同兼容性**: 保留原前后端数据共享契约 `04-前后端共享数据合同.md`。
- [x] **无隐式依赖**: 全原生技术栈，纯 CSS + JS + ECharts。

## Project Structure

### Documentation (this feature)

```text
specs/002-ui-redesign/
├── spec.md              # 功能需求规范文件
├── plan.md              # 实施计划文件
├── research.md          # 技术方案设计与调研
├── data-model.md        # UI 实体模型与状态定义
├── quickstart.md        # 快速开始与测试验证说明
└── checklists/
    └── requirements.md  # 质量规范检查清单
```

### Source Code (repository root)

```text
2.0版/
├── docs/
│   ├── index.html       # 主看板 HTML 结构 (重新构建为现代 App-Shell)
│   ├── portfolio.html   # 模拟盘与量化组合 HTML 结构
│   └── assets/
│       ├── style.css    # 全局现代 CSS 样式 (Design Tokens + 组件样式)
│       └── app.js       # 前端逻辑与 ECharts 响应式绑定控制
├── src/                 # 后端 API 服务器与数据接口
└── tests/               # 前端自动化测试集
```

**Structure Decision**: 采用前端 `docs/` 静态网页架构配合 `src/` 后端 API 服务，重构重点在 `docs/assets/style.css` 及 `docs/index.html` / `portfolio.html` 的结构与脚本升级。
