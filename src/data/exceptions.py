"""Data integrity exceptions for real data enforcement and anti-cheat guards.

This module defines standard exceptions to eliminate silent synthetic fallbacks,
enforce strict real-data guarantees, and reject contaminated synthetic inputs
in formal quantitative backtesting and research pipelines.
"""

from typing import Any, Optional


class MissingRealDataError(Exception):
    """Raised when required real market or factor data is missing and allow_synthetic is False."""

    def __init__(self, missing_items: Any = None, message: Optional[str] = None):
        self.missing_items = missing_items
        if message is None:
            if missing_items is not None:
                message = f"Missing required real data: {missing_items}"
            else:
                message = "Missing required real data and allow_synthetic is False."
        super().__init__(message)


class SyntheticDataRejectedError(Exception):
    """Raised when a formal backtest or evaluation pipeline encounters synthetic data."""

    def __init__(self, source_or_reason: Any = None, message: Optional[str] = None):
        self.source_or_reason = source_or_reason
        if message is None:
            if source_or_reason is not None:
                message = f"Synthetic data rejected in formal evaluation: {source_or_reason}"
            else:
                message = "Formal backtest / evaluation rejected synthetic data."
        super().__init__(message)
