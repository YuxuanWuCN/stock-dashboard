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

## CSMAR SDK 下载模板（需先确认学校账号的实际签名）

任务包提供的 `STK_MKT_Thrfac` 与字段名只是常见示例，不能替代 CSMAR 网站上
对表结构、字段单位和账号权限的确认。确认后，在已安装 `csmarapi` 的学校 Python
环境中运行：

```powershell
python scripts/download_csmar_carhart_factors.py `
  --table-name STK_MKT_Thrfac `
  --start-date 2020-01-01 `
  --end-date 2026-09-01 `
  --trading-calendar data/school_factors/cn_trading_calendar.csv `
  --overwrite
```

脚本默认写入 `data/school_factors/csmar_carhart_4factors.csv`，会在写入前检查
六个标准列、日期合法性、重复日期、有限数值和最少 1500 条记录；已有文件默认
拒绝覆盖，需明确加 `--overwrite`。提供 `--trading-calendar` 后，脚本会对请求
窗口内的日期集合做严格的缺失/多余检查；交易日历也必须没有非法或重复日期。
没有交易日历时仍可运行，但只验证结构和区间，终端会打印
`coverage_unverified` 警告；在自动化流程中可加 `--require-coverage`，强制要求
日历（或显式加 `--allow-unverified-coverage` 表示接受未验证覆盖）。未安装 SDK、
认证失败、查询失败或返回空/不完整数据时会以失败退出，不生成代理或合成因子。
`SCNUAcademicFactorProvider(strict=True)` 也必须传入 `expected_trading_dates`；
否则无法证明区间中间没有缺口，调用会直接失败。

若学校 SDK 的查询方法不是 `query(table_name, start_date, end_date, fields)`，请
先在脚本外包装成兼容 callable，再注入 `CSMARFactorProvider(query=...)`；不要把
用户名和密码放进 `query_params`，认证参数应单独传入 `connection_params`。
