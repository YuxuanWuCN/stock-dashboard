"""Cross-Asset Mixed Portfolio Contract Specifications and Asset Position Models.

This module defines unified contract specifications, trading rules, positions,
and orders for cross-asset portfolios spanning A-share equities (spot) and
Chinese commodity futures (CZCE Pure Soda SA, CZCE Glass FG, SHFE Gold AU).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Union
import math
import re


class AssetType(str, Enum):
    """Asset class enumeration."""
    STOCK = "STOCK"
    FUTURES = "FUTURES"

    def __str__(self) -> str:
        return self.value


class FuturesExchange(str, Enum):
    """Futures and securities exchanges."""
    CZCE = "CZCE"    # 郑州商品交易所 (Zhengzhou Commodity Exchange)
    SHFE = "SHFE"    # 上海期货交易所 (Shanghai Futures Exchange)
    DCE = "DCE"      # 大连商品交易所 (Dalian Commodity Exchange)
    CFFEX = "CFFEX"  # 中国金融期货交易所 (China Financial Futures Exchange)
    INE = "INE"      # 上海国际能源交易中心 (Shanghai International Energy Exchange)
    SSE = "SSE"      # 上海证券交易所 (Shanghai Stock Exchange)
    SZSE = "SZSE"    # 深圳证券交易所 (Shenzhen Stock Exchange)
    NONE = "NONE"


class OrderSide(str, Enum):
    """Trading order direction."""
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Trading order execution type."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"


@dataclass
class ContractSpec:
    """Contract specification and trading parameters for an asset.

    Attributes:
        symbol: Standardized asset symbol (e.g., 'SA', 'FG', 'AU', '600519').
        name: Human-readable Chinese name (e.g., '郑商所纯碱', '贵州茅台').
        asset_type: AssetType (STOCK or FUTURES).
        multiplier: Contract multiplier (e.g., 20 tons/lot for SA/FG, 1000g/lot for AU, 100 shares/lot for stock).
        margin_ratio: Minimum margin requirement ratio (1.0 for stocks = 100% cash spot; 0.10~0.15 for futures).
        tick_size: Minimum price movement increment.
        exchange: Exchange code (e.g., 'CZCE', 'SHFE', 'SSE', 'SZSE').
        trading_hours: Standard trading session hours.
    """
    symbol: str
    name: str
    asset_type: AssetType
    multiplier: float
    margin_ratio: float
    tick_size: float
    exchange: Union[FuturesExchange, str]
    trading_hours: str = "09:30-11:30, 13:00-15:00"

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Validate specification bounds and sanity constraints."""
        if not self.symbol:
            raise ValueError("Contract symbol cannot be empty.")
        if self.multiplier <= 0:
            raise ValueError(f"Contract multiplier must be positive, got {self.multiplier}")
        if not (0.0 < self.margin_ratio <= 1.0):
            raise ValueError(f"Margin ratio must be in (0.0, 1.0], got {self.margin_ratio}")
        if self.tick_size <= 0:
            raise ValueError(f"Tick size must be positive, got {self.tick_size}")

    @property
    def margin_rate(self) -> float:
        """Alias for margin_ratio for cross-module compatibility."""
        return self.margin_ratio

    @property
    def lot_size(self) -> int:
        """Discrete lot size (100 shares for stocks, 1 lot for futures)."""
        if self.asset_type == AssetType.STOCK or str(self.asset_type).upper().endswith("STOCK"):
            return 100
        return 1

    def calculate_notional(self, price: float, quantity_lots: float) -> float:
        """Calculate total notional exposure value.

        Formula: Notional = Price * Quantity (in lots) * Multiplier
        """
        if price < 0:
            raise ValueError(f"Price cannot be negative: {price}")
        return float(price * abs(quantity_lots) * self.multiplier)

    def calculate_margin(self, price: float, quantity_lots: float) -> float:
        """Calculate required margin for position.

        Formula: Margin = Notional * MarginRatio
        For stocks, MarginRatio=1.0 (100% cash).
        For futures, MarginRatio=0.10~0.12 (standard exchange margin).
        """
        notional = self.calculate_notional(price, quantity_lots)
        return float(notional * self.margin_ratio)

    def round_to_lot_size(self, raw_quantity: float, mode: str = "round") -> int:
        """Round continuous quantity into discrete integer lot sizes.

        Args:
            raw_quantity: Desired float quantity (in lots).
            mode: 'round' (nearest integer) or 'floor' (truncate toward zero).

        Returns:
            Discrete integer lot count.
        """
        if mode == "floor":
            if raw_quantity >= 0:
                return int(math.floor(raw_quantity))
            return int(math.ceil(raw_quantity))
        return int(round(raw_quantity))

    def round_to_tick(self, price: float) -> float:
        """Round price to the nearest tick size increment."""
        if self.tick_size <= 0:
            return price
        steps = round(price / self.tick_size)
        rounded = steps * self.tick_size
        # Format decimals according to tick_size precision
        precision = max(0, -int(math.floor(math.log10(self.tick_size)))) if self.tick_size < 1 else 2
        return round(rounded, precision)

    def calculate_pnl(
        self,
        entry_price: float,
        exit_price: float,
        quantity_lots: float,
        side: OrderSide = OrderSide.BUY,
    ) -> float:
        """Calculate realized or unrealized PnL."""
        price_diff = (exit_price - entry_price) if side == OrderSide.BUY else (entry_price - exit_price)
        return float(price_diff * quantity_lots * self.multiplier)


