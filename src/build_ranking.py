# build_ranking.py —— 自选股短线风险收益排行榜 主流水线
#
# 每个交易日北京时间 17:30 运行。
# 产出:
#   docs/data/analysis/ranking.json
#   docs/data/analysis/{code}.json
#
# 用法: python -m src.build_ranking

import json
import os
import sys
import time
import traceback
from datetime import date, datetime
from pathlib import Path
from typing import Optional

# ---- 清理代理环境变量 ----
for _key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
             "ALL_PROXY", "all_proxy", "FTP_PROXY", "ftp_proxy"):
    os.environ.pop(_key, None)
os.environ["NO_PROXY"] = "*"

import requests as _requests

_orig_init = _requests.Session.__init__


def _patched_session_init(self, *args, **kwargs):
    _orig_init(self, *args, **kwargs)
    self.trust_env = False


_requests.Session.__init__ = _patched_session_init

import akshare as ak
import pandas as pd
import numpy as np

# 导入项目模块
from src.config import (
    LOOKBACK_DAYS as KLINE_LOOKBACK_DAYS,
    ADJUST,
    PERIOD,
    REQUEST_INTERVAL as KLINE_REQUEST_INTERVAL,
    MAX_RETRIES as KLINE_MAX_RETRIES,
    MIN_VALID_ROWS,
    MA_WINDOWS,
    WATCHLIST_PATH,
    DATA_DIR,
    KLINE_DIR,
)
from src.utils import (
    setup_logging,
    beijing_now,
    beijing_today,
    beijing_date_str,
    beijing_datetime_str,
    calc_start_date,
    validate_ohlcv,
    calc_ma,
    atomic_write_json,
    has_existing_data,
)
from src.fetch_data import read_watchlist, fetch_one, compute_derived, build_kline_json

from src.analysis.config import (
    LOOKBACK_DAYS_5Y,
    STANDARDIZATION_WINDOW,
    ANALYSIS_DIR_NAME,
    REQUEST_INTERVAL,
    REQUEST_TIMEOUT,
    MAX_RETRIES,
    FORECAST_HORIZONS,
    KNN_K,
    KNN_MIN_SAMPLES,
    MA_WINDOWS as ANALYSIS_MA_WINDOWS,
)
from src.analysis.indicators import (
    compute_all_indicators,
    get_latest_value,
    determine_trend,
    calc_mas,
)
from src.analysis.industry import IndustryProvider
from src.analysis.similarity import find_similar_samples
from src.analysis.scoring import (
    compute_risk_score,
    compute_technical_score,
    compute_industry_score,
    compute_composite_score,
)
from src.analysis.schema import validate_ranking, validate_stock_detail

logger = setup_logging()

# 输出路径
ANALYSIS_DIR = os.path.join(DATA_DIR, ANALYSIS_DIR_NAME)
RANKING_PATH = os.path.join(ANALYSIS_DIR, "ranking.json")


# ============================================================
# 1. 5 年数据抓取
# ============================================================

def fetch_5y_data(item: dict) -> Optional[pd.DataFrame]:
    """
    抓取单只标的 5 年日线数据（用于分析/相似匹配）。
    返回清洗后升序排列的 DataFrame。

    注意：这个方法使用更大的 LOOKBACK_DAYS_5Y，
    与 fetch_data.py 中的 fetch_one（400 自然日）不同。
    """
    code = item["code"]
    typ = item["type"]
    today = beijing_today()
    start_date_str = calc_start_date(today, LOOKBACK_DAYS_5Y)
    end_date_str = today.strftime("%Y%m%d")

    for attempt in range(1 + MAX_RETRIES):
        try:
            if typ == "stock":
                df = _fetch_stock_5y(code, start_date_str, end_date_str, attempt)
            else:
                df = _fetch_etf_5y(code, start_date_str, end_date_str, attempt)

            if df is None or df.empty:
                continue

            # 清洗
            df = _clean_dataframe(df, code, item["name"])
            if df is None:
                continue

            df = df.sort_values("date").reset_index(drop=True)
            return df

        except Exception:
            logger.warning(
                "%s(%s) 5Y 抓取异常 (attempt %d): %s",
                item["name"], code, attempt + 1, traceback.format_exc(),
            )

        if attempt < MAX_RETRIES:
            time.sleep(REQUEST_INTERVAL)

    logger.error("%s(%s) 5Y 数据全部尝试失败", item["name"], code)
    return None


