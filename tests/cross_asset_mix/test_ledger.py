"""Unit tests for DualTrackLedger and Margin Accounting Mechanics.

Verifies:
1. Fundamental dual-track accounting identity: Total Equity = Free Cash + Margin Locked + Stock Market Value.
2. Equities spot trading: 100% full cash, discrete 100 shares, commissions and stamp duty.
3. Futures leveraged trading: Standard exchange margins (SA/FG 12%, AU 10%), discrete integer lots.
4. Daily Mark-to-Market (MTM) settlement and dynamic locked margin adjustment.
5. Idle cash interest accrual (1.5% annual / 252 days).
6. Risk control, margin call triggers (Free Cash < 0), and tiered forced liquidation.
7. Rebalance deadband filtering and turnover friction control.
"""

import math
import pytest
import numpy as np

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


class TestDualTrackLedgerInitialization:
    """Test initial attributes and default ledger states."""

    def test_default_initialization(self):
        ledger = DualTrackLedger()
        assert ledger.initial_cash == 10_000_000.0
        assert ledger.free_cash == 10_000_000.0
        assert ledger.rf_annual == 0.015
        assert ledger.min_free_cash_buffer == 0.0
        assert ledger.max_leverage == 3.0
        assert ledger.enable_fees is False
        assert ledger.margin_locked == 0.0
        assert ledger.stock_market_val == 0.0
        assert ledger.total_equity == 10_000_000.0
        assert ledger.leverage_ratio == 0.0
        assert len(ledger.positions) == 0
        assert len(ledger.history) == 0
        assert len(ledger.trades) == 0

    def test_custom_parameters(self):
        ledger = DualTrackLedger(
            initial_cash=500_000.0,
            rf_annual=0.02,
            min_free_cash_buffer=0.05,
            max_leverage=2.5,
            enable_fees=True,
            commission_rate=0.0002,
            stamp_duty_rate=0.001,
            min_commission=5.0,
            futures_fee_rate=0.00003,
        )
        assert ledger.initial_cash == 500_000.0
        assert ledger.free_cash == 500_000.0
        assert ledger.rf_annual == 0.02
        assert ledger.min_free_cash_buffer == 0.05
        assert ledger.max_leverage == 2.5
        assert ledger.enable_fees is True
        assert ledger.commission_rate == 0.0002
        assert ledger.stamp_duty_rate == 0.001
        assert ledger.futures_fee_rate == 0.00003


class TestAccountingIdentity:
    """Verify that Total Equity = Free Cash + Margin Locked + Stock Market Value always holds."""

    def test_accounting_identity_on_cash_only(self):
        ledger = DualTrackLedger(initial_cash=1_000_000.0)
        assert ledger.total_equity == ledger.free_cash + ledger.margin_locked + ledger.stock_market_val
        assert ledger.total_equity == 1_000_000.0

    def test_accounting_identity_pure_stock(self):
        ledger = DualTrackLedger(initial_cash=1_000_000.0)
        ledger.rebalance(
            target_weights={"600519": 0.40, "000858": 0.30},
            current_prices={"600519": 100.0, "000858": 80.0},
        )
        assert ledger.margin_locked == 0.0
        assert ledger.stock_market_val > 0.0
        assert ledger.total_equity == pytest.approx(
            ledger.free_cash + ledger.margin_locked + ledger.stock_market_val
        )
        assert ledger.total_equity == pytest.approx(1_000_000.0)

    def test_accounting_identity_pure_futures(self):
        ledger = DualTrackLedger(initial_cash=1_000_000.0)
        ledger.rebalance(
            target_weights={"SA": 0.30, "FG": 0.20},
            current_prices={"SA": 2000.0, "FG": 1500.0},
        )
        assert ledger.stock_market_val == 0.0
        assert ledger.margin_locked > 0.0
        assert ledger.total_equity == pytest.approx(
            ledger.free_cash + ledger.margin_locked + ledger.stock_market_val
        )
        assert ledger.total_equity == pytest.approx(1_000_000.0)

    def test_accounting_identity_mixed_portfolio(self):
        ledger = DualTrackLedger(initial_cash=2_000_000.0)
        ledger.rebalance(
            target_weights={"600519": 0.35, "000858": 0.25, "SA": 0.20, "AU": 0.15},
            current_prices={"600519": 100.0, "000858": 80.0, "SA": 2000.0, "AU": 450.0},
        )
        assert ledger.stock_market_val > 0.0
        assert ledger.margin_locked > 0.0
        assert ledger.free_cash > 0.0
        assert ledger.total_equity == pytest.approx(
            ledger.free_cash + ledger.margin_locked + ledger.stock_market_val
        )


