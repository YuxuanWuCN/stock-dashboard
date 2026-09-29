# -*- coding: utf-8 -*-
"""
共享数据读取层

统一负责 ``docs/data/**`` 下 JSON 文件的读取、mtime 缓存与取值工具，
供 ``dataset_api``（数据集/处理接口）与 ``homepage_api``（首页视图模型）复用。

设计要点
--------
1. 按文件 mtime 缓存：分析流水线更新文件后缓存自动失效，无需重启服务。
2. 所有取值工具对脏数据（None / NaN / inf / 字符串数字）保持容错，
   保证接口永远返回干净 JSON，而不是把原始脏值透传给前端。
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

# server.py 位于 <repo>/src/server.py，因此 parents[1] 即仓库根目录
REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "docs" / "data"

_FILE_CACHE: Dict[Path, Tuple[int, Any]] = {}


def data_path(relative: str) -> Path:
    """把 ``docs/data`` 下的相对路径解析为绝对路径。"""
    return DATA_ROOT / relative


def load_json(path: Path) -> Any:
    """读取 JSON 文件；按 mtime 缓存，文件更新后自动失效。读取失败返回 None。"""
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return None

    cached = _FILE_CACHE.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None

    _FILE_CACHE[path] = (mtime, payload)
    return payload


def load_relative(relative: str) -> Any:
    """按 ``docs/data`` 下的相对路径读取 JSON。"""
    return load_json(data_path(relative))


def first_list(payload: Any, key: str) -> list:
    """从 payload 中取出列表字段，取不到时返回空列表。"""
    if isinstance(payload, Mapping):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def pick(*values: Any) -> Any:
    """返回第一个非 None 的值（比 ``a or b`` 更安全：0 / "" / False 也算有效值）。"""
    for value in values:
        if value is not None:
            return value
    return None


def num(value: Any, digits: int = 2) -> Optional[float]:
    """转成定点浮点数；非数值 / NaN / inf 一律返回 None。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, digits)


def integer(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def text(value: Any) -> Optional[str]:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def get(row: Any, *path: str) -> Any:
    """按路径取嵌套字段，任一层缺失返回 None。"""
    current: Any = row
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current
