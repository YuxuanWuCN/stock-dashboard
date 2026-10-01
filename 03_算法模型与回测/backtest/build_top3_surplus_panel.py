# -*- coding: utf-8 -*-
"""构建可审计的跨资产明日盈余回测面板。

股票日线从腾讯公开前复权接口下载；SA、FG 期货日线使用本仓库的原始 CSV。
每个交易日的分数只使用截至该日的 20 个交易日收益和波动率，下一日收益单独
保存在 ``next_return_pct`` 中供回测器结算，避免前视偏差。
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
STOCKS = {"300750": "sz300750", "601012": "sh601012", "600438": "sh600438"}
FUTURES = {
    "SA": ROOT / "data" / "raw" / "czce_sa_futures_daily_raw.csv",
    "FG": ROOT / "data" / "raw" / "czce_fg_futures_daily_raw.csv",
}
YAHOO_FUTURES = {"GC=F": "COMEX Gold continuous futures"}


def fetch_tencent_qfq(code: str, start: str, end: str) -> pd.DataFrame:
    """获取公开前复权日线，并保留下载来源便于复核。"""
    query = urlencode({"param": "%s,day,%s,%s,1200,qfq" % (code, start, end)})
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?" + query
    with urlopen(url, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rows = payload.get("data", {}).get(code, {}).get("qfqday", [])
    if not rows:
        raise RuntimeError("腾讯接口未返回 %s 的日线" % code)
    # 腾讯格式可在末尾附带换手率等扩展字段；前六列顺序固定：
    # 日期、开盘、收盘、最高、最低、成交量。
    frame = pd.DataFrame([row[:6] for row in rows], columns=["date", "open", "close", "high", "low", "volume"])
    frame["date"] = pd.to_datetime(frame["date"])
    frame["close"] = pd.to_numeric(frame["close"], errors="raise")
    return frame[["date", "close"]].drop_duplicates("date").sort_values("date")


def local_futures(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, encoding="utf-8")
    frame = frame.rename(columns={"日期": "date", "收盘价": "close"})
    frame["date"] = pd.to_datetime(frame["date"])
    frame["close"] = pd.to_numeric(frame["close"], errors="raise")
    return frame[["date", "close"]].drop_duplicates("date").sort_values("date")


def fetch_yahoo_future(symbol: str, start: str, end: str) -> pd.DataFrame:
    """获取 Yahoo Finance 的连续期货日线并返回可审计的收盘价序列。"""
    start_ts = int(pd.Timestamp(start, tz="UTC").timestamp())
    end_ts = int((pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)).timestamp())
    query = urlencode({"period1": start_ts, "period2": end_ts, "interval": "1d", "events": "history"})
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%s?%s" % (symbol, query)
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; research-backtest/1.0)"})
    last_error = None
    for delay in (0, 3, 8):
        if delay:
            time.sleep(delay)
        try:
            with urlopen(request, timeout=60) as response:
                result = json.loads(response.read().decode("utf-8"))["chart"]["result"][0]
            break
        except Exception as exc:
            last_error = exc
    else:
        raise RuntimeError("Yahoo Finance %s 下载失败: %s" % (symbol, last_error))
    quote = result["indicators"]["quote"][0]
    frame = pd.DataFrame({"date": pd.to_datetime(result["timestamp"], unit="s").normalize(),
                          "close": quote["close"]}).dropna()
    frame["close"] = pd.to_numeric(frame["close"], errors="raise")
    return frame[["date", "close"]].drop_duplicates("date").sort_values("date")


def score_asset(prices: pd.DataFrame, symbol: str, asset_type: str) -> pd.DataFrame:
    """以 20 日因果动量/波动率构造统一的风险调整明日盈余分数。"""
    out = prices.copy().sort_values("date")
    out["ret"] = out["close"].pct_change()
    mean20 = out["ret"].rolling(20, min_periods=20).mean()
    vol20 = out["ret"].rolling(20, min_periods=20).std(ddof=1)
    momentum20 = out["close"].pct_change(20)
    # 股票仅做多；期货按历史动量方向做多或做空。两者均按同一波动率归一。
    direction = np.where((asset_type == "futures") & (momentum20 < 0), -1.0, 1.0)
    out["expected_surplus_pct"] = 100.0 * direction * mean20 / vol20.replace(0.0, np.nan)
    out["next_return_pct"] = 100.0 * direction * out["ret"].shift(-1)
    out["symbol"] = symbol
    out["asset_type"] = asset_type
    out["direction"] = np.where(direction > 0, "long", "short")
    return out[["date", "symbol", "asset_type", "direction", "expected_surplus_pct", "next_return_pct"]]


def build_panel(start: str, end: str) -> tuple[pd.DataFrame, dict]:
    pieces, source = [], {"stocks": {}, "futures": {}}
    for symbol, vendor_code in STOCKS.items():
        prices = fetch_tencent_qfq(vendor_code, start, end)
        source["stocks"][symbol] = {"vendor": "Tencent qfqday", "rows": len(prices)}
        pieces.append(score_asset(prices, symbol, "stock"))
    for symbol, path in FUTURES.items():
        prices = local_futures(path)
        prices = prices[(prices["date"] >= start) & (prices["date"] <= end)]
        source["futures"][symbol] = {"file": str(path.relative_to(ROOT)), "rows": len(prices)}
        pieces.append(score_asset(prices, symbol, "futures"))
    for symbol, description in YAHOO_FUTURES.items():
        prices = fetch_yahoo_future(symbol, start, end)
        raw_path = ROOT / "data" / "raw" / "yahoo_gc_futures_daily_raw.csv"
        prices.to_csv(raw_path, index=False, encoding="utf-8-sig")
        source["futures"][symbol] = {
            "vendor": "Yahoo Finance chart API",
            "description": description,
            "file": str(raw_path.relative_to(ROOT)),
            "rows": len(prices),
        }
        pieces.append(score_asset(prices, symbol, "futures"))
    panel = pd.concat(pieces, ignore_index=True).dropna().sort_values(["date", "symbol"])
    common_dates = panel.groupby("date")["asset_type"].agg(set)
    valid_dates = common_dates[common_dates.map(lambda kinds: {"stock", "futures"}.issubset(kinds))].index
    panel = panel[panel["date"].isin(valid_dates)].reset_index(drop=True)
    source["sample_start"] = panel["date"].min().strftime("%Y-%m-%d")
    source["sample_end"] = panel["date"].max().strftime("%Y-%m-%d")
    source["eligible_dates"] = int(panel["date"].nunique())
    return panel, source


def main() -> None:
    parser = argparse.ArgumentParser(description="构建跨资产 Top 3 历史候选面板")
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2026-09-28")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "processed" / "cross_asset_top3_panel.csv")
    parser.add_argument("--metadata", type=Path, default=ROOT / "data" / "processed" / "cross_asset_top3_panel_metadata.json")
    args = parser.parse_args()
    panel, metadata = build_panel(args.start, args.end)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(args.output, index=False, encoding="utf-8-sig")
    args.metadata.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print("已写入 %d 行、%d 个交易日: %s" % (len(panel), panel["date"].nunique(), args.output))


if __name__ == "__main__":
    main()
