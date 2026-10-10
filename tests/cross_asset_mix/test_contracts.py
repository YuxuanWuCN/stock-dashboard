"""Unit tests for Cross-Asset Mixed Portfolio Contract Specifications and Positions."""

import pytest
import math
from src.assets.cross_asset_mix.contracts import (
    AssetPosition,
    AssetType,
    CONTRACT_SPECS,
    ContractSpec,
    FuturesExchange,
    OrderSide,
    OrderType,
    SPEC_AU,
    SPEC_FG,
    SPEC_SA,
    TradeOrder,
    calculate_margin_requirement,
    calculate_notional_value,
    get_contract_spec,
    get_stock_contract_spec,
    round_to_lot_size,
)


class TestEnums:
    """Test enumeration definitions and value compliance."""

    def test_asset_type_values(self):
        assert AssetType.STOCK.value == "STOCK"
        assert AssetType.FUTURES.value == "FUTURES"

    def test_futures_exchange_values(self):
        assert FuturesExchange.CZCE.value == "CZCE"
        assert FuturesExchange.SHFE.value == "SHFE"
        assert FuturesExchange.SSE.value == "SSE"
        assert FuturesExchange.SZSE.value == "SZSE"

    def test_order_side_and_type(self):
        assert OrderSide.BUY.value == "BUY"
        assert OrderSide.SELL.value == "SELL"
        assert OrderType.MARKET.value == "MARKET"
        assert OrderType.LIMIT.value == "LIMIT"


class TestConcreteSpecs:
    """Test standard specifications for CZCE SA, FG, SHFE AU and equities."""

    def test_sa_spec(self):
        assert SPEC_SA.symbol == "SA"
        assert SPEC_SA.name == "郑商所纯碱"
        assert SPEC_SA.asset_type == AssetType.FUTURES
        assert SPEC_SA.multiplier == 20.0  # 20 tons / lot
        assert SPEC_SA.margin_ratio == 0.12  # 12% margin
        assert SPEC_SA.tick_size == 1.0  # 1 RMB / ton
        assert SPEC_SA.exchange == "CZCE"

    def test_fg_spec(self):
        assert SPEC_FG.symbol == "FG"
        assert SPEC_FG.name == "郑商所玻璃"
        assert SPEC_FG.asset_type == AssetType.FUTURES
        assert SPEC_FG.multiplier == 20.0  # 20 tons / lot
        assert SPEC_FG.margin_ratio == 0.12  # 12% margin
        assert SPEC_FG.tick_size == 1.0  # 1 RMB / ton
        assert SPEC_FG.exchange == "CZCE"

    def test_au_spec(self):
        assert SPEC_AU.symbol == "AU"
        assert SPEC_AU.name == "上期所沪金"
        assert SPEC_AU.asset_type == AssetType.FUTURES
        assert SPEC_AU.multiplier == 1000.0  # 1000 grams / lot
        assert SPEC_AU.margin_ratio == 0.10  # 10% margin
        assert SPEC_AU.tick_size == 0.02  # 0.02 RMB / gram
        assert SPEC_AU.exchange == "SHFE"

    def test_stock_spec_generation(self):
        spec_600519 = get_stock_contract_spec("600519", name="贵州茅台")
        assert spec_600519.symbol == "600519"
        assert spec_600519.name == "贵州茅台"
        assert spec_600519.asset_type == AssetType.STOCK
        assert spec_600519.multiplier == 100.0  # 100 shares / lot
        assert spec_600519.margin_ratio == 1.0  # 100% cash spot
        assert spec_600519.tick_size == 0.01
        assert spec_600519.exchange == "SSE"

        spec_000001 = get_stock_contract_spec("000001", name="平安银行")
        assert spec_000001.exchange == "SZSE"