class TestStockExecutionRules:
    """Test spot equities execution, 100-share discrete rounding, and overdraft protections."""

    def test_stock_lot_rounding_to_100_shares(self):
        ledger = DualTrackLedger(initial_cash=100_000.0)
        # 100,000 * 0.5 = 50,000. Price = 83.0 -> 50,000 / 83 = 602.4 shares -> 600 shares
        ledger.rebalance(target_weights={"600519": 0.50}, current_prices={"600519": 83.0})
        pos = ledger.positions["600519"]
        assert pos.quantity == 600
        assert pos.quantity % 100 == 0

    def test_stock_zero_overdraft_on_tight_budget(self):
        ledger = DualTrackLedger(initial_cash=9_000.0)
        # 100 shares of 600519 at 100.0 costs 10,000 > 9,000
        trades = ledger.rebalance(target_weights={"600519": 1.0}, current_prices={"600519": 100.0})
        assert len(trades) == 0
        assert "600519" not in ledger.positions
        assert ledger.free_cash == 9_000.0

    def test_stock_weighted_average_entry_price(self):
        ledger = DualTrackLedger(initial_cash=500_000.0)
        # Initial buy: 1000 shares at 100.0
        ledger.rebalance(target_weights={"600519": 0.20}, current_prices={"600519": 100.0})
        pos = ledger.positions["600519"]
        assert pos.quantity == 1000
        assert pos.avg_price == 100.0

        # Additional buy at 120.0
        ledger.rebalance(target_weights={"600519": 0.40}, current_prices={"600519": 120.0})
        pos = ledger.positions["600519"]
        # Total shares = 500,000 * 0.40 / 120 = 200,000 / 120 = 1666.6 -> 1600 shares (delta +600)
        assert pos.quantity == 1600
        expected_avg = (1000 * 100.0 + 600 * 120.0) / 1600
        assert pos.avg_price == pytest.approx(expected_avg)

    def test_stock_sell_and_purge(self):
        ledger = DualTrackLedger(initial_cash=100_000.0)
        ledger.rebalance(target_weights={"600519": 0.50}, current_prices={"600519": 100.0})
        assert "600519" in ledger.positions

        # Sell all
        trades = ledger.rebalance(target_weights={"600519": 0.0}, current_prices={"600519": 110.0})
        assert len(trades) == 1
        assert trades[0].action == "SELL"
        assert "600519" not in ledger.positions
        assert ledger.stock_market_val == 0.0
        assert ledger.free_cash == pytest.approx(100_000.0 + 500 * 10.0)  # Gained 10 per share


class TestFuturesExecutionRules:
    """Test commodity futures margin locking, discrete lots, and multiplier calculations."""

    def test_sa_fg_au_margin_rates(self):
        spec_sa = get_contract_spec("SA")
        spec_fg = get_contract_spec("FG")
        spec_au = get_contract_spec("AU")

        assert spec_sa.margin_ratio == 0.12
        assert spec_fg.margin_ratio == 0.12
        assert spec_au.margin_ratio == 0.10

    def test_futures_discrete_1_lot_rounding(self):
        ledger = DualTrackLedger(initial_cash=100_000.0)
        # SA at 2000 -> notional = 2000 * 20 = 40,000 per lot, margin = 4,800
        # Target weight 0.5 = 50,000 target val -> 50,000 / 40,000 = 1.25 lots -> 1 lot
        ledger.rebalance(target_weights={"SA": 0.5}, current_prices={"SA": 2000.0})
        pos = ledger.positions["SA"]
        assert pos.quantity == 1.0
        assert pos.margin_locked == pytest.approx(4800.0)
        assert ledger.free_cash == pytest.approx(100_000.0 - 4800.0)

    def test_gold_au_notional_and_margin(self):
        ledger = DualTrackLedger(initial_cash=1_000_000.0)
        # AU at 450.0 RMB/g -> multiplier 1000g -> 450,000 RMB/lot
        # Margin 10% -> 45,000 RMB/lot
        ledger.rebalance(target_weights={"AU": 0.5}, current_prices={"AU": 450.0})
        pos = ledger.positions["AU"]
        assert pos.quantity == 1.0
        assert pos.margin_locked == pytest.approx(45_000.0)
        assert ledger.free_cash == pytest.approx(1_000_000.0 - 45_000.0)

    def test_futures_insufficient_margin_zero_overdraft(self):
        ledger = DualTrackLedger(initial_cash=3_000.0)
        # SA margin 4800 > 3000 free cash
        trades = ledger.rebalance(target_weights={"SA": 1.0}, current_prices={"SA": 2000.0})
        assert len(trades) == 0
        assert "SA" not in ledger.positions
        assert ledger.free_cash == 3_000.0


