# 数据模型与实体规范：019-hybrid-silver-quant-merge
# 银发普惠与学术量化投研双核融合终端 (Hybrid Silver-Care & Academic Quant Terminal)

---

## 1. 核心实体定义 (Entities)

### 1.1 Fama-MacBeth 因子实证回归模型 (`FamaMacBethFactor`)
定义滚动两阶段 OLS 截面回归定价模型中各核心系统性因子的计量检验结果。

| 字段名 | 类型 | 必填 | 示例 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `name` | string | 是 | `"MKT (市场风险溢价)"` | 因子名称及中文经济学含义 |
| `beta` | number | 是 | `0.42` | 截面风险溢价估计系数 ($\beta$) |
| `t_stat` | number | 是 | `4.85` | Newey-West HAC 稳健 t 检验统计量 |
| `p_value` | string | 是 | `"< 0.001"` | 显著性 p 值检验 |
| `meaning` | string | 是 | `"显著低 Beta 防守稳健属性"` | 经济学与投研策略解读 |

### 1.2 CSMAR 原生数据源与学术字段映射 (`CsmarFieldMapping`)
规范量化研究中底层学术数据库字段与商业终端的对齐映射。

| 字段名 | 类型 | 必填 | 示例 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `variable` | string | 是 | `"无风险利率 (Rf)"` | 计量模型中的自变量定义 |
| `open_source` | string | 是 | `"中国1年期国债"` | 开源公开可复现数据源 |
| `wind_field` | string | 是 | `"cn_bond_1y"` | 万得 (Wind) 商业数据字段 |
| `csmar_field` | string | 是 | `"sz_rf_rate / TRD_Nrrate"`| 国泰安 (CSMAR) 学术因子库字段 |

### 1.3 学术文献引用实体 (`AcademicCitation`)
规范论文答辩时权威文献与计量方法学的 BibTeX 引用。

| 字段名 | 类型 | 必填 | 示例 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `id` | string | 是 | `"fama-macbeth-1973"` | 文献唯一标识符 |
| `title` | string | 是 | `"Risk, Return, and Equilibrium: Empirical Tests"` | 经典文献标题 |
| `authors` | string | 是 | `"Eugene F. Fama, James D. MacBeth"` | 作者清单 |
| `journal` | string | 是 | `"Journal of Political Economy, 1973"` | 出版期刊与年份 |
| `bibtex` | string | 是 | `"@article{fama1973risk, ...}"` | 完整 BibTeX 文本 |

### 1.4 学术计量经济学全景聚合实体 (`AcademicEconometricsData`)
聚合计量回归、数据源映射与文献列表的完整对象。

```typescript
export interface AcademicEconometricsData {
  methodology: {
    title: string;
    description: string;
    hacRobustLag: number; // Newey-West 截断阶数
  };
  factors: FamaMacBethFactor[];
  csmarMappings: CsmarFieldMapping[];
  citations: AcademicCitation[];
}
```

---

## 2. 关系与视图模型集成 (ViewModel Integration)

在已有的 `HomepageResponse` 视图模型中无缝引入 `academic` 属性：

```typescript
export interface HomepageResponse {
  generated_at: string;
  hero: HeroData;
  equityCurve: EquityCurveData;
  allocation: AllocationSegment[];
  cashNote: CashNoteData;
  riskEvents: RiskEvent[];
  expert: ExpertData;
  academic?: AcademicEconometricsData; // ★ 学术计量实证资产深度注入
  meta?: HomepageMeta;
}
```
