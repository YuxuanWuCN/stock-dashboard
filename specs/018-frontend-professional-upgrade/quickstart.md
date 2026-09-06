# Phase 1 Quickstart: 前端运行与验证指南

## 1. 启动本地投研看板

在项目根目录下运行一键启动脚本（无需任何外部前端构建工具）：

```powershell
python start_local.py --no-browser
```

终端将输出服务地址：
- **看板前端**: `http://127.0.0.1:8001/`
- **后台 API**: `http://127.0.0.1:5000/api/health`

在浏览器中打开 `http://127.0.0.1:8001/` 查看看板；如需查看多组合实盘，访问 `http://127.0.0.1:8001/portfolio.html`。

---

## 2. 自动化契约测试

运行所有 5 个前端契约测试文件，验证 26 项断言全部通过：

```powershell
python -m pytest tests/test_frontend_v25.py tests/test_frontend_report_ui.py tests/test_frontend_watchlist_regions.py tests/test_frontend_watchlist_search.py tests/test_frontend_paper_manifest.py -v
```

---

## 3. 视觉与交互核验清单

1. **主题切换**:
   - 点击顶部右上角的主题切换开关。
   - 确认暗黑（Institutional Pro Dark）与明亮（FinTech Light）模式顺滑切换。
   - 确认图表坐标轴与网格线颜色跟随主题同步自适应。
2. **图标与文字检查**:
   - 检查 Header、导航栏、各个卡片标题，确认无操作系统自带杂乱 Emoji，呈现清晰锐利的矢量微图标。
3. **去内联化与响应式检查**:
   - 打开 Chrome DevTools 移动端视口（iPhone 15 Pro, 393x852），检查导航栏自适应与表格横向平滑滚动。
   - 检查存储超级周期卡片与妖股鉴定器卡片在窄屏下自动转为单列垂直流，无截断或横向空白溢出。