# Concrete Specifications for Commodity Futures
SPEC_SA = ContractSpec(
    symbol="SA",
    name="郑商所纯碱",
    asset_type=AssetType.FUTURES,
    multiplier=20.0,       # 20 吨 / 手
    margin_ratio=0.12,     # 12% 保证金
    tick_size=1.0,         # 1 元 / 吨
    exchange=FuturesExchange.CZCE.value,
    trading_hours="09:00-11:30, 13:30-15:00, 21:00-23:00",
)

SPEC_FG = ContractSpec(
    symbol="FG",
    name="郑商所玻璃",
    asset_type=AssetType.FUTURES,
    multiplier=20.0,       # 20 吨 / 手
    margin_ratio=0.12,     # 12% 保证金
    tick_size=1.0,         # 1 元 / 吨
    exchange=FuturesExchange.CZCE.value,
    trading_hours="09:00-11:30, 13:30-15:00, 21:00-23:00",
)

SPEC_AU = ContractSpec(
    symbol="AU",
    name="上期所沪金",
    asset_type=AssetType.FUTURES,
    multiplier=1000.0,     # 1000 克 / 手
    margin_ratio=0.10,     # 10% 保证金
    tick_size=0.02,        # 0.02 元 / 克
    exchange=FuturesExchange.SHFE.value,
    trading_hours="09:00-11:30, 13:30-15:00, 21:00-02:30",
)

SPEC_AG = ContractSpec(
    symbol="AG",
    name="上期所沪银",
    asset_type=AssetType.FUTURES,
    multiplier=15.0,       # 15 千克 / 手
    margin_ratio=0.12,     # 12% 保证金
    tick_size=1.0,         # 1 元 / 千克
    exchange=FuturesExchange.SHFE.value,
    trading_hours="09:00-11:30, 13:30-15:00, 21:00-02:30",
)

SPEC_CU = ContractSpec(
    symbol="CU",
    name="上期所沪铜",
    asset_type=AssetType.FUTURES,
    multiplier=5.0,        # 5 吨 / 手
    margin_ratio=0.10,     # 10% 保证金
    tick_size=10.0,        # 10 元 / 吨
    exchange=FuturesExchange.SHFE.value,
    trading_hours="09:00-11:30, 13:30-15:00, 21:00-01:00",
)

