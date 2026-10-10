"""Empirical Stress Tests and Adversarial Invariance Verification for DualTrackLedger.

Mission: Challenger 1 (teamwork_preview_challenger) - Milestone 5 Final Verification.
Validates:
1. Severe drawdown and consecutive limit downs.
2. Margin call scenarios (free cash < 0) and tiered forced liquidation hierarchy.
3. Mathematical precision and invariance of the fundamental identity:
   Total Equity == Free Cash + Margin Locked + Stock Market Value
4. Cash interest accrual validation (strictly 1.5% annualized on unencumbered positive free cash).
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from src.assets.cross_asset_mix.contracts import (
    AssetType,
    get_contract_spec,
    SPEC_AU,
    SPEC_FG,
    SPEC_SA,
)
from src.assets.cross_asset_mix.ledger import (
    DailyLedgerState,
    DualTrackLedger,
    Position,
    TradeRecord,
)


# ===========================================================================
# 1. Severe Drawdown and Consecutive Limit Downs
# ===========================================================================

class TestSevereDrawdownsAndLimitDowns:
    """Stress tests simulating flash crashes, consecutive limit downs, and extreme market stress."""

    def test_futures_consecutive_limit_downs_halts_mtm_bleed(self):
        """Simulates 5 consecutive limit downs (-6% per day) on futures.
        
        Verifies:
        - Margin call triggers as free cash becomes negative.
        - Forced liquidation executes Tier 1 (futures closed).
        - Locked margin is released, halting further MTM losses.
        - Ledger state remains consistent and bounded.
        """
        ledger = DualTrackLedger(initial_cash=100_000.0, rf_annual=0.0)
        # Buy 1 lot SA at 2000 (notional 40,000, margin 4,800, free cash 95,200)
        ledger.rebalance(target_weights={"SA": 0.4}, current_prices={"SA": 2000.0})
        assert "SA" in ledger.positions
        assert ledger.positions["SA"].quantity == 1.0

        # Day 1: settle at 2000
        ledger.settle_daily(settle_prices={"SA": 2000.0}, close_prices={"SA": 2000.0})

        # Artificially drain free cash to test limit downs with tight margin
        # Suppose free cash is reduced to 100 RMB
        ledger.free_cash = 100.0

        # Day 2: First limit down -6% (2000 -> 1880). MTM loss = 1 * 20 * (-120) = -2400 RMB
        # Free cash: 100 - 2400 = -2300 < 0 -> Margin call triggers!
        state_d2 = ledger.settle_daily(settle_prices={"SA": 1880.0}, close_prices={"SA": 1880.0})
        
        assert state_d2.margin_call is True
        assert len(state_d2.liquidations) == 1
        assert state_d2.liquidations[0].action == "LIQUIDATE"
        assert state_d2.liquidations[0].symbol == "SA"
        # Position closed -> halts further bleed
        assert "SA" not in ledger.positions
        assert ledger.margin_locked == 0.0
        # Free cash restored by released margin (1880 * 20 * 0.12 = 4512) -> -2300 + 4512 > 0
        assert ledger.free_cash > 0.0

        # Days 3 to 6: SA drops another 4 limit downs to 1400
        # Because SA was liquidated on Day 2, portfolio suffers 0 further losses
        equity_after_liq = ledger.total_equity
        for day_px in [1760.0, 1650.0, 1550.0, 1450.0]:
            st = ledger.settle_daily(settle_prices={"SA": day_px}, close_prices={"SA": day_px})
            assert st.margin_call is False
            assert len(st.liquidations) == 0
            assert ledger.total_equity == pytest.approx(equity_after_liq)

    def test_mixed_portfolio_drawdown_cascading_liquidation(self):
        """Simulates simultaneous stock crash and leveraged futures crash.
        
        Verifies:
        - Leverage > 1.0 creates a margin deficit upon shock.
        - Futures are liquidated first (Tier 1).
        - If free cash remains negative, stocks are liquidated (Tier 2).
        - Risk is bounded and equity is preserved or solvently managed.
        """
        ledger = DualTrackLedger(initial_cash=200_000.0, rf_annual=0.0)
        # 50% stock (100,000 RMB), 1.5x futures leverage (300,000 RMB target val -> 7 lots SA)
        ledger.rebalance(
            target_weights={"600519": 0.5, "SA": 1.5},
            current_prices={"600519": 100.0, "SA": 2000.0},
        )
        assert "600519" in ledger.positions
        assert "SA" in ledger.positions
        sa_lots = ledger.positions["SA"].quantity
        assert sa_lots >= 7.0

        # High shock: SA drops 30% from 2000 to 1400 (-600 pts * 140 = -84,000 loss)
        # Stock drops 15% from 100 to 85
        state = ledger.settle_daily(
            settle_prices={"SA": 1400.0},
            close_prices={"600519": 85.0, "SA": 1400.0},
        )
        assert state.margin_call is True
        # SA must be liquidated first
        liq_symbols = [tr.symbol for tr in state.liquidations]
        assert "SA" in liq_symbols
        assert "SA" not in ledger.positions
        assert ledger.margin_locked == 0.0
        # Solvency restored (free cash >= 0)
        assert ledger.free_cash >= 0.0
        assert ledger.total_equity > 0.0

    def test_insolvency_boundary_negative_equity_guard(self):
        """Catastrophic loss causing equity to approach or cross zero under leverage.
        
        Verifies:
        - Leverage ratio does not divide by zero (safe guard returns >= 100.0).
        - Rebalance refuses further allocations when equity <= 0.
        """
        ledger = DualTrackLedger(initial_cash=50_000.0, rf_annual=0.0)
        # Buy 3 lots SA with 50,000 cash -> notional 120,000, margin 14,400, free cash 35,600
        ledger.rebalance(target_weights={"SA": 2.4}, current_prices={"SA": 2000.0})
        assert ledger.positions["SA"].quantity == 3.0

        # Catastrophic gap down: SA drops to 1000 (-1000 pts * 60 = -60,000 loss > 50,000 equity)
        state = ledger.settle_daily(settle_prices={"SA": 1000.0}, close_prices={"SA": 1000.0})
        assert state.margin_call is True
        assert ledger.total_equity < 0.0
        assert ledger.leverage_ratio >= 100.0
        assert np.isfinite(ledger.leverage_ratio)

        # Attempt to rebalance when broke (equity <= 0)
        trades = ledger.rebalance(target_weights={"600519": 0.5}, current_prices={"600519": 100.0})
        assert len(trades) == 0
        assert "600519" not in ledger.positions


# ===========================================================================
# 2. Margin Call Scenarios and Tiered Liquidation
# ===========================================================================

class TestMarginCallAndTieredLiquidation:
    """Rigorous boundary and hierarchy testing for forced liquidation."""

    def test_margin_call_exact_epsilon_thresholds(self):
        """Tests exact 0.0 boundary for margin calls."""
        ledger = DualTrackLedger(initial_cash=100.0)
        assert ledger.check_margin_call() is False

        ledger.free_cash = 0.0
        assert ledger.check_margin_call() is False

        ledger.free_cash = 1e-12
        assert ledger.check_margin_call() is False

        ledger.free_cash = -1e-12
        assert ledger.check_margin_call() is True

        ledger.free_cash = -0.01
        assert ledger.check_margin_call() is True

    def test_tiered_liquidation_futures_alone_restores_solvency(self):
        """If free cash is slightly negative, liquidating futures restores free cash >= 0,
        leaving stock holdings completely undisturbed.
        """
        ledger = DualTrackLedger(initial_cash=300_000.0, rf_annual=0.0)
        ledger.rebalance(
            target_weights={"600519": 0.5, "FG": 0.3},
            current_prices={"600519": 100.0, "FG": 1500.0},
        )
        assert "600519" in ledger.positions
        assert "FG" in ledger.positions
        initial_stock_shares = ledger.positions["600519"].quantity

        # Introduce small deficit (-500 RMB)
        ledger.free_cash = -500.0
        state = ledger.settle_daily(
            settle_prices={"FG": 1500.0},
            close_prices={"600519": 100.0, "FG": 1500.0},
        )
        assert state.margin_call is True
        assert len(state.liquidations) == 1
        assert state.liquidations[0].symbol == "FG"
        assert state.liquidations[0].asset_type == "FUTURES"

        # Stock position must remain 100% untouched
        assert "600519" in ledger.positions
        assert ledger.positions["600519"].quantity == initial_stock_shares
        assert ledger.free_cash >= 0.0

    def test_tiered_liquidation_preserves_unneeded_futures(self):
        """If multiple futures are held and closing the first restores solvency,
        the second futures position must NOT be liquidated.
        """
        # Initial cash 2,000,000 so AU (450,000 notional) and SA (40,000 notional) can both be bought
        ledger = DualTrackLedger(initial_cash=2_000_000.0, rf_annual=0.0)
        ledger.rebalance(
            target_weights={"SA": 0.3, "AU": 0.3},
            current_prices={"SA": 2000.0, "AU": 450.0},
        )
        assert "SA" in ledger.positions
        assert "AU" in ledger.positions

        # Small deficit that SA margin alone can cover
        sa_margin = ledger.positions["SA"].margin_locked
        assert sa_margin > 1000.0
        ledger.free_cash = -1000.0

        state = ledger.settle_daily(
            settle_prices={"SA": 2000.0, "AU": 450.0},
            close_prices={"SA": 2000.0, "AU": 450.0},
        )
        assert state.margin_call is True
        # Only one asset liquidated
        assert len(state.liquidations) == 1
        assert state.free_cash >= 0.0
        # Exactly one futures was closed, the other remains open
        remaining_futures = [pos for pos in ledger.positions.values() if pos.asset_type != "STOCK"]
        assert len(remaining_futures) == 1

    def test_tiered_liquidation_with_fees_solvency(self):
        """With commissions enabled, net cash from liquidation = margin_released - fee.
        Verifies fee deduction does not violate solvency restoration.
        """
        ledger = DualTrackLedger(
            initial_cash=100_000.0,
            rf_annual=0.0,
            enable_fees=True,
            futures_fee_rate=0.0001,
            commission_rate=0.0003,
            stamp_duty_rate=0.001,
        )
        ledger.rebalance(
            target_weights={"SA": 0.4, "600519": 0.3},
            current_prices={"SA": 2000.0, "600519": 100.0},
        )
        ledger.free_cash = -500.0
        state = ledger.settle_daily(
            settle_prices={"SA": 2000.0},
            close_prices={"SA": 2000.0, "600519": 100.0},
        )
        assert state.margin_call is True
        for tr in state.liquidations:
            assert tr.fee > 0.0
            assert tr.cash_flow == pytest.approx(
                (tr.price * tr.quantity if tr.asset_type == "STOCK" else 
                 get_contract_spec(tr.symbol).multiplier * tr.price * tr.quantity * get_contract_spec(tr.symbol).margin_rate)
                - tr.fee
            )
        assert ledger.free_cash >= 0.0


# ===========================================================================
# 3. Precision Test of Fundamental Accounting Identity
# ===========================================================================

    def test_futures_rebalance_delta_lots_pnl_invariance(self):
        """Adversarial stress test: Holding futures overnight and adding/reducing lots on Day 2.
        
        Demonstrates that when price moves from 2000 to 2100 (+100 pts -> +2000 RMB gain on 1 lot),
        buying 1 additional lot at 2100 must preserve the +2000 RMB gain in total equity.
        """
        ledger = DualTrackLedger(initial_cash=1_000_000.0, rf_annual=0.0)
        # Day 1: Buy 1 lot SA at 2000 (notional 40,000, margin 4,800, free cash 995,200)
        ledger.rebalance({"SA": 0.04}, {"SA": 2000.0}, deadband=0.0)
        ledger.settle_daily({"SA": 2000.0}, {"SA": 2000.0})
        assert ledger.total_equity == pytest.approx(1_000_000.0)

        # Day 2: SA price rises to 2100 (+100 pts -> +2000 RMB gain on 1 lot)
        # We increase target weight to 0.12 (buying 1 more lot to reach 2 lots)
        ledger.rebalance({"SA": 0.12}, {"SA": 2100.0}, deadband=0.0)
        state = ledger.settle_daily({"SA": 2100.0}, {"SA": 2100.0})

        # True economic equity must be 1,002,000.0
        assert ledger.total_equity == pytest.approx(1_002_000.0), (
            f"Expected total_equity 1,002,000.0, got {ledger.total_equity}. "
            f"PnL of existing lot was not credited during rebalance!"
        )

        # Day 3: SA price rises further to 2150 (+50 pts -> +2000 RMB gain on 2 lots)
        # We reduce target weight to 0.05 (selling 1 lot to reduce from 2 lots to 1 lot; 1 lot = 43,000 notional)
        ledger.rebalance({"SA": 0.05}, {"SA": 2150.0}, deadband=0.0)
        state3 = ledger.settle_daily({"SA": 2150.0}, {"SA": 2150.0})
        # True economic equity must be 1,002,000 + 2,000 = 1,004,000.0
        assert ledger.total_equity == pytest.approx(1_004_000.0), (
            f"Expected total_equity 1,004,000.0 post-reduction, got {ledger.total_equity}."
        )
        assert ledger.positions["SA"].quantity == 1.0

        # Day 4: SA price falls to 2050 (-100 pts on 1 lot -> -2000 RMB loss)
        # We exit SA completely (weight 0.0)
        ledger.rebalance({"SA": 0.0}, {"SA": 2050.0}, deadband=0.0)
        state4 = ledger.settle_daily({"SA": 2050.0}, {"SA": 2050.0})
        # True economic equity must be 1,004,000 - 2,000 = 1,002,000.0
        assert ledger.total_equity == pytest.approx(1_002_000.0), (
            f"Expected total_equity 1,002,000.0 post-exit, got {ledger.total_equity}."
        )
        assert "SA" not in ledger.positions
        assert ledger.margin_locked == 0.0


    def test_accounting_identity_invariance_100_day_random_walk(self):
        """Executes a 100-step stochastic random walk with frequent rebalancing,
        divergent settle vs close prices, and fee frictions.
        
        Verifies the identity holds to within 1e-9 at EVERY step.
        """
        rng = np.random.default_rng(2026)
        ledger = DualTrackLedger(
            initial_cash=2_000_000.0,
            rf_annual=0.015,
            enable_fees=True,
            commission_rate=0.00015,
            stamp_duty_rate=0.001,
            futures_fee_rate=0.00005,
        )

        symbols = ["600519", "000858", "SA", "FG", "AU"]
        prices = {"600519": 100.0, "000858": 80.0, "SA": 2000.0, "FG": 1500.0, "AU": 450.0}

        for day in range(100):
            # 1. Stochastic price evolution
            for sym in symbols:
                ret = rng.normal(0.0002, 0.015)
                prices[sym] = max(1.0, prices[sym] * (1.0 + ret))

            # Settle prices for futures jittered from close
            settle_prices = {}
            close_prices = {}
            for sym in symbols:
                close_prices[sym] = prices[sym]
                if sym in ["SA", "FG", "AU"]:
                    jitter = rng.normal(0.0, 0.002)
                    settle_prices[sym] = prices[sym] * (1.0 + jitter)
                else:
                    settle_prices[sym] = prices[sym]

            # 2. Periodic rebalancing every 5 days
            if day % 5 == 0:
                raw_w = rng.dirichlet(np.ones(len(symbols)))
                weights = {sym: float(w) for sym, w in zip(symbols, raw_w)}
                ledger.rebalance(weights, close_prices, deadband=0.005)

                # Check identity immediately after rebalance
                computed_eq = ledger.free_cash + ledger.margin_locked + ledger.stock_market_val
                assert abs(ledger.total_equity - computed_eq) < 1e-8, (
                    f"Identity violated post-rebalance on day {day}: "
                    f"equity={ledger.total_equity}, sum={computed_eq}"
                )

            # 3. Daily settlement & interest accrual
            state = ledger.settle_daily(settle_prices, close_prices, date_str=f"Day_{day}")

            # Check identity post settlement
            computed_eq = state.free_cash + state.margin_locked + state.stock_market_val
            assert abs(state.total_equity - computed_eq) < 1e-8, (
                f"Identity violated post-settle on day {day}: "
                f"equity={state.total_equity}, sum={computed_eq}"
            )
            assert abs(ledger.total_equity - computed_eq) < 1e-8

    def test_identity_preservation_under_extreme_settle_close_divergence(self):
        """Tests identity when settlement price diverges from close price by +20% and -20%."""
        ledger = DualTrackLedger(initial_cash=1_000_000.0, rf_annual=0.0)
        ledger.rebalance(
            target_weights={"SA": 0.4, "600519": 0.4},
            current_prices={"SA": 2000.0, "600519": 100.0},
        )

        # Huge divergence: settle price +20% higher than close price
        state1 = ledger.settle_daily(
            settle_prices={"SA": 2400.0},
            close_prices={"SA": 2000.0, "600519": 105.0},
        )
        assert abs(state1.total_equity - (state1.free_cash + state1.margin_locked + state1.stock_market_val)) < 1e-8

        # Settle price -25% lower than close price
        state2 = ledger.settle_daily(
            settle_prices={"SA": 1800.0},
            close_prices={"SA": 2200.0, "600519": 102.0},
        )
        assert abs(state2.total_equity - (state2.free_cash + state2.margin_locked + state2.stock_market_val)) < 1e-8

    def test_identity_preservation_on_position_dropout(self):
        """When an asset drops out of target weights, closing it preserves identity perfectly."""
        ledger = DualTrackLedger(initial_cash=2_000_000.0, rf_annual=0.0)
        ledger.rebalance(
            target_weights={"SA": 0.3, "600519": 0.3, "AU": 0.3},
            current_prices={"SA": 2000.0, "600519": 100.0, "AU": 450.0},
        )
        assert "SA" in ledger.positions
        assert "600519" in ledger.positions
        assert "AU" in ledger.positions

        # Drop SA and 600519
        ledger.rebalance(
            target_weights={"AU": 0.8},
            current_prices={"SA": 2050.0, "600519": 98.0, "AU": 455.0},
        )
        assert "SA" not in ledger.positions
        assert "600519" not in ledger.positions
        assert "AU" in ledger.positions
        assert abs(ledger.total_equity - (ledger.free_cash + ledger.margin_locked + ledger.stock_market_val)) < 1e-8


# ===========================================================================
# 4. Cash Interest Accrual Validation (Strictly 1.5% Annualized)
# ===========================================================================

class TestCashInterestAccrualValidation:
    """Validates daily idle cash interest accrual: max(0, Free Cash) * (0.015 / 252)."""

    def test_interest_daily_precision_and_compounding_252_days(self):
        """252 trading days of pure idle cash.
        
        Verifies:
        - Daily interest strictly equals free_cash * (0.015 / 252.0).
        - Annual compounded return matches (1 + 0.015 / 252)^252 - 1.
        """
        initial_cash = 10_000_000.0
        rf_annual = 0.015
        ledger = DualTrackLedger(initial_cash=initial_cash, rf_annual=rf_annual)

        expected_daily_rate = rf_annual / 252.0
        expected_cash = initial_cash

        for day in range(252):
            daily_interest = expected_cash * expected_daily_rate
            expected_cash += daily_interest

            state = ledger.settle_daily(settle_prices={}, close_prices={})
            assert state.daily_interest == pytest.approx(daily_interest, rel=1e-10)
            assert state.free_cash == pytest.approx(expected_cash, rel=1e-10)

        # Compounded annual rate
        effective_annual_rate = (ledger.total_equity / initial_cash) - 1.0
        theoretical_compound = (1.0 + expected_daily_rate) ** 252 - 1.0
        assert effective_annual_rate == pytest.approx(theoretical_compound, rel=1e-6)
        # ~1.5113% effective due to daily compounding
        assert 0.0150 < effective_annual_rate < 0.0152

    def test_encumbered_capital_strictly_zero_interest(self):
        """Verifies that:
        - Capital locked in stock spot does NOT accrue interest.
        - Capital locked as futures margin does NOT accrue interest.
        - Only unencumbered positive free cash accrues interest.
        """
        ledger = DualTrackLedger(initial_cash=1_000_000.0, rf_annual=0.015)
        # Allocate 50% to stocks, 30% to futures
        ledger.rebalance(
            target_weights={"600519": 0.50, "SA": 0.30},
            current_prices={"600519": 100.0, "SA": 2000.0},
        )
        stock_val = ledger.stock_market_val
        margin = ledger.margin_locked
        free_cash = ledger.free_cash

        assert stock_val > 0.0
        assert margin > 0.0
        assert free_cash > 0.0
        assert free_cash < 1_000_000.0

        state = ledger.settle_daily(
            settle_prices={"SA": 2000.0},
            close_prices={"600519": 100.0, "SA": 2000.0},
        )

        expected_interest = free_cash * (0.015 / 252.0)
        assert state.daily_interest == pytest.approx(expected_interest)
        # Must not include stock or margin capital
        wrong_interest = (free_cash + margin + stock_val) * (0.015 / 252.0)
        assert state.daily_interest < wrong_interest * 0.9

    def test_interest_on_negative_or_zero_cash_strictly_zero(self):
        """Negative free cash (margin deficit) or zero free cash must yield exactly 0.0 interest."""
        ledger = DualTrackLedger(initial_cash=0.0, rf_annual=0.015)
        assert ledger.accrue_daily_interest() == 0.0

        ledger.free_cash = -10_000.0
        assert ledger.accrue_daily_interest() == 0.0

        ledger.free_cash = -0.0001
        assert ledger.accrue_daily_interest() == 0.0

    def test_interest_micro_and_macro_scale_numerical_stability(self):
        """Micro scale (1.0 RMB) and macro scale (100 Billion RMB) test."""
        # Micro
        micro_ledger = DualTrackLedger(initial_cash=1.0, rf_annual=0.015)
        micro_interest = micro_ledger.accrue_daily_interest()
        assert micro_interest == pytest.approx(1.0 * 0.015 / 252.0)
        assert micro_interest > 0.0

        # Macro
        macro_ledger = DualTrackLedger(initial_cash=100_000_000_000.0, rf_annual=0.015)
        macro_interest = macro_ledger.accrue_daily_interest()
        assert macro_interest == pytest.approx(100_000_000_000.0 * 0.015 / 252.0)
