# IMIS数据成员 - Week 1任务卡：因子数据准备

## 👤 你的角色
数据层工程师 - 负责提取、清洗、准备用于PCA的因子矩阵

---

## 🎯 你的Week 1目标
**从现有回测数据中提取因子矩阵，用于PCA降维和PC5提取**

---

## 📋 详细任务（Day 1-2）

> [!IMPORTANT]
> **终端工作路径说明**：
> 请直接在**仓库根目录**下打开终端执行命令与脚本，所有相对路径（如 `data/raw/...`、`scripts/...`）均以仓库根目录为基准。切勿进入 `Rainbow_FinGPTv2/` 子目录，当前统一主数据中心为根目录下的 `data/`。

### Day 1 上午：理解数据结构（2小时）

#### 任务1.1：定位因子数据文件

**你需要找到这些文件**：
```bash
# 可能的位置1（推荐）
data/raw/backtest_storage_2025q2_2026q3/factors.csv

# 可能的位置2
data/raw/backtest_gold_2025q3_2026q8/factors.csv

# 可能的位置3
data/raw/backtest_green_2025q3_2026q3/factors.csv

# 可能的位置4（如果上面都没有）
docs/data/analysis/*.json  # 可能需要从这里提取
```

**检查命令**：
```bash
# Windows PowerShell
Get-ChildItem data/raw -Recurse -Filter "*.csv" | Select-Object FullName

# 或者用Python
python -c "from pathlib import Path; print(list(Path('data/raw').rglob('*.csv')))"
```

---

#### 任务1.2：查看文件结构

**用Python查看**：
```python
import pandas as pd

# 读取第一个可能的文件
file_path = "data/raw/backtest_storage_2025q2_2026q3/factors.csv"

try:
    df = pd.read_csv(file_path, nrows=10)  # 先只读前10行
    
    print("="*60)
    print("文件基本信息")
    print("="*60)
    print(f"文件路径: {file_path}")
    print(f"形状: {df.shape}")
    print(f"\n前5行:")
    print(df.head())
    print(f"\n列名:")
    print(list(df.columns))
    print(f"\n数据类型:")
    print(df.dtypes)
    
except FileNotFoundError:
    print(f"❌ 文件不存在: {file_path}")
    print("\n请检查其他可能的位置")
except Exception as e:
    print(f"❌ 读取失败: {e}")
```

**你需要回答这些问题**：
1. ✅ 文件存在吗？
2. ✅ 行是什么？（日期？股票代码？）
3. ✅ 列是什么？（因子名称？）
4. ✅ 值是什么？（因子得分？）
5. ✅ 有多少天的数据？
6. ✅ 有多少只股票？
7. ✅ 有缺失值吗？

**预期的结构（两种可能）**：

**结构A（推荐）**：
```
          MKT     SMB     HML     MOM   Quality  ...
date
2025-05-01  0.5    0.3    -0.2     0.8     0.6
2025-05-02  0.4    0.2    -0.1     0.7     0.5
...
```
- 行：日期
- 列：因子名称
- 值：某只股票在该日期、该因子的得分

**结构B（需要转置）**：
```
        2025-05-01  2025-05-02  2025-05-03  ...
MKT          0.5        0.4        0.6
SMB          0.3        0.2        0.4
HML         -0.2       -0.1        0.0
...
```
- 行：因子名称
- 列：日期
- 需要转置 `df.T`

---

### Day 1 下午：数据清洗（3小时）

#### 任务1.3：编写数据准备脚本

**创建文件**：`scripts/day1_prepare_factor_data.py`

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Day 1: 准备因子数据用于PCA