SPEC_AL = ContractSpec(
    symbol="AL",
    name="上期所沪铝",
    asset_type=AssetType.FUTURES,
    multiplier=5.0,        # 5 吨 / 手
    margin_ratio=0.10,     # 10% 保证金
    tick_size=5.0,         # 5 元 / 吨
    exchange=FuturesExchange.SHFE.value,
    trading_hours="09:00-11:30, 13:30-15:00, 21:00-01:00",
)

SPEC_RB = ContractSpec(
    symbol="RB",
    name="上期所螺纹钢",
    asset_type=AssetType.FUTURES,
    multiplier=10.0,       # 10 吨 / 手
    margin_ratio=0.10,     # 10% 保证金
    tick_size=1.0,         # 1 元 / 吨
    exchange=FuturesExchange.SHFE.value,
    trading_hours="09:00-11:30, 13:30-15:00, 21:00-23:00",
)

SPEC_I = ContractSpec(
    symbol="I",
    name="大商所铁矿石",
    asset_type=AssetType.FUTURES,
    multiplier=100.0,      # 100 吨 / 手
    margin_ratio=0.12,     # 12% 保证金
    tick_size=0.5,         # 0.5 元 / 吨
    exchange=FuturesExchange.DCE.value,
    trading_hours="09:00-11:30, 13:30-15:00, 21:00-23:00",
)

SPEC_SC = ContractSpec(
    symbol="SC",
    name="能源中心原油",
    asset_type=AssetType.FUTURES,
    multiplier=1000.0,     # 1000 桶 / 手
    margin_ratio=0.10,     # 10% 保证金
    tick_size=0.1,         # 0.1 元 / 桶
    exchange=FuturesExchange.INE.value,
    trading_hours="09:00-11:30, 13:30-15:00, 21:00-02:30",
)

SPEC_TA = ContractSpec(
    symbol="TA",
    name="郑商所PTA",
    asset_type=AssetType.FUTURES,
    multiplier=5.0,        # 5 吨 / 手
    margin_ratio=0.10,     # 10% 保证金
    tick_size=2.0,         # 2 元 / 吨
    exchange=FuturesExchange.CZCE.value,
    trading_hours="09:00-11:30, 13:30-15:00, 21:00-23:00",
)

SPEC_M = ContractSpec(
    symbol="M",
    name="大商所豆粕",
    asset_type=AssetType.FUTURES,
    multiplier=10.0,       # 10 吨 / 手
    margin_ratio=0.10,     # 10% 保证金
    tick_size=1.0,         # 1 元 / 吨
    exchange=FuturesExchange.DCE.value,
    trading_hours="09:00-11:30, 13:30-15:00, 21:00-23:00",
)

SPEC_P = ContractSpec(
    symbol="P",
    name="大商所棕榈油",
    asset_type=AssetType.FUTURES,
    multiplier=10.0,       # 10 吨 / 手
    margin_ratio=0.10,     # 10% 保证金
    tick_size=2.0,         # 2 元 / 吨
    exchange=FuturesExchange.DCE.value,
    trading_hours="09:00-11:30, 13:30-15:00, 21:00-23:00",
)

# Registry of concrete commodity futures specs
CONTRACT_SPECS: Dict[str, ContractSpec] = {
    "SA": SPEC_SA,
    "SA0": SPEC_SA,
    "FG": SPEC_FG,
    "FG0": SPEC_FG,
    "AU": SPEC_AU,
    "AU0": SPEC_AU,
    "AG": SPEC_AG,
    "AG0": SPEC_AG,
    "CU": SPEC_CU,
    "CU0": SPEC_CU,
    "AL": SPEC_AL,
    "AL0": SPEC_AL,
    "RB": SPEC_RB,
    "RB0": SPEC_RB,
    "I": SPEC_I,
    "I0": SPEC_I,
    "SC": SPEC_SC,
    "SC0": SPEC_SC,
    "TA": SPEC_TA,
    "TA0": SPEC_TA,
    "M": SPEC_M,
    "M0": SPEC_M,
    "P": SPEC_P,
    "P0": SPEC_P,
}


