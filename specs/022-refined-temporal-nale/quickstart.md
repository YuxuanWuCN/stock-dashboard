# 快速入门与原型验证指引 (quickstart.md)

**功能**：`022-refined-temporal-nale`  
**目标**：在 1 分钟内运行精修后的 NALE 时效变化原型，复核关键技术指标。

---

## 1. 运行原型对决回测

在终端中执行以下命令（全过程在纯 CPU 上运行，约需 10~20 秒）：

```powershell
# 切换到 Rainbow_FinGPTv2 目录
cd D:\股票分析项目\Rainbow_FinGPTv2

# 运行自适应时效 NALE 原型消融
python scratch/refined_temporal_nale/run_prototype.py
```

---

## 2. 核心验证指标自查

运行完毕后，重点核对以下三项指标是否达标：

1. **时效截面离散度**：
   - 检查打印日志中的 `std(node_ages)` 是否 $> 3.0$（证明不同股票的信息年龄分化明显，未退化为常数）。
2. **Version D (学习型) vs Version A (经典静态)**：
   - 检查 5 日向前预测的 `Mean Rank IC` 是否实现正向提升（预期提升 $\ge +15\%$）；
   - 检查 Newey-West HAC $t$ 统计量是否达到显著水平（$t \ge 1.96$）。
3. **高清图谱生成**：
   - 查看生成的冲激响应双波峰图：`reports/figures/refined_temporal_nale/impulse_response_curve.png`。
