# M0 收益口径审计报告（unified_total_return_basis_v1）

- 生成时间：2026-09-14T06:15:10Z
- run_id：`m0-baseline-v2`
- 口径水印：`unified_total_return_basis_v1_declared_caliber`
- 输入面板：`data\task_split\csmar_master\csmar_factor_panel_master.csv`（SHA256 `0a2daa7134e3defe…`）
- 口径声明：`config\data_caliber\csmar_master_close_basis.json`（SHA256 `cb37cf817e045880…`）

## 1. 面板规模

- 股票数：299
- 行数：192199
- 交易日：2024-01-02 → 2026-08-28

## 2. 口径判定分布

| 复核结论 | 股票数 |
|---|---:|
| `confirmed` | 254 |
| `inconclusive` | 45 |
| `contradicted` | 0 |

- 声明不复权组（A 组）中出现越限跳空的行数：**12**（除权除息伪收益，已由申报总收益取代，不再作为成交收益）

## 3. 统一口径覆盖率

| 声明口径 | 覆盖率 |
|---|---:|
| `forward_adjusted` | 99.8447% |
| `unadjusted` | 100.0000% |
| **全池** | **99.8959%** |

## 4. 收益基来源分布

| basis_source | 行数 | 占比 |
|---|---:|---:|
| `forward_adjusted_close_return` | 128600 | 66.9098% |
| `declared_total_return` | 63399 | 32.9861% |
| `unavailable` | 200 | 0.1041% |

## 5. 口径混用的量化代价（仅 A 组两口径同时可得）

- 可比行数：63300
- 日均差值（申报总收益 − close 日收益）：**0.000123439**
- 年化系统偏差：**3.1107%**
- 单日最大绝对差：**0.6730**
- 差值超 1% 的行占比：**0.2512%**

结论：凡使用原始 `close` 计算前瞻收益的历史产物（含 `scripts/evaluate_ashare_pca_factors.py:157` 的 5/20 日前瞻收益）
都对 A 组引入了最高 67 个百分点的伪崩盘与年化约 3.11% 的收益低估，须以本口径重做后方可引用。

## 6. 局限与未核验项

- B 组口径已从'推断'升级为'原始导出逐行核验'（trd_fward_quotation.csv ↔ 主面板 B close 完全相等）；但 CSMAR 官方字段字典仍不在库内，'FwardQuotation = 前复权'的语义解释仍属表名+恒等式双证，未获文档级确认。
- C 组原始导出缺失（data/task_split/student_c/sources/ 不存在），其前复权判定证据等级低于 B 组；重抓或取得字段字典前须按'未经文档确认'披露。
- 前复权基准日未知：日收益率对 uniform 重基不变（MA20/MA60 之类比率型状态变量同样不变），但任何使用 close **绝对水平**的特征（如 price_pos、涨停价推算）仍依赖基准日，须单独核验。
- 600317 在 768 维因子表中存在但不在 CSMAR 主面板，逐支调查未完成。
- 板块涨跌停规则未建模 ST(±5%) 与北交所(±30%)；纳入前必须扩展 board_price_limit。
- 面板缺 357 整行（非 NaN 单元格）：601989 中国重工 264 行（2025-08-12 被 600150 吸并退市）+ 12 支共 93 个停牌日，全部落在 student_A；前瞻标签必须按交易日历计数并对缺行占位，禁止 groupby.shift(-h) 按可用行偏移。
- `inconclusive` 股票并非证据支持其声明，只是窗口内未发生可观察的公司行为；其口径依赖来源表名（`TRD_FwardQuotation`），属未获文档级确认的推断。
- 本审计不改动任何原始数据，也不覆盖 M1.4 既有稳定产物。