def get_stock_contract_spec(
    symbol: str,
    name: str = "",
    multiplier: float = 100.0,
    margin_ratio: float = 1.0,
    tick_size: float = 0.01,
) -> ContractSpec:
    """Generate a standard A-share stock contract specification (100 shares/lot, 100% cash)."""
    norm_sym = str(symbol).strip()
    exchange = "SSE" if (norm_sym.startswith("6") or norm_sym.endswith(".SH")) else "SZSE"
    display_name = name or f"A股_{norm_sym}"
    return ContractSpec(
        symbol=norm_sym,
        name=display_name,
        asset_type=AssetType.STOCK,
        multiplier=multiplier,     # 100 股 / 手
        margin_ratio=margin_ratio, # 100% 现货现金
        tick_size=tick_size,       # 0.01 元
        exchange=exchange,
        trading_hours="09:30-11:30, 13:00-15:00",
    )


def get_contract_spec(symbol: str, name: str = "") -> ContractSpec:
    """Retrieve or construct the ContractSpec for a given symbol.

    If symbol is a known commodity future (SA, FG, AU), returns the concrete spec.
    Otherwise, treats the symbol as an A-share equity.
    """
    clean_sym = str(symbol).strip().upper()
    # Strip common suffixes/prefixes if matching commodity
    base_sym = clean_sym.replace(".CZC", "").replace(".SHF", "").replace(".INE", "")
    if base_sym in CONTRACT_SPECS:
        return CONTRACT_SPECS[base_sym]
    if clean_sym in CONTRACT_SPECS:
        return CONTRACT_SPECS[clean_sym]

    # Regex matching for commodity futures with delivery months (e.g. SA2405, FG409, AU2406)
    match = re.match(r"^(SA|FG|AU)\d*$", base_sym)
    if match:
        root_key = match.group(1)
        if root_key in CONTRACT_SPECS:
            return CONTRACT_SPECS[root_key]

    # Default to A-share stock spec
    return get_stock_contract_spec(symbol=symbol, name=name)


def calculate_notional_value(symbol: str, price: float, quantity_lots: float) -> float:
    """Helper function to calculate notional value by symbol."""
    spec = get_contract_spec(symbol)
    return spec.calculate_notional(price, quantity_lots)


def calculate_margin_requirement(symbol: str, price: float, quantity_lots: float) -> float:
    """Helper function to calculate margin requirement by symbol."""
    spec = get_contract_spec(symbol)
    return spec.calculate_margin(price, quantity_lots)


def round_to_lot_size(symbol: str, raw_quantity: float, mode: str = "round") -> int:
    """Helper function to round raw quantity to lot size by symbol."""
    spec = get_contract_spec(symbol)
    return spec.round_to_lot_size(raw_quantity, mode=mode)


