# -*- coding: utf-8 -*-
"""tools/sector_rotation_data_probe.py —— 板块轮动回测数据可行性只读探测

阶段1产物：不写任何业务代码、不修改任何原始数据，仅统计并生成
docs/sector_rotation/DATA_FEASIBILITY.md，作为回测引擎（可插拔情绪 provider）
设计与回测报告"数据与局限性"章节的输入。

探测内容：
1. W_price: config.SECTORS 全部成分股在 docs/data/kline/{code}.json 的公共可用交易日窗口。
2. W_real : ak.stock_news_em 每只票可回溯的最早新闻日期构成的真实情绪重放窗口
            （外部请求可用 --offline 跳过并复用上次探测缓存 JSON）。
3. 旁证核查: docs/data/analysis/*.json 是否含个股情绪字段、reports/market_sentiment/*.json
   的覆盖区间（用于说明为何无法直接喂给 SectorSentimentAggregator）。

用法：
    python tools/sector_rotation_data_probe.py            # 联网实测新闻回溯深度
    python tools/sector_rotation_data_probe.py --offline  # 复用缓存，不发外部请求
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src.sector_rotation.config import SECTORS  # noqa: E402

KLINE_DIR = ROOT_DIR / "docs" / "data" / "kline"
ANALYSIS_DIR = ROOT_DIR / "docs" / "data" / "analysis"
MARKET_SENTIMENT_DIR = ROOT_DIR / "reports" / "market_sentiment"
DEFAULT_OUT = ROOT_DIR / "docs" / "sector_rotation" / "DATA_FEASIBILITY.md"
DEFAULT_CACHE = ROOT_DIR / "scratch" / "sector_rotation_data_probe_cache.json"

ALL_TICKERS: List[str] = [t for cfg in SECTORS.values() for t in cfg.tickers]
TICKER_SECTOR: Dict[str, str] = {
    t: cfg.sector_id for cfg in SECTORS.values() for t in cfg.tickers
}


# ============================================================================
# 1. 价格侧探测（纯本地，只读）
# ============================================================================

def _common_window(date_sets: Dict[str, set]) -> Optional[Dict[str, Any]]:
    """由 {code: set(dates)} 求公共窗口（交集非空时）。"""
    common: Optional[set] = None
    for s in date_sets.values():
        common = s if common is None else (common & s)
    if not common:
        return None
    ordered = sorted(common)
    return {"start": ordered[0], "end": ordered[-1], "n_days": len(ordered)}


def probe_kline() -> Dict[str, Any]:
    """统计全部成分股 K 线覆盖区间、按板块与可用子集的公共窗口 W_price。"""
    per_code: Dict[str, Any] = {}
    date_sets: Dict[str, set] = {}
    missing: List[str] = []

    for code in ALL_TICKERS:
        path = KLINE_DIR / f"{code}.json"
        if not path.exists():
            missing.append(code)
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as err:
            missing.append(f"{code} (读取失败: {err})")
            continue
        dates = [str(d)[:10] for d in data.get("dates", [])]
        if not dates:
            missing.append(f"{code} (dates 为空)")
            continue
        date_sets[code] = set(dates)
        bars = data.get("kline") or []
        per_code[code] = {
            "sector": TICKER_SECTOR[code],
            "name": data.get("name", ""),
            "start": min(dates),
            "end": max(dates),
            "n_days": len(dates),
            "n_kline_rows": len(bars) if isinstance(bars, list) else 0,
        }

    result: Dict[str, Any] = {"per_code": per_code, "missing": missing,
                              "w_price_full": (_common_window(date_sets)
                                               if len(date_sets) == len(ALL_TICKERS) else None)}
    # 操作性 W_price：仅基于有 K 线数据的成分股子集
    result["w_price"] = _common_window(date_sets)
    # 板块级窗口（回测净值按板块成分估值，板块级更贴近可用性）
    result["w_price_by_sector"] = {}
    for sector_id, cfg in SECTORS.items():
        sub = {c: date_sets[c] for c in cfg.tickers if c in date_sets}
        result["w_price_by_sector"][sector_id] = {
            "n_stocks_with_data": len(sub),
            "window": _common_window(sub),
        }
    return result


# ============================================================================
# 2. 真实新闻侧探测（外部请求，可 --offline 跳过并复用缓存）
# ============================================================================

def probe_news_online(cache_path: Path) -> Dict[str, Any]:
    """逐票实测 ak.stock_news_em 可回溯的最早新闻日期，结果写入缓存 JSON。"""
    import akshare as ak  # 延迟导入，离线模式无需依赖

    per_code: Dict[str, Any] = {}
    for i, code in enumerate(ALL_TICKERS):
        entry: Dict[str, Any] = {"probed_at": datetime.now().isoformat(timespec="seconds")}
        try:
            df = ak.stock_news_em(symbol=code)
            col = "发布时间" if "发布时间" in df.columns else None
            if col is None or df.empty:
                entry["error"] = "返回为空或缺少'发布时间'列"
                entry["rows"] = 0 if df is None else int(len(df))
            else:
                times = df[col].astype(str).str.strip()
                times = times[times.str.len() >= 10]
                dates = sorted(t[:10] for t in times)
                entry["rows"] = len(dates)
                if dates:
                    entry["earliest"] = dates[0]
                    entry["latest"] = dates[-1]
                else:
                    entry["error"] = "发布时间无法解析"
        except Exception as err:  # noqa: BLE001 —— 网络/接口异常均记录后继续
            entry["error"] = f"{type(err).__name__}: {err}"
        per_code[code] = entry
        print(f"[news {i + 1}/{len(ALL_TICKERS)}] {code}: "
              + entry.get("earliest", entry.get("error", "?")))
        time.sleep(0.5)  # 简单限流，避免触发接口封禁

    payload = {"mode": "online", "cached_at": datetime.now().isoformat(timespec="seconds"),
               "results": per_code}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def probe_news_offline(cache_path: Path) -> Dict[str, Any]:
    """离线模式：复用上次探测缓存；无缓存则标记不可用。"""
    if not cache_path.exists():
        return {"mode": "offline-no-cache", "cached_at": None, "results": {}}
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        payload["mode"] = f"offline(from cache {payload.get('cached_at')})"
        return payload
    except (json.JSONDecodeError, OSError) as err:
        return {"mode": "offline-corrupt-cache", "cached_at": None,
                "results": {}, "error": str(err)}


def _window_from(earliest_list: List[str], latest_list: List[str],
                 w_price: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not earliest_list:
        return {"available": False, "reason": "无有效新闻日期"}
    start = max(earliest_list)  # 公共窗口起点 = 各票最早日期中最晚者
    end = min(latest_list)
    if w_price:
        start = max(start, w_price["start"])
        end = min(end, w_price["end"])
    if start > end:
        return {"available": False, "inverted": True, "start": start, "end": end,
                "reason": "各票新闻回溯区间无公共重叠（起点晚于终点），全票同窗重放不可行"}
    n_days = (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days + 1
    return {"available": True, "start": start, "end": end, "n_calendar_days": n_days}


def derive_w_real(news_results: Dict[str, Any], w_price: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """由每票最早/最新新闻日期推导真实情绪重放窗口：全票公共 + 板块级 + 单票级。"""
    earliest_all: List[str] = []
    latest_all: List[str] = []
    failed: List[str] = []
    per_sector: Dict[str, Dict[str, Any]] = {}
    for code in ALL_TICKERS:
        entry = news_results.get(code) or {}
        if entry.get("earliest"):
            earliest_all.append(entry["earliest"])
            latest_all.append(entry.get("latest", entry["earliest"]))
        else:
            failed.append(code)

    w_real = _window_from(earliest_all, latest_all, w_price)
    w_real["failed"] = failed

    for sector_id, cfg in SECTORS.items():
        e_list = [news_results[c]["earliest"] for c in cfg.tickers
                  if (news_results.get(c) or {}).get("earliest")]
        l_list = [news_results[c].get("latest", news_results[c]["earliest"]) for c in cfg.tickers
                  if (news_results.get(c) or {}).get("earliest")]
        per_sector[sector_id] = _window_from(e_list, l_list, w_price)
    w_real["by_sector"] = per_sector
    return w_real


# ============================================================================
# 3. 旁证核查（说明为何不存在个股日频情绪历史）
# ============================================================================

def probe_analysis_snapshots() -> Dict[str, Any]:
    """核查 docs/data/analysis/{code}.json：单日快照、是否含 sentiment 字段。"""
    checked = 0
    with_sentiment_field = 0
    trade_dates: List[str] = []
    for code in ALL_TICKERS:
        path = ANALYSIS_DIR / f"{code}.json"
        if not path.exists():
            continue
        checked += 1
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        keys = set(data.keys()) if isinstance(data, dict) else set()
        if keys & {"sentiment", "sentiment_score", "llm_sentiment"}:
            with_sentiment_field += 1
        td = data.get("trade_date") if isinstance(data, dict) else None
        if td:
            trade_dates.append(str(td)[:10])
    return {
        "files_checked": checked,
        "with_sentiment_field": with_sentiment_field,
        "distinct_trade_dates": sorted(set(trade_dates)),
    }


def probe_market_sentiment() -> Dict[str, Any]:
    """核查 reports/market_sentiment/*.json：市场级情绪，非个股级，无法喂聚合器。"""
    files = sorted(MARKET_SENTIMENT_DIR.glob("sentiment_*.json")) if MARKET_SENTIMENT_DIR.exists() else []
    dates: List[str] = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        td = str(data.get("date") or f.stem.split("_")[-1])[:10]
        dates.append(td)
    return {
        "n_files": len(files),
        "start": min(dates) if dates else None,
        "end": max(dates) if dates else None,
        "note": "字段为市场级 sentiment_score(0-10) + hot_sectors(中文名)，非个股 [-1,1] 情绪，无法直接输入 SectorSentimentAggregator",
    }


# ============================================================================
# 4. Markdown 报告生成
# ============================================================================

def render_markdown(kline: Dict[str, Any], news: Dict[str, Any], w_real: Dict[str, Any],
                    analysis: Dict[str, Any], market_sent: Dict[str, Any],
                    generated_at: str) -> str:
    w_price = kline["w_price"]
    lines: List[str] = []
    ap = lines.append

    ap("# 板块轮动回测数据可行性报告（DATA_FEASIBILITY）")
    ap("")
    ap(f"- 生成时间：`{generated_at}`")
    ap("- 生成工具：`tools/sector_rotation_data_probe.py`（只读探测，可用 `--offline` 复用缓存重放）")
    ap("- 探测范围：`src/sector_rotation/config.py` SECTORS 三大板块共 "
       f"{len(ALL_TICKERS)} 只成分股（green/storage/gold）")
    ap("")

    ap("## 1. 结论速览")
    ap("")
    ap("| 窗口 | 口径 | 区间 | 长度 | 用途 |")
    ap("|---|---|---|---|---|")
    wp_full = kline.get("w_price_full")
    if wp_full:
        ap(f"| W_price | 19 票全量交集 | {wp_full['start']} ~ {wp_full['end']} | "
           f"{wp_full['n_days']} 交易日 | （存在缺失票，不可用） |")
    else:
        ap("| W_price | 19 票全量交集 | **不可用**（存在 K 线缺失票，见 §2） | - | - |")
    if w_price:
        ap(f"| W_price | 可用票子集交集（{len(kline['per_code'])} 票） | {w_price['start']} ~ {w_price['end']} | "
           f"{w_price['n_days']} 交易日 | 代理情绪（price_breadth_proxy）回测全窗口（操作性口径） |")
    else:
        ap("| W_price | 可用票子集 | **不可用** | - | - |")
    for sector_id, info in kline.get("w_price_by_sector", {}).items():
        win = info["window"]
        n_tot = len(SECTORS[sector_id].tickers)
        if win:
            ap(f"| W_price[{sector_id}] | 板块级（{info['n_stocks_with_data']}/{n_tot} 票） | "
               f"{win['start']} ~ {win['end']} | {win['n_days']} 交易日 | 板块净值与基准对比窗口 |")
        else:
            ap(f"| W_price[{sector_id}] | 板块级（{info['n_stocks_with_data']}/{n_tot} 票） | "
               "**无公共日** | - | - |")
    if w_real.get("available"):
        ap(f"| W_real | 全票新闻公共窗口 | {w_real['start']} ~ {w_real['end']} | "
           f"约 {w_real['n_calendar_days']} 日历日 | 真实情绪重放（结论性场景） |")
    elif w_real.get("inverted"):
        ap(f"| W_real | 全票新闻公共窗口 | **空窗**（起点 {w_real['start']} 晚于终点 "
           f"{w_real['end']}，各票回溯区间无重叠） | 0 | S2 按 §5 降级，见 §3 |")
    else:
        ap(f"| W_real | 全票新闻公共窗口 | 未探测（{news.get('mode', 'unknown')}） | - | 见 §3 |")
    ap("")

    ap("## 2. 价格侧：成分股 K 线覆盖（docs/data/kline）")
    ap("")
    ap("| 代码 | 名称 | 板块 | 起 | 止 | 交易日数 |")
    ap("|---|---|---|---|---|---|")
    for code, info in sorted(kline["per_code"].items(), key=lambda kv: (kv[1]["sector"], kv[0])):
        ap(f"| {code} | {info['name']} | {info['sector']} | {info['start']} | "
           f"{info['end']} | {info['n_days']} |")
    ap("")
    if kline["missing"]:
        ap(f"**缺失/异常**：{', '.join(str(m) for m in kline['missing'])}（回测按可用子集成分估值，"
           "缺失票在 run_manifest 与监控告警中显式登记）")
        ap("")

    ap("## 3. 真实新闻侧：ak.stock_news_em 可回溯深度")
    ap("")
    ap(f"探测模式：`{news.get('mode')}`（缓存时间 `{news.get('cached_at')}`）")
    ap("")
    if news.get("results"):
        ap("| 代码 | 新闻条数 | 最早 | 最新 | 备注 |")
        ap("|---|---|---|---|---|")
        for code in ALL_TICKERS:
            e = news["results"].get(code) or {}
            ap(f"| {code} | {e.get('rows', '-')} | {e.get('earliest', '-')} | "
               f"{e.get('latest', '-')} | {e.get('error', '')} |")
    else:
        ap("未进行在线探测（离线且无缓存），W_real 待首次联网探测后回填。")
    ap("")
    if w_real.get("by_sector"):
        ap("**板块级 W_real**（板块内各票新闻窗口的公共重叠）：")
        ap("")
        for sector_id, wr in w_real["by_sector"].items():
            if wr.get("available"):
                ap(f"- `{sector_id}`：{wr['start']} ~ {wr['end']}（约 {wr['n_calendar_days']} 日历日）")
            elif wr.get("inverted"):
                ap(f"- `{sector_id}`：**空窗**（起点 {wr['start']} 晚于终点 {wr['end']}）")
            else:
                ap(f"- `{sector_id}`：不可用（{wr.get('reason', '?')}）")
        ap("")

    ap("## 4. 旁证：为何不存在个股日频情绪历史")
    ap("")
    ap(f"- `docs/data/analysis/{{code}}.json`：核查 {analysis['files_checked']} 个文件，"
       f"含个股情绪字段的 **{analysis['with_sentiment_field']}** 个；"
       f"trade_date 取值仅 {analysis['distinct_trade_dates'] or '无'}（单日快照，非时序）。")
    ap(f"- `reports/market_sentiment/sentiment_*.json`：共 {market_sent['n_files']} 个文件"
       + (f"，覆盖 {market_sent['start']} ~ {market_sent['end']}" if market_sent['start'] else "")
       + f"。{market_sent['note']}。")
    ap("- 新闻由 `src/llm/news_fetcher.py` 经 `ak.stock_news_em` 实时抓取，仓库内无历史归档。")
    ap("")

    ap("## 5. W_real 不足 W_price 时的处理方式（设计约束）")
    ap("")
    ap("1. 回测情绪输入必须为**可插拔 provider**，两窗口分列、禁止混用：")
    ap("   - 代理场景 S1/S3：`ProxyBreadthSentimentProvider` × W_price 全窗口，"
       "所有产物强制标注 `sentiment_source=\"price_breadth_proxy\"`，仅用于机制与成本链路验证。")
    ap("   - 真实场景 S2：`LLMReplaySentimentProvider` × W_real 收缩区间，"
       "标注 `sentiment_source=\"llm_news_replay\"`，为唯一可支撑结论性陈述的场景。")
    ap("2. W_real 短于 20 个交易日时，S2 结论降级为\"前向累积观察\"，由每日任务的 `history.jsonl` "
       "持续累积真实个股情绪序列，2-4 周后重跑 S2。")
    ap("3. 代理情绪结果禁止标注为 LLM 情绪、禁止写入 `docs/data/` 供前端消费（AGENTS.md 数据诚实性）。")
    ap("")

    ap("## 6. 局限性声明")
    ap("")
    ap("- 交易日历按 weekday<5 近似（`sector_utils.is_trading_day`），未含法定节假日调休。")
    ap("- `ak.stock_news_em` 仅返回接口当前可回溯的最近批次新闻（约百条级），W_real 会随时间"
       "滚动缩短，本报告的探测结果具有时效性，重跑前请勿长期引用。")
    ap("- 新闻发布时间为新闻落地时间，非事件发生时间；LLM 重放情绪的历史深度受接口回溯深度硬约束"
       "（实测 `ak.stock_news_em` 每票仅返回约 10 条）。")
    if w_price and w_real.get("available") and w_real["n_calendar_days"] < 20:
        ap(f"- 本次探测 W_real 仅约 {w_real['n_calendar_days']} 个日历日（< 20 交易日门槛），"
           "S2 按 §5.2 降级为前向累积观察。")
    if w_real.get("inverted"):
        ap("- 本次探测全票公共新闻窗口为空（倒挂）：`W_real` 不足 `W_price` 的极端情形。"
           "处理：S2 不产出结论性指标，仅保留单日采样验证链路；由 `daily_job` 的 "
           "`history.jsonl` 每日归档个股情绪，累积 ≥20 个交易日后重跑 S2。")
    if kline["missing"]:
        ap(f"- K 线缺失票：{', '.join(str(m) for m in kline['missing'])}；另有部分板块 K 线终点早于 "
           "W_price 终点（如 gold 板块），板块级可用窗口以 §2 板块级口径为准。")
    ap("")
    return "\n".join(lines) + "\n"


# ============================================================================
# 5. CLI
# ============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="板块轮动回测数据可行性只读探测")
    parser.add_argument("--offline", action="store_true",
                        help="跳过 ak.stock_news_em 外部请求，复用上次探测缓存 JSON")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="DATA_FEASIBILITY.md 输出路径")
    parser.add_argument("--cache", default=str(DEFAULT_CACHE), help="新闻探测缓存 JSON 路径")
    args = parser.parse_args()

    cache_path = Path(args.cache)
    out_path = Path(args.out)

    print("[1/4] 探测价格侧 K 线公共窗口 ...")
    kline = probe_kline()

    print("[2/4] 探测真实新闻回溯深度 ...")
    if args.offline:
        news = probe_news_offline(cache_path)
    else:
        news = probe_news_online(cache_path)
    w_real = derive_w_real(news.get("results", {}), kline["w_price"])

    print("[3/4] 旁证核查 analysis / market_sentiment ...")
    analysis = probe_analysis_snapshots()
    market_sent = probe_market_sentiment()

    print("[4/4] 生成报告 ...")
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    md = render_markdown(kline, news, w_real, analysis, market_sent, generated_at)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")

    wp = kline["w_price"]
    print(f"W_price(可用子集): {wp['start']} ~ {wp['end']} ({wp['n_days']} 交易日)" if wp
          else "W_price: 不可用")
    for sector_id, info in kline.get("w_price_by_sector", {}).items():
        win = info["window"]
        print(f"  [{sector_id}] {win['start']} ~ {win['end']} ({win['n_days']}d)" if win
              else f"  [{sector_id}] 无公共窗口")
    if w_real.get("available"):
        print(f"W_real(全票): {w_real['start']} ~ {w_real['end']} (~{w_real['n_calendar_days']} 日历日)")
    elif w_real.get("inverted"):
        print(f"W_real(全票): 空窗（起点 {w_real['start']} 晚于终点 {w_real['end']}）")
    else:
        print(f"W_real(全票): 不可用（{news.get('mode')}）")
    print(f"报告已写入: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
