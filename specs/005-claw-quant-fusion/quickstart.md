# Quickstart: 本地启用领先指标真实数据（005 融合）

## 前置

- 本地可联网（akshare 需要访问东财/新浪/上金所）
- 已安装 akshare：`pip install akshare`（2.0版 requirements 已含或手动安装）

## 步骤

```bash
cd D:\股票分析项目\2.0版

# 1) 抓取四类领先数据（半导体/光通信/新能源/贵金属），写入 docs/data/leading_signals/
python tools/fetch_leading_data.py

# 2) 查看抓取结果（data_source 应为 akshare；断网时为 synthetic_fallback）
type docs\data\leading_signals\_summary.json

# 3) 离线重生成：为现有分析 JSON 附加领先信号并重算排名
python tools/regenerate_leading_offline.py

# 4) （或直接跑完整流水线，分析时会自动按类别抓取领先数据）
python -m src.build_ranking
```

## 验证

- 打开看板：详情页摘要出现"领先指标：触底反转（供需拐点向上）（半导体行业指数（领先代理））"
- 排行榜原因列出现"领先拐点↑/↓"徽章（真实数据时）
- 排名变化：领先信号会让半导体/光通信/新能源/贵金属类别内排名按拐点方向换位
- docs/data/factors/quality_report.json 含 half_life_days 与 crowding

## 说明

- 合成降级（synthetic_fallback）数据不参与评分（保持 50 中性），避免假数据打分
- 因子半衰期/拥挤度报告：`python -m src.analysis.factor_db quality`