@dataclass
class AssetPosition:
    """Unified position tracking object across equities and futures.

    Attributes:
        symbol: Asset symbol.
        asset_type: AssetType (STOCK or FUTURES).
        quantity_lots: Current held quantity in integer lots (positive for long).
        avg_open_price: Volume-weighted average entry price.
        current_price: Latest mark price or close price.
        margin_ratio: Margin requirement ratio (1.0 for stock, 0.10~0.15 for futures).
        multiplier: Contract multiplier.
        settle_price: Daily settlement price (used for futures MTM settlement).
    """
    symbol: str
    asset_type: AssetType
    quantity_lots: int = 0
    avg_open_price: float = 0.0
    current_price: float = 0.0
    margin_ratio: float = 1.0
    multiplier: float = 1.0
    settle_price: float = 0.0

    @classmethod
    def from_spec(cls, spec: ContractSpec, quantity_lots: int = 0, open_price: float = 0.0) -> AssetPosition:
        """Construct position initialized with contract spec defaults."""
        return cls(
            symbol=spec.symbol,
            asset_type=spec.asset_type,
            quantity_lots=quantity_lots,
            avg_open_price=open_price,
            current_price=open_price,
            margin_ratio=spec.margin_ratio,
            multiplier=spec.multiplier,
            settle_price=open_price,
        )

    @property
    def is_open(self) -> bool:
        """Return True if position has non-zero holdings."""
        return self.quantity_lots != 0

    @property
    def notional_value(self) -> float:
        """Total current notional exposure value."""
        return float(abs(self.quantity_lots) * self.multiplier * self.current_price)

    @property
    def margin_locked(self) -> float:
        """Margin locked by this position.

        For equities, 100% of stock market value is locked.
        For futures, Notional * MarginRatio is locked.
        """
        return float(self.notional_value * self.margin_ratio)

    @property
    def unrealized_pnl(self) -> float:
        """Unrealized PnL vs average open price using latest current_price."""
        return float((self.current_price - self.avg_open_price) * self.quantity_lots * self.multiplier)

    @property
    def mtm_pnl(self) -> float:
        """Mark-to-Market PnL using settlement price (if set), else current price."""
        ref_price = self.settle_price if self.settle_price > 0 else self.current_price
        return float((ref_price - self.avg_open_price) * self.quantity_lots * self.multiplier)

    def update_price(self, new_price: float, new_settle: Optional[float] = None) -> None:
        """Update current market price and optional settlement price."""
        self.current_price = float(new_price)
        if new_settle is not None:
            self.settle_price = float(new_settle)

    def update_position(self, delta_lots: int, exec_price: float) -> float:
        """Update position on fill and return realized PnL.

        Args:
            delta_lots: Signed lots to change (+ for buy, - for sell).
            exec_price: Fill price.

        Returns:
            Realized PnL from any closed portion.
        """
        if delta_lots == 0:
            return 0.0

        realized_pnl = 0.0
        # Check if closing or reducing existing position
        if (self.quantity_lots > 0 and delta_lots < 0) or (self.quantity_lots < 0 and delta_lots > 0):
            close_lots = min(abs(self.quantity_lots), abs(delta_lots))
            direction = 1 if self.quantity_lots > 0 else -1
            realized_pnl = direction * (exec_price - self.avg_open_price) * close_lots * self.multiplier

            new_qty = self.quantity_lots + delta_lots
            if new_qty == 0:
                self.quantity_lots = 0
                self.avg_open_price = 0.0
            elif (new_qty > 0 and self.quantity_lots > 0) or (new_qty < 0 and self.quantity_lots < 0):
                # Reduced but not flipped
                self.quantity_lots = new_qty
            else:
                # Flipped direction
                self.quantity_lots = new_qty
                self.avg_open_price = float(exec_price)
        else:
            # Increasing position in same direction or opening new position
            total_qty = self.quantity_lots + delta_lots
            if self.quantity_lots == 0:
                self.avg_open_price = float(exec_price)
            else:
                total_cost = (
                    abs(self.quantity_lots) * self.avg_open_price + abs(delta_lots) * exec_price
                )
                self.avg_open_price = float(total_cost / abs(total_qty))
            self.quantity_lots = total_qty

        self.current_price = float(exec_price)
        return float(realized_pnl)


@dataclass
class TradeOrder:
    """Trade order descriptor for portfolio rebalancing.

    Attributes:
        order_id: Unique order identifier.
        symbol: Target asset symbol.
        side: OrderSide (BUY or SELL).
        order_type: OrderType (MARKET or LIMIT).
        quantity_lots: Discrete order size in lots.
        price: Limit price (0.0 for market order).
        timestamp: Creation timestamp string.
        status: Execution status ('PENDING', 'FILLED', 'REJECTED', 'CANCELLED').
        filled_quantity: Successfully executed lot count.
        filled_price: Weighted average execution price.
    """
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType = OrderType.MARKET
    quantity_lots: int = 0
    price: float = 0.0
    timestamp: str = ""
    status: str = "PENDING"
    filled_quantity: int = 0
    filled_price: float = 0.0

    def is_complete(self) -> bool:
        """Check if order has finished processing."""
        return self.status in ("FILLED", "REJECTED", "CANCELLED")