负责人: IMIS数据
日期: 2026-09-06
"""

import pandas as pd
import numpy as np
from pathlib import Path
import sys

print("="*60)
print("Day 1: 因子数据准备")
print("="*60)

# ========== 步骤1: 加载原始数据 ==========
print("\n[步骤1] 加载原始数据...")

# TODO: 替换为实际文件路径
file_path = "data/raw/backtest_storage_2025q2_2026q3/factors.csv"

try:
    # 读取数据
    df_raw = pd.read_csv(file_path, index_col=0, parse_dates=True)
    print(f"✅ 加载成功: {file_path}")
    print(f"   形状: {df_raw.shape}")
    print(f"   日期范围: {df_raw.index.min()} 到 {df_raw.index.max()}")
    
except FileNotFoundError:
    print(f"❌ 文件不存在: {file_path}")
    print("\n请检查以下位置：")
    print("  - data/raw/backtest_storage_2025q2_2026q3/factors.csv")
    print("  - data/raw/backtest_gold_2025q3_2026q8/factors.csv")
    sys.exit(1)
    
except Exception as e:
    print(f"❌ 读取失败: {e}")
    sys.exit(1)

# ========== 步骤2: 检查数据结构 ==========
print("\n[步骤2] 检查数据结构...")

print(f"\n列名（前10个）:")
print(list(df_raw.columns[:10]))

print(f"\n数据类型:")
print(df_raw.dtypes.value_counts())

print(f"\n前3行:")
print(df_raw.head(3))

# 检查是否需要转置
# 如果列名看起来像日期，那就需要转置
first_col = str(df_raw.columns[0])
if first_col.startswith("20"):  # 可能是年份开头
    print("\n⚠️ 检测到列名可能是日期，需要转置")
    df_raw = df_raw.T
    print(f"   转置后形状: {df_raw.shape}")

# ========== 步骤3: 数据清洗 ==========
print("\n[步骤3] 数据清洗...")

# 3.1 检查缺失值
missing_ratio = df_raw.isnull().sum() / len(df_raw)
print(f"\n缺失值统计:")
print(missing_ratio[missing_ratio > 0].sort_values(ascending=False))

# 3.2 删除缺失值过多的列（>20%）
cols_to_keep = missing_ratio[missing_ratio < 0.2].index
df_clean = df_raw[cols_to_keep].copy()

n_dropped = len(df_raw.columns) - len(df_clean.columns)
if n_dropped > 0:
    print(f"\n删除了 {n_dropped} 个缺失率>20%的列")
    print(f"保留列数: {len(df_clean.columns)}")

# 3.3 填充剩余缺失值
# 策略：前向填充（用前一天的值）+ 用0填充开头
df_clean = df_clean.fillna(method='ffill').fillna(0)

print(f"\n✅ 清洗完成")
print(f"   最终形状: {df_clean.shape}")
print(f"   剩余缺失值: {df_clean.isnull().sum().sum()}")

# 3.4 检查数据质量
print(f"\n数据质量检查:")
print(f"  - 行数（天数）: {len(df_clean)}")
print(f"  - 列数（因子数）: {len(df_clean.columns)}")
print(f"  - 最小值: {df_clean.min().min():.4f}")
print(f"  - 最大值: {df_clean.max().max():.4f}")
print(f"  - 均值: {df_clean.mean().mean():.4f}")

# 警告检查
if len(df_clean) < 60:
    print("\n⚠️ 警告: 数据不足60天，可能影响PCA结果")
    
if len(df_clean.columns) < 5:
    print("\n⚠️ 警告: 因子数不足5个，可能无法提取PC5")

# ========== 步骤4: 保存结果 ==========
print("\n[步骤4] 保存结果...")

output_dir = Path("data/week1_pca")
output_dir.mkdir(exist_ok=True, parents=True)

# 4.1 保存清洗后的因子矩阵
output_path = output_dir / "factors_for_pca.csv"
df_clean.to_csv(output_path)
print(f"✅ 因子矩阵已保存: {output_path}")

# 4.2 保存统计信息
stats = df_clean.describe()
stats.to_csv(output_dir / "factors_stats.csv")
print(f"✅ 统计信息已保存: {output_dir / 'factors_stats.csv'}")

# 4.3 保存元数据
metadata = {
    "source_file": str(file_path),
    "n_days": len(df_clean),
    "n_factors": len(df_clean.columns),
    "date_start": str(df_clean.index.min()),
    "date_end": str(df_clean.index.max()),
    "factors": list(df_clean.columns),
    "missing_filled": True
}

import json
with open(output_dir / "metadata.json", "w", encoding="utf-8") as f:
    json.dump(metadata, f, indent=2, ensure_ascii=False)
print(f"✅ 元数据已保存: {output_dir / 'metadata.json'}")

# ========== 步骤5: 生成报告 ==========
print("\n" + "="*60)
print("Day 1 数据准备完成")
print("="*60)

print(f"\n✅ 交付物:")
print(f"  1. 因子矩阵: {output_path}")
print(f"  2. 统计信息: {output_dir / 'factors_stats.csv'}")
print(f"  3. 元数据: {output_dir / 'metadata.json'}")

print(f"\n✅ 数据质量:")
print(f"  - {len(df_clean)} 天 × {len(df_clean.columns)} 因子")
print(f"  - 日期: {df_clean.index.min()} 到 {df_clean.index.max()}")
print(f"  - 无缺失值")

print(f"\n✅ 可以进入Day 2（PCA降维）")
print("="*60)
```

**运行命令**：
```bash
cd D:\R-FinGPTv2（国创版本）
python scripts/day1_prepare_factor_data.py
```

---

#### 任务1.4：检查输出

**运行后，检查这些文件是否生成**：
```bash
ls data/week1_pca/

# 应该看到：
# - factors_for_pca.csv      (因子矩阵)
# - factors_stats.csv         (统计信息)
# - metadata.json             (元数据)
```

**查看输出**：
```python
import pandas as pd

# 查看因子矩阵
factors = pd.read_csv("data/week1_pca/factors_for_pca.csv", index_col=0)
print(f"因子矩阵: {factors.shape}")
print(factors.head())

# 查看元数据
import json
with open("data/week1_pca/metadata.json") as f:
    meta = json.load(f)
print(f"\n元数据: {meta}")
```

---

### Day 2：支援CS成员（可选）

**如果CS成员在Day 2遇到问题，你可以协助**：

1. **数据格式问题**：帮忙检查CSV是否正确
2. **缺失值问题**：进一步清洗数据
3. **异常值问题**：识别并处理极端值

---

## ✅ 验收标准

### 必须完成（Must Have）
- [ ] `data/week1_pca/factors_for_pca.csv` 文件生成
- [ ] 因子数 ≥ 5个（否则无法提取PC5）
- [ ] 日期数 ≥ 60天（否则PCA不稳定）
- [ ] 无缺失值
- [ ] 数据类型正确（全部是数值型）

### 期望完成（Should Have）
- [ ] 因子数 ≥ 10个（可以提取更多主成分）
- [ ] 日期数 ≥ 100天（更稳定）
- [ ] 统计报告生成
- [ ] 元数据记录完整

### 卓越完成（Nice to Have）
- [ ] 可视化因子相关性热力图
- [ ] 检查因子的时间序列平稳性
- [ ] 文档说明每个因子的金融含义

---

## 🚨 常见问题与解决

### 问题1：找不到factors.csv
**症状**：`FileNotFoundError: data/raw/backtest_storage.../factors.csv`

**解决方案**：
1. 检查其他回测目录（gold, green）
2. 查看 `docs/data/analysis/*.json` 是否包含因子数据
3. 如果都没有，需要从 `src/build_ranking.py` 重新生成

**紧急方案**：用GFCA的因子
```python
# 从scoringv3.py提取GFCA因子
from src.analysis.scoringv3 import GFCAScoringEngine

# 重新生成因子矩阵
# （需要你提供股票列表和日期范围）
```

---

### 问题2：列名不是因子名，而是股票代码
**症状**：列名像 `000001.SZ, 000002.SZ, ...`

**解决方案**：
```python
# 这种情况需要转置
df = df.T  # 转置后，行变列，列变行

# 然后重命名列为因子名（如果知道的话）
df.columns = ["Factor1", "Factor2", "Factor3", ...]  # 根据实际情况
```

---

### 问题3：因子数太少（<5个）
**症状**：清洗后只剩3-4个因子

**解决方案**：
1. **降低缺失率阈值**：从20%改为30%
   ```python
   cols_to_keep = missing_ratio[missing_ratio < 0.3].index  # 改为0.3
   ```

2. **合并多个回测目录的因子**
   ```python
   df1 = pd.read_csv("data/raw/backtest_storage.../factors.csv")
   df2 = pd.read_csv("data/raw/backtest_gold.../factors.csv")
   df_combined = pd.concat([df1, df2], axis=1)  # 横向合并
   ```

3. **从GFCA直接提取更多因子**

---

### 问题4：数据天数太少（<60天）
**症状**：只有30-40天数据

**解决方案**：
1. **合并多个时间窗口**
   ```python
   df1 = pd.read_csv(".../2025q2_2026q3/factors.csv")
   df2 = pd.read_csv(".../2026q1_2026q3/factors.csv")
   df_combined = pd.concat([df1, df2], axis=0)  # 纵向合并
   ```

2. **降低Day 5验证的要求**（但要说明局限性）

---

## 🔧 调试技巧

### 技巧1：逐步调试
```python
# 不要一次运行全部代码
# 在Jupyter Notebook或IPython里一步步调试

# 第1步：先读取
df = pd.read_csv("...", nrows=10)
print(df.head())

# 第2步：检查结构
print(df.columns)
print(df.index)

# 第3步：检查数据类型
print(df.dtypes)

# 第4步：检查缺失值
print(df.isnull().sum())

# ...依次进行
```

### 技巧2：用小样本测试
```python
# 先用前10天数据测试脚本
df_test = df.head(10)

# 确认脚本无误后，再用全量数据
```

### 技巧3：保留中间结果
```python
# 在关键步骤保存中间文件
df_raw.to_csv("data/week1_pca/debug_raw.csv")
df_clean.to_csv("data/week1_pca/debug_clean.csv")

# 方便回溯问题
```

---

## 📞 遇到问题找谁

### 技术问题
- **文件找不到** → 找队长（你）
- **数据格式不对** → 找CS成员一起看
- **Python报错** → 群里问，或用Cursor/Copilot

### 数据问题
- **缺失值太多** → 找队长决策（降低阈值 or 换数据源）
- **因子数不够** → 找队长决策（合并数据 or 调整目标）
- **不理解金融概念** → 找IMIS女生（她在做文献调研）

---

## 🎯 总结

你的Day 1任务很简单：
1. ✅ 找到 `factors.csv`
2. ✅ 清洗数据（删缺失、填空值）
3. ✅ 保存到 `data/week1_pca/factors_for_pca.csv`

**如果完成了，Day 2-5你就轻松了，主要是CS成员和队长的工作。**

**预计工作量**：3-5小时（如果数据结构清晰）

---

## 📝 今晚会议你要说什么

**汇报模板（1分钟）**：

"我负责Day 1的因子数据准备。我的任务是：
1. 找到回测数据里的factors.csv
2. 清洗后保存到data/week1_pca/
3. 确保至少5个因子、60天数据、无缺失值

我明天（周日）完成，交付factors_for_pca.csv给CS成员做PCA。"

---

**任务卡已完成！现在就可以发给IMIS数据成员了。** ✅
