# -*- coding: utf-8 -*-
"""src/pricing/__init__.py —— 定价与校准模块"""

from .calibration_config import (
    CalibrationConfig,
    DEFAULT_CONFIG,
    HIGH_COVERAGE_CONFIG,
    HIGH_CONFIDENCE_CONFIG,
)
from .rolling_direction_calibration import (
    FactorDirection,
    CalibrationResult,
    StockPrediction,
    calculate_hit_rate,
    calibrate_factor_direction,
    apply_calibrated_direction,
    generate_calibration_report,
)
from .factor_orthogonalization import (
    orthogonalize_factor,
    pca_factor_reduction,
    LowR2Warning,
    HighVIFWarning,
)

__all__ = [
    "CalibrationConfig",
    "DEFAULT_CONFIG",
    "HIGH_COVERAGE_CONFIG",
    "HIGH_CONFIDENCE_CONFIG",
    "FactorDirection",
    "CalibrationResult",
    "StockPrediction",
    "calculate_hit_rate",
    "calibrate_factor_direction",
    "apply_calibrated_direction",
    "generate_calibration_report",
    "orthogonalize_factor",
    "pca_factor_reduction",
    "LowR2Warning",
    "HighVIFWarning",
]
