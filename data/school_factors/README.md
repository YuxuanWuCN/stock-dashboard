# 华南师范大学 (SCNU) / 阿伯丁数据科学学院校内因子库专用目录

## 📁 目录定位
本目录 `data/school_factors/` 是为**华南师范大学 (SCNU) / 阿伯丁学院学术终端（CSMAR 国泰安 / Wind 万得 / RESSET 锐思 / 实验室自建因子）**预留的**热插拔官方因子库位置**。

---

## 🚀 如何使用（零配置热插拔）
当您从学校图书馆或机房导出官方因子数据后，**直接将 CSV / Excel / Parquet 文件拖入本文件夹**即可，系统运行时会自动热加载并完成字段映射清洗！

### 支持的文件格式：
- `*.csv`（例如 `STK_MKT_Thrfac.csv`, `Carhart_4factor_daily.csv`）
- `*.parquet`（高压缩、微秒级读取）
- `*.xlsx` / `*.xls`

### 自动识别与支持的标准字段映射：
系统内置了中文与 CSMAR / Wind 英文标准字段的自动对齐：
- **交易日期**：`TradingDate`, `date`, `日期` $\to$ `date`
- **市场溢价因子**：`RiskPremium1`, `MKT`, `市场溢价因子` $\to$ `MKT`
- **规模因子**：`SMB1`, `SMB`, `规模因子` $\to$ `SMB`
- **价值因子**：`HML1`, `HML`, `账面市值比因子` $\to$ `HML`
- **动量因子**：`UMD1`, `MOM`, `动量因子` $\to$ `MOM`
- **无风险利率**：`RiskFreeRate`, `rf`, `无风险利率` $\to$ `rf`

---

## 💻 代码调用方式
```python
from src.analysis.factor_providers import SCNUAcademicFactorProvider

# 自动扫描并加载 data/school_factors/ 中的所有因子文件
provider = SCNUAcademicFactorProvider()
df_factors = provider.get_daily_factors(start_date="2020-01-01", end_date="2025-12-31")
```
