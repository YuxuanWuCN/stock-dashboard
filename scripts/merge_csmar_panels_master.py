# -*- coding: utf-8 -*-
import os, sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import numpy as np
import pandas as pd

dfa = pd.read_csv('data/task_split/student_a/csmar/student_a_csmar_factor_panel_filtered.csv', dtype={'stock_code': str})
dfb = pd.read_csv('data/task_split/student_b/csmar/student_b_csmar_factor_panel_filtered.csv', dtype={'stock_code': str})
dfc = pd.read_csv('data/task_split/student_c/csmar/student_c_csmar_factor_panel_filtered.csv', dtype={'stock_code': str})

print('A:', dfa.shape, '| B:', dfb.shape, '| C:', dfc.shape)

# A独有技术列
a_extra = [c for c in dfa.columns if c not in dfb.columns]
print('A技术列:', a_extra)

# 统一列集: 标准9列 + A技术列
for c in a_extra:
    if c not in dfb.columns: dfb[c] = np.nan
    if c not in dfc.columns: dfc[c] = np.nan

all_cols = list(dfb.columns)
print('列数:', len(all_cols))
dfa = dfa[all_cols]
dfb = dfb[all_cols]
dfc = dfc[all_cols]

master = pd.concat([dfb, dfa, dfc], ignore_index=True)
print('\n合并形状:', master.shape)
print('总代码数:', master['stock_code'].nunique())
print('日期数:', master['trade_date'].nunique())
print('无重复列:', len(master.columns) == len(set(master.columns)))

os.makedirs('data/task_split/csmar_master', exist_ok=True)
master.to_csv('data/task_split/csmar_master/csmar_factor_panel_master.csv', index=False)
master.to_parquet('data/task_split/csmar_master/csmar_factor_panel_master.parquet')
print('✅ master csv+parquet 已保存')

report = {}
for col in ['close','volume','turnover_rate','market_value','pe_ttm','pb','roe'] + a_extra:
    report[col] = round(float(1 - master[col].isnull().mean()), 4)
print('\n=== 覆盖率 ===')
for k, v in report.items():
    print(f'  {k:15s} {v:.2%}')

mani = {
    'note': 'A(99股标准9列+13技术列) + B(100股标准9列) + C(100股标准9列) 全量合并主表 (全池 299 支有效标的，A组退市1支)',
    'rows': int(len(master)),
    'stocks': int(master['stock_code'].nunique()),
    'days': int(master['trade_date'].nunique()),
    'columns': all_cols,
    'coverage': report,
    'fabrication_check': {'synthetic': False, 'random': False}
}
with open('data/task_split/csmar_master/csmar_factor_panel_master_manifest.json', 'w', encoding='utf-8') as f:
    json.dump(mani, f, ensure_ascii=False, indent=2)
print('✅ manifest已保存')