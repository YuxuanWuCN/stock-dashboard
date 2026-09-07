# 同学 B 提交范围（Matt9x）

本目录对应任务单中的同学 B：新能源与周期资源 100 支标的，覆盖绿电/公用事业/清洁能源与黄金/有色/煤炭等周期资源。

## 提交文件

- `../student_B_energy_materials_100.csv`：100 支任务池清单。
- `csmar/student_b_csmar_factor_panel_filtered.csv`：过滤到 644 个真实交易日的标准面板。
- `csmar/student_b_csmar_factor_panel_filtered.parquet`：同一面板的 Parquet 版本。
- `csmar/student_b_csmar_factor_panel_filtered_manifest.json`：过滤范围、覆盖率和合成数据检查记录。
- `../factors_768d_student_B.csv`：100 支标的的 768 维文本因子文件。

## 可复现代码

- `scripts/fetch_student_b_csmar_data.py`：CSMAR 四张源表拉取与桥接。
- `scripts/build_student_b_factor_panel.py`：标准面板清洗和写出。
- `scripts/filter_csmar_panel_to_real_days.py`：过滤 CSMAR 的填充日期到真实交易日历。
- `scripts/crawl_and_extract_768d_factors.py`：768D 文本因子生成；优先读取 `DEEPSEEK_API_KEY`，不把 Key 写入文件。
- `src/data/factor_panel.py`：代码规范化、股票内填充和公告日锚定。
- `tests/test_fetch_student_b_csmar_data.py`
- `tests/test_student_b_csmar_ingest.py`
- `tests/test_student_b_factor_panel.py`

## 未纳入提交

- 同学 A/C 的数据和脚本。
- 公开行情过渡源及 `_raw_cache`。
- CSMAR 原始 CSV：这些文件含授权数据库数据，当前只保留在本机工作区；公开 push 前需确认再分发许可。
- `checkpoint_student_B.jsonl`、`work/` 等运行中间文件。

## 已知限制

- PE/PB 源表覆盖率低于 100%，缺失值保留并记录在 CSMAR manifest 中。
- 768D Stage 1 使用 DeepSeek；若 Embedding 接口不可用，Stage 2 使用脚本内确定性本地 768 维 fallback。
- CSMAR 的年报 ROE 已通过 `AIQ_AccInfoDisTimeY.DeclareDate` 做公告日桥接；FI_T5 的 `Typrep` 重复需在后续回测口径冻结时进一步处理。