def _fetch_stock_5y(code: str, start_date: str, end_date: str, attempt: int) -> Optional[pd.DataFrame]:
    """抓取 A 股 5 年历史数据。"""
    if attempt == 0:
        df = ak.stock_zh_a_hist(
            symbol=code, period=PERIOD,
            start_date=start_date, end_date=end_date, adjust=ADJUST,
        )
    else:
        start_fmt = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
        end_fmt = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
        prefix = "sh" if code.startswith("6") else "sz"
        df = ak.stock_zh_a_daily(
            symbol=f"{prefix}{code}",
            start_date=start_fmt, end_date=end_fmt, adjust=ADJUST,
        )

    if df is None or df.empty:
        return None

    col_map = {
        "日期": "date", "开盘": "open", "收盘": "close",
        "最高": "high", "最低": "low", "成交量": "volume",
        "成交额": "amount", "振幅": "amplitude", "涨跌幅": "change_pct",
        "涨跌额": "change_amt", "换手率": "turnover",
    }
    return df.rename(columns=col_map)


def _fetch_etf_5y(code: str, start_date: str, end_date: str, attempt: int) -> Optional[pd.DataFrame]:
    """抓取 ETF 5 年历史数据。修复 ETF 数据抓取问题。"""
    if attempt == 0:
        try:
            df = ak.fund_etf_hist_em(
                symbol=code, period=PERIOD,
                start_date=start_date, end_date=end_date, adjust=ADJUST,
            )
        except Exception:
            df = None
    else:
        try:
            start_fmt = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
            end_fmt = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
            prefix = "sh" if code.startswith("5") else "sz"
            df = ak.stock_zh_a_daily(
                symbol=f"{prefix}{code}",
                start_date=start_fmt, end_date=end_fmt, adjust=ADJUST,
            )
        except Exception:
            df = None

    # ETF 主源失败时，尝试用 fund_etf_hist_sina 备用
    if df is None or df.empty:
        try:
            logger.info("ETF %s 尝试备用源 fund_etf_hist_sina", code)
            df = ak.fund_etf_hist_sina(symbol=code)
        except Exception:
            pass

    if df is None or df.empty:
        return None

    col_map = {
        "日期": "date", "开盘": "open", "收盘": "close",
        "最高": "high", "最低": "low", "成交量": "volume",
        "成交额": "amount", "振幅": "amplitude", "涨跌幅": "change_pct",
        "涨跌额": "change_amt", "换手率": "turnover",
    }
    return df.rename(columns=col_map)


def _clean_dataframe(df: pd.DataFrame, code: str, name: str) -> Optional[pd.DataFrame]:
    """清洗 DataFrame，统一列名和日期格式。"""
    if "date" not in df.columns:
        logger.warning("%s(%s) 缺少日期列", name, code)
        return None

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df["date"] = df["date"].dt.date

    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 逐行校验
    valid_mask = []
    for idx, row in df.iterrows():
        ok = validate_ohlcv(
            row_index=idx,
            open_=row.get("open"),
            high=row.get("high"),
            low=row.get("low"),
            close=row.get("close"),
            volume=row.get("volume"),
            logger=logger,
        )
        valid_mask.append(ok)

    df = df[valid_mask].copy()

    if len(df) < MIN_VALID_ROWS:
        logger.warning("%s(%s) 5Y 有效行数 %d < %d", name, code, len(df), MIN_VALID_ROWS)
        return None

    logger.info("%s(%s) 5Y 有效数据 %d 行", name, code, len(df))
    return df


# ============================================================
# 2. 单只分析
# ============================================================