class TestContractSpecValidationAndCalculations:
    """Test validation boundaries, notional, margin, tick rounding and lot rounding."""

    def test_invalid_contract_spec_raises(self):
        with pytest.raises(ValueError, match="symbol cannot be empty"):
            ContractSpec(symbol="", name="Bad", asset_type=AssetType.STOCK, multiplier=100, margin_ratio=1.0, tick_size=0.01, exchange="SSE")

        with pytest.raises(ValueError, match="multiplier must be positive"):
            ContractSpec(symbol="X", name="Bad", asset_type=AssetType.STOCK, multiplier=0, margin_ratio=1.0, tick_size=0.01, exchange="SSE")

        with pytest.raises(ValueError, match="Margin ratio must be in"):
            ContractSpec(symbol="X", name="Bad", asset_type=AssetType.STOCK, multiplier=100, margin_ratio=1.5, tick_size=0.01, exchange="SSE")

        with pytest.raises(ValueError, match="Tick size must be positive"):
            ContractSpec(symbol="X", name="Bad", asset_type=AssetType.STOCK, multiplier=100, margin_ratio=1.0, tick_size=-0.01, exchange="SSE")

    def test_notional_calculation(self):
        # SA: 1500 RMB/ton, 5 lots, multiplier=20 -> 1500 * 5 * 20 = 150,000 RMB
        assert SPEC_SA.calculate_notional(1500.0, 5) == 150000.0
        # AU: 600 RMB/g, 2 lots, multiplier=1000 -> 600 * 2 * 1000 = 1,200,000 RMB
        assert SPEC_AU.calculate_notional(600.0, 2) == 1200000.0
        # Stock: 20 RMB/share, 10 lots, multiplier=100 -> 20 * 10 * 100 = 20,000 RMB
        stock_spec = get_stock_contract_spec("002415")
        assert stock_spec.calculate_notional(20.0, 10) == 20000.0

        with pytest.raises(ValueError, match="Price cannot be negative"):
            SPEC_SA.calculate_notional(-10.0, 1)

    def test_margin_calculation(self):
        # SA: notional 150,000 * 12% = 18,000 RMB
        assert SPEC_SA.calculate_margin(1500.0, 5) == 18000.0
        # AU: notional 1,200,000 * 10% = 120,000 RMB
        assert SPEC_AU.calculate_margin(600.0, 2) == 120000.0
        # Stock: notional 20,000 * 100% = 20,000 RMB
        stock_spec = get_stock_contract_spec("002415")
        assert stock_spec.calculate_margin(20.0, 10) == 20000.0

    def test_round_to_lot_size(self):
        assert SPEC_SA.round_to_lot_size(3.4, mode="floor") == 3
        assert SPEC_SA.round_to_lot_size(3.7, mode="floor") == 3
        assert SPEC_SA.round_to_lot_size(3.7, mode="round") == 4
        assert SPEC_SA.round_to_lot_size(-3.7, mode="floor") == -3
        assert SPEC_SA.round_to_lot_size(-3.7, mode="round") == -4

    def test_round_to_tick(self):
        # AU tick_size = 0.02
        assert SPEC_AU.round_to_tick(600.013) == 600.02
        assert SPEC_AU.round_to_tick(600.009) == 600.00
        assert SPEC_AU.round_to_tick(600.029) == 600.02
        assert SPEC_AU.round_to_tick(600.031) == 600.04
        # SA tick_size = 1.0
        assert SPEC_SA.round_to_tick(1500.4) == 1500.0
        assert SPEC_SA.round_to_tick(1500.6) == 1501.0

    def test_calculate_pnl(self):
        # Buy 2 lots SA at 1500, sell at 1600 -> (1600-1500) * 2 * 20 = 4000
        pnl_long = SPEC_SA.calculate_pnl(1500.0, 1600.0, 2, side=OrderSide.BUY)
        assert pnl_long == 4000.0
        # Short 2 lots SA at 1600, cover at 1550 -> (1600-1550) * 2 * 20 = 2000
        pnl_short = SPEC_SA.calculate_pnl(1600.0, 1550.0, 2, side=OrderSide.SELL)
        assert pnl_short == 2000.0


