# API 契约：因子正交化模块

**模块**：`src/pricing/factor_orthogonalization.py`  
**版本**：v1.0  
**更新日期**：2026-09-01

---

## 1. 核心接口

### 1.1 orthogonalize_factor

**功能**：对候选因子进行 Carhart 四因子正交化，提取特质成分

**签名**：
```python
def orthogonalize_factor(
    candidate_factor: pd.Series,
    carhart_factors: pd.DataFrame,
    return_exposure: bool = False
) -> Union[pd.Series, Tuple[pd.Series, Dict[str, float]]]:
    """
    对候选因子正交化，剥离市场/规模/价值/动量风格暴露
    
    Parameters
    ----------
    candidate_factor : pd.Series
        原始因子值，index 为日期，values 为因子得分
    carhart_factors : pd.DataFrame
        Carhart 四因子时间序列，columns = ['MKT', 'SMB', 'HML', 'MOM']
    return_exposure : bool, default False
        是否返回对四因子的暴露系数
    
    Returns
    -------
    orthogonal_residual : pd.Series
        正交化后的特质成分（残差）
    exposures : Dict[str, float], optional
        对四因子的回归系数 {'MKT': 0.8, 'SMB': 0.2, ...}
    
    Raises
    ------
    ValueError
        如果 candidate_factor 和 carhart_factors 日期不对齐
    ValueError
        如果存在缺失值或无穷值
    
    Examples
    --------
    >>> factor = pd.Series([0.5, 0.8, 0.3], index=dates)
    >>> carhart = pd.DataFrame({'MKT': [0.01, 0.02, -0.01], ...})
    >>> residual = orthogonalize_factor(factor, carhart)
    >>> residual.mean()  # 接近0（已去除系统性成分）
    0.001
    """
```

**前置条件**：
- `candidate_factor` 和 `carhart_factors` 的日期索引必须对齐
- 数据无缺失值（NaN）或无穷值（Inf）
- 至少有 30 个观测点（保证回归自由度）

**后置条件**：
- 返回的残差序列均值接近 0（±0.01）
- 残差与四因子的相关系数 < 0.05（近似正交）

---

### 1.2 pca_factor_reduction

**功能**：对多个语义因子进行 PCA 降维，避免多重共线性

**签名**：
```python
def pca_factor_reduction(
    semantic_factors: pd.DataFrame,
    n_components: Union[int, float] = 0.8,
    return_loadings: bool = False
) -> Union[pd.DataFrame, Tuple[pd.DataFrame, pd.DataFrame]]:
    """
    对语义因子矩阵进行 PCA 降维
    
    Parameters
    ----------
    semantic_factors : pd.DataFrame
        语义因子矩阵，行=日期，列=因子名称
    n_components : int or float, default 0.8
        保留的主成分数量（int）或解释方差比例（float, 0-1）
    return_loadings : bool, default False
        是否返回主成分载荷矩阵
    
    Returns
    -------
    principal_components : pd.DataFrame
        主成分矩阵，columns = ['PC1', 'PC2', ...]
    loadings : pd.DataFrame, optional
        载荷矩阵，行=原始因子，列=主成分
    
    Examples
    --------
    >>> factors = pd.DataFrame({'订单增长': [...], '产能扩张': [...]})
    >>> pcs = pca_factor_reduction(factors, n_components=0.8)
    >>> pcs.shape[1]  # 保留80%方差所需的主成分数
    3
    """
```

**前置条件**：
- 输入矩阵无缺失值
- 列数（因子数）≥ 2

**后置条件**：
- 主成分之间两两正交（相关系数 < 0.01）
- 累计解释方差 ≥ `n_components`（如为比例）

---

## 2. 数据结构

### 2.1 输入格式

**CarhartFactors DataFrame**：
```python
            MKT     SMB     HML     MOM
date                                    
2025-01-02  0.012   0.005  -0.003  0.008
2025-01-03 -0.008   0.002   0.001  -0.004
...
```

**SemanticFactors DataFrame**：
```python
            订单增长  产能扩张  毛利率改善
date                              
2025-01-02  0.75    0.60    0.45
2025-01-03  0.82    0.55    0.50
...
```

### 2.2 输出格式

**Orthogonal Residual Series**：
```python
date
2025-01-02    0.031
2025-01-03   -0.012
...
Name: orthogonal_factor, dtype: float64
```

**Exposure Dict**：
```python
{
    'MKT': 0.783,
    'SMB': 0.215,
    'HML': -0.102,
    'MOM': 0.341,
    'R2': 0.65,        # 拟合优度
    't_MKT': 3.21,     # t统计量
    ...
}
```

---

## 3. 错误处理

### 3.1 异常类型

| 异常 | 触发条件 | 处理建议 |
|------|---------|---------|
| `ValueError` | 日期不对齐 | 使用 `pd.merge` 对齐后重试 |
| `ValueError` | 存在 NaN/Inf | 使用 `dropna()` 或填充 |
| `LinAlgError` | 矩阵奇异（完全共线） | 移除共线列后重试 |
| `ValueError` | 观测数 < 30 | 扩展时间窗口 |

### 3.2 警告

| 警告 | 触发条件 | 说明 |
|------|---------|------|
| `LowR2Warning` | R² < 0.3 | 四因子解释力弱，特质成分可能包含噪声 |
| `HighVIFWarning` | VIF > 10 | 四因子间存在多重共线性 |

---

## 4. 性能指标

| 操作 | 输入规模 | 预期耗时 |
|------|---------|---------|
| `orthogonalize_factor` | 252 天 × 4 因子 | < 10ms |
| `pca_factor_reduction` | 252 天 × 20 因子 | < 50ms |

---

## 5. 测试用例

### 5.1 单元测试

```python
def test_orthogonalize_removes_market_exposure():
    """验证正交化后与市场因子不相关"""
    factor = pd.Series([...])  # 人工构造与 MKT 高度相关的因子
    carhart = load_carhart_factors()
    residual = orthogonalize_factor(factor, carhart)
    
    assert abs(residual.corr(carhart['MKT'])) < 0.05

def test_pca_orthogonality():
    """验证主成分两两正交"""
    factors = pd.DataFrame(...)
    pcs = pca_factor_reduction(factors)
    
    corr_matrix = pcs.corr()
    off_diagonal = corr_matrix.values[np.triu_indices_from(corr_matrix.values, k=1)]
    assert np.all(np.abs(off_diagonal) < 0.01)
```

### 5.2 集成测试

```python
def test_end_to_end_立新能源_case():
    """复现立新能源案例：高涨幅但 Alpha 不显著"""
    # 构造人工数据：收益 = 0.8*MKT + 0.5*噪声
    returns = 0.8 * carhart['MKT'] + np.random.normal(0, 0.01, len(carhart))
    
    # 正交化
    residual = orthogonalize_factor(returns, carhart)
    
    # Fama-MacBeth 检验
    alpha, pvalue = fama_macbeth_test(residual)
    
    # 应该不显著（因为收益主要来自市场暴露）
    assert pvalue > 0.05
```

---

## 6. 版本兼容性

| 版本 | 变更 | 向后兼容 |
|------|------|---------|
| v1.0 | 初始版本 | N/A |
| v1.1（计划） | 增加 `method='gram-schmidt'` 参数 | ✅ 默认行为不变 |