class TestDailyMTMSettlement:
    """Test daily mark-to-market settlement, settle vs close price handling, and dynamic margin adjustment."""

    def test_mtm_gain_credits_free_cash(self):
        ledger = DualTrackLedger(initial_cash=100_000.0, rf_annual=0.0)
        ledger.rebalance(target_weights={"SA": 0.5}, current_prices={"SA": 2000.0})
        cash_after_buy = ledger.free_cash
        margin_after_buy = ledger.margin_locked

        # Settle at 2100 (+100 points * 20 mult = +2000 PnL)
        # Margin increases by 100 * 20 * 0.12 = 240
        # Net free cash change: +2000 - 240 = +1760
        state = ledger.settle_daily(settle_prices={"SA": 2100.0}, close_prices={"SA": 2100.0})
        assert state.free_cash == pytest.approx(cash_after_buy + 1760.0)
        assert state.margin_locked == pytest.approx(margin_after_buy + 240.0)
        assert state.daily_pnl == pytest.approx(2000.0)
        assert ledger.total_equity == pytest.approx(102_000.0)

    def test_mtm_loss_debits_free_cash(self):
        ledger = DualTrackLedger(initial_cash=100_000.0, rf_annual=0.0)
        ledger.rebalance(target_weights={"SA": 0.5}, current_prices={"SA": 2000.0})

        # Settle at 1900 (-100 points * 20 mult = -2000 PnL)
        # Margin decreases by 100 * 20 * 0.12 = 240 released
        # Net free cash change: -2000 + 240 = -1760
        state = ledger.settle_daily(settle_prices={"SA": 1900.0}, close_prices={"SA": 1900.0})
        assert state.daily_pnl == pytest.approx(-2000.0)
        assert ledger.total_equity == pytest.approx(98_000.0)

    def test_settle_and_close_divergence_preserves_equity(self):
        ledger = DualTrackLedger(initial_cash=500_000.0, rf_annual=0.0)
        ledger.rebalance(
            target_weights={"600519": 0.3, "SA": 0.4},
            current_prices={"600519": 100.0, "SA": 2000.0},
        )
        # Settle at 2100, close at 2050 for SA; stock close at 110.0
        state = ledger.settle_daily(
            settle_prices={"SA": 2100.0},
            close_prices={"600519": 110.0, "SA": 2050.0},
        )
        assert state.total_equity == pytest.approx(
            state.free_cash + state.margin_locked + state.stock_market_val
        )


class TestInterestAccrual:
    """Test idle cash daily interest accrual model."""

    def test_daily_accrual_formula(self):
        ledger = DualTrackLedger(initial_cash=2_520_000.0, rf_annual=0.015)
        state = ledger.settle_daily(settle_prices={}, close_prices={})
        expected_interest = 2_520_000.0 * 0.015 / 252.0  # 150.0 RMB
        assert state.daily_interest == pytest.approx(expected_interest)
        assert ledger.free_cash == pytest.approx(2_520_000.0 + expected_interest)

    def test_no_interest_on_zero_or_negative_cash(self):
        ledger = DualTrackLedger(initial_cash=0.0, rf_annual=0.015)
        assert ledger.accrue_daily_interest() == 0.0

        ledger.free_cash = -500.0
        assert ledger.accrue_daily_interest() == 0.0

    def test_margin_locked_does_not_earn_interest(self):
        ledger = DualTrackLedger(initial_cash=100_000.0, rf_annual=0.015)
        ledger.rebalance(target_weights={"SA": 0.5}, current_prices={"SA": 2000.0})
        free_cash = ledger.free_cash
        assert free_cash < 100_000.0

        state = ledger.settle_daily(settle_prices={"SA": 2000.0}, close_prices={"SA": 2000.0})
        expected_interest = free_cash * (0.015 / 252.0)
        assert state.daily_interest == pytest.approx(expected_interest)


