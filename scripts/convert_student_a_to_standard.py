# -*- coding: utf-8 -*-
import os, sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import numpy as np
import pandas as pd

pd.set_option('display.width', 200)

# ============================================================
# 方案1：A面板 -> 标准9列 + 技术因子附加列
# ============================================================

# 1. 读取A原始面板
src_a = 'data/task_split/student_a_delivery/01_因子数据/factors_daily_panel_student_A.csv'
dfa = pd.read_csv(src_a, dtype={'ticker': str})
print('A原始:', dfa.shape)

# 2. 读取B标准面板作为schema参照
dfb = pd.read_csv('data/task_split/student_b/csmar/student_b_csmar_factor_panel_filtered.csv', dtype={'stock_code': str})
print('B标准:', dfb.shape)
print('B列:', list(dfb.columns))

# 3. 基础列重命名 + 派生
std = pd.DataFrame({
    'stock_code': dfa['ticker'].str.zfill(6),
    'trade_date': dfa['date'],
    'close': dfa['close'],
    'volume': np.exp(dfa['log_amount']) / dfa['vwap'].replace(0, np.nan),  # 成交额/均价
    'turnover_rate': dfa['turnover'],
    'market_value': np.exp(dfa['log_mktcap']),
    'pe_ttm': np.nan,   # A无估值源
    'pb': np.nan,       # A无估值源
    'roe': np.nan        # A无财报源
})

# 4. A技术因子保留（去重后的附加列）
tech_cols = [c for c in dfa.columns if c not in ['date', 'ticker', 'close', 'vwap', 'turnover', 'log_amount', 'log_mktcap']]
for c in tech_cols:
    std[c] = dfa[c].values
print('附加技术列:', tech_cols)

# 5. 与B列顺序统一：标准9列在前
b_std_cols = list(dfb.columns)
extra = [c for c in std.columns if c not in b_std_cols]
std = std[b_std_cols + extra]

# 6. 质量检查
print('\nA转换后形状:', std.shape)
print('代码数:', std['stock_code'].nunique(), '| 前导零长度:', std['stock_code'].str.len().unique())
print('日期数:', std['trade_date'].nunique())
miss = std.isnull().mean()
print('\n关键列缺失率:');
for c in b_std_cols + ['ret','mom_20d','amihud']:
    print(f'  {c:15s} {miss[c]:.4f}')

# 7. 存为与B同构位置（不覆盖B）
out_dir = 'data/task_split/student_a/csmar'
os.makedirs(out_dir, exist_ok=True)
out_csv = out_dir + '/student_a_csmar_factor_panel_filtered.csv'
std.to_csv(out_csv, index=False)
print('\n✅ 已写出:', out_csv)

# 8. manifest
mani = {
    'source': 'student A delivery v3 -> standard schema (plan 1)',
    'rows': int(len(std)),
    'stocks': int(std['stock_code'].nunique()),
    'days': int(std['trade_date'].nunique()),
    'window': {'start': str(std['trade_date'].min()), 'end': str(std['trade_date'].max())},
    'derived_columns': ['volume(exp(log_amount)/vwap)', 'market_value(exp(log_mktcap))'],
    'missing_by_design': ['pe_ttm','pb','roe'] + ['(A无估值/财报源)'],
    'tech_extra_columns': tech_cols,
    'fabrication_check': {'synthetic_values_generated': False, 'random_data_used': False}
}
with open(out_dir + '/student_a_csmar_factor_panel_filtered_manifest.json', 'w', encoding='utf-8') as f:
    json.dump(mani, f, ensure_ascii=False, indent=2)
print('✅ 已写出 manifest')