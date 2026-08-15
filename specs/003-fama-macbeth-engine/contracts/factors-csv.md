# 契约: 因子 CSV 输入格式（用户手工提供，CSMAR/RESSET 导出）

**Feature**: 003-fama-macbeth-engine | **Date**: 2026-08-15

## 格式要求（FR-001 / FR-002 的输入边界）

- 编码：UTF-8（含 BOM 可容忍）
- 首行表头，列序与命名（大小写不敏感）：date, MKT, SMB, HML, MOM [, rf]
- date：ISO YYYY-MM-DD，唯一且按升序（乱序时加载器排序并告警）
- 数值列：可为空（该行剔除，计入缺口率）；禁止除数值/空值外的内容
- 允许额外元信息列：source、version（写进 source_meta）
- 示例：

```csv
date,MKT,SMB,HML,MOM,rf,source,version
2021-08-13,0.0042,-0.0011,0.0008,-0.0021,0.000099,CSMAR,20260814
```

## 校验规则（加载器必须执行）

| 检查 | 失败行为 |
|---|---|
| 缺失 date 或任一因子列 | 报错退出（指明缺失列） |
| 重复日期 | 报错退出（列出重复日期），不做静默去重 |
| 空值缺口率 > 5%（可配置） | 报错退出（给出缺口统计） |
| 日期乱序 | 排序后导入 + 告警 |
| 覆盖区间不足（< 最小窗口 250 交易日） | 报错退出 |

## 输出侧（SQLite）

- docs/data/factors/factors.db；表结构与 UPSERT 语义见 data-model.md
- 入库幂等：同日数据重复导入 = 后写覆盖 + 告警（事务性）