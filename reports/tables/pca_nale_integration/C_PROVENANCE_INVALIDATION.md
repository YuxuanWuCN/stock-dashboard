# C 组 768 维静态向量：溯源作废说明（INVALIDATION_NOTICE）

- **冻结日期**：2026-09-14
- **执行单元**：`UNIT-20260914-*`（M6 C 组溯源作废单元，凭证见 `.quality-state/reports/`）
- **涉及产物**：`data/task_split/factors_768d_student_C.csv`、
  `data/task_split/factors_768d_student_C_provenance.json`、`data/task_split/factors_768d_all.csv` 的 C 组 100 行
- **本说明不改写任何数据文件**：原件一律保留，仅冻结事实并禁止引用

---

## 1. 结论（一句话）

**C 组 100 支的 768 维静态向量，其输入语料在本仓库、全部本地分支、GitHub 全部 PR、全部可达与不可达对象、
reflog 与 LFS 中均不存在**，因此该组向量的 `input_sha256` / `announcement_count` / `news_count`
**不可核验**；任何以 C 组静态向量为输入的分组结论、IC、回测与夏普数字，**溯源等级降级为"不可核验"，
禁止进入网申、PPT、对外报告与任何主结论**。

## 2. 证据（全部可复算，脚本 `scratch/probe_invalidation_numbers.py`，测试
`tests/test_c_cohort_provenance_invalidation.py`）

### 2.1 哈希配方是**正确**的（用 A 组反证）

配方取自 PR5 的生成脚本 `scripts/generate_student_c_768d_strict.py::_corpus_hash`：

```python
canonical = json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
sha256(canonical.encode("utf-8"))
```

对盘上语料逐支重算，与 sidecar（`data/raw/student_ac_crawled/<code>.meta.json`）比对：

| 组 | 支数 | 重算 == sidecar | 因子表 == sidecar | 因子表 == 重算 |
|---|---:|---:|---:|---:|
| **student_A** | 100 | **100/100** | **100/100** | **100/100** |
| **student_C** | 100 | **100/100** | **0/100** | **0/100** |

A 组三方完全自洽 ⇒ **配方、规范化方式、比对口径都对**；C 组是**输入不同**，不是算法不同。

### 2.2 C 组因子表声明的输入规模是盘上实有的 4.77 倍

| 指标 | sidecar / 盘上 jsonl | C 组因子表声明 | 比值 |
|---|---:|---:|---:|
| 公告数合计 | **36,255** | **172,968** | **4.7709×** |
| 新闻数合计 | **991** | **0** | 表把 C 组新闻全记为 0 |
| 逐条记录合计（`total_items`） | **37,246**（= jsonl 行数 37,246，自洽） | — | — |
| A 组对照：公告 40,999 / 新闻 980 / 记录 41,979 | 41,979（= jsonl 行数，自洽） | 40,999 / 980 | 1.0000× |

即：C 表声明约 **17.3 万条**公告，盘上只有 **3.6 万条**；差额约 13.7 万条**在任何位置都不存在**。
（C 组单支示例：`000001` 表声明 `7e67fb0e…`，盘上 sidecar 记录 `d0e166b0…`。）

### 2.3 全域搜索（本轮实测，含用户授权的联网抓取）

