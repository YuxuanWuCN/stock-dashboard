# Quickstart: 股票研究看板 UI 重构验证与预览指南

## 本地预览与验证步骤

### 1. 启动静态服务器 / 预览服务

在 `2.0版` 根目录下运行本地服务器：

```bash
python start_local.py
```

或使用 Python 内置 http 服务器查看 `docs/`：

```bash
python -m http.server 8000 --directory docs
```

打开浏览器访问 `http://localhost:8000/index.html` 及 `http://localhost:8000/portfolio.html`。

---

### 2. 响应式布局与移动端测试

1. 按 `F12` 打开 Chrome / Edge 开发者工具。
2. 开启移动端设备模拟（Device Mode），切换至 **iPhone 14 Pro (393px)** 或 **iPad (768px)**。
3. 检查顶部/侧栏导航是否转换为抽屉式并正常折叠/展开。
4. 检查股票数据表格在窄屏下是否有良好的滑行体验或卡片化呈现。

---

### 3. 运行前端与 UI 自动化测试

运行 pytest 前端 UI 相关的门禁测试以校验 DOM 契约与接口绑定无损坏：

```bash
pytest tests/test_frontend_report_ui.py tests/test_frontend_v25.py -v
```
