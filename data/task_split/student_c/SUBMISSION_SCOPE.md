# 同学 C 提交范围

本目录对应任务单中的同学 C：大金融与消费医药 100 支标的，覆盖大金融/银行券商保险地产与消费/食品/医药生物两个子板块。

## 标准交付物

- `../student_C_finance_consumer_100.csv`：100 支任务池清单。
- `csmar/student_c_csmar_factor_panel_filtered.csv`：CSMAR 面板，过滤到 644 个真实交易日。
- `csmar/student_c_csmar_factor_panel_filtered.parquet`：同一面板的 Parquet 版本。
- `csmar/student_c_csmar_factor_panel_filtered_manifest.json`：日期过滤、覆盖率、来源和无合成数据审计记录。
- `../factors_768d_student_C.csv`：100 支标的的严格 768 维文本因子。
- `../factors_768d_student_C_provenance.json`：真实新闻/公告计数、输入哈希和模型来源契约。

## 可复现脚本

- `scripts/fetch_student_c_csmar_data.py`：CSMAR 四张源表拉取与面板桥接。
- `scripts/build_student_c_factor_panel.py`：代码规范化、股票内填充和公告日锚定。
- `scripts/fetch_student_c_csmar_filling_calendar.py`：单标的 CSMAR `Filling` 交易日标记查询。
- `scripts/filter_csmar_panel_to_real_days.py`：按 CSMAR `Filling=0` 过滤真实交易日。
- `scripts/generate_student_c_768d_strict.py`：严格真实来源 768D 生成；失败不回退。
- `src/data/factor_panel.py`：标准字段、股票内填充和公告日锚定实现。

## 数据来源与限制

- CSMAR 原始表：`TRD_FwardQuotation`、`FI_T10`、`FI_T5`、`AIQ_AccInfoDisTimeY`。
- 行情窗口初始返回 694 个日期；CSMAR `Filling=0` 保留 644 个真实交易日，`Filling=2` 的 50 个填充日期被剔除。
- close、volume、turnover_rate、market_value、ROE 覆盖率 100%；PE_TTM 覆盖率约 87.3%，PB 覆盖率约 90.8%，缺失值保持为空。
- 768D 使用真实外部新闻/公告、DeepSeek Stage 1 和 `jinaai/jina-embeddings-v2-base-zh` Stage 2；`fallbacks_allowed=false`。
- CSMAR 原始 CSV 与 Filling 日历保留在本机授权目录，未默认纳入公开提交范围。
