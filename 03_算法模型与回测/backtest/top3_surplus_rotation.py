# -*- coding: utf-8 -*-
"""按“明日预期盈余”榜单进行 Top 3 跨资产轮动回测。

输入面板每一行代表一个标的在交易日 ``date`` 收盘时可获得的信息，至少包含：
``date,symbol,asset_type,expected_surplus_pct,next_return_pct``。
``next_return_pct`` 必须是从该日收盘到下一交易日收盘的收益，避免把未来信息
混入当日排名。``asset_type`` 使用 ``stock`` 或 ``futures``。

示例：
    python top3_surplus_rotation.py --input panel.csv --output reports/tables/top3.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = {
    "date", "symbol", "asset_type", "expected_surplus_pct", "next_return_pct"
}
ASSET_TYPES = {"stock", "futures"}


def validate_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """标准化并校验输入，拒绝不完整或未知资产类型。"""
    missing = REQUIRED_COLUMNS.difference(panel.columns)
    if missing:
        raise ValueError("panel 缺少字段: " + ", ".join(sorted(missing)))
    out = panel.copy()
    out["date"] = pd.to_datetime(out["date"], errors="raise").dt.normalize()
    out["asset_type"] = out["asset_type"].astype(str).str.lower().str.strip()
    unknown = set(out["asset_type"].dropna()) - ASSET_TYPES
    if unknown:
        raise ValueError("未知 asset_type: " + ", ".join(sorted(unknown)))
    for col in ("expected_surplus_pct", "next_return_pct"):
        out[col] = pd.to_numeric(out[col], errors="raise")
    if out[["date", "symbol"]].duplicated().any():
        raise ValueError("同一 date/symbol 存在重复记录")
    return out.sort_values(["date", "symbol"]).reset_index(drop=True)


def select_top3(day: pd.DataFrame, asset_type: Optional[str] = None, top_n: int = 3) -> pd.DataFrame:
    """选择当日榜单，排序规则固定，保证同分时结果可复现。"""
    if asset_type is not None:
        day = day[day["asset_type"] == asset_type]
    return day.sort_values(
        ["expected_surplus_pct", "symbol"], ascending=[False, True], kind="mergesort"
    ).head(top_n)


def _portfolio_curve(panel: pd.DataFrame, asset_type: Optional[str], top_n: int) -> pd.DataFrame:
    rows = []
    for date, day in panel.groupby("date", sort=True):
        selected = select_top3(day, asset_type, top_n)
        if selected.empty:
            continue
        rows.append({
            "date": date,
            "daily_return": float(selected["next_return_pct"].mean()) / 100.0,
            "selected_count": int(len(selected)),
            "futures_weight": float((selected["asset_type"] == "futures").mean()),
            "symbols": ",".join(selected["symbol"].astype(str)),
        })
    if not rows:
        return pd.DataFrame(columns=["date", "daily_return", "equity", "drawdown", "futures_weight"])
    curve = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    curve["equity"] = (1.0 + curve["daily_return"]).cumprod()
    curve["drawdown"] = curve["equity"] / curve["equity"].cummax() - 1.0
    return curve


def _metrics(curve: pd.DataFrame, summer_months: Iterable[int]) -> dict:
    if curve.empty:
        return {"days": 0, "total_return_pct": None, "annualized_sharpe": None,
                "max_drawdown_pct": None, "summer_max_drawdown_pct": None}
    returns = curve["daily_return"].astype(float)
    vol = returns.std(ddof=1)
    sharpe = np.sqrt(252.0) * returns.mean() / vol if vol > 0 else None
    summer = curve[curve["date"].dt.month.isin(list(summer_months))]
    summer_mdd = float(summer["drawdown"].min() * 100.0) if not summer.empty else None
    return {
        "days": int(len(curve)),
        "total_return_pct": float((curve["equity"].iloc[-1] - 1.0) * 100.0),
        "annualized_sharpe": None if sharpe is None else float(sharpe),
        "max_drawdown_pct": float(curve["drawdown"].min() * 100.0),
        "summer_max_drawdown_pct": summer_mdd,
    }


def compare_top3(panel: pd.DataFrame, top_n: int = 3,
                 summer_months: Iterable[int] = (6, 7, 8),
                 weak_stock_threshold_pct: float = 0.0) -> dict:
    """比较纯股票、纯期货和混合 Top 3，并统计弱势月的期货配置。"""
    data = validate_panel(panel)
    curves = {
        "stocks_top3": _portfolio_curve(data, "stock", top_n),
        "futures_top3": _portfolio_curve(data, "futures", top_n),
        "mixed_top3": _portfolio_curve(data, None, top_n),
    }
    result = {name: _metrics(curve, summer_months) for name, curve in curves.items()}

    stock = curves["stocks_top3"]
    mixed = curves["mixed_top3"]
    joined = stock[["date", "daily_return"]].rename(columns={"daily_return": "stock_return"}).merge(
        mixed[["date", "futures_weight"]], on="date", how="inner"
    )
    weak = joined[joined["stock_return"] * 100.0 <= weak_stock_threshold_pct]
    result["switching"] = {
        "weak_stock_days": int(len(weak)),
        "weak_stock_days_with_futures": int((weak["futures_weight"] > 0).sum()),
        "weak_stock_futures_day_share_pct": float((weak["futures_weight"] > 0).mean() * 100.0)
        if not weak.empty else None,
        "average_futures_weight_on_weak_stock_days_pct": float(weak["futures_weight"].mean() * 100.0)
        if not weak.empty else None,
    }
    stock_monthly = stock.set_index("date")["daily_return"].resample("ME").apply(
        lambda values: (1.0 + values).prod() - 1.0
    ).rename("stock_month_return")
    mixed_monthly = mixed.set_index("date")["futures_weight"].resample("ME").mean()
    monthly = pd.concat([stock_monthly, mixed_monthly], axis=1).dropna()
    weak_months = monthly[monthly["stock_month_return"] <= weak_stock_threshold_pct / 100.0]
    result["switching"].update({
        "weak_stock_months": int(len(weak_months)),
        "weak_stock_months_with_futures": int((weak_months["futures_weight"] > 0).sum()),
        "weak_stock_month_futures_share_pct": float((weak_months["futures_weight"] > 0).mean() * 100.0)
        if not weak_months.empty else None,
        "average_futures_weight_on_weak_stock_months_pct": float(weak_months["futures_weight"].mean() * 100.0)
        if not weak_months.empty else None,
    })
    return {"metrics": result, "curves": curves}


def _json_default(value):
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    raise TypeError(type(value).__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="明日预期盈余 Top 3 跨资产回测")
    parser.add_argument("--input", required=True, type=Path, help="统一候选面板 CSV")
    parser.add_argument("--output", type=Path, help="JSON 输出路径")
    args = parser.parse_args()
    result = compare_top3(pd.read_csv(args.input))
    payload = {"metrics": result["metrics"]}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))


if __name__ == "__main__":
    main()
