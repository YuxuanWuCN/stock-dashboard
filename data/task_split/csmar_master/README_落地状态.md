# CSMAR 300支面板落地状态（2026-09-09）

## 总体状态

| 组 | 状态 | 文件 | 行×列 | 代码数 |
|----|------|------|-------|--------|
| B | ✅ 落地 | data/task_split/student_b/csmar/student_b_csmar_factor_panel_filtered.csv | 64,400 × 9 | 100 |
| A | ✅ 落地（zip→解压→转标准） | data/task_split/student_a/csmar/student_a_csmar_factor_panel_filtered.csv | 63,399 × 22 | 99 |
| A+B | ✅ 合并主表 | data/task_split/csmar_master/csmar_factor_panel_master.csv / .parquet | 127,799 × 22 | 199 |
| C | ⏳ 待交付 | （规范见 data/task_split/student_c/交付规范_同学C.md） | — | — |

## 本次完成动作

1. 解压 `同学A_数据交付_2026-09-09.zip` → `data/task_split/student_a_delivery/`
2. 编写并运行 `scripts/convert_student_a_to_standard.py`：A面板（20列技术面板）→ 标准9列 + 13技术列 = 22列
   - close/turnover/market_value 保留原生；volume 由 exp(log_amount)/vwap 推导（已在manifest注明）
   - pe_ttm/pb/roe 置NaN（A无估值/财报源），由B组补全
3. 编写并运行 `scripts/merge_csmar_panels_master.py`：A+B合并为统一主表
4. 生成 `data/task_split/student_c/交付规范_同学C.md`：C按标准9列交付

## 已知问题

- A的 pe_ttm/pb/roe = NaN（100%缺失）：A同学走的是 TRD_Dalyr 日回报率管道，不含估值与财报。若论文回归需要全样本基本面因子，需让A补跑四表管道，或在回归中剔除该组基本面列。
- A的 volume 为推导值（exp(log_amount)/vwap），非CSMAR原生 volume 字段；B的 volume 为原生。
- A组有1支退市（601989中国重工380天、600317营口港0天），已在交付说明中注明。
- C 未交付，master 目前 199 支。

## 下一步

1. 等 C 交付（按规范落地到 student_c/csmar/）
2. C 落地后重跑 merge 脚本 → 300支全量主表
3. 全量主表确认后 → 开始因子时效性研究（PC5改造）
