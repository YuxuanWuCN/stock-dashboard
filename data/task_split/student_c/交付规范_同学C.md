# 同学 C（大金融与消费医药）CSMAR 面板交付规范

> **更新日期**：2026-09-09
> **依据**：300支主表已按「方案1」统一口径（标准9列 + 技术因子附加列）

---

## 📌 当前进度

| 组 | 状态 | 文件 | 形状 |
|----|------|------|------|
| B | ✅ 已落地 | `data/task_split/student_b/csmar/student_b_csmar_factor_panel_filtered.csv` | 64,400 × 9 |
| A | ✅ 已落地（已转标准） | `data/task_split/student_a/csmar/student_a_csmar_factor_panel_filtered.csv` | 63,399 × 22 |
| A+B | ✅ 已合并 | `data/task_split/csmar_master/csmar_factor_panel_master.csv` | 127,799 × 22 |
| **C** | ⏳ **待交付** | `data/task_split/student_c/csmar/student_c_csmar_factor_panel_filtered.csv` | 应 ≈64,000 × 9+ |

---

## 🎯 同学 C 必须交付的格式（标准9列，与B完全一致）

```csv
stock_code,trade_date,close,volume,turnover_rate,market_value,pe_ttm,pb,roe
000001,2024-01-02,10.23,52345678,0.0112,1.23e11,5.6,0.7,0.12
...
```

### 列定义（与 `src/data/factor_panel.py` 的 STANDARD_COLUMNS 完全一致）

| 列名 | 含义 | 来源 | 必备 |
|------|------|------|------|
| `stock_code` | 6位证券代码（字符串，保留前导0！如 000001） | CSMAR SecuCode | ✅ |
| `trade_date` | 交易日 YYYY-MM-DD | CSMAR TrdTrdDt | ✅ |
| `close` | 收盘价 | STK_TRADE_DAYADJ | ✅ |
| `volume` | 成交量（股） | STK_TRADE_DAYADJ | ✅ |
| `turnover_rate` | 换手率（小数，1%=0.01） | STK_TRADE_DAYADJ | ✅ |
| `market_value` | 总市值（元） | STK_CAPITALS | ✅ |
| `pe_ttm` | 市盈率TTM | STK_PE_ADJ | ✅（可缺少数值，需记录） |
| `pb` | 市净率 | STK_PE_ADJ | ✅（可缺少数值，需记录） |
| `roe` | ROE（年报，公告日桥接） | STK_FIN_Anlysis | ✅ |

### 硬性要求（红线）

1. **代码6位字符串**：`000001` 不能写成 `1`，读取用 `dtype={"stock_code": str}`
2. **交易日=644天**：2024-01-02 ~ 2026-08-28，过滤到真实交易日历（剔除CSMAR的填充日），参考B的manifest（696→644天，剔52天）
3. **个股内填充**：缺失只 `groupby("stock_code").ffill()`，绝不跨股票借用
4. **不造假**：源缺失就留NaN并写入 manifest 的覆盖率记录，禁止合成值
5. **停牌/退市**：停牌日无记录（ffill顺延）；退市股截至最后交易日

### 必须同时交付的文件（与B同学对齐）

```
data/task_split/student_c/
├── SUBMISSION_SCOPE.md                                  # 交付说明（含已知限制）
└── csmar/
    ├── student_c_csmar_factor_panel_filtered.csv        # 主面板（标准9列）
    ├── student_c_csmar_factor_panel_filtered.parquet    # 同内容parquet
    └── student_c_csmar_factor_panel_filtered_manifest.json  # 覆盖率/合成检查
```

### manifest 模板（必须填写）

```json
{
  "source": "filtered from CSMAR panel to real trading days",
  "rows_after": 64400,
  "days_after": 644,
  "window": {"start": "2024-01-02", "end": "2026-08-28"},
  "factor_coverage": {
    "close": 1.0, "volume": 1.0, "turnover_rate": 1.0,
    "market_value": 1.0, "pe_ttm": <真实值>, "pb": <真实值>, "roe": 1.0
  },
  "fabrication_check": {"synthetic_values_generated": false, "random_data_used": false}
}
```

---

## 🧬 可选附加：技术因子列（A同学做了，C可选项）

A同学在标准9列之外附加了 **13个技术因子**（ret、mom_5d/20d/60d、vol_20d/60d、turnover_20d、amihud、price_pos、amplitude、gap、hit_limit、abnormal_trd），列名直接接在9列后面即可。C如果也跑技术因子，请用**相同列名**，保证合并后无冲突：

```python
# 列名对照（A同学已用，C请照抄）
tech_columns = ["ret", "mom_5d", "mom_20d", "mom_60d", "vol_20d", "vol_60d",
                "turnover_20d", "amihud", "price_pos", "amplitude", "gap",
                "hit_limit", "abnormal_trd"]
```

如果C暂不做技术因子，只交付标准9列即可（B同学就是这样），master合并脚本会自动补NaN。

---

## 🔧 落地后合并命令

C同学交付后，把文件放到上面路径，然后运行：

```bash
# 1. 用 B 的脚本路径但指向 C 的清单（或让C复用 build_student_b_factor_panel.py）
python scripts/build_student_b_factor_panel.py ^
    --task-file data/task_split/student_C_finance_consumer_100.csv ^
    --out-dir data/task_split/student_c/csmar ^
    --stem student_c_csmar_factor_panel

# 2. 重新合并 master（脚本会自动带上C）
python scripts/merge_csmar_panels_master.py
```

> 注：如果 C 用的是与 A 相同的 `build_csmar_daily_panel_factors.py --cohort student_C` 管道（20列技术面板），
> 那么先跑 `scripts/convert_student_a_to_standard.py` 的思路给 C 转成标准列（把脚本里的 cohort 参数改成 student_C 即可复用）。

---

## 📊 300支主表最终期望形态（A+B+C全部落地后）

```
127,799 + ~64,000 ≈ 191,799 行 × 22 列
200股左右（B 100 + A 99 + C 100，A退市1支、C若有退市照实记录）
列：stock_code, trade_date, close, volume, turnover_rate, market_value,
    pe_ttm, pb, roe, ret, mom_5d, mom_20d, mom_60d, vol_20d, vol_60d,
    turnover_20d, amihud, price_pos, amplitude, gap, hit_limit, abnormal_trd
```

---

## ❓ 同学 C 需要自己确认的问题

1. 你的 CSMAR 表能导出 `STK_TRADE_DAYADJ / STK_PE_ADJ / STK_CAPITALS / STK_FIN_Anlysis` 四张表吗？（B 用的是这四张，能覆盖全部9列）
2. 交易日历过滤：你们手上有没有同一份 644 天交易日历？如果没有，参考 B 的 manifest（`data/task_split/student_b/csmar/student_b_csmar_factor_panel_filtered_manifest.json`）里 696→644 的剔除逻辑
3. 如果 PE/PB/ROE 覆盖率不足100%，如实记录在 manifest 中即可（B 的 pe_ttm 也只有 87.4%）