def analyze_single(
    item: dict,
    df: pd.DataFrame,
    industry_provider: IndustryProvider,
    all_latest_values: list,   # 用于跨标的百分位排名（不断累积）
) -> dict:
    """
    对单只标的执行完整分析：
    - 技术指标
    - 行业数据
    - 相似走势
    - 评分

    返回按共享数据合同格式的 dict。
    """
    code = item["code"]
    name = item["name"]
    typ = item["type"]
    category = item.get("category", "")

    logger.info("=" * 50)
    logger.info("分析 %s(%s) ...", name, code)

    # ---- 2.1 计算技术指标 ----
    df = compute_all_indicators(df)

    # ---- 2.2 获取行业数据 ----
    industry_close, ref_type, ref_name, bench_code = industry_provider.get_industry_close_series(
        category, df["date"]
    )

    # 若成功获取行业数据，重新计算含行业信息的指标
    if industry_close is not None:
        df = compute_all_indicators(df, industry_close=industry_close)

        # 计算行业自身的指标
        # 构造行业 DataFrame
        ind_df = pd.DataFrame({"close": industry_close.values}, index=df.index)
        ind_df = ind_df.dropna(subset=["close"])
        if len(ind_df) >= 60:
            ind_indicators = compute_all_indicators(
                pd.DataFrame({
                    "date": df["date"], "open": ind_df["close"],
                    "high": ind_df["close"], "low": ind_df["close"],
                    "close": ind_df["close"], "volume": pd.Series(0, index=df.index),
                })
            )
        else:
            ind_indicators = df.copy()
    else:
        ind_indicators = df.copy()

    # ---- 2.3 提取最新值 ----
    latest = {
        "close": get_latest_value(df["close"]),
        "ma5": get_latest_value(df.get("ma5")),
        "ma10": get_latest_value(df.get("ma10")),
        "ma20": get_latest_value(df.get("ma20")),
        "ma60": get_latest_value(df.get("ma60")),
        "rsi14": get_latest_value(df.get("rsi14")),
        "macd_dif": get_latest_value(df.get("macd_dif")),
        "macd_dea": get_latest_value(df.get("macd_dea")),
        "macd_hist": get_latest_value(df.get("macd_hist")),
        "atr14_pct": get_latest_value(df.get("atr14_pct")),
        "boll_position": get_latest_value(df.get("boll_position")),
        "volume_ratio_5d": get_latest_value(df.get("volume_ratio_5d")),
        "volatility_20d": get_latest_value(df.get("volatility_20d")),
        "max_drawdown_60d": get_latest_value(df.get("max_drawdown_60d")),
        "return_5d": get_latest_value(df.get("return_5d")),
        "return_20d": get_latest_value(df.get("return_20d")),
        "return_60d": get_latest_value(df.get("return_60d")),
        "trend": determine_trend(
            df["close"], df.get("ma20", pd.Series()), df.get("ma60", pd.Series()), df.get("rsi14", pd.Series())
        ),
        # 行业波动
        "industry_volatility_20d": get_latest_value(ind_indicators.get("volatility_20d")),
    }

    # ---- 2.4 历史相似走势 ----
    similarity = find_similar_samples(df)

    # ---- 2.5 技术分 ----
    technical = compute_technical_score(latest)

    # ---- 2.6 行业数据（对齐共享合同字段） ----
    industry_info = {
        "name": category if category else ref_name,
        "reference_type": ref_type,
        "benchmark_code": bench_code,
        "return_5d_pct": None,
        "return_20d_pct": None,
        "return_60d_pct": None,
        "relative_strength_20d_pct": None,
    }

    if industry_close is not None and len(industry_close.dropna()) >= 21:
        ind_close_valid = industry_close.dropna()
        # 计算行业自身收益
        if len(ind_close_valid) >= 6:
            ind_ret_5 = (ind_close_valid.iloc[-1] - ind_close_valid.iloc[-6]) / ind_close_valid.iloc[-6] * 100
            industry_info["return_5d_pct"] = round(float(ind_ret_5), 2)
        if len(ind_close_valid) >= 21:
            ind_ret_20 = (ind_close_valid.iloc[-1] - ind_close_valid.iloc[-21]) / ind_close_valid.iloc[-21] * 100
            industry_info["return_20d_pct"] = round(float(ind_ret_20), 2)
        if len(ind_close_valid) >= 61:
            ind_ret_60 = (ind_close_valid.iloc[-1] - ind_close_valid.iloc[-61]) / ind_close_valid.iloc[-61] * 100
            industry_info["return_60d_pct"] = round(float(ind_ret_60), 2)

        # 相对强度
        rs_20 = latest.get("industry_rs_20d")
        if rs_20 is not None:
            industry_info["relative_strength_20d_pct"] = round(float(rs_20), 2)

    # ---- 2.7 行业分 ----
    industry_scoring = compute_industry_score(latest, industry_info, all_latest_values)

    # 将最新值加入全局列表（用于跨标的百分位排名）
    all_latest_values.append(latest)

    # ---- 2.8 收集 reasons ----
    tech_reasons = _collect_technical_reasons(latest, technical)
    ind_reasons = industry_scoring.get("_reasons", [])
    if "_reasons" in industry_scoring:
        del industry_scoring["_reasons"]

    reasons = tech_reasons + ind_reasons
    # 先不排序，等 risk 计算完成后再统一排序

    # ---- 2.9 构建返回值 ----
    latest_trade_date = df["date"].iloc[-1]
    trade_date_str = (
        latest_trade_date.isoformat()
        if hasattr(latest_trade_date, "isoformat")
        else str(latest_trade_date)[:10]
    )

    result = {
        "schema_version": "2.0",
        "generated_at": "",  # 最后统一填充
        "trade_date": trade_date_str,
        "code": code,
        "name": name,
        "type": typ,
        "category": category,
        "stale": False,
        "latest": latest,
        "technical": technical,
        "industry_info": industry_info,
        "industry_scoring": industry_scoring,
        "similarity": similarity,
        "reasons": reasons,
        # kline_file 指向已有 K 线数据
        "kline_file": f"../kline/{code}.json",
    }

    return result


