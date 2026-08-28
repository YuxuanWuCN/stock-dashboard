#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量修复 JSON 文件中的中文乱码
从 summary.json 读取正确的股票名称，修复所有模拟盘数据文件
"""

import json
import sys
from pathlib import Path

# 确保 UTF-8 输出
if sys.stdout.encoding.lower() != 'utf-8':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def load_name_mapping():
    """从 summary.json 加载股票代码到名称的映射"""
    summary_path = Path('docs/data/summary.json')
    with open(summary_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    name_map = {}
    for item in data['items']:
        name_map[item['code']] = item['name']

    print(f"✅ 加载了 {len(name_map)} 个股票名称映射")
    return name_map

def fix_performance_file(filepath, name_map, portfolio_name_fix):
    """修复单个模拟盘数据文件"""
    print(f"\n📝 处理: {filepath}")

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 修复组合名称
    if portfolio_name_fix:
        old_name = data.get('portfolio_name', '')
        if '?' in old_name:
            data['portfolio_name'] = portfolio_name_fix
            print(f"   修复组合名称: {old_name} -> {portfolio_name_fix}")

    # 修复每条记录中的股票名称
    fixed_count = 0
    for record in data.get('records', []):
        for item in record.get('items', []):
            code = item['code']
            old_name = item.get('name', '')

            if '?' in old_name and code in name_map:
                item['name'] = name_map[code]
                fixed_count += 1

    print(f"   修复了 {fixed_count} 个股票名称")

    # 保存修复后的文件
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"   ✅ 已保存")

def main():
    print("=" * 60)
    print("批量修复 JSON 文件中文乱码")
    print("=" * 60)

    # 加载股票名称映射
    name_map = load_name_mapping()

    # 定义要修复的文件及其正确的组合名称
    files_to_fix = [
        ('docs/data/paper/performance.json', '稳健组合-1号'),
        ('docs/data/paper/performance_bluechip.json', '蓝筹组合'),
        ('docs/data/paper/performance_defensive.json', '防御组合'),
        ('docs/data/paper/performance_global.json', '全球组合'),
        ('docs/data/paper/performance_tech.json', '科技组合'),
    ]

    # 修复每个文件
    for filepath, portfolio_name in files_to_fix:
        path = Path(filepath)
        if path.exists():
            fix_performance_file(path, name_map, portfolio_name)
        else:
            print(f"\n⚠️  文件不存在: {filepath}")

    print("\n" + "=" * 60)
    print("✅ 修复完成！")
    print("=" * 60)

if __name__ == '__main__':
    main()
