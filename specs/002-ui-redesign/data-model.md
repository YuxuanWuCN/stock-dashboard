# Phase 1 Data Model & UI Component State

## 1. UI 实体与状态模型

### ThemeToken (样式变量系统)

- `bgPrimary`: CSS 颜色值，代表全局背景色
- `surfaceCard`: CSS 颜色值，代表卡片与容器表面背景
- `textPrimary`: 高对比度文本颜色
- `textMuted`: 次要辅助文本颜色
- `stockUp`: 股票上涨代表色 (默认醒目红)
- `stockDown`: 股票下跌代表色 (默认醒目绿)
- `radiusMd`: 常用组件圆角 (默认 8px / 12px)
- `shadowCard`: 卡片精致阴影与 Glow 提示

### NavState (导航与页面路由状态)

- `activePage`: 字符串，可选值 `['today', 'watchlist', 'ranking', 'query', 'detail', 'paper']`
- `mobileSidebarOpen`: 布尔值，标识移动端抽屉是否处于打开遮罩状态
- `lastUpdated`: 时间戳/格式化字符串，代表数据服务器最新同步时间

### CardViewState (看板卡片视图组件模型)

- `id`: 字符串，唯一卡片标识
- `title`: 卡片主标题
- `subtitle`: 次要描述/指标统计区间
- `loading`: 布尔值，当为 true 时激活 Skeleton 骨架屏占位
- `error`: 字符串/null，若拉取失败呈现错误重试交互

---

## 2. 前端组件与契约 (Contracts)

### Toast Component API

```javascript
window.showToast = function (message, type = 'info', duration = 3000) {
  // 校验 type: 'info' | 'success' | 'warning' | 'error'
  // 插入/更新全局 Toast 容器 DOM，自动 3s 后透明淡出
};
```

### Chart Resize Binding Contract

```javascript
window.bindChartResize = function (chartInstance, containerElem) {
  const ro = new ResizeObserver(() => {
    chartInstance.resize();
  });
  ro.observe(containerElem);
};
```
