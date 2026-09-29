# 快速上手与验证指南：019-hybrid-silver-quant-merge
# 银发普惠与学术量化投研双核融合终端 (Hybrid Silver-Care & Academic Quant Terminal)

---

## 方式 1：双击即看（全离线无依赖，路演最稳）

直接在文件资源管理器中双击打开：
```text
Rainbow_FinGPTv2/docs/index_wealth.html
```
- **特点**：全代码、全样式、SVG 矢量图表、学术回归表格与保底同构数据 100% 内嵌在单个 450KB 文件内；
- **环境**：无需安装 Python、Node、无需联网、无需启动任何后台服务，Edge / Chrome 毫秒级打开。

---

## 方式 2：启动本地完整后端服务（双页面联动 + 实时 API）

```powershell
cd d:\股票分析项目\Rainbow_FinGPTv2
python src/server.py
```

终端输出 `Running on http://127.0.0.1:5000` 后，在浏览器中访问：

1. **新首页（银发安心理财助手 · 双核融合版）**：
   - 访问地址：`http://127.0.0.1:5000/home`
   - 支持实时数据拉取，右上角点击「机构量化研报模式」可一键穿透至专业看板；
2. **专业量化投研看板（底座全功能）**：
   - 访问地址：`http://127.0.0.1:5000/`
   - 右上角可一键返回银发首页。

---

## 方式 3：改动前端组件与重新构建

```powershell
cd d:\股票分析项目\Rainbow_FinGPTv2\rainbow-fingpt-web
npm run build            # 产出生产环境 dist 构建包
npm run build:offline    # 编译单文件离线封箱版并更新到 docs/index_wealth.html
```

---

## 核心核验清单 (Checklist)

- [ ] 顶部摄影 Hero 横幅温润清晰，无图片裂开；
- [ ] 资产健康晴雨表（多彩半圆仪表盘）正确定位在 70.2 市场温度；
- [ ] 绝对收益走势图（金实线 vs 灰虚线）鼠标悬浮数值对齐准确；
- [ ] 资产配置环图悬浮正常，点击“为什么留 36% 现金？”展开气泡；
- [ ] 展开底部「机构量化研报模式」，点击【学术因子与计量定价】Tab，能清晰核验 Fama-MacBeth 回归与 CSMAR 映射表；
- [ ] 点击「穿透至 A 股智能量化投研看板 ↗」能正确跳转至全功能量化看板，并在量化看板能平滑点击返回新首页。
