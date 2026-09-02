# -*- coding: utf-8 -*-
"""运行最佳参数配置并保存最终结果。"""

from __future__ import annotations
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from src.analysis.green_backtest_runner import GreenBacktestRunner
from src.risk.market_regime_detector import RegimeDetectorConfig
from src.risk.dynamic_position_sizer import PositionSizerConfig

# 最佳参数组合（基于调优结果）
regime_cfg = RegimeDetectorConfig(
    momentum_threshold_bull=0.012,
    momentum_threshold_bear=-0.012,
    volatility_threshold_high=0.038,
    hysteresis_min_duration=2,
    momentum_override_threshold=0.03,
)

pos_cfg = PositionSizerConfig(
    bull_multiplier=1.4,
    bear_multiplier=0.35,
    sideways_multiplier=0.95,
    drawdown_threshold=0.08,
    drawdown_penalty_factor=3.0,
    drawdown_penalty_min=0.5,
    volatility_high_adj=0.78,
    max_position=1.85,
    min_position=0.35,
    use_exponential_drawdown=True,
    exponential_drawdown_k=3.2,
)

runner = GreenBacktestRunner(
    regime_config=regime_cfg,
    position_config=pos_cfg,
)
res = runner.run_walk_forward_backtest()
runner.generate_and_save_artifacts(res)

s = res["metrics"]["strategy_stats"]
pos = res["metrics"].get("position_stats", {})
reg = res["metrics"].get("market_regime_stats", {})
rd = reg.get("regime_distribution", {})

print("=" * 60)
print("最终结果：市场状态机 + 动态仓位管理")
print("=" * 60)
print(f"Sharpe Ratio:       {s['sharpe_ratio']:.2f}  (目标: 1.31, 基线: 1.19)")
print(f"年化收益率:         {s['annualized_return']*100:.2f}%")
print(f"最大回撤:           {s['max_drawdown']*100:.2f}%")
print(f"Calmar Ratio:       {s['calmar_ratio']:.2f}")
print(f"信息比率:           {s['information_ratio']:.2f}")
print(f"总收益:             {s['total_return']*100:.2f}%")
print(f"仓位均值:           {pos.get('avg_position', 0):.2f}")
print(f"状态分布:           BULL={rd.get('bull_days',0)} / BEAR={rd.get('bear_days',0)} / SIDEWAYS={rd.get('sideways_days',0)}")

# 提升幅度
sharpe_imp = (s['sharpe_ratio'] / 1.19 - 1) * 100
print(f"\nSharpe 提升:        {sharpe_imp:.1f}%")
if sharpe_imp >= 10:
    print("目标达成: ✅ Sharpe 提升 >= 10%")
else:
    print(f"目标未达成: ❌ 需再提升 {10 - sharpe_imp:.1f}%")

if s['max_drawdown'] * 100 <= 15:
    print("风控达标: ✅ 最大回撤 <= 15%")
else:
    print(f"风控未达标: ❌ 回撤超限 {s['max_drawdown']*100 - 15:.1f}%")