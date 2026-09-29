# 技术研究与决策：019-hybrid-silver-quant-merge
# 银发普惠与学术量化投研双核融合终端 (Hybrid Silver-Care & Academic Quant Terminal)

---

## 1. 技术选型与融合决策 (Technical Decisions)

### 决策 1：前端框架与图表渲染体系
- **最终决策**：全面采纳组员实现的 **React 18 + TypeScript + Tailwind CSS 3 + 纯数学原生 SVG 矢量图表** 架构。
- **决策理由**：
  1. **零外部网络与 CDN 依赖**：组员编写的 `EquityCurveChart.tsx` 与 `DonutChart.tsx` 采用纯三角函数与 SVG 路径计算，彻底摒弃了外部 jsDelivr CDN 依赖，在任何断网或受限网络下绝不发生脚本加载失败或白屏；
  2. **高分屏与适老视觉**：SVG 矢量缩放具备绝对的高清锐利度，结合 Tailwind 的 16px 圆角卡片与等宽数字体系（`tabular-nums`），大幅超越老版本手写 CSS 的排版质感；
  3. **可维护性与类型安全**：借助 TypeScript 与由 OpenAPI 自动生成的类型定义，杜绝运行时 `undefined` 错误。
- **考虑的替代方案**：
  - *方案 A：继续沿用原单文件 `index_wealth.html` 手写 JS*：代码量达 2200 行，难以模块化重构，且强依赖外部 ECharts CDN，风险极高；
  - *方案 B：引入完整版 ECharts npm 包*：会造成离线单文件体积膨胀至 3MB 以上，违反离线秒开原则。

---

### 决策 2：学术计量资产（Fama-MacBeth & CSMAR）的嵌入方式
- **最终决策**：在底部折叠栏「机构量化研报模式」中，设计分段切换控件（Segmented Control / Tabs）：
  - **Tab 1: 策略回测表现**（策略评分排名、净值多线走势、相关性热力图）；
  - **Tab 2: 学术因子与计量定价**（Fama-MacBeth 滚动两阶段回归明细表、CSMAR 原生数据源与学术字段映射表、BibTeX 引用）。
- **决策理由**：
  1. 保证默认折叠状态下，页面保持对老年长辈与非金融评委的极致亲和力（防焦虑）；
  2. 当专业金融工程/计量经济学评委点击“机构量化研报模式”展开时，一眼便能看到严谨的实证回归统计量（市场 MKT、规模 SMB、价值 HML、动量 MOM 的 $\beta$ 系数、Newey-West HAC 稳健 t 值及 p-Value）以及国泰安 (CSMAR) 数据库官方映射，构筑不可替代的学术壁垒。

---

### 决策 3：全离线单文件封箱发布机制
- **最终决策**：升级 `rainbow-fingpt-web/scripts/build-offline.py`，将融合学术计量模块后的 React 代码编译打包为单文件 `docs/index_wealth.html`。
- **决策理由**：
  1. 原有的 `docs/index_wealth.html` 为老旧手写版，替换为由 React 现代工程编译打包的高内聚单文件（内联 CSS/JS/SVG/同构快照），文件大小严格控制在 450KB 左右；
  2. 用户或评委在本地无需安装 Python 或 Node，直接双击 `index_wealth.html` 即可在 Edge 浏览器中离线顺畅体验全量功能。

---

### 决策 4：双向路由与服务托管策略
- **最终决策**：在 Flask 后端（`src/server.py`）中实现动静互通路由：
  - `/home`：托管新首页（银发安心理财助手 构建版）；
  - `/`：托管 A 股专业量化投研看板（`docs/index.html`）；
  - 新首页顶部右上角与底部提供“穿透至 A 股智能量化投研看板 ↗”入口；
  - 量化看板右上角提供“← 返回银发安心理财首页”入口，形成严密闭环。