def _collect_technical_reasons(latest: dict, technical: dict) -> list:
    """从技术指标生成 reasons（直接基于数据，不调用 LLM）。"""
    reasons = []

    close = latest.get("close")
    ma20 = latest.get("ma20")
    ma60 = latest.get("ma60")
    rsi = latest.get("rsi14")
    vr = latest.get("volume_ratio_5d")
    ret_5 = latest.get("return_5d")
    ret_20 = latest.get("return_20d")
    mdd = latest.get("max_drawdown_60d")
    vol = latest.get("volatility_20d")
    atr = latest.get("atr14_pct")

    # 趋势相关
    trend = technical.get("trend", "range")
    if trend in ("uptrend", "strong_uptrend"):
        reasons.append({
            "type": "positive",
            "title": "中短期趋势向上",
            "detail": "收盘价位于20日和60日均线上方。",
            "contribution": 8.0,
        })
    elif trend == "rebound":
        reasons.append({
            "type": "positive",
            "title": "短期反弹中",
            "detail": "价格站上20日均线，关注持续性。",
            "contribution": 5.0,
        })
    elif trend == "downtrend":
        reasons.append({
            "type": "negative",
            "title": "趋势偏弱",
            "detail": "价格低于主要均线，短期承压。",
            "contribution": -8.0,
        })

    # 量能
    if vr is not None:
        if vr >= 1.5:
            reasons.append({
                "type": "positive" if ret_5 and ret_5 > 0 else "warning",
                "title": "成交活跃",
                "detail": f"近5日量能为前期{vr:.2f}倍。",
                "contribution": 5.0 if ret_5 and ret_5 > 0 else 2.0,
            })
        elif vr <= 0.5:
            reasons.append({
                "type": "warning",
                "title": "成交缩量",
                "detail": f"近5日量能仅为前期{vr:.2f}倍。",
                "contribution": -3.0,
            })

    # RSI
    if rsi is not None:
        if rsi > 70:
            reasons.append({
                "type": "warning",
                "title": "RSI偏高",
                "detail": f"RSI14={rsi:.1f}，短期超买。",
                "contribution": -5.0,
            })
        elif rsi < 30:
            reasons.append({
                "type": "warning",
                "title": "RSI偏低",
                "detail": f"RSI14={rsi:.1f}，短期超卖。",
                "contribution": -5.0,
            })

    # 回撤
    if mdd is not None and mdd < -15:
        reasons.append({
            "type": "negative",
            "title": "近期回撤较大",
            "detail": f"近60日最大回撤 {abs(mdd):.1f}%，风险偏高。",
            "contribution": -7.0,
        })

    return reasons


