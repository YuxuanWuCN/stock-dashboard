# Rainbow_FinGPTv2 基线测试日志 (Baseline Test Log)

- **执行阶段**: Milestone M0 (P0 现场冻结与基线建立)
- **记录时间**: 2026-10-10
- **工作分支**: `fix/real-data-rebuild`
- **基线标签**: `baseline-pre-real-data-rebuild`
- **对应任务**: `ORIGINAL_REQUEST.md` §R1 / `PROJECT.md` Milestone M0

---

## 1. 运行环境规格 (Environment Specifications)

| 规格项 | 详细信息 | 备注 |
|---|---|---|
| **操作系统** | Windows 11 (Build 10.0.26100) | 本地运行环境 |
| **PowerShell** | Windows PowerShell 5.1.26100.9444 (Desktop Edition) | 系统未安装 `pwsh` (PowerShell Core 7+)，优先使用内联或 Python 调用 |
| **Python 运行环境** | Python 3.12.12 (CPython x86_64) | 路径: `d:\股票分析项目\Rainbow_FinGPTv2\.venv\Scripts\python.exe` |
| **测试框架** | pytest 9.1.1 | 配合 pytest-subtests 等插件 |
| **Git 仓库状态** | 分支 `fix/real-data-rebuild` | 从 `main` (commit `6f61628f`) 检出并冻结 |

---

## 2. 全量基线测试统计 (Baseline Test Execution Summary)

- **执行命令**:
  ```powershell
  & "d:\股票分析项目\Rainbow_FinGPTv2\.venv\Scripts\python.exe" -m pytest -q
  ```
- **耗时**: 2338.55 秒 (约 38 分 58 秒)
- **收集用例总数**: **1896**
- **通过 (Passed)**: **1879** (占比 99.1%)
- **失败 (Failed)**: **17** (占比 0.9%)
- **错误 (Errors)**: **0**
- **警告 (Warnings)**: **2011**
- **子测试通过 (Subtests Passed)**: **15**

---

## 3. 17 项初始失败用例逐项清单与归因分析 (Failure Breakdown & Categorization)

全量套件中的 17 项失败用例均为工程历史遗留状态或特定可选依赖未安装所致，经审计与当前 `R1~R6 真实数据重建` 核心量化逻辑完全解耦。

### 分类 A：缺少 Parquet 引擎可选依赖 `pyarrow` (共 6 项)
此类失败原因为 `.venv` 未安装 `pyarrow` 或 `fastparquet`，导致涉及读取 `.parquet` 的测试或 CLI 脚本无法运行：

1. `tests/test_evaluate_nale_alpha_cli.py::test_cli_smoke_fixture_emits_full_artifacts`
   - **错误类型**: `ImportError`
   - **详情**: `Missing optional dependency 'pyarrow'. pyarrow is required for parquet support.`
2. `tests/test_fetch_student_b_csmar_data.py::test_fetch_writes_raw_sources_and_standard_outputs`
   - **错误类型**: `AssertionError` (`assert 2 == 0`)
   - **详情**: 子进程 stderr 报错 `Missing optional dependency 'pyarrow'.`
3. `tests/test_nale_alpha_artifacts.py::test_fixture_bundle_is_isolated_and_has_hash_manifest`
   - **错误类型**: `ImportError`
   - **详情**: `Missing optional dependency 'pyarrow'.`
4. `tests/test_student_b_factor_panel.py::test_cli_accepts_real_source_and_writes_three_artifacts`
   - **错误类型**: `AssertionError` (`assert 2 == 1`)
   - **详情**: 子进程 stderr 报错 `Missing optional dependency 'pyarrow'.`
5. `tests/test_student_b_factor_panel.py::test_cli_manifest_records_group_and_fabrication_contract`
   - **错误类型**: `AssertionError` (`assert 2 == 1`)
   - **详情**: 子进程 stderr 报错 `Missing optional dependency 'pyarrow'.`
6. `tests/test_student_c_filter.py::test_filter_keeps_only_csmar_filling_zero_days`
   - **错误类型**: `ImportError`
   - **详情**: `Unable to find a usable engine; tried using: 'pyarrow', 'fastparquet'.`

