# show_aggressive_portfolio.ps1 - 显示激进组合详细报告

$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

# 强制 UTF-8 编码
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 > $null

$py = Join-Path $repo ".venv\Scripts\python.exe"

& $py -c @"
import json

# 读取激进组合数据
with open('docs/data/paper/performance_aggressive.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

print('=' * 70)
print('激进组合-全宇宙 模拟盘对决')
print('=' * 70)
print()

for i, record in enumerate(data['records'], 1):
    print(f'【第 {i} 个交易日】 {record[\"trade_date\"]}')
    print(f'记录时间: {record[\"recorded_at\"]}')
    print(f'组合收益: {record[\"portfolio_return_pct\"]:+.2f}%')
    print(f'等权基准: {record[\"equal_weight_return_pct\"]:+.2f}%')
    print(f'持仓数量: {record[\"valid_count\"]} 只')
    print()
    print('持仓明细:')
    print('-' * 70)

    # 按涨跌幅排序
    items = sorted(record['items'], key=lambda x: x['change_pct'], reverse=True)

    for item in items:
        code = item['code']
        name = item['name']
        chg = item['change_pct']
        pred_up3 = item['pred_up3']
        pred_ret3 = item['pred_ret3']

        # 判断预测是否准确
        actual_up = chg > 0
        predicted_up = pred_up3 > 50
        correct = '✅' if actual_up == predicted_up else '❌'

        print(f'{correct} {code:8s} {name:12s} {chg:+6.2f}%  |  预测3日: {pred_up3:.1f}% 概率, {pred_ret3:+.2f}% 收益')

    print()
    print('=' * 70)
    print()

# 计算累计收益
total_return = sum(r['portfolio_return_pct'] for r in data['records'])
total_benchmark = sum(r['equal_weight_return_pct'] for r in data['records'])

print('【累计表现】')
print(f'组合累计收益: {total_return:+.2f}%')
print(f'等权基准累计: {total_benchmark:+.2f}%')
print(f'超额收益: {total_return - total_benchmark:+.2f}%')
print('=' * 70)
"@