# ============================================================
# 3. 排名构建
# ============================================================

def build_ranking(
    results: dict,  # {code: analysis_dict or None}
    watchlist: list,
) -> dict:
    """
    根据所有标的分结果构建 ranking.json。
    results 中 None 表示该只分析失败。
    """
    # 收集所有 valid results 用于跨标的百分位排名
    all_latest = []
    for code, r in results.items():
        if r and r.get("latest"):
            all_latest.append(r["latest"])

    # 收集所有预测收益（用于百分位排名）
    all_forecast_5d = []
    all_up_prob_5d = []
    for code, r in results.items():
        if r and r.get("similarity"):
            sim = r["similarity"]
            fc = sim.get("horizon_5d", {}).get("average_return_pct")
            up = sim.get("horizon_5d", {}).get("up_probability_pct")
            if fc is not None:
                all_forecast_5d.append(fc)
            if up is not None:
                all_up_prob_5d.append(up)

    # ---- 为每只标的重算风险分（使用全局百分位）----
    for code, r in results.items():
        if r is None or not r.get("latest"):
            continue

        # 风险分（需要全局 latest 列表）
        risk_result = compute_risk_score(r["latest"], all_latest)

        # 综合评分
        composite = compute_composite_score(
            risk_result,
            r["technical"],
            r["industry_scoring"],
            r["similarity"],
            all_forecast_5d,
            all_up_prob_5d,
        )

        r["risk_result"] = risk_result
        r["composite"] = composite

        # 合并并排序 reasons
        # 提取 risk reasons
        risk_reasons = []
        for f in risk_result.get("factors", []):
            if f.get("name") == "60日最大回撤" and f.get("value") is not None and f["value"] < -15:
                risk_reasons.append({
                    "type": "negative",
                    "title": "回撤风险",
                    "detail": f"近60日最大回撤 {abs(f['value']):.1f}%，风险扣分。",
                    "contribution": -7.0,
                })
            elif f.get("name") == "20日波动率" and f.get("value") is not None and f["value"] > 40:
                risk_reasons.append({
                    "type": "negative",
                    "title": "波动较大",
                    "detail": f"20日年化波动率 {f['value']:.1f}%，波动偏高。",
                    "contribution": -5.0,
                })

        all_reasons = r["reasons"] + risk_reasons
        all_reasons.sort(key=lambda x: abs(x.get("contribution", 0)), reverse=True)
        r["reasons"] = all_reasons[:5]

    # ---- 构建 items 排序 ----
    succeeded = []
    failed_codes = []

    for item in watchlist:
        code = item["code"]
        r = results.get(code)
        if r is None:
            failed_codes.append(code)
        else:
            succeeded.append(r)

    # 风险收益榜：按 risk_adjusted_score 降序（null 排最后）
    succeeded.sort(
        key=lambda r: r["composite"]["risk_adjusted"] if r["composite"]["risk_adjusted"] is not None else -999,
        reverse=True,
    )

    # 编制 items
    items = []
    for rank_idx, r in enumerate(succeeded, start=1):
        code = r["code"]
        sim = r["similarity"]
        risk = r["risk_result"]
        comp = r["composite"]
        tech = r["technical"]
        ind_info = r["industry_info"]
        ind_score = r["industry_scoring"]

        fc_3d = sim.get("horizon_3d", {})
        fc_5d = sim.get("horizon_5d", {})

        item_entry = {
            "rank": rank_idx,
            "code": code,
            "name": r["name"],
            "type": r["type"],
            "category": r.get("category", ""),
            "trade_date": r["trade_date"],
            "stale": r.get("stale", False),
            "risk_adjusted_score": comp["risk_adjusted"],
            "risk": {
                "score": risk["score"],
                "level": risk["level"],
                "label": risk["label"],
                "factors": risk["factors"],
            },
            "forecast": {
                "return_3d_pct": fc_3d.get("average_return_pct"),
                "return_5d_pct": fc_5d.get("average_return_pct"),
                "up_probability_3d_pct": fc_3d.get("up_probability_pct"),
                "up_probability_5d_pct": fc_5d.get("up_probability_pct"),
                "confidence": sim.get("confidence", "low"),
                "sample_size": sim.get("sample_size", 0),
            },
            "technical": {
                "score": tech["score"],
                "trend": tech["trend"],
                "rsi14": tech["rsi14"],
                "volume_ratio_5d": tech["volume_ratio_5d"],
            },
            "industry": {
                "name": ind_info["name"],
                "reference_type": ind_info["reference_type"],
                "score": ind_score["score"],
                "return_5d_pct": ind_score.get("return_5d_pct"),
                "return_20d_pct": ind_score.get("return_20d_pct"),
                "relative_strength_20d_pct": ind_score.get("relative_strength_20d_pct"),
            },
            "reasons": r["reasons"],
        }

        items.append(item_entry)

    # 失败项
    errors_list = []
    for code in failed_codes:
        last_success = _get_last_success_date(code)
        errors_list.append({
            "code": code,
            "message": "数据源暂时不可用或分析失败",
            "last_success_trade_date": last_success,
        })

    total = len(watchlist)
    succeeded_count = len(succeeded)
    failed_count = len(failed_codes)

    trade_dates = [
        r.get("trade_date")
        for r in succeeded
        if r.get("trade_date")
    ]
    trade_date_str = max(trade_dates) if trade_dates else beijing_date_str()
    generated_at = beijing_datetime_str() + "+08:00"

    # 统一填充 generated_at
    for r in results.values():
        if r:
            r["generated_at"] = generated_at

    ranking = {
        "schema_version": "2.0",
        "generated_at": generated_at,
        "trade_date": trade_date_str,
        "horizons": FORECAST_HORIZONS,
        "ranking_method": "risk_adjusted_v1",
        "status": "success" if failed_count == 0 else "partial",
        "total": total,
        "succeeded": succeeded_count,
        "failed": failed_count,
        "items": items,
        "errors": errors_list if errors_list else [],
        "disclaimer": "基于历史日线的统计分析，仅用于学习和研究，不构成投资建议或收益保证。",
    }

    return ranking


