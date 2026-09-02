# -*- coding: utf-8 -*-
"""精细调参：追求 Sharpe ≥ 1.31 且 回撤 ≤ 15%。"""

from __future__ import annotations

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from src.analysis.green_backtest_runner import GreenBacktestRunner
from src.risk.market_regime_detector import RegimeDetectorConfig
from src.risk.dynamic_position_sizer import PositionSizerConfig


def try_config(name, regime_cfg, pos_cfg, runner_kwargs=None):
    """尝试一个配置并返回结果。"""
    kwargs = dict(regime_config=regime_cfg, position_config=pos_cfg)
    if runner_kwargs:
        kwargs.update(runner_kwargs)
    runner = GreenBacktestRunner(**kwargs)
    res = runner.run_walk_forward_backtest()
    runner.generate_and_save_artifacts(res)
    s = res["metrics"]["strategy_stats"]
    pos = res["metrics"].get("position_stats", {})
    regime = res["metrics"].get("market_regime_stats", {})
    rd = regime.get("regime_distribution", {})
    return {
        "name": name,
        "sharpe": s["sharpe_ratio"],
        "ann_ret": s["annualized_return"] * 100,
        "max_dd": s["max_drawdown"] * 100,
        "calmar": s["calmar_ratio"],
        "ir": s["information_ratio"],
        "avg_pos": pos.get("avg_position", 0),
        "bull": rd.get("bull_days", 0),
        "bear": rd.get("bear_days", 0),
        "sideways": rd.get("sideways_days", 0),
    }


def main():
    trials = []

    # === 基线 ===
    trials.append(try_config(
        "基线(无动态仓位)",
        RegimeDetectorConfig(),
        PositionSizerConfig(bull_multiplier=1.0, bear_multiplier=1.0, sideways_multiplier=1.0),
    ))

    # === 试1：激进版，但加回撤惩罚 ===
    trials.append(try_config(
        "试1: 激进+强回撤惩罚",
        RegimeDetectorConfig(
            momentum_threshold_bull=0.012,
            momentum_threshold_bear=-0.012,
            volatility_threshold_high=0.04,
            hysteresis_min_duration=2,
            momentum_override_threshold=0.035,
        ),
        PositionSizerConfig(
            bull_multiplier=1.35,
            bear_multiplier=0.45,
            sideways_multiplier=0.95,
            drawdown_threshold=0.08,
            drawdown_penalty_factor=3.0,
            drawdown_penalty_min=0.45,
            volatility_high_adj=0.8,
            max_position=1.8,
            min_position=0.35,
            use_exponential_drawdown=True,
            exponential_drawdown_k=3.5,
        ),
    ))

    # === 试2：中等激进，EMA平滑 ===
    trials.append(try_config(
        "试2: 中等+EMA平滑",
        RegimeDetectorConfig(
            momentum_threshold_bull=0.015,
            momentum_threshold_bear=-0.015,
            volatility_threshold_high=0.035,
            hysteresis_min_duration=3,
            momentum_override_threshold=0.04,
        ),
        PositionSizerConfig(
            bull_multiplier=1.3,
            bear_multiplier=0.5,
            sideways_multiplier=0.95,
            drawdown_threshold=0.08,
            drawdown_penalty_factor=2.5,
            drawdown_penalty_min=0.5,
            volatility_high_adj=0.8,
            volatility_low_adj=1.05,
            max_position=1.7,
            min_position=0.4,
            smoothing_alpha=0.2,
            use_exponential_drawdown=True,
            exponential_drawdown_k=3.0,
        ),
    ))

    # === 试3：高牛市仓位，强风控 ===
    trials.append(try_config(
        "试3: 高牛市+强风控",
        RegimeDetectorConfig(
            momentum_threshold_bull=0.01,
            momentum_threshold_bear=-0.01,
            volatility_threshold_high=0.038,
            hysteresis_min_duration=2,
            momentum_override_threshold=0.03,
        ),
        PositionSizerConfig(
            bull_multiplier=1.5,
            bear_multiplier=0.4,
            sideways_multiplier=0.9,
            drawdown_threshold=0.06,
            drawdown_penalty_factor=3.0,
            drawdown_penalty_min=0.4,
            volatility_high_adj=0.75,
            max_position=1.9,
            min_position=0.3,
            use_exponential_drawdown=True,
            exponential_drawdown_k=4.0,
        ),
    ))

    # === 试4：平衡版 ===
    trials.append(try_config(
        "试4: 平衡版",
        RegimeDetectorConfig(
            momentum_threshold_bull=0.015,
            momentum_threshold_bear=-0.015,
            volatility_threshold_high=0.035,
            hysteresis_min_duration=2,
            momentum_override_threshold=0.035,
        ),
        PositionSizerConfig(
            bull_multiplier=1.25,
            bear_multiplier=0.5,
            sideways_multiplier=0.95,
            drawdown_threshold=0.08,
            drawdown_penalty_factor=2.5,
            drawdown_penalty_min=0.5,
            volatility_high_adj=0.85,
            max_position=1.6,
            min_position=0.4,
            smoothing_alpha=0.15,
            use_exponential_drawdown=True,
            exponential_drawdown_k=3.0,
        ),
    ))

    # === 试5：低波动率阈值，更灵敏 ===
    trials.append(try_config(
        "试5: 低波动阈值",
        RegimeDetectorConfig(
            momentum_threshold_bull=0.008,
            momentum_threshold_bear=-0.008,
            volatility_threshold_high=0.032,
            hysteresis_min_duration=2,
            momentum_override_threshold=0.025,
        ),
        PositionSizerConfig(
            bull_multiplier=1.3,
            bear_multiplier=0.45,
            sideways_multiplier=0.9,
            drawdown_threshold=0.07,
            drawdown_penalty_factor=2.5,
            drawdown_penalty_min=0.45,
            volatility_high_adj=0.8,
            max_position=1.7,
            min_position=0.35,
            smoothing_alpha=0.1,
            use_exponential_drawdown=True,
            exponential_drawdown_k=3.5,
        ),
    ))

    # === 输出对比表 ===
    print(f"\n{'=' * 100}")
    print(f"{'配置':<18} {'Sharpe':<10} {'年化%':<10} {'回撤%':<10} {'Calmar':<10} {'IR':<8} {'仓位':<8} {'B/B/S':<18}")
    print(f"{'=' * 100}")
    for t in trials:
        bbs = f"{t['bull']}/{t['bear']}/{t['sideways']}"
        print(f"{t['name']:<18} {t['sharpe']:<10.2f} {t['ann_ret']:<10.2f} {t['max_dd']:<10.2f} {t['calmar']:<10.2f} {t['ir']:<8.2f} {t['avg_pos']:<8.2f} {bbs:<18}")

    # 找出最佳
    print(f"\n{'=' * 100}")
    best = max(trials, key=lambda t: t["sharpe"])
    print(f"🥇 最高Sharpe: {best['name']} → Sharpe={best['sharpe']:.2f}, 回撤={best['max_dd']:.2f}%")
    
    # 找出满足回撤≤15%的最高Sharpe
    valid = [t for t in trials if t["max_dd"] <= 15.0]
    if valid:
        best_valid = max(valid, key=lambda t: t["sharpe"])
        print(f"🥇 合规最佳(回撤≤15%): {best_valid['name']} → Sharpe={best_valid['sharpe']:.2f}, 回撤={best_valid['max_dd']:.2f}%")
    else:
        print("⚠️ 没有配置同时满足回撤≤15%的要求")


if __name__ == "__main__":
    main()