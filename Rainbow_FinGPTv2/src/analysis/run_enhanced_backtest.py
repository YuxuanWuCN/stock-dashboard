# -*- coding: utf-8 -*-
"""运行增强版绿电回测（含市场状态机 + 动态仓位管理）。"""

from __future__ import annotations

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from src.analysis.green_backtest_runner import GreenBacktestRunner
from src.risk.market_regime_detector import RegimeDetectorConfig
from src.risk.dynamic_position_sizer import PositionSizerConfig


def main():
    # ==========================================
    # 配置1：激进的参数（追求 Sharpe 提升）
    # ==========================================
    regime_cfg = RegimeDetectorConfig(
        momentum_threshold_bull=0.015,
        momentum_threshold_bear=-0.015,
        volatility_threshold_high=0.035,
        hysteresis_min_duration=2,
        momentum_override_threshold=0.04,
    )
    pos_cfg = PositionSizerConfig(
        base_position=1.0,
        bull_multiplier=1.5,
        bear_multiplier=0.4,
        sideways_multiplier=0.95,
        drawdown_threshold=0.08,
        drawdown_penalty_factor=2.5,
        drawdown_penalty_min=0.4,
        volatility_high_threshold=0.04,
        volatility_high_adj=0.75,
        volatility_low_adj=1.15,
        max_position=2.5,
        use_exponential_drawdown=True,
        exponential_drawdown_k=3.0,
    )

    print("=" * 60)
    print("配置1：激进参数（更高牛市仓位 + 指数回撤惩罚）")
    print("=" * 60)

    runner1 = GreenBacktestRunner(
        regime_config=regime_cfg,
        position_config=pos_cfg,
    )
    res1 = runner1.run_walk_forward_backtest()
    runner1.generate_and_save_artifacts(res1)

    s1 = res1["metrics"]["strategy_stats"]
    pos1 = res1["metrics"].get("position_stats", {})
    regime1 = res1["metrics"].get("market_regime_stats", {})

    print(f"  Sharpe: {s1['sharpe_ratio']:.2f}")
    print(f"  年化收益: {s1['annualized_return']*100:.2f}%")
    print(f"  最大回撤: {s1['max_drawdown']*100:.2f}%")
    print(f"  Calmar: {s1['calmar_ratio']:.2f}")
    print(f"  仓位均值: {pos1.get('avg_position', 0):.2f}")
    rd = regime1.get("regime_distribution", {})
    print(f"  状态分布: BULL={rd.get('bull_days', 0)} BEAR={rd.get('bear_days', 0)} SIDEWAYS={rd.get('sideways_days', 0)}")

    # ==========================================
    # 配置2：保守参数（追求更低回撤）
    # ==========================================
    regime_cfg2 = RegimeDetectorConfig(
        momentum_threshold_bull=0.025,
        momentum_threshold_bear=-0.025,
        volatility_threshold_high=0.04,
        hysteresis_min_duration=3,
        momentum_override_threshold=0.05,
    )
    pos_cfg2 = PositionSizerConfig(
        base_position=1.0,
        bull_multiplier=1.2,
        bear_multiplier=0.5,
        sideways_multiplier=0.85,
        drawdown_threshold=0.06,
        drawdown_penalty_factor=3.0,
        drawdown_penalty_min=0.35,
        volatility_high_threshold=0.035,
        volatility_high_adj=0.7,
        volatility_low_adj=1.1,
        max_position=1.8,
        use_exponential_drawdown=True,
        exponential_drawdown_k=4.0,
    )

    print("\n" + "=" * 60)
    print("配置2：保守参数（更低回撤 + 更强风控）")
    print("=" * 60)

    runner2 = GreenBacktestRunner(
        regime_config=regime_cfg2,
        position_config=pos_cfg2,
    )
    res2 = runner2.run_walk_forward_backtest()
    runner2.generate_and_save_artifacts(res2)

    s2 = res2["metrics"]["strategy_stats"]
    pos2 = res2["metrics"].get("position_stats", {})
    regime2 = res2["metrics"].get("market_regime_stats", {})

    print(f"  Sharpe: {s2['sharpe_ratio']:.2f}")
    print(f"  年化收益: {s2['annualized_return']*100:.2f}%")
    print(f"  最大回撤: {s2['max_drawdown']*100:.2f}%")
    print(f"  Calmar: {s2['calmar_ratio']:.2f}")
    print(f"  仓位均值: {pos2.get('avg_position', 0):.2f}")
    rd2 = regime2.get("regime_distribution", {})
    print(f"  状态分布: BULL={rd2.get('bull_days', 0)} BEAR={rd2.get('bear_days', 0)} SIDEWAYS={rd2.get('sideways_days', 0)}")

    # ==========================================
    # 对比总结
    # ==========================================
    print("\n" + "=" * 60)
    print("对比总结")
    print("=" * 60)
    print(f"{'指标':<20} {'基线':<12} {'配置1(激进)':<14} {'配置2(保守)':<14}")
    print(f"{'-'*20} {'-'*12} {'-'*14} {'-'*14}")
    print(f"{'Sharpe':<20} {1.19:<12.2f} {s1['sharpe_ratio']:<14.2f} {s2['sharpe_ratio']:<14.2f}")
    print(f"{'年化收益':<20} {26.49:<12.2f} {s1['annualized_return']*100:<14.2f} {s2['annualized_return']*100:<14.2f}")
    print(f"{'最大回撤':<20} {13.97:<12.2f} {s1['max_drawdown']*100:<14.2f} {s2['max_drawdown']*100:<14.2f}")
    print(f"{'Calmar':<20} {1.90:<12.2f} {s1['calmar_ratio']:<14.2f} {s2['calmar_ratio']:<14.2f}")
    print(f"{'信息比率':<20} {'N/A':<12} {s1['information_ratio']:<14.2f} {s2['information_ratio']:<14.2f}")


if __name__ == "__main__":
    main()