def _get_last_success_date(code: str) -> Optional[str]:
    """从已有的分析文件读取最后成功交易日。"""
    path = os.path.join(ANALYSIS_DIR, f"{code}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("trade_date")
    except Exception:
        return None


# ============================================================
# 4. 生成个股详情文件
# ============================================================

def build_stock_detail(r: dict, generated_at: str) -> dict:
    """将分析结果转为个股详情 JSON（共享合同格式）。"""
    sim = r["similarity"]
    risk = r["risk_result"]
    comp = r["composite"]
    tech = r["technical"]
    ind_info = r["industry_info"]
    ind_score = r["industry_scoring"]
    latest = r.get("latest", {})

    fc_3d = sim.get("horizon_3d", {})
    fc_5d = sim.get("horizon_5d", {})

    return {
        "schema_version": "2.0",
        "generated_at": generated_at,
        "trade_date": r["trade_date"],
        "code": r["code"],
        "name": r["name"],
        "type": r["type"],
        "category": r.get("category", ""),
        "stale": r.get("stale", False),
        "scores": {
            "risk_adjusted": comp["risk_adjusted"],
            "risk": comp["risk"],
            "technical": comp["technical"],
            "industry": comp["industry"],
        },
        "risk": {
            "level": risk["level"],
            "label": risk["label"],
            "annualized_volatility_20d_pct": risk.get("annualized_volatility_20d_pct"),
            "max_drawdown_60d_pct": risk.get("max_drawdown_60d_pct"),
            "atr14_pct": risk.get("atr14_pct"),
            "factors": risk["factors"],
        },
        "forecast": {
            "return_3d_pct": fc_3d.get("average_return_pct"),
            "return_5d_pct": fc_5d.get("average_return_pct"),
            "up_probability_3d_pct": fc_3d.get("up_probability_pct"),
            "up_probability_5d_pct": fc_5d.get("up_probability_pct"),
            "confidence": sim.get("confidence", "low"),
            "sample_size": sim.get("sample_size", 0),
        },
        "technical": {
            "trend": tech["trend"],
            "ma5": latest.get("ma5"),
            "ma10": latest.get("ma10"),
            "ma20": latest.get("ma20"),
            "ma60": latest.get("ma60"),
            "rsi14": tech["rsi14"],
            "macd_dif": latest.get("macd_dif"),
            "macd_dea": latest.get("macd_dea"),
            "macd_hist": latest.get("macd_hist"),
            "atr14_pct": latest.get("atr14_pct"),
            "boll_position": latest.get("boll_position"),
            "return_5d_pct": latest.get("return_5d"),
            "return_20d_pct": latest.get("return_20d"),
            "volume_ratio_5d": tech["volume_ratio_5d"],
        },
        "industry": {
            "name": ind_info["name"],
            "reference_type": ind_info["reference_type"],
            "benchmark_code": ind_info["benchmark_code"],
            "return_5d_pct": ind_score.get("return_5d_pct"),
            "return_20d_pct": ind_score.get("return_20d_pct"),
            "return_60d_pct": ind_score.get("return_60d_pct"),
            "relative_strength_20d_pct": ind_score.get("relative_strength_20d_pct"),
        },
        "similarity": {
            "method": sim.get("method", "standardized_knn_v1"),
            "sample_size": sim.get("sample_size", 0),
            "minimum_sample_size": sim.get("minimum_sample_size", KNN_MIN_SAMPLES),
            "confidence": sim.get("confidence", "low"),
            "horizon_3d": {
                "up_probability_pct": fc_3d.get("up_probability_pct"),
                "average_return_pct": fc_3d.get("average_return_pct"),
                "median_return_pct": fc_3d.get("median_return_pct"),
                "best_return_pct": fc_3d.get("best_return_pct"),
                "worst_return_pct": fc_3d.get("worst_return_pct"),
            },
            "horizon_5d": {
                "up_probability_pct": fc_5d.get("up_probability_pct"),
                "average_return_pct": fc_5d.get("average_return_pct"),
                "median_return_pct": fc_5d.get("median_return_pct"),
                "best_return_pct": fc_5d.get("best_return_pct"),
                "worst_return_pct": fc_5d.get("worst_return_pct"),
            },
        },
        "reasons": r["reasons"],
        "kline_file": r["kline_file"],
        "disclaimer": "基于历史日线的统计分析，仅用于学习和研究，不构成投资建议或收益保证。",
    }


# ============================================================
# 5. 主流程
# ============================================================

def main() -> int:
    run_start = beijing_now()
    logger.info("=" * 60)
    logger.info("自选股短线风险收益排行榜分析开始 —— %s", run_start.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 60)

    # ---- 5.1 读取自选股 ----
    watchlist = read_watchlist(WATCHLIST_PATH)

    # 读取 category 列
    watchlist_with_category = _read_watchlist_with_category(WATCHLIST_PATH)
    if watchlist_with_category:
        # 将 category 合并到 watchlist
        cat_map = {w["code"]: w.get("category", "") for w in watchlist_with_category}
        for item in watchlist:
            item["category"] = cat_map.get(item["code"], "")

    logger.info("自选股数量: %d", len(watchlist))

    # ---- 5.2 初始化行业提供器 ----
    industry_provider = IndustryProvider()

    # ---- 5.3 逐只抓取 5 年数据并分析 ----
    analysis_results: dict[str, Optional[dict]] = {}
    all_latest_values: list = []  # 存 latest dict 列表

    for i, item in enumerate(watchlist):
        code = item["code"]
        logger.info("[%d/%d] %s(%s) 分析中...", i + 1, len(watchlist), item["name"], code)

        try:
            # 抓取 5 年数据
            df_5y = fetch_5y_data(item)

            if df_5y is None:
                logger.warning("%s(%s) 5Y 数据抓取失败，标记为 stale", item["name"], code)
                # 尝试加载上次成功结果
                stale_result = _load_stale_result(code, item)
                analysis_results[code] = stale_result
                continue

            # 全量分析
            result = analyze_single(item, df_5y, industry_provider, all_latest_values)
            analysis_results[code] = result
            logger.info("%s(%s) ✓ 分析完成", item["name"], code)

        except Exception:
            logger.error("%s(%s) 分析异常: %s", item["name"], code, traceback.format_exc())
            stale_result = _load_stale_result(code, item)
            analysis_results[code] = stale_result

        # 限流
        if i < len(watchlist) - 1:
            time.sleep(REQUEST_INTERVAL)

    # ---- 5.4 全部失败保护 ----
    success_count = sum(1 for v in analysis_results.values() if v is not None and not v.get("stale"))
    if success_count == 0:
        logger.error("所有标的分分析均失败！")
        if has_existing_data(ANALYSIS_DIR):
            logger.warning("保留分析目录旧数据，不覆盖")
        return 1

    # ---- 5.5 生成排名 ----
    logger.info("生成排行榜...")
    ranking = build_ranking(analysis_results, watchlist)
    generated_at = ranking["generated_at"]

    # ---- 5.6 校验 ranking ----
    errors = validate_ranking(ranking)
    if errors:
        for err in errors:
            logger.error("排名校验失败: %s", err)
    else:
        logger.info("排名 JSON 校验通过")

    # ---- 5.7 生成个股详情文件 ----
    logger.info("生成个股详情文件...")
    os.makedirs(ANALYSIS_DIR, exist_ok=True)

    for code, r in analysis_results.items():
        if r is None or r.get("stale"):
            continue  # 跳过 stale 的数据（保留上次文件）

        try:
            detail = build_stock_detail(r, generated_at)
            detail_errors = validate_stock_detail(detail)
            if detail_errors:
                logger.warning("%s 详情校验问题: %s", code, "; ".join(detail_errors))

            path = os.path.join(ANALYSIS_DIR, f"{code}.json")
            atomic_write_json(detail, path, logger)
            logger.info("  %s.json ✓", code)
        except Exception:
            logger.error("%s 写入详情文件失败: %s", code, traceback.format_exc())

    # ---- 5.8 写入 ranking.json ----
    logger.info("写入排行榜文件...")
    atomic_write_json(ranking, RANKING_PATH, logger)

    # ---- 5.9 汇总 ----
    elapsed = (beijing_now() - run_start).total_seconds()
    logger.info("=" * 60)
    logger.info("排行榜分析完成！总 %d / 成功 %d / 失败 %d / 耗时 %.1f 秒",
                ranking["total"], ranking["succeeded"], ranking["failed"], elapsed)
    logger.info("分析目录: %s", ANALYSIS_DIR)
    logger.info("=" * 60)

    if ranking["status"] == "failed":
        return 1
    return 0


def _read_watchlist_with_category(path: str) -> list[dict]:
    """读取 watchlist.csv 包含 category 列。"""
    import csv

    if not os.path.exists(path):
        return []

    items = []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return []
        reader.fieldnames = [h.strip() for h in reader.fieldnames]

        for row in reader:
            if not row or all(v.strip() == "" for v in row.values()):
                continue
            code = row.get("code", "").strip()
            if code.startswith("#") or not code:
                continue
            items.append({
                "code": code,
                "name": row.get("name", "").strip(),
                "type": row.get("type", "stock").strip().lower(),
                "category": row.get("category", "").strip(),
            })

    return items


def _load_stale_result(code: str, item: dict) -> Optional[dict]:
    """加载上次成功的分析结果并标记 stale。"""
    path = os.path.join(ANALYSIS_DIR, f"{code}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["stale"] = True
        data["code"] = code
        data["name"] = item.get("name", code)
        data["type"] = item.get("type", "stock")
        data["category"] = item.get("category", "")
        return data
    except Exception:
        return None


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    sys.exit(main())
