> **2026-09-19 PR #10 (Matt9x/week2-m4-fullrun-B) 吸收与合并完成**：
> 1. **代码与数据合并**：通过本地 `--no-ff` 将 PR #10（Commit `93916e5`）合入 `contest-2026`。
> 2. **交付物内容**：
>    - B 组（新能源与周期 100 支）真实技术因子入库（100 支 × 644 交易日，64,310 行，覆盖率 97.53%），经 `scripts/enrich_master_panel_bc_technical.py --only student_B` 幂等并入 master 面板；
>    - 附带 TRD_Dalyr 真实性独立验证 C1–C7（跨两独立管道相关 0.999997、行情指纹与外部公开源 29 点逐分一致、涨跌停 0 越限）；
>    - 两大走步评测真实产物集：`m4-full-run-B-20260919`（可比 69 信号日）与 `m4-full-run-B-long126-20260919`（全日历 644 交易日长样本大推演）；
>    - 学术级 Bootstrap 显著性图集（森林图、分布图、时序图、组合净收益 CI、Holm 热图，PNG 300dpi + PDF 矢量图）；
> 3. **科学结论与学术防假**：
>    - 彻底证实：在训练池扩至 216 信号日（远超 126 门限）时，动态门控依然 100% 回落至 B0（`calibration_slope_zero`），证实非样本量问题；全变体 Holm 校正后无显著项，干净披露负结果；
>    - 因 B 组盘上无语料，评测器直接 fail-closed 拒评 W-attn（并在报告第 4 节并列登记 `NO_CORPUS`），严守防造假底线；
> 4. **质量验证**：专属测试 `tests/test_enrich_master_bc.py`、`tests/test_m4_domain_extension.py`、`tests/test_plot_m4_bootstrap.py` 共 31 项测试 100% 绿灯通过（38.2s）。
>
> **2026-09-16 PR #8 (kkkk0517-pixel/feat(data-A+nale)) 吸收与合并完成**：
> 1. **代码与数据合并**：通过本地 `--no-ff` 将 PR #8（Commit `0379860`）合入 `contest-2026`（Merge Commit `52749a7`）。
> 2. **交付物内容**：
>    - 同学 A CSMAR 原生日频因子面板构建脚本（`scripts/build_csmar_daily_panel_factors.py`），采用 CSMAR `TRD_Dalyr` 原生 `Dretwd`（现金红利再投资总收益率），消除了未复权除权日暴跌痛点与市值千元换手率单位 bug，并通过三重零偏差审计（`工作规划/数据审计报告_同学A_CSMAR日频面板.md`）；
>    - M4 全周期走步评测真实产物集（`m4-full-run-20260916`，含 `reports/tables/pca_nale_integration/m4-full-run-20260916/` 及图表 `ic_by_variant.png`）；
> 3. **实证与学术纪律**：全周期 69 个信号日评测忠实反映负面结果（动态门控退化等同于 B0 $\alpha=0.40$，Mean Rank IC=0.0138，Holm $p=1.000$ 不显著），学术道德严谨合规；
> 4. **质量验证**：回归套件 `tests/test_return_basis.py` 与 `tests/test_evaluate_pca_nale_integration.py` 共 79 项测试 100% 绿灯通过（46.9s）。
>
> **2026-09-15 PR #6 (SoliloquyRyan/codex/pc5-component) 吸收与适配完成**：
> 1. **代码合并**：吸收 Commit `fb13cca` 至 `contest-2026`，新增 `src/pricing/pc5_component.py`、`scripts/extract_pc5.py`，更新 `scripts/day2_pca_extraction.py`（彻底消灭保留6/10维时误将最后一个成分命名为 PC5 的缺陷）。
> 2. **工程适配**：`scripts/extract_pc5.py` 强化 Windows CRLF 换行符与 Git Blob 跨平台比对容错；`config/experiments/pc5_component.json` 锚定至历史输入快照隔离目录，与 M0–M6 清洗后的最新数据层互不污染。
> 3. **质量验证**：`tests/test_pc5_component.py`（15 passed）与 `tests/test_factor_orthogonalization.py`（7 passed）共 22 项测试 100% 通过；质量门禁 `small` 与 `medium` 当前**双有效**。
>
> **2026-09-14 M6 C 组 768 维静态向量【溯源作废】（用户裁定执行）**：
> 产物 `reports/tables/pca_nale_integration/C_PROVENANCE_INVALIDATION.md`
> + `tests/test_c_cohort_provenance_invalidation.py`（6 项全绿，把作废变成**可执行断言**）；
> 门禁 `small`（`…202614230701-small-4c19f6`）与 `medium`（`…230735-medium-549903`）当前**有效**。
> 1. **实测数字（双重锁定：探针 + 测试）**：哈希配方取自 PR5 `generate_student_c_768d_strict.py::_corpus_hash`
>    （`json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",",":"))` 的 sha256）。
>    **A 组三方 100/100 自洽**（重算 == sidecar == 因子表）⇒ **配方正确**；
>    **C 组**："重算 == sidecar" 100/100（盘上自洽），但 "因子表 == sidecar" **0/100**、"因子表 == 重算" **0/100**；
>    C 组公告 sidecar **36,255** vs 表 **172,968**（**4.7709×**）、新闻 sidecar **991** vs 表 **0**；
>    逐条记录 37,246 = 盘上 jsonl 行数。
> 2. **全域搜索结论（含用户授权联网）**：本地 8 个分支、GitHub `refs/pull/*` 共 9 条（仅 #1–#7，
>    **无 #8+**）、全部可达对象（从未提交过任何 `*.jsonl`/`*crawled*`）、不可达对象、reflog、LFS
>    —— **C 组输入语料一处都没有**；只有 **PR4** 带 B 组原始导出（`student_b/sources/csmar_raw/`）；
>    C 组自身 manifest 引用的 `student_c/sources/…` 不存在。
> 3. **作废范围**：C 组 768 维向量的 `input_sha256`/`announcement_count`/`news_count` 不可核验；
>    一切以 C 组静态向量为输入的分组结论（**含 M1.4 `student_C` 夏普 +0.2347 一类数字**）
>    **禁止进入网申/PPT/对外报告与主结论**。
> 4. **未作废**：A 组 768 维向量（100/100 有效）；C 组 CSMAR 日频面板（前复权、恒等式复核通过）；
>    C 组逐条 `publish_time` 语料（可作**新特征族** `text_flow_v1`，**不得**称"复现因子表输入"）。
> 5. **防静默漂移**：该测试实时重算并断言"C 组表与盘上不一致"，因此**任何改写因子表哈希去凑 sidecar
>    的操作会立刻失败**（属伪造溯源，比缺失更严重）；将来补全输入必须人工显式更新测试与说明。
> 6. **解除条件（三条全满足并独立复算一致）**：①`student_c/sources/csmar_raw/trd_fward_quotation.csv`
>    （+ filling calendar）；②能对出 `7e67fb0e…` 的 C 组语料（100 支、约 172,968 条公告）；
>    ③同批次 C 组 sidecar。
> 7. **当前发布判定**：`verdict = block`（heavy 仍无凭证）。仅剩两条真实阻塞：上述溯源链（BUG-0025/0026）
>    与依赖冲突 BUG-0024（magika 0.6.3 要求 onnxruntime≤1.20.1、实装 1.29.0）。
>    **稳定量化基准未被覆盖**。
>
> **2026-09-14 M5 独立复核 + M5b heavy 遗留失败修复（同一轮收尾）**：
> `small`（`.quality-state/reports/20260914200923-small-d384c9.md`）与
> `medium`（`…20261013-medium-e286c5`）当前**有效**；`heavy` 仍**无通过凭证**（见第 6 条）。
> 1. **M5 独立复核**（单元 `UNIT-20260914-185638-a2fc0d`）：新增 `tests/test_pca_nale_integration_review.py`
>    12 项全绿（独立重建夹具）：跨模块一致性（M4 `alpha_0.00` ≡ 面板 `S0` ≡ α=0 权威核；`b0` ≡ 用 M3
>    重建同一 W-ind 网络 + 权威核传播，误差 <1e-12，注明 1e-16 级 BLAS 非确定性）；CLI 级时间往返
>    （改远处未来 ⇒ 断点前的面板/得分/IC/网络诊断逐列逐位不变）+ **反向守卫**（证明改动确实改变了断点
>    之后的行，避免假绿灯）；spy 截获 `compute_return_basis` 的 verification 确认窗口止于冻结日
>    （防全样本复核回流）；手算两点传播与三点去边敏感性；门控目标函数闭式损失 + 中心差分梯度校验。
> 2. **M5b 修复 4 项 heavy 失败（全部按证据修，未放宽任何断言）**：
>    * `test_validate_teacher_framework` ×2 = **工具未来数据泄漏**：`docs/data/kline/001258.json`
>      已由 252 根（`LAST_DATE=2026-08-13`）长到 **268 根（2026-09-04）**，而 `run_three_actions` /
>      `list_limit_up_events` 未夹断到模块自声明的截止日 ⇒ 聚簇 6→7、20 日收益 +17.28%→−3.46%。
>      已加 `clamp_to_last_date` / `report_lookahead_drift`，四个统计函数统一夹断（缺 `LAST_DATE` 即
>      fail-closed），空表仍返回 `[]`；**测试断言一字未改**，夹断后自动回到文档化数值。
>    * `test_data_adapter` = **诊断口径错**：本地无数据却报"缺交易日历"。已改为仅当本地确有数据但缺日历
>      才要求 `expected_trading_dates`，无数据时报覆盖错误；两路径仍 fail-closed，并补反向守卫。
>    * `test_git_push_with_fallback` = **断言过窄**：改为传递性校验（直接调用或经 `tools/daily_routine.py`
>      调用同一助手），保留 `git push origin main` 禁令断言并加反向守卫。
> 3. **heavy 由 5 failed → 1 failed（1,383 passed / 127s）**，唯一失败为
>    `test_adversarial_m4_data_provenance`。
> 4. **该失败不可修复（如实保留）**：它比对盘上重算哈希 `7e67fb0e…` 与 provenance 声明 `d0e166b0…`；
>    而 BUG-0026 已实测 C 组**申报公告数 172,968 条 vs 盘上实有 36,255 条（21%）**、`input_sha256` 100/100
>    不合、哈希配方未记录 ⇒ **声明哈希的输入根本不在盘上，任何配方都不可能复现**。该测试本身就是完整性
>    检查，**必须继续失败**，禁止跳过/放宽。
> 5. ⚠️ **门禁机制发现（需裁定）**：heavy 每次失败都会登记 Bug（本次 BUG-0024/BUG-0029 复发），
>    而 bug 合集哈希是凭证绑定项 ⇒ 每次 heavy 失败都会把刚通过的 small/medium 判为失效，
>    形成"重跑 heavy → 登记 Bug → 凭证失效"的循环（本轮已复现两次）。当前处置：不再重复触发 heavy，
>    阻塞项登记清楚即可。
> 6. **发布判定（未达交接书 §8-V 三条，verdict = block）**：①上述溯源测试失败（BUG-0025/0026）；
>    ②`Python 依赖一致性`（BUG-0024：magika 0.6.3 要求 onnxruntime≤1.20.1、实装 1.29.0）；③heavy 无凭证。
>    **稳定量化基准未被覆盖**；M2–M5 的集成结论一律按各自的"局限/负面结果"条目引用。
>
> **2026-09-14 M4 走步评测 CLI 已交付（同一轮）**：单元 `UNIT-20260914-170510-acf02b`；
> 凭证 `20260914180655-small-caa922`（small）+ `20260914180745-medium-593edc`（medium）；
> `tests/test_evaluate_pca_nale_integration.py` 43 项全绿，弱断言 0 error（3,748 条断言、0.3%）。
> 1. **新增 `scripts/evaluate_pca_nale_integration.py`**：只读消费 M2/M3；`--run-id` 必填且三处产物目录
>    任一已存在即**拒绝运行**（实测二次运行被拒）；口径复核结论只用**首个应用信号日之前**的数据冻结
>    （冻结日入 manifest，测试证明改未来价/市值不改变历史结论）；全部变体同一批 (股票, 信号日)、
>    同一标签，`alpha_0.00` 与面板 `S0` 逐位相等。
> 2. **变体 28 个**：α=0 / B0 0.40 / α 网格 / 动态门控 V1·V2·V3（按网络分别拟合、训练段只用标签已成熟
>    的信号日、V3 用真实交易日年龄）/ W-ind 节点标签置换安慰剂 × 三条网络。
> 3. **统计纪律**：日截面 Pearson+Spearman IC（<20 只有效股记缺失）、ICIR 不年化、区块 bootstrap
>    （seed 42、10/40 交易日块 + 5/20 敏感性）、Holm 校正；**字段名守卫**含 `annual` 即抛错（修 F3）；
>    组合显式计费（0 成本对照 + 双边 15bp）、换手按名单更替估计，只报每期均值/标准差/区间。
> 4. **真实冒烟** `m4-smoke-20260914a`（A 组 99 支，计划 93 信号日、应用 6 个，语料 79,225 条）：
>    28 变体、336 行 IC、0 排除日；W-corr 覆盖 1.000、W-attn 平均覆盖 0.911（孤立点最多 15）。
> 5. ⚠️ **负面结果（必须并列引用）**：9 次门控拟合全部回落 `calibration_slope_zero` ⇒ α 恒为 0.4，
>    **V1/V2/V3 与 B0 数值完全相同**；即本样本上**动态 α 不可识别**，不得宣称动态门控增益。
>    训练段仅 23 个信号日，`gate_min_train_dates` 已从 Week1 默认 126 降至 20（**降级设置**，已入 manifest）。
> 6. ⚠️ 冒烟期 6 个信号日的 IC（−0.14~+0.10）只是管线连通性检查，**不是实证结论**，禁止引用。
> 7. **未做**：`heavy` 与 `verdict` 仍为 `block`（09-10 遗留 5 项 heavy 失败 + BUG-0024 依赖冲突），属 M5。
>
> **2026-09-14 M3 网络工厂已交付（同一轮）**：单元 `UNIT-20260914-163520-66302d`，凭证
> `.quality-state/reports/20260914164434-small-89e27f.md`；`tests/test_pca_nale_networks.py` 38 项全绿，弱断言 0 error。
> 1. **新增 `src/graph/pca_nale_networks.py`**：三类 PIT 可评网络 —— `W-ind`（同 `sub_industry` 共现，
>    静态结构假设、`is_observed=False`）、`W-corr`（截至 t 的过去 60 日 `basis_return` 相关）、
>    `W-attn`（日频文本对数计数滚动相关，逐条 `publish_time` + 次日可用）；两条**拒绝产出**的登记：
>    `W-text` 嵌入相似 = `NOT_ASOF`（768 维向量全晚于 2026-09-07、本机无嵌入模型缓存），
>    `W-supply` = `NOT_EVALUABLE`（仓库无带 `available_at` 的供应链边账本）。两条必须与主结论并列出现。
> 2. **F6 陷阱工程化**：缺相关性证据（重叠不足 / 零方差 / 非有限 ρ）一律**拒边并分别计数**，
>    **绝不回落 0.5**；测试里有反向守卫断言权重集合中不出现 0.5。归一化与传播复用 M1 权威实现
>    （为此在 `nale_alpha_adapter` 暴露公开 `normalize_network`），孤立点仅自环（N=S0）。
> 3. **产物**：覆盖率/密度/度分布/孤立点统计 + 去边敏感性（权威传播核 α=0.4）+ §3 契约边账本
>    （校验 `available_at >= valid_from`；空边账本拒绝下结论）。
> 4. **真实冒烟**（`scratch/smoke_m3_real.py`，只读，域 A 组 99 支，信号日 2025-04-02，语料 79,225 条）：
>    W-ind 2,401 边（= C(50,2)+C(49,2) 精确吻合）、密度 0.4949、覆盖 1.000；
>    W-corr 1,520 边、密度 0.3133、覆盖 1.000、权重 0.4001~0.9547、低于阈值 3,331 对；
>    **W-attn 387 边、密度 0.0798、覆盖 0.869（13/99 孤立）**、零方差 98 对；
>    去边敏感性：W-corr 移 5%（76 边）max|ΔS|=0.809、W-ind（120 边）0.573、W-attn（19 边）0.172。
> 5. **更正**：交接书 §5 曾称行业字段有"38 类"，实测为 **6 类各 50 支**，已改。
> 6. **局限（M4 必须遵守）**：W-attn 的孤立点在传播中等价于不传播，须分网络报告覆盖度；
>    W-ind 与中性化行业哑变量同源，**必须做去共线消融**后才能谈"传播增益"；C 组无技术因子，
>    网络与 S0 不能跨组同域，跨域结论一律不下。
>
> **2026-09-14 M2 as-of S0 面板工厂已交付 + 新登记 BUG-0027（同一轮）**：单元
> `UNIT-20260914-154005-978deb`，凭证 `.quality-state/reports/20260914161226-small-2655f9.md`，
> `small: 有效`、活动单元已关闭；`tests/test_pca_nale_asof_panel.py` 45 项全绿，弱断言扫描 0 error。
> 1. **新增 `src/data/pca_nale_asof_panel.py`**（纯函数、夹具可测）：把 S0 从"无日期静态截面复制到每一天"
>    改成**逐信号日**截面 —— 交易日历对齐（占位状态 `trading/suspended/delisted/not_listed`）、
>    **按日历计数**的前瞻标签（`label_h/label_ok_h/label_reason_h` 逐例记拒绝原因，修 F10）、
>    训练期定标 `StandardScaler`+full-SVD `PCA(10)` → PC 截面 Z → 等权合成 → MAD 去极值 →
>    行业哑变量 + **当日**对数流通市值 OLS 残差 → 截面 Z-score；缺失特征**整行标不可用并计数**（绝不填 0）；
>    输出满足交接书 §3 契约列。`S0_pc5_prior` 仅作"历史固定先验基线"（版本号写明 `lookahead_derived`），
>    主口径 `S0` 不使用任何标签拟合（裁决 D3）。
> 2. **独立复核（不依赖门禁退出码）**：时间往返（改 cutoff 之后的特征/价格/市值/收益，此前信号日的
>    `S0` 与 PC 得分逐位不变）；跨停牌 5 日标签手算乘积逐位比对 + 反向守卫（证明"按可用行偏移"会给出
>    跨过停牌日的假数字）；中性化残差对行业哑变量与对数市值的正交性用 `lstsq` 独立验证；
>    PCA 符号对齐用手造载荷手算 + 引擎内不变量双测；`NOT_ASOF` 族任何配置下被拒绝。
> 3. **真实数据冒烟**（`scratch/smoke_m2_real.py`，只读，无产物覆盖）：A 组 99 支 × 89 个信号日 = 8,746 行
>    全部可用；`S0` 均值 0 / 标准差 0.995 / 范围 [−3.54, +4.05]；10 PC 累计解释方差均值 96.77%；
>    **`S0` 与 `S0_pc5_prior` 截面相关仅 0.09** ⇒ 十维口径与五维固定先验不可互称，必须并列报告；
>    标签可用 1 日 8743/8746、5 日 8636、10 日 8526、20 日 8306，拒绝原因全部可归因。
> 4. **误判与改正（自记）**：曾写"把全部特征取反后 S0 不变"作为符号对齐的守卫 —— 该断言**是错的**
>    （数据取反会让投影得分整体变号，这是正确行为），已改为对手写载荷矩阵直接验证对齐规则本身。
> 5. **新登记 BUG-0027（data/heavy，评分 16/22）**：主面板特征族**按组割裂** —— 技术类因子只在 A 组
>    99 支有值、基本面 `pe_ttm/pb/roe` 只在 B/C 组有值、申报总收益 `ret` 只在 A 组有值；即 "master"
>    面板是三份不同交付的纵向拼接（同 F1 性质），**任何跨 299 支统一因子截面都得到整列 NaN 且静默**。
>    另实测 A 组申报 100 支而面板仅 99 支：**`600317` 整支 644 行完全缺失**（完成 M0.4 逐支归因）。
>    未修复；as-of 面板工厂已据此 fail-closed，跨组建模在补数据前不可行。
> 6. **遗留（下一单元）**：M4 CLI 必须改用**训练期** `verify_caliber` 结论（冒烟脚本为省事传了全样本表，
>    属前视通道，不得复制进 CLI）；`text_flow_v1` 尚未在真实语料上跑通（与 M3 的 W-text 一起做）；
>    `industry` 来自 `universe_300_assigned.csv` 静态 `sub_industry`，属静态结构假设须在 W-ind 处声明。
>
> **2026-09-14 M1 权威模块收敛（同一轮，紧随 M0/M0.5）**：单元 `UNIT-20260914-150259-a0f6c1`，
> 凭证 `.quality-state/reports/20260914151622-small-3975bd.md`，`small: 有效`、活动单元已关闭。
> 1. **传播核唯一化**：权威实现 `src/graph/nale_alpha_adapter.propagate_nale_vectorized`
>    （`S = S0 + α·(S0 @ Wᵀ − S0)`）。`src/pricing/dynamic_nale_alpha.propagate_nale` 改为
>    **模块级别名再导出**（`propagate_nale = propagate_nale_vectorized`，不是 def 包装），故 `is` 同一性成立，
>    任何一方被改写都会立刻被 `tests/test_nale_propagation_authority.py` 发现；字典式
>    `nale_alpha_adapter.propagate_nale` 内部也改为调用同一核并加等式自证。签名 `(S0, W_norm, alpha)` 不变。
> 2. **修掉"缺相关即通过"的静默兜底**（`src/graph/sector_graph_engine.py`）：删除
>    `corr = 0.5` 与 `stock_corr_with_leader = 0.5` 两个默认值。修复前**没有任何相关性证据**时
>    （无矩阵 / 股票不在矩阵 / 值为 NaN）`0.5 >= corr_threshold(0.40)` 恒成立 → 任意 peer 都被塞进
>    `co_movement_peers`，且板块一旦有涨停就必然判 `follower_catchup` 并凭空给出 0.5%~3.0% 溢出收益，
>    属编造量化结论。现改为缺证据即拒绝该 peer 并计数；龙头相关性无证据时为 `None`，**不得**推断追随；
>    新增 `corr_missing_evidence_count` / `leader_corr_with_stock` / `leader_corr_missing` 字段显式透出缺口
>    （未知板块兜底分支同 schema）。`corr_threshold` 仍为 0.40，未放宽。
> 3. **独立复核**：`tests/test_nale_propagation_authority.py`（18 项）含两条入口逐位一致、
>    手算两点图、α=0 不动点、孤立行自环、五类非法输入拒绝路径；`tests/test_sector_graph_missing_corr.py`（9 项）
>    含矩阵缺失 / 整行 NaN / 代码不在索引 / 负相关 / **真实高相关正向路径**（未误伤）。
>    `probe_m1_mutation_check.py` 反向能力自检：同一夹具下旧逻辑给出
>    `follower_catchup + 1.25% 溢出 + 2 peer`，修复后为 `divergent + 0.0% + 0 peer + missing=2`。
>    弱断言扫描 0 error（3408 条断言，占比 0.4%）。**局限**：本轮只做静态/单元级复核，
>    传播层生产调用仍为 0，B0 与网络 W 尚无合法输入（见 F6），不得据此宣称 NALE 已可实证。
> 4. `verdict` 仍为 `block`，原因不变且与本次改动无关：09-10 遗留 heavy 失败凭证 + BUG-0024 依赖冲突。
>
> **2026-09-14 M0 收益口径独立复核与统一（优先于本日 768 维条目与 09-10 更正）**：交接书见
> [`docs/handoff_pca_to_nale_integration.md`](file:///D:/R-FinGPTv2（国创版本）/docs/handoff_pca_to_nale_integration.md)。
> 1. **推翻一条流传的因果判断**："M1.4 用 `close.pct_change()` 填 B/C 造成 −10%~−67% 伪崩盘"不成立。
>    实测板块涨跌停越限行：**A 组 12 行、B 组 0/64,300、C 组 0/64,300**（若同为不复权，期望各约 12.2 行，
>    P(0)≈5×10⁻⁶）；复权恒等式 `(market_value/close)÷(volume/turnover_rate)`：A 组平坦于 1.0040，
>    B/C 组自 1.0623/1.0795 收敛到**恰好 1.000**。结合 `scripts/fetch_student_{b,c}_csmar_data.py:77-81`
>    与两份 manifest 指向 CSMAR `TRD_FwardQuotation.ClosePrice`，判定 **B/C 的 close 已是前复权价、
>    A 的 close 是不复权 `Clsprc`（其 `ret` 才是 `Dretwd` 总收益）**。09-10 接续审计当时因缺元数据
>    撤回了"前复权"说法，本轮补上了可计算判据，但仍**未获 CSMAR 字段字典级确认**。
> 2. **真正的缺陷在反方向**：凡拿 `close` 直接算前瞻收益的代码对 A 组会把除权日读成暴跌并丢分红。
>    `scripts/evaluate_ashare_pca_factors.py:145,157-164` 对全部 299 支用 `close.shift(-h)/close-1`，
>    致 A 组 12 行伪崩盘入标签、年化 3.11% 系统性低估（日均背离 1.234e-4，159 行 >1%）。
>    **故 `reports/tables/ashare_pca_factors/` 全部 IC 指标作废待重算**（含 `alpha_composite_nale`
>    Mean Rank IC +0.0144、年化 ICIR 2.24、胜率 54.93%、PC5 p=0.004），已就地放置
>    [`INVALIDATION_NOTICE.md`](file:///D:/R-FinGPTv2（国创版本）/reports/tables/ashare_pca_factors/INVALIDATION_NOTICE.md)，
>    原件保留不删。**本日上一条 768 维条目所引用的这些数字同步失效，不得再用于网申/PPT。**
>    M1.4 回测汇总（`ashare_pca_backtest/`）仍不可用，但作废理由改为全样本 fit、静态截面当逐日信号、
>    重叠收益逐年化、`transaction_cost` 形参未生效，**不再是**"伪崩盘"。
> 3. **交付**：`src/data/return_basis.py`（声明式口径 + 恒等式独立复核 + 统一总收益构造）、
>    `config/data_caliber/csmar_master_close_basis.json`（逐支 `source_table/adjustment/provenance`）、
>    `scripts/audit_return_basis.py`、`tests/test_return_basis.py`（36 项全绿、弱断言扫描 0 命中）、
>    审计产物 `reports/tables/pca_nale_integration/m0-baseline-v2/`（**权威版**；`m0-baseline-v1/` 为
>    B 组证据升级前的历史 run，按不可覆盖原则保留）。统一口径覆盖 **191,999/192,199 = 99.8959%**，
>    越限伪收益行数 **0**，`contradicted` **0**，`max|basis_return| = 0.20035`。
>    B 组口径证据已升级：库内原始导出 `data/raw/pr_sources/pr4-dd94761/trd_fward_quotation.csv`
>    （sha256 `b818d4cf…`）与主面板 B 组 `close` **64,400/64,400 行逐行完全相等（max|Δ|=0.0）**；
>    **C 组原始导出缺失**（`student_c/sources/` 不存在），其前复权判定仍属表名+恒等式推断，证据等级低于 B。
>    另：面板缺的 357 个"单元格"实为 **357 整行**（`601989 中国重工` 264 行 2025-08-12 被 `600150` 吸并退市
>    + 12 支共 93 个停牌日，全在 A 组）→ 前瞻标签必须按交易日历计数并显式占位，
>    **禁止 `groupby(code).shift(-h)` 按可用行偏移**（实测会使"5 日标签"横跨约 19 个交易日）。
> 4. **两条防回退教训**：(a) 用"市值增速背离"修复除权日反而凭空造出 5%~16% 新误差（52 行中 40 行受害），
>    不复权序列的恒等式比值本就平坦、不含除权信息，故废弃该修复；(b) 用恒等式漂移反驳"不复权"声明会
>    误判 36 支 A 组股票，漂移实为**解禁/增发/回购**改变流通股本，不构成反证。另：口径**必须由来源声明驱动、
>    不得由全样本收益反推**——实测扰动 2025-06-30 之后的行情会改变历史行收益，是一与前视同源通道。
> 5. **NALE 侧现状**：`alpha_composite_nale` 之名与 NALE 传播无关（`factor_neutralization.py:302` 只是
>    PC1~PC5 固定权重线性组合）；`calculate_nale_score` 非测试调用方为 **0**、`SupplyChainGraph()` 实例化为**零边**、
>    `data/` 下网络边证据 **0 命中**、768 维嵌入**无任何点时历史**（300 个抓取时间戳挤在 2026-09-07~09）。
>    故 NALE 传播层在本项目实质为绿地，M1.4 也从未真正运行 NALE。
> 6. **门禁扫描器已修（M0.5，同批）**：`tools/assert_scanner.py` 曾漏认 pandas 断言
>    （`assert_frame_equal/series_equal/index_equal`）并把测试内的 `def test_*` 辅助函数当用例，
>    造成 **2 条 error 级假阳性**（`test_nale_alpha_pit_panel.py:43`、`test_nale_alpha_selection.py:34`）
>    —— 此前 `verdict = block` 正是被这两条驱动。修复后 `errors 2→0`、`total_asserts 3321→3341`、
>    `weak_ratio 0.45%→0.39%`、`scan passed→True`，回归锁定 `tests/test_assert_scanner_false_positives.py`
>    （含"真无断言仍须报 error"的反向能力用例），门禁自测 70 项仍全绿，凭证 `…/20260914144221-small-80aa24.md`。
>    **今后引用 `verdict` 前请注意**：剩余 `block` 项是 09-10 遗留 heavy 失败凭证（5 项全量回归）
>    与 BUG-0024 依赖冲突（`magika` 要求 `onnxruntime<=1.20.1`，实装 1.29.0），二者均为真实问题，
>    不得再归因于扫描器假阳性。`weak_assert_check` 的 fail-open 分支实测未被触发，未擅自改为 fail-closed。

> **2026-09-14 768 维语义主成分 A 股化因子工程与日频截面评测落地（⚠ 本条 IC 数字已由上方 M0 条目作废）**：已根据 `/grill-me` 互动达成的 4 项核心设计共识，全栈实现 768 维降维主成分（PC1~PC5）至 A 股标准化因子的流水线架构并完成实证评测。
> 1. **核心算法模块**：新增 `src/pricing/factor_neutralization.py`，实现 3 倍 MAD 去极值 (`winsorize_mad`)、行业哑变量 + 对数流通市值多元 OLS 残差正交化 (`neutralize_cross_section`)、截面 Z-score 标准化 (`standardize_zscore`)，以及 `ASharePCAFactorPipeline` 端到端子因子映射与综合 Alpha 合成。
> 2. **单元测试与门禁**：新增 `tests/test_factor_neutralization.py`（7 个测试全部通过，验证残差与市值/行业相关系数绝对值严格降至 $10^{-10}$ 量级）。已通过质量门禁 `small` 与 `medium` 双层测试凭证。
> 3. **300 股日频截面评测与白皮书 CLI**：新增 `scripts/evaluate_ashare_pca_factors.py`，对全池 300 标的在 644 个交易日（2024-2026）进行真实前瞻 5 日截面 Rank IC 与 10 日重叠块 Bootstrap（500次采样）评测。实证表明：
>    - `alpha_institutional_gaming` (PC5, 机构博弈兑现回踩因子) 呈现强劲且高度显著的负溢价：Mean Rank IC = -0.0225，年化 ICIR = -3.52，95% CI = [-0.0374, -0.0072]，Block Bootstrap $p = 0.004 < 0.01$（5%与1%水平下双重显著），5 分组单调性得分 = -0.90；
>    - `alpha_composite_nale` (加权综合 Alpha 信号) 表现卓越：Mean Rank IC = +0.0144，年化 ICIR = 2.24（工业级可用），胜率 = 54.93%，5 分组 Q5-Q1 5日超额收益 = +0.129%。
>    - 评测报表与白皮书已固化输出至 `reports/tables/ashare_pca_factors/`。

> **2026-09-12 PR #7 审查与采纳更新**：已严格检验并采纳远端 PR #7 (`feat(nale): add Week1 alpha engineering scaffold (draft)`)，由 SoliloquyRyan 提交（commit `6d895c8`）。该 PR 涵盖 48 个文件，完整实现了 Week1 NALE 无前视工程骨架：时点数据契约、点在时间修订选择器 (`nale_alpha_asof.py`)、因果标签生成 (`nale_alpha_labels.py`)、B0 校准非负约束 ($c \ge 0$)、Sigmoid 有界门控 ($\alpha \in [0.05, 0.75]$)、解析梯度与优化失败 B0 兜底 (`nale_alpha_models.py`)、走步回测管道与 5/20 日隔离、块 Bootstrap (2000次/10日块) 与 Holm 多重检验校正 (`nale_alpha_metrics.py`)，以及安全只读审计 CLI (`tools/audit_nale_alpha_inputs.py`)。经独立复核，发现并修复了 2 处兼容细节：1) `test_nale_alpha_panel.py` 在 Pandas 3.0+ pyarrow 字符串列下非六位代码测试赋值抛出 TypeError 的问题；2) `nale_alpha_source_contract.py` 中时区正则捕获组产生的 UserWarning。新加入的 25 个测试套件（120 个测试）及现有动态 NALE 测试（9 个测试）共 129 个测试 100% 绿灯通过，0 警告。旧版 2026-09-10 代理实验草稿已安全迁移至 `scratch/proxy_study_20260910/` 归档。

> **2026-09-12 PR #7 工程吸收与统一评测 CLI 交付**：已封装实现 Week 1 NALE 统一评测与审计 CLI `scripts/evaluate_nale_alpha.py`，打通 PR #7 研发骨架。CLI 提供双模式支持：1) 默认严格因果门禁（Fail-Closed，未通过 PIT 数据溯源审计退出码为 2，输出结构化 JSON 审计报告，拒绝虚假绿灯）；2) 测试夹具与冒烟执行模式（`--allow-fixture --smoke`，自动将产物安全隔离至 `research-outputs/nale_alpha_week1/fixtures/<run_id>`，产出 11 份标准化产物与图表，强制附带 `engineering_fixture` 水印，拒绝覆盖已有目录）。编写了专门端到端测试套件 `tests/test_evaluate_nale_alpha_cli.py`（5 个测试全部通过），全量 NALE 测试套件扩展至 134 个测试 100% 通过（34.10s，0 失败 0 警告）。

> **2026-09-10 实际回测完成更新（优先于下方旧状态）**：已完成V1–V5及B0的98股历史标题/真实Dretwd代理实验，测试378个信号日，独立复核通过。各版Rank IC约-0.033，净Sharpe约0.885，最大回撤37.46%；逐级增益不显著，V1全程不可识别回退、V2另有22日求解失败回退。研究结果不支持替换稳定基准。生产300股统一历史输入仍不足；不能把代理研究称生产NALE全量验收。报告见 reports/tables/nale_alpha_week1/20260910-five-formulas/five_formula_report.md。PR1–6远端已核对，PR4四份缺失原始表已隔离恢复。旧前视成绩仍无效。

# 🧠 项目全局记忆与双向上下文同步 (Antigravity ⟷ Codex Shared Memory)
> **2026-09-10 接续独立审计更正（优先于第五节旧结论）**：Week1现状是“已有工程原型，真实无前视MVP未完成”。旧评估存在最新文本截面回填历史、未成熟标签训练、V5直接使用当前未来收益，以及绿电同日选股计收益和未来参数回灌。因此第五节Rank IC提升/显著性、>100%收益和>7.8夏普只保留为旧原型输出，不可用于有效实证、比赛宣传或稳定版本替换。9个既有测试本轮重跑通过，但独立解析样例发现校准器斜率错误；行情主表实为299股644日，特征中心化秩299。详情见 [接续审计](reports/tables/nale_alpha_week1/recovery-audit-20260910/validation_report.md) 与 [接续计划](specs/contest-2026/week1-recovery-plan.md)。原始数据及稳定产物保留，后续先核历史可用性并修复公式/时间管线。

> **追加数据来源更正**：`data/raw/backtest_paper_2024_2026_300stocks/market_prices.csv` 的694日行情经生成源码及内存重算确认是seed42随机模拟（指数及300750吻合至1e-12量级），不得作为真实300股回测输入。CSMAR master的A组close是Clsprc未复权价，与Dretwd总收益字段不同；B/C复权元数据仍缺，不能宣称统一前复权。原文件保留，真实实验需使用经审计的一致收益口径。

> 同步时间：2026-09-10（新增接续审计；旧章节保留历史）  
> 同步主体：Antigravity Agent 与 OpenAI Codex  
> 核心项目根目录：`D:\R-FinGPTv2（国创版本）`

---

## 一、 项目全局基本信息 (Project Metadata)
- **项目名称**：Rainbow-FinGPT（2026年中国国际大学生创新大赛 - 产业命题赛道 / 校赛网申）
- **根目录路径**：`D:\R-FinGPTv2（国创版本）`
- **主要参与者**：吴宇轩（申报人/负责人）等团队成员
- **比赛要求节点**：校赛网申窗口
- **最终交付物清单 (必须为 PDF，单个 < 50MB，不上传 PPTX 源文件)**：
  1. `Rainbow-FinGPT+参赛作品申报表+吴宇轩.pdf`
  2. `Rainbow-FinGPT+项目PPT.pdf`
  3. `Rainbow-FinGPT+商业计划书.pdf`

---

## 二、 算法、数据与研发进展记忆 (Antigravity 研发成果)
1. **真实数据抓取 (Milestone 1)**：
   - 抓取 A 组与 C 组 200 支真实股票的公告与新闻数据（共计 77,254 条真实公告，严格 6 位股票代码）。
   - 存放于 `data/raw/student_ac_crawled/{code}.jsonl`，拒绝任何假数据或合成模板。
2. **768 维因子提取与 SHA256 溯源 (Milestone 2)**：
   - 本地 FastEmbed 嵌入模型：`jinaai/jina-embeddings-v2-base-zh`，生成 768D 向量且单位 L2 归一化。
   - 生成 `factors_768d_student_A.csv` 与 `factors_768d_student_C.csv`（100行 × 780列），配备每只股票的 SHA256 溯源 JSON 文件。
3. **300 支股票因子融合与高维资产定价回归 (Milestone 3)**：
   - 形成全量 300 × 780 主宽表 `data/task_split/factors_768d_all.csv`。
   - 运行高维 Fama-MacBeth 回归，在 `reports/tables/regression_768d/` 生成 7 份标准学术回归报表。
4. **全套自动化测试与验证门禁**：
   - 38/38 端到端流水线测试、99/99 验收测试、156/156 整体测试 100% 通过。
   - 审计结论：零 Mock、零硬编码、哈希与原始语料 100% 对应。
   - ⚠️ **2026-09-14 实测更正（本条第二句不再成立）**：768 维因子表声明的公告总数 409,017 条中，
     盘上可核实的只有 77,254 条（**18.9%**）。分组：A 组 40,999/40,999 = 100% 且 `input_sha256` 与
     抓取 sidecar 100/100 一致；**B 组声明 195,050 条、盘上 0 条**（`student_ac_crawled` 无 B 组文件、
     `student_b/sources` 不存在）；**C 组声明 172,968 条、盘上 36,255 条（21.0%），且 100/100 支哈希不合**
     （因子表还把 C 组新闻数全记为 0，实测 sidecar 有 991 条）。
     BUG-0025 的 `000001` 哈希失败因此**不是孤例而是整个 C 组系统性失配**，根因已定位但尚未修复，不得 `resolve`。
     另外 `.meta.json` 的 `raw_text` 是 2,746 字符截断摘要，5 种规范化候选均无法复现 `input_sha256`（含 A 组），
     故该哈希链在仓库内**不可第三方复算**，"100% 对应"当初也未被独立复算过。
     复现：`scratch/verify_cohort_backing.py`、`scratch/verify_provenance_reconciliation.py`、
     `scratch/verify_hash_reproducibility.py`；影响与处置见交接书 F12/F13。
   - 同批实测更正：`feature_source` 的分组归属为 **A=fastembed 本地蒸馏 100 支、B/C=DeepSeek 摘要各 100 支**
     （provenance JSON 的 `llm_backend` 一致），即同一 768 维基底混两种摘要后端、**离群组是 A**；
     先前两份清点报告分别把离群组说成 B 与 A∪C，均不准确。

---

## 三、 网申与 PPT 评审核心要点与纠错记忆 (Codex 评审成果)
1. **PPT 与 PDF 版本一致性**：
   - 根目录旧版 PDF 是 9 月 1 日深色版导出，与 9 月 3 日最新 18 页白底 PPTX 存在严重版本脱节。必须从定稿 PPTX 重新导出为最终 PDF。
2. **数据口径统一与诚实原则**：
   - 必须严格以 [PPT素材包/05_参考文档/诚实口径数据源(以此为准).md](file:///D:/R-FinGPTv2（国创版本）/PPT素材包/05_参考文档/诚实口径数据源(以此为准).md) 和 [学术纠错报告](file:///D:/R-FinGPTv2（国创版本）/学术纠错报告_Academic_Integrity_Corrections.md) 为唯一事实源。
   - 避免在新旧 PPT 中混淆标的范围、胜率口径与策略对比。
3. **申报表与 PPT 待修硬伤**：
   - **PPT 第 16 页**：标题写“10 项核心考核指标”但内容只列出 1~8 项，必须对齐。
   - **申报表**：官方模板为 A4 页面，需移除“高校导师组、企业导师组”等占位字符，补全真实联系方式。
   - **视觉增强**：PPT 第 6、9、11、13~15、17 页需替换为真实的架构图、回撤图、校准曲线与案例截图，减少纯文本框。

---

## 四、 协作准则与环境约束 (Shared Working Protocol)
- **代码与测试规范**：修改源码前严格执行 `tools/run_quality.ps1 begin-unit`，阅读 `bug合集`，遵循 `small -> medium -> heavy` 渐进测试。
- **量化回测原则**：新版本必须在全量回测中体现出显著优于上一版本的实质提升，否则坚决保留稳定基准。
- **文件管理与安全**：禁止直接整目录删除嵌套的 `Rainbow_FinGPTv2/`；所有中间预览在 `scratch/` 进行，最终提交文件汇总于 `00_网申提交_2026/`。

## 五、Week1 最新进展与实证结果（2026-09-10）

> ⚠️ **本节数字已被本节下方的 09-10 接续审计与文件顶部条目作废，仅保留为旧原型输出史**。
> 下述 Mean Rank IC 0.0510、t=3.92/p=0.0001、">100% 收益"、">7.8 夏普"存在最新文本截面回填历史、
> 未成熟标签训练与同日选股计收益等问题，**不得用于有效实证、网申宣传或稳定版本替换**；
> 末行"凭证有效"亦已过时——门禁凭证与源码哈希绑定，须以 `tools/quality_gate.py status` 实时结果为准。
> 保留本节只为记录口径演进，标题中"已实现并经独立门禁验证"的说法不再成立。

- **实施基准与代码交付**：
  - 核心模块：`src/pricing/dynamic_nale_alpha.py`（实现十维 PCA 冻结投影、公共校准器、Sigmoid 有界门控 $[0.05, 0.75]$、B0~V5 全版本非线性求解引擎）。
  - 独立验证：`tests/test_dynamic_nale_alpha.py`（覆盖 Section 10 规定的 8 项独立断言，9/9 单元测试 100% 通过）。
  - 评估流水线：`scripts/evaluate_nale_alpha_mvp.py`（完成跨板块 40 支标的 453 交易日走步回测与 2025Q3 绿电板块对决回测）。
- **核心量化实证发现**：
  1. **V1 静态十维赋权显著超越旧版 B0**：全样本 Mean Rank IC 达到 **0.0510**（相比 B0 的 0.0372 提升 **+0.0138**，配对检验 $t=3.92, p=0.0001 < 0.001$ 具有极强统计显著性），ICIR 由 0.1046 提升至 **0.1325**。
  2. **2025Q3 绿电板块突破行情扭转被动**：在绿电等权 ETF 累计上涨 20.50% 的主升浪中，结合市场状态感知的 V4/V5 及 V1 策略均斩获 **>100%** 累计收益率与 **>7.8** 年化夏普比率，有效解决了“暴涨不知道、财报滞后”的核心痛点。
- **全套归档工件**：
  - 数据审计与溯源：`reports/tables/nale_alpha_week1/mvp/data_audit.md`
  - 需求矩阵跟踪：`reports/tables/nale_alpha_week1/mvp/requirements_traceability.csv`
  - 学术文献差异表：`reports/tables/nale_alpha_week1/mvp/literature_difference.md`
  - 核心对比报表：`reports/tables/nale_alpha_week1/mvp/version_comparison.csv`、`green_energy_2025q3_backtest.csv`、`mvp_evolution_report.md`
  - 运行元数据清单：`reports/tables/nale_alpha_week1/mvp/run_manifest.json`
- **质量门禁状态**：`tools/quality_gate.py small` 绿灯通过，凭证有效。