| 范围 | 结果 |
|---|---|
| 本地分支 `contest-2026`/`main`/`pr-1`/`pr-2`/`pr-4`/`pr-5-student-c`/`016-…`/`teacher-framework-refactor` | 仅 **PR4** 有 `data/task_split/student_b/sources/csmar_raw/`（**B 组**原始导出）；无 C 组 sources |
| GitHub 远端（`ls-remote` + `fetch`，用户授权） | `refs/pull/*` 共 **9 条**（`pull/1..7/head`、`pull/6/merge`、`pull/7/merge`），**不存在 #8+** |
| PR5（student C）全树 | 仅 C 因子表 + provenance + `student_c/csmar/*`（面板/parquet/manifest）+ `SUBMISSION_SCOPE.md` + `data/school_factors/README.md`；**无 jsonl、无语料、无 sources/** |
| 全部可达对象 | **从来没有任何 `*.jsonl` 或 `*crawled*` 路径被提交**（语料一直是本地未入库文件） |
| 不可达对象 / reflog / LFS | 仅 2 个无关 WIP 提交；**未使用 Git LFS** |
| C 组自身 manifest | 引用的 `data/task_split/student_c/sources/csmar_raw/trd_fward_quotation_filling_calendar.csv` **不存在** |

## 3. 影响范围

**作废（不得引用）**

- C 组 768 维向量及其 `input_sha256`、`announcement_count`、`news_count` 的任何"已核验"表述；
- 一切以 C 组静态向量为输入的分组结论，尤其 **M1.4 的 student_C 夏普 +0.2347 一类数字**；
- 任何"全池 300 支 768 维向量均已溯源核验"的整体表述（A 组成立，C 组不成立）；
- 以这些向量为输入的因子合成/IC/回测结论（此前 `reports/tables/ashare_pca_factors/` 的 IC 指标已因口径问题另案作废）。

**未作废（仍可用）**

- **A 组 100 支**的 768 维向量：三方 100/100 自洽，溯源有效；
- C 组的 **CSMAR 日频面板**（前复权 `close`，恒等式复核通过），仍可用于收益/网络类研究；
- C 组的**逐条 `publish_time` 语料本身**（盘上 37,246 条，与 sidecar 自洽）：可作为**新的 as-of 特征族**
  使用（M2 的 `text_flow_v1`），但**不得**称为"复现 768 维因子表的输入"。

## 4. 下游硬约束（已在代码层执行）

- `src/data/pca_nale_asof_panel.py`：静态 768 维嵌入族登记为
  `NOT_ASOF`（`NOT_ASOF_FAMILIES`），任何配置一旦选用即抛错（`AsofPanelConfig.__post_init__`）；
  其原因是**向量全晚于 2026-09-07 且本机无嵌入模型缓存**，与本说明的"输入不可得"叠加，双重禁止。
- `src/graph/pca_nale_networks.py`：`text_embedding_similarity` 同样标 `NOT_ASOF`，
  必须与主结论并列出现；替代物为逐条 `publish_time` 的 `attention_correlation`。

## 5. 解除条件（三条全部满足才可解除，且必须**独立复算**）

1. 补入 C 组原始导出 `data/task_split/student_c/sources/csmar_raw/trd_fward_quotation.csv`
   （+ `…_filling_calendar.csv`）——可将 C 组**收益口径**由"表名+恒等式推断"升级为**导出级核验**（对齐 B 组）；
2. 补入能对出 `7e67fb0e…`（逐支不同）的 C 组语料：100 支、约 **172,968** 条公告、新闻 **991** 条；
3. 补入同一次抓取的 C 组 sidecar（`<code>.meta.json`），其 `input_sha256` 应与因子表一致。

满足后按上述配方**逐支重算**：`重算 == sidecar == 因子表`、且逐支条数与 `total_count/announcement_count`
一致，方为解除；**严禁改写因子表哈希去"对上"**——那会把"来自更大语料"伪装成"来自盘上语料"，
属伪造溯源，比缺失更严重。

## 6. 冻结方式（防止静默漂移）

本说明对应一条**可执行断言**：`tests/test_c_cohort_provenance_invalidation.py`。
它实时重算并断言"配方正确（A 组 100/100）"与"C 组表与盘上不一致（0/100、172,968 vs 36,255、991 vs 0）"。
因此：任何试图悄悄改写 C 组表哈希来"让 heavy 变绿"的操作都会**立刻被该测试拒绝**；
将来真正补全输入后，也必须由人工显式更新该测试与本文档（这正是它的设计目的）。