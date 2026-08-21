# -*- coding: utf-8 -*-
"""验证立新能源与美光科技的最终分类结果"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(r"D:\股票分析项目\2.0版")))

from src.analysis.bet_type_classifier import classify_bet_type, get_strategy_recommendation

ROOT = Path(r"D:\股票分析项目\2.0版")

stocks = [
    ("001258", "立新能源"),
    ("MU", "美光科技"),
    ("600519", "贵州茅台"),
    ("NVDA", "英伟达"),
]

print("=" * 75)
print(f"{'代码':<8} {'名称':<10} {'分类结果':<12} {'年化波动率':<10} {'动量半衰期':<10} {'ATR比例':<10}")
print("=" * 75)

for code, name in stocks:
    p = ROOT / "docs" / "data" / "kline" / f"{code}.json"
    if not p.exists():
        continue
    with open(p, encoding="utf-8") as f:
        k = json.load(f)
    closes = [r[1] for r in k["kline"]]
    highs = [r[3] for r in k["kline"]]
    lows = [r[2] for r in k["kline"]]
    
    state, m = classify_bet_type(closes, highs, lows)
    rec = get_strategy_recommendation(state)
    
    vol_str = f"{m['volatility_annual']*100:.1f}%"
    hl_str = f"{m['momentum_half_life']:.1f}天" if m['momentum_half_life'] else "持续不衰减"
    atr_str = f"{m['atr_ratio']*100:.1f}%"
    
    print(f"{code:<8} {name:<10} {state:<12} {vol_str:<10} {hl_str:<10} {atr_str:<10}")
    print(f"  └ 建议：{rec['description']}")
