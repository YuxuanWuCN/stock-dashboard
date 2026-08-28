# utils.py —— 工具函数（日志、时区、数据校验、原子写入等）

import os
import json
import logging
import shutil
import tempfile
from datetime import date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

try:
    from .config import TIMEZONE_NAME, LOG_FORMAT, LOG_DATE_FORMAT
except ImportError:  # Support direct execution from src/.
    from config import TIMEZONE_NAME, LOG_FORMAT, LOG_DATE_FORMAT

# ============================================================
# 日志
# ============================================================

def setup_logging() -> logging.Logger:
    """配置并返回 logger，同时输出到控制台。"""
    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
    )
    return logging.getLogger("stock-dashboard")


# ============================================================
# 时区
# ============================================================

def beijing_now() -> datetime:
    """返回当前北京时间（Asia/Shanghai），带时区信息。"""
    return datetime.now(ZoneInfo(TIMEZONE_NAME))


def beijing_today() -> date:
    """返回当前北京日期。"""
    return beijing_now().date()


def beijing_date_str() -> str:
    """返回当前北京日期字符串 'YYYY-MM-DD'。"""
    return beijing_today().isoformat()


def beijing_datetime_str() -> str:
    """返回当前北京时间字符串 'YYYY-MM-DD HH:MM:SS'。"""
    return beijing_now().strftime("%Y-%m-%d %H:%M:%S")


def calc_start_date(today: date, lookback_days: int = 400) -> str:
    """根据今天日期和回看天数，计算 start_date 字符串。"""
    start = today - timedelta(days=lookback_days)
    return start.strftime("%Y%m%d")


# ============================================================
# 数据校验
# ============================================================

def validate_ohlcv(
    row_index: int,  # 在原始 df 中的位置，用于日志定位
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float,
    logger: logging.Logger,
) -> bool:
    """校验单行 OHLCV 数据。返回 True 表示通过，False 表示应剔除。"""
    # 开/高/低/收必须为正数
    for name, val in [("open", open_), ("high", high), ("low", low), ("close", close)]:
        if val is None or val <= 0:
            logger.warning(
                "第 %d 行 %s=%.2f ≤0，剔除该行", row_index, name, val or 0
            )
            return False

    # 高 ≥ max(开, 收)
    if high < max(open_, close):
        logger.warning(
            "第 %d 行 high=%.2f < max(open=%.2f, close=%.2f)，剔除该行",
            row_index, high, open_, close,
        )
        return False

    # 低 ≤ min(开, 收)
    if low > min(open_, close):
        logger.warning(
            "第 %d 行 low=%.2f > min(open=%.2f, close=%.2f)，剔除该行",
            row_index, low, open_, close,
        )
        return False

    # 成交量非负
    if volume is not None and volume < 0:
        logger.warning("第 %d 行 volume=%d <0，剔除该行", row_index, volume)
        return False

    return True


# ============================================================
# 均线计算
# ============================================================

def calc_ma(close_prices: list[float], window: int) -> list[Optional[float]]:
    """计算 N 日简单移动平均。不足 N 天的位置填 None。"""
    result: list[Optional[float]] = []
    running_sum = 0.0
    for i, price in enumerate(close_prices):
        running_sum += price
        if i < window - 1:
            result.append(None)
        else:
            if i >= window:
                running_sum -= close_prices[i - window]
            ma = round(running_sum / window, 2)
            result.append(ma)
    return result


# ============================================================
# 原子写入
# ============================================================

def atomic_write_json(data: Any, path: str, logger: logging.Logger) -> None:
    """原子写入 JSON：先写临时文件再重命名，避免读到坏 JSON。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        suffix=".json",
        prefix=".tmp_",
        dir=os.path.dirname(path),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        # Windows 上重命名前需删除目标文件
        if os.path.exists(path):
            os.replace(tmp_path, path)
        else:
            os.rename(tmp_path, path)
    except Exception:
        # 清理临时文件
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


# ============================================================
# 备用：已有数据目录保护
# ============================================================

def has_existing_data(data_dir: str) -> bool:
    """检查是否已有上次成功产出的数据（用于全部失败时保留旧数据）。"""
    kline_dir = os.path.join(data_dir, "kline")
    if not os.path.isdir(kline_dir):
        return False
    files = os.listdir(kline_dir)
    return any(f.endswith(".json") for f in files)