class TestRiskControlAndLiquidation:
    """Test margin calls and tiered forced liquidation hierarchy."""

    def test_check_margin_call(self):
        ledger = DualTrackLedger(initial_cash=100.0)
        assert ledger.check_margin_call() is False

        ledger.free_cash = 0.0
        assert ledger.check_margin_call() is False

        ledger.free_cash = -0.01
        assert ledger.check_margin_call() is True

    def test_tiered_liquidation_futures_first(self):
        ledger = DualTrackLedger(initial_cash=100_000.0)
        ledger.rebalance(
            target_weights={"SA": 0.4, "600519": 0.3},
            current_prices={"SA": 2000.0, "600519": 100.0},
        )
        # Small deficit: 500 RMB. SA margin locked is 4800 RMB
        ledger.free_cash = -500.0
        state = ledger.settle_daily(settle_prices={"SA": 2000.0}, close_prices={"SA": 2000.0, "600519": 100.0})

        assert state.margin_call is True
        assert "SA" not in ledger.positions  # Futures liquidated
        assert "600519" in ledger.positions  # Stock preserved
        assert state.free_cash >= 0.0

    def test_tiered_liquidation_cascades_to_stocks(self):
        ledger = DualTrackLedger(initial_cash=100_000.0)
        ledger.rebalance(
            target_weights={"SA": 0.2, "600519": 0.6},
            current_prices={"SA": 2000.0, "600519": 100.0},
        )
        # Massive deficit 20,000 exceeds SA margin (4800)
        ledger.free_cash = -20_000.0
        state = ledger.settle_daily(settle_prices={"SA": 2000.0}, close_prices={"SA": 2000.0, "600519": 100.0})

        assert state.margin_call is True
        assert "SA" not in ledger.positions
        assert state.free_cash >= 0.0

    def test_liquidation_trades_recorded(self):
        ledger = DualTrackLedger(initial_cash=50_000.0)
        ledger.rebalance(target_weights={"SA": 0.8}, current_prices={"SA": 2000.0})
        ledger.free_cash = -100.0
        state = ledger.settle_daily(settle_prices={"SA": 2000.0}, close_prices={"SA": 2000.0})

        assert len(state.liquidations) > 0
        assert state.liquidations[0].action == "LIQUIDATE"
        assert state.liquidations[0].symbol == "SA"
        assert state.liquidations[0].margin_change < 0.0


class TestFeeCalculationsAndBuffer:
    """Test commission structures, stamp duties, and minimum cash buffer."""

    def test_fees_disabled_by_default(self):
        ledger = DualTrackLedger(initial_cash=100_000.0)
        trades = ledger.rebalance(
            target_weights={"600519": 0.5, "SA": 0.3},
            current_prices={"600519": 100.0, "SA": 2000.0},
        )
        for tr in trades:
            assert tr.fee == 0.0

    def test_fees_enabled_computes_commission_and_tax(self):
        ledger = DualTrackLedger(
            initial_cash=100_000.0,
            enable_fees=True,
            commission_rate=0.00015,
            stamp_duty_rate=0.001,
            min_commission=5.0,
            futures_fee_rate=0.00005,
        )
        # Buy stock 500 shares at 100 = 50,000 -> commission = max(5, 50000 * 0.00015 = 7.5) = 7.5
        trades = ledger.rebalance(target_weights={"600519": 0.5}, current_prices={"600519": 100.0})
        assert len(trades) == 1
        assert trades[0].fee == pytest.approx(7.5)

        # Sell stock at 100 -> commission 7.5 + stamp duty 50000 * 0.001 = 50 -> total 57.5
        sell_trades = ledger.rebalance(target_weights={"600519": 0.0}, current_prices={"600519": 100.0})
        assert len(sell_trades) == 1
        assert sell_trades[0].fee == pytest.approx(57.5)

    def test_min_free_cash_buffer_preserves_reserve(self):
        ledger = DualTrackLedger(initial_cash=100_000.0, min_free_cash_buffer=0.10)
        # 10% buffer reserves 10,000. Target equity available for allocation is 90,000.
        ledger.rebalance(target_weights={"600519": 1.0}, current_prices={"600519": 100.0})
        pos = ledger.positions["600519"]
        assert pos.quantity == 900  # 90,000 / 100
        assert ledger.free_cash >= 10_000.0


class TestEdgeCasesAndDeadband:
    """Test numerical stability, deadbands, zero division, and extreme inputs."""

    def test_deadband_filtering(self):
        ledger = DualTrackLedger(initial_cash=1_000_000.0)
        ledger.rebalance(target_weights={"600519": 0.50}, current_prices={"600519": 100.0})

        # Micro shift 0.4% within 1% deadband -> 0 trades
        trades = ledger.rebalance(target_weights={"600519": 0.504}, current_prices={"600519": 100.0}, deadband=0.01)
        assert len(trades) == 0

        # Large shift 5% exceeds deadband -> executes trade
        trades = ledger.rebalance(target_weights={"600519": 0.55}, current_prices={"600519": 100.0}, deadband=0.01)
        assert len(trades) == 1

    def test_nan_or_negative_price_skipped(self):
        ledger = DualTrackLedger(initial_cash=100_000.0)
        trades = ledger.rebalance(
            target_weights={"600519": 0.5, "000858": 0.5},
            current_prices={"600519": np.nan, "000858": -10.0},
        )
        assert len(trades) == 0
        assert len(ledger.positions) == 0

    def test_zero_equity_infinite_leverage_guard(self):
        ledger = DualTrackLedger(initial_cash=0.0)
        assert ledger.leverage_ratio >= 100.0
        assert np.isfinite(ledger.leverage_ratio)