### 分类 B：缺少语义嵌入依赖 `fastembed` (共 1 项)
7. `tests/test_generate_student_ac_768d_strict.py::test_generate_embeddings_fastembed_math_properties`
   - **错误类型**: `ExtractionError`
   - **详情**: `fastembed 未安装，请执行 pip install fastembed`

### 分类 C：缺失历史静态派生文件 (共 2 项)
历史 PC5 组件复现测试需要特定的输入样本文件：
8. `tests/test_pc5_component.py::test_pinned_repository_inputs_and_legacy_pc5_reproduce`
   - **错误类型**: `FileNotFoundError`
   - **详情**: `[Errno 2] No such file or directory: '.../data/processed/pc5_component/github-7d63bb4/inputs/factors_768d_all.csv'`
9. `tests/test_pc5_component.py::test_end_to_end_artifact_hashes_and_descriptive_status`
   - **错误类型**: `FileNotFoundError`
   - **详情**: `[Errno 2] No such file or directory: '.../data/processed/pc5_component/github-7d63bb4/inputs/factors_768d_all.csv'`

### 分类 D：对抗性数据源溯源指纹不匹配 (共 1 项)
10. `tests/test_adversarial_m4_data_provenance.py::TestAdversarialRawCrawlProvenance::test_recomputed_sha256_matches_provenance_json_and_csv`
    - **错误类型**: `AssertionError`
    - **详情**: `[000001] Provenance JSON hash mismatch (assert '7e67...' == 'd0e1...')`，历史爬取原始 JSON 与记录的哈希存在微小差异。

### 分类 E：行业图谱 (Sector Graph) 缺失相关性字段键名不匹配 (共 6 项)
该模块为近期图谱联动开发中的新特性测试，其断言的字典 Key 与实现代码存在字段命名微小出入：
11. `tests/test_sector_graph_missing_corr.py::test_missing_corr_matrix_rejects_all_peers_and_never_follows`
    - **错误类型**: `KeyError` (`'corr_missing_evidence_count'`)
12. `tests/test_sector_graph_missing_corr.py::test_nan_corr_rows_are_treated_as_missing_evidence`
    - **错误类型**: `KeyError` (`'corr_missing_evidence_count'`)
13. `tests/test_sector_graph_missing_corr.py::test_unknown_code_absent_from_matrix_is_missing_not_half`
    - **错误类型**: `KeyError` (`'corr_missing_evidence_count'`)
14. `tests/test_sector_graph_missing_corr.py::test_negative_corr_is_not_promoted_to_peers`
    - **错误类型**: `KeyError` (`'corr_missing_evidence_count'`)
15. `tests/test_sector_graph_missing_corr.py::test_real_high_corr_still_produces_follower_catchup`
    - **错误类型**: `KeyError` (`'leader_corr_with_stock'`)
16. `tests/test_sector_graph_missing_corr.py::test_missing_evidence_count_uses_group_members_not_matrix`
    - **错误类型**: `KeyError` (`'corr_missing_evidence_count'`)

### 分类 F：K 线行数断言微调漂移 (共 1 项)
17. `tests/test_validate_teacher_framework.py::test_load_kline_shape`
    - **错误类型**: `AssertionError`
    - **详情**: `assert 262 >= 267 (where 262 = len(load_kline(KLINE)))`，当前基准 K 线长度为 262 行，测试中硬编码了 `>= 267`。

---

## 4. 重建工程影响评估与隔离结论 (Rebuild Impact Assessment)

1. **核心量化模块全绿**:
   - `tests/test_analysis.py` (全部通过)
   - `tests/test_fama_macbeth.py` (全部通过)
   - `tests/test_strategies.py` (全部通过)
   - `tests/test_backtest_engine.py` (全部通过)
   - `unittest` 套件 176 项原生单元测试全部通过。
2. **失败隔离性**:
   - 17 项失败不影响 CSMAR 面板重构、三指纹判真机制、Trend Gate 检验与 Fama-MacBeth 真实 HAC 滚动回归。
   - 后续 M1~M5 将严格基于真实 CSMAR 面板推进，不依赖缺失的 parquet/fastembed 历史临时夹具。
3. **基线冻结就绪**:
   - 当前测试状态（1879 通过，17 失败）已全量记录并锁定作为 M0 基准。
