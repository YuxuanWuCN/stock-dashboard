# -*- coding: utf-8 -*-
"""运行优化版绿电回测 —— 使用板块自身动量进行状态检测。"""

from __future__ import annotations

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from src.analysis.green_backtest_runner import GreenBacktestRunner
from src.risk.market_regime_detector import RegimeDetectorConfig
from src.risk.dynamic_position_sizer import PositionSizerConfig


def main():
    # 使用绿电板块的等权价格作为市场状态检测基准
    # 关键改进：regime detection 使用板块自身动量而非大盘指数

    # 配置A：中性偏进取（基于板块自身动量）
    cfg_a = {
        "regime_config": RegimeDetectorConfig(
            momentum_threshold_bull=0.01,
            momentum_threshold_bear=-0.01,
            volatility_threshold_high=0.04,
            hysteresis_min_duration=2,
            momentum_override_threshold=0.035,
        ),
        "position_config": PositionSizerConfig(
            base_position=1.0,
            bull_multiplier=1.3,
            bear_multiplier=0.5,
            sideways_multiplier=1.0,
            drawdown_threshold=0.10,
            drawdown_penalty_factor=2.0,
            drawdown_penalty_min=0.5,
            volatility_high_threshold=0.05,
            volatility_high_adj=0.85,
            volatility_low_adj=1.05,
            max_position=1.8,
            min_position=0.4,
            use_exponential_drawdown=False,
        ),
    }

    # 配置B：利用板块趋势，牛市高仓位，熊市保守
    cfg_b = {
        "regime_config": RegimeDetectorConfig(
            momentum_threshold_bull=0.015,
            momentum_threshold_bear=-0.015,
            volatility_threshold_high=0.035,
            hysteresis_min_duration=3,
            momentum_override_threshold=0.04,
        ),
        "position_config": PositionSizerConfig(
            base_position=1.0,
            bull_multiplier=1.4,
            bear_multiplier=0.4,
            sideways_multiplier=0.95,
            drawdown_threshold=0.08,
            drawdown_penalty_factor=2.5,
            drawdown_penalty_min=0.45,
            volatility_high_threshold=0.04,
            volatility_high_adj=0.8,
            volatility_low_adj=1.1,
            max_position=2.0,
            min_position=0.35,
            use_exponential_drawdown=True,
            exponential_drawdown_k=3.0,
        ),
    }

    # 配置C：保守但平滑（侧重回撤控制）
    cfg_c = {
        "regime_config": RegimeDetectorConfig(
            momentum_threshold_bull=0.02,
            momentum_threshold_bear=-0.02,
            volatility_threshold_high=0.045,
            hysteresis_min_duration=4,
            momentum_override_threshold=0.05,
        ),
        "position_config": PositionSizerConfig(
            base_position=1.0,
            bull_multiplier=1.15,
            bear_multiplier=0.55,
            sideways_multiplier=0.9,
            drawdown_threshold=0.07,
            drawdown_penalty_factor=2.0,
            drawdown_penalty_min=0.5,
            volatility_high_threshold=0.045,
            volatility_high_adj=0.8,
            volatility_low_adj=1.05,
            max_position=1.5,
            min_position=0.4,
            smoothing_alpha=0.3,
            use_exponential_drawdown=True,
            exponential_drawdown_k=3.5,
        ),
    }

    configs = [
        ("配置A: 中性偏进取", cfg_a),
        ("配置B: 趋势跟随", cfg_b),
        ("配置C: 保守平滑", cfg_c),
    ]

    results = []

    for name, cfg in configs:
        print(f"\n{'=' * 60}")
        print(f"{name}")
        print(f"{'=' * 60}")

        # 修改 backtest runner 使用等权板块价格
        runner = GreenBacktestRunner(
            regime_config=cfg["regime_config"],
            position_config=cfg["position_config"],
        )

        # 重写 regime detection 使用板块等权价格
        # 通过在 runner 上设置标志来实现
        runner._use_sector_regime = True

        res = runner.run_walk_forward_backtest()
        # 保存结果但跳过原来的 generate_and_save_artifacts（避免覆盖）
        # runner.generate_and_save_artifacts(res)

        s = res["metrics"]["strategy_stats"]
        pos = res["metrics"].get("position_stats", {})
        regime = res["metrics"].get("market_regime_stats", {})
        rd = regime.get("regime_distribution", {})

        print(f"  Sharpe: {s['sharpe_ratio']:.2f} (目标 1.31)")
        print(f"  年化收益: {s['annualized_return']*100:.2f}%")
        print(f"  最大回撤: {s['max_drawdown']*100:.2f}%")
        print(f"  Calmar: {s['calmar_ratio']:.2f}")
        print(f"  仓位均值: {pos.get('avg_position', 0):.2f}")
        print(f"  状态分布: BULL={rd.get('bull_days', 0)} BEAR={rd.get('bear_days', 0)} SIDEWAYS={rd.get('sideways_days', 0)}")

        results.append((name, s, pos, regime))

    # 对比总结
    print(f"\n{'=' * 60}")
    print(f"对比总结")
    print(f"{'=' * 60}")
    print(f"{'配置':<18} {'Sharpe':<10} {'年化%':<10} {'回撤%':<10} {'Calmar':<10} {'仓位':<8}")
    print(f"{'-'*18} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*8}")
    print(f"{'基线':<18} {1.19:<10.2f} {26.49:<10.2f} {13.97:<10.2f} {1.90:<10.2f} {'1.00':<8}")
    for name, s, pos, _ in results:
        avg_pos = pos.get("avg_position", 0)
        print(f"{name:<18} {s['sharpe_ratio']:<10.2f} {s['annualized_return']*100:<10.2f} {s['max_drawdown']*100:<10.2f} {s['calmar_ratio']:<10.2f} {avg_pos:<8.2f}")


if __name__ == "__main__":
    main()