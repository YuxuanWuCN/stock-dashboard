# -*- coding: utf-8 -*-
"""src/pricing/calibration_config.py —— 滚动方向校准配置参数"""

from dataclasses import dataclass


@dataclass
class CalibrationConfig:
    """滚动方向校准配置。

    注意：修改这些参数后，必须重新运行完整验证，不允许仅在验证期调参。
    """
    # 回溯窗口长度（交易日数）
    lookback_days: int = 30

    # 最小有效样本量门槛
    min_samples: int = 50

    # 统计显著性阈值（p-value）
    significance_level: float = 0.05

    # 置信度门槛（低于此值拒绝预测）
    confidence_threshold: float = 0.70

    # 最小命中率要求（低于此值拒绝预测）
    min_hit_rate: float = 0.52

    # 极端行情检测阈值（单边涨跌比例 > 此值不去均值）
    extreme_market_threshold: float = 0.80

    # 是否启用调试日志（记录每日校准细节）
    debug_logging: bool = False

    def validate(self) -> None:
        """参数合理性检查。"""
        assert 10 <= self.lookback_days <= 60, "lookback_days 应在 10-60 天范围"
        assert 20 <= self.min_samples <= 200, "min_samples 应在 20-200 范围"
        assert 0.01 <= self.significance_level <= 0.10, "significance_level 应在 0.01-0.10 范围"
        assert 0.50 <= self.confidence_threshold <= 0.95, "confidence_threshold 应在 0.50-0.95 范围"
        assert 0.50 <= self.min_hit_rate <= 0.60, "min_hit_rate 应在 0.50-0.60 范围"
        assert 0.50 <= self.extreme_market_threshold <= 1.0, "extreme_market_threshold 应在 0.50-1.0 范围"


# 默认配置（用于回测与线上实测）
DEFAULT_CONFIG = CalibrationConfig()

# 高覆盖率配置（降低门槛，提高覆盖率）
HIGH_COVERAGE_CONFIG = CalibrationConfig(
    confidence_threshold=0.60,
    min_hit_rate=0.51,
    min_samples=30
)

# 高置信度配置（提高门槛，降低覆盖率但提高命中率）
HIGH_CONFIDENCE_CONFIG = CalibrationConfig(
    confidence_threshold=0.80,
    min_hit_rate=0.53,
    min_samples=80
)
