# 📈 量化组合看板集成说明

## 新增功能

在原有股票看板基础上，新增了**量化组合实盘监控页面**（`portfolio.html`），展示：

### 1️⃣ 今日市场情绪 🌡️
- 市场情绪指数（DeepSeek AI分析）
- 热点板块识别
- 资金流向判断
- AI推荐组合+理由

### 2️⃣ 六大组合表现 📊
- **激进成长**（aggressive）- 鲜红色
- **均衡稳健**（robust）- 亮紫色
- **防御保守**（defensive）- 鲜绿色
- **科技主题**（tech）- 亮蓝色
- **蓝筹价值**（bluechip）- 亮橙色
- **全球配置**（global）- 紫罗兰色

每个组合显示：
- 今日涨跌幅（大字号+鲜艳配色）
- 累计收益率
- 夏普比率
- 当前持仓明细

### 3️⃣ 累计收益曲线 📈
- 6条组合收益曲线对比
- 可选时间段：近7天、近30天、全部
- ECharts交互图表

### 4️⃣ 策略进化追踪 🧬
- 本周冠军策略（金色渐变卡片）
- AI深度分析（为什么这个策略赢了）
- 3个衍生策略（下周测试）

---

## 数据同步机制

### 自动同步
在 `2.0版/tools/daily_local.ps1` 第63-95行已添加自动同步逻辑：

```powershell
# 3.10) 同步量化数据到 Dashboard
```

每次运行 `daily_local.ps1` 时，会自动：
1. 复制 6 个 `performance_*.json` → Dashboard
2. 复制最新市场情绪 → `latest_sentiment.json`
3. 复制最新策略进化 → `latest_evolution.json`

### 数据路径
**源目录**（2.0版）：
- `docs/data/paper/performance_*.json`（6个组合）
- `reports/market_sentiment/sentiment_*.json`（市场情绪）
- `reports/strategy_evolution/weekly_*.json`（策略进化）

**目标目录**（Dashboard）：
- `.upload-stock-dashboard/docs/data/quantitative/`

### 手动同步
如需手动同步，在 `2.0版` 目录运行：
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "
$repo = 'D:\股票分析项目\2.0版'
$dashboardDataDir = 'D:\股票分析项目\.upload-stock-dashboard\docs\data\quantitative'

# 复制组合数据
Copy-Item '$repo\docs\data\paper\performance_*.json' -Destination $dashboardDataDir -Force

# 复制最新情绪
$latest = Get-ChildItem '$repo\reports\market_sentiment\sentiment_*.json' | 
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
Copy-Item $latest.FullName -Destination '$dashboardDataDir\latest_sentiment.json' -Force

# 复制最新进化
$latest = Get-ChildItem '$repo\reports\strategy_evolution\weekly_*.json' | 
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
Copy-Item $latest.FullName -Destination '$dashboardDataDir\latest_evolution.json' -Force
"
```

---

## 使用方式

### 本地查看
1. 进入 `.upload-stock-dashboard` 目录
2. 双击 `start_local.bat` 启动服务
3. 浏览器打开 `http://127.0.0.1:8001/`
4. 点击右上角 **"📈 量化组合"** 按钮

### GitHub Pages查看
1. 运行 `2.0版/tools/daily_local.ps1`（自动同步+推送）
2. 在GitHub上访问Dashboard网址
3. 点击 **"📈 量化组合"**

---

## 新增文件清单

```
.upload-stock-dashboard/
├── docs/
│   ├── portfolio.html           # 量化组合页面（新增）
│   ├── assets/
│   │   ├── portfolio.css        # 鲜艳风格样式（新增）
│   │   └── portfolio.js         # 数据加载逻辑（新增）
│   └── data/
│       └── quantitative/        # 量化数据目录（新增）
│           ├── performance_aggressive.json
│           ├── performance_robust.json
│           ├── performance_defensive.json
│           ├── performance_tech.json
│           ├── performance_bluechip.json
│           ├── performance_global.json
│           ├── latest_sentiment.json
│           └── latest_evolution.json
└── PORTFOLIO_README.md          # 本说明文档（新增）
```

修改的文件：
- `docs/index.html`（添加导航按钮）
- `docs/assets/style.css`（添加按钮样式）
- `2.0版/tools/daily_local.ps1`（添加数据同步）

---

## 设计特点

### 鲜艳配色方案
- 使用高饱和度颜色：`#ff2d55`（鲜红）、`#34c759`（鲜绿）等
- 渐变背景卡片
- 涨跌数字带阴影效果
- 金色渐变突出冠军策略

### 响应式设计
- 桌面端：多列网格布局
- 移动端：单列堆叠，大字号易读

### 交互体验
- 卡片悬浮放大效果
- 图表交互式tooltip
- 时间段切换按钮

---

## 故障排查

### 数据未显示
1. 检查 `docs/data/quantitative/` 目录是否存在
2. 确认有 8 个 JSON 文件
3. 运行 `2.0版/tools/daily_local.ps1` 同步数据

### 样式错误
1. 清除浏览器缓存
2. 检查 `portfolio.css` 是否正确加载

### GitHub Pages未更新
1. 确认 `daily_local.ps1` 已推送到GitHub
2. 等待 1-2 分钟让 GitHub Pages 重新构建

---

## 后续扩展建议

- [ ] 添加组合持仓对比热力图
- [ ] 历史回测曲线叠加
- [ ] 风险指标雷达图
- [ ] 移动端手势滑动切换组合
- [ ] WebSocket实时推送（盘中更新）

---

**完成日期**: 2026-08-11  
**设计风格**: 鲜艳、活泼、数据醒目  
**兼容性**: Chrome/Safari/Edge 最新版
