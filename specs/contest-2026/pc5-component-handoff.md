# PC5（第5主成分）个人交付

负责人通过用户明确指定“选取PC5（第5主成分）”，本交付据此聚焦单个主成分的正确提取和可复现数据。项目的十维NALE研究任务书保留为总设计；本次不把PC5解释为人工P1-P5融合，也不把它单独替换为整个十维NALE门控模型。

上游基准：[contest-2026 @ 7d63bb4](https://github.com/YuxuanWuCN/stock-dashboard/tree/7d63bb4f22821549efa20c23e9ffb28ee35cbcd4)。

## 直接查看交付

[结果总览与限制](../../data/processed/pc5_component/github-7d63bb4/README.md)

- [300股 PC5 得分](../../data/processed/pc5_component/github-7d63bb4/snapshot_768d/pc5_scores.csv)
- [PC5 载荷](../../data/processed/pc5_component/github-7d63bb4/snapshot_768d/pc5_loadings.csv)
- [十个主成分解释率](../../data/processed/pc5_component/github-7d63bb4/snapshot_768d/explained_variance.csv)
- [运行清单和文件哈希](../../data/processed/pc5_component/github-7d63bb4/run_manifest.json)
- [旧绿色能源 PC5 复核](../../data/processed/pc5_component/github-7d63bb4/legacy_green/checks.json)

## 复现

在项目根目录运行；使用已安装项目依赖、matplotlib 和 scikit-learn 的 Python 环境：

```powershell
python scripts/extract_pc5.py
```

默认创建唯一的UTC时间戳目录。固定文件输入及Git blob哈希由 `config/experiments/pc5_component.json` 声明；输入变化必须先审计再更新配置。不要把输出指定为已存在目录。

旧Day2入口保留，但输出默认隔离，`--n-components` 只控制保留数量，目标始终是第5个：

```powershell
python scripts/day2_pca_extraction.py --n-components 6
```

日期因子可用 `--fit-end YYYY-MM-DD` 限制PCA拟合窗口，之后的样本只应用冻结变换。历史预测仍需另外核对 `available_at`、来源版本和标签成熟期；这一选项本身不证明上游数据无前视。

## 口径

设拟合样本特征为X，保存均值μ和总体标准差σ，X_std=(X-μ)/σ；零方差列按scale=1处理。完整SVD得到按奇异值递减排列的方向v_k，固定最大绝对载荷为正。严格选择 `PC05=X_std @ v_5`；`PC05_z` 再使用拟合样本PC05的均值和总体标准差定标。

原始PC分数不保证标准差为1。载荷是单位长度方向系数，不是收益系数或持仓权重。保存10维基底不会把目标变为PC10；不足5维或指定的保留维数超过中心化有效秩均报错。

768维输入只包含300股当前截面且全部标记local_semantic。主交付是对这些仓库文件的描述性提取。另一份legacy_green有258个日期和8个因子，供旧文件复核；两套基底的PC5不能互换。研究收益、IC和策略优劣本次均不作推断。

测试入口：

```powershell
python -m pytest -q tests/test_pc5_component.py tests/test_factor_orthogonalization.py
```

独立核对包括五个已知相关系数的因子对手算、协方差特征分解、scikit-learn full PCA对照、旧PC5逐日复现、未来样本扰动不改变训练结果、数据键和来源哈希校验、拒绝覆盖。