class TestSpecRegistryAndHelpers:
    """Test symbol resolution and registry access."""

    def test_get_contract_spec_commodity(self):
        assert get_contract_spec("SA") == SPEC_SA
        assert get_contract_spec("SA0") == SPEC_SA
        assert get_contract_spec("FG") == SPEC_FG
        assert get_contract_spec("FG0") == SPEC_FG
        assert get_contract_spec("AU") == SPEC_AU
        assert get_contract_spec("AU0") == SPEC_AU

    def test_get_contract_spec_delivery_months(self):
        assert get_contract_spec("SA2405") == SPEC_SA
        assert get_contract_spec("FG409") == SPEC_FG
        assert get_contract_spec("AU2406") == SPEC_AU
        assert get_contract_spec("sa2409") == SPEC_SA
        assert get_contract_spec("fg405.czc") == SPEC_FG

    def test_margin_rate_and_lot_size_aliases(self):
        assert SPEC_SA.margin_rate == 0.12
        assert SPEC_FG.margin_rate == 0.12
        assert SPEC_AU.margin_rate == 0.10
        assert SPEC_SA.lot_size == 1
        assert SPEC_FG.lot_size == 1
        assert SPEC_AU.lot_size == 1

        stock_spec = get_stock_contract_spec("600519")
        assert stock_spec.margin_rate == 1.0
        assert stock_spec.lot_size == 100

    def test_get_contract_spec_stocks(self):
        spec = get_contract_spec("300750")
        assert spec.asset_type == AssetType.STOCK
        assert spec.multiplier == 100.0
        assert spec.margin_ratio == 1.0
        assert spec.margin_rate == 1.0
        assert spec.lot_size == 100

    def test_standalone_helpers(self):
        notional = calculate_notional_value("SA", 1000.0, 1)
        assert notional == 20000.0
        margin = calculate_margin_requirement("SA", 1000.0, 1)
        assert margin == 2400.0
        lots = round_to_lot_size("SA", 5.6)
        assert lots == 6


class TestAssetPosition:
    """Test unified position accounting for stock and futures."""

    def test_position_lifecycle(self):
        pos = AssetPosition.from_spec(SPEC_SA)
        assert not pos.is_open
        assert pos.quantity_lots == 0
        assert pos.notional_value == 0.0
        assert pos.margin_locked == 0.0

        # Open 10 lots at 1500
        realized = pos.update_position(10, 1500.0)
        assert realized == 0.0
        assert pos.is_open
        assert pos.quantity_lots == 10
        assert pos.avg_open_price == 1500.0
        assert pos.notional_value == 1500.0 * 10 * 20.0  # 300,000 RMB
        assert pos.margin_locked == 300000.0 * 0.12  # 36,000 RMB

        # Market price increases to 1600
        pos.update_price(1600.0)
        assert pos.notional_value == 1600.0 * 10 * 20.0  # 320,000 RMB
        assert pos.unrealized_pnl == (1600.0 - 1500.0) * 10 * 20.0  # 20,000 RMB

        # Partially close 4 lots at 1650
        realized_close = pos.update_position(-4, 1650.0)
        expected_realized = (1650.0 - 1500.0) * 4 * 20.0  # 12,000 RMB
        assert realized_close == expected_realized
        assert pos.quantity_lots == 6
        assert pos.avg_open_price == 1500.0

        # Close remaining 6 lots at 1700
        realized_final = pos.update_position(-6, 1700.0)
        expected_final = (1700.0 - 1500.0) * 6 * 20.0  # 24,000 RMB
        assert realized_final == expected_final
        assert pos.quantity_lots == 0
        assert not pos.is_open

    def test_position_flip(self):
        pos = AssetPosition.from_spec(SPEC_SA, quantity_lots=5, open_price=1000.0)
        # Sell 8 lots at 1100 -> closes 5 long, opens 3 short at 1100
        realized = pos.update_position(-8, 1100.0)
        assert realized == (1100.0 - 1000.0) * 5 * 20.0
        assert pos.quantity_lots == -3
        assert pos.avg_open_price == 1100.0


class TestTradeOrder:
    """Test trade order properties and status tracking."""

    def test_order_creation(self):
        order = TradeOrder(
            order_id="ORD_001",
            symbol="SA",
            side=OrderSide.BUY,
            quantity_lots=10,
            price=1500.0,
        )
        assert order.status == "PENDING"
        assert not order.is_complete()

        order.status = "FILLED"
        order.filled_quantity = 10
        order.filled_price = 1500.0
        assert order.is_complete()
