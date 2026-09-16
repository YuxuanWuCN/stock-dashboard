# Phase 1 Data Model & UI Component State

## 1. UI 主题实体模型 (Theme State Model)

```typescript
interface ThemeState {
  currentTheme: 'dark' | 'light';
  tokens: {
    // 基础背景
    bgBase: string;        // 全局最底层背景色 (dark: #090d16, light: #f8fafc)
    bgSurface: string;     // 卡片、侧栏、表格容器背景色 (dark: #111827, light: #ffffff)
    bgElevated: string;    // 悬浮层、下拉框、模态弹窗背景色 (dark: #1f2937, light: #f1f5f9)
    
    // 边框体系
    borderSubtle: string;  // 卡片外框、分隔细线 (dark: rgba(255,255,255,0.08), light: #e2e8f0)
    borderStrong: string;  // 激活项、焦点输入框边框
    
    // 文字层级
    textPrimary: string;   // 标题、现价、核心数据 (dark: #f8fafc, light: #0f172a)
    textSecondary: string; // 副标题、指标标签、正文说明 (dark: #94a3b8, light: #475569)
    textMuted: string;     // 辅助说明、脚注、无效提示 (dark: #64748b, light: #94a3b8)
    
    // 品牌与金融语义
    accentPrimary: string; // 科技金融蓝 (#2563eb / #3b82f6)
    colorUp: string;       // A股红涨 (#ef4444)
    colorDown: string;     // A股绿跌 (#10b981)
    colorFlat: string;     // 平盘灰 (#64748b)
    
    // 字体规范
    fontSans: string;      // 系统排版无衬线字体
    fontMono: string;      // 等宽金融数据与代码字体 (含 tabular-nums)
  };
}
```

## 2. 页面导航路由实体模型 (NavState Model)

```typescript
type PageId = 'today' | 'watchlist' | 'ranking' | 'query' | 'detail' | 'paper' | 'monster';

interface NavState {
  activePage: PageId;
  mobileMenuOpen: boolean;
  theme: 'dark' | 'light';
}
```

## 3. 核心卡片组件规范契约 (Component Contracts)

### StorageBacktestCard (存储超级周期回测专属卡片)
- **容器类名**: `.storage-backtest-card`
- **头部结构**: `.storage-backtest-header` (含 `.badge-pill`, `.storage-backtest-title`, `.storage-backtest-subtitle`, `.storage-backtest-badges`)
- **指标网格**: `.storage-metrics-grid` (4 列等宽网格，包含总收益、等权基准、卡玛比率、Alpha t值)
- **图表网格**: `.storage-figures-grid` (双列自适应出版级图表容器)

### MonsterDetectorPage (妖股鉴定器)
- **头部结构**: `.monster-heading`
- **统计指标卡片**: `.monster-stats-grid` -> `.stat-card` (支持 `.stat-total`, `.stat-volatile`, `.stat-trend`, `.stat-range`)
- **筛选按钮栏**: `.monster-filters-row` (支持 `.ranking-tab.active`)
- **股票网格**: `.monster-cards-grid`
