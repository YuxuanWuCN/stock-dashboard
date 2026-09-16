"""
Flask API 后端：实时查询个股 K 线 + 大盘指数 K 线对比数据

启动方式：python src/server.py
默认端口：5000
API: GET /api/query?code=<6位代码>&start_date=<YYYY-MM-DD>
"""

import json
import os
import sys
import traceback
from datetime import date, datetime, timedelta
from typing import Any, Optional, Union

# 确保 src/ 在 path 中，方便 import 同目录模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ---- 清除系统代理 ----
try:
    from .proxy import configure_proxy_from_system
except ImportError:  # Support direct execution from src/.
    from proxy import configure_proxy_from_system

configure_proxy_from_system()

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import akshare as ak
import pandas as pd
import requests as _requests

try:
    from .config import ADJUST, PERIOD, MA_WINDOWS, LOOKBACK_DAYS, OFFLINE_MODE, KLINE_DIR
    from .utils import setup_logging, validate_ohlcv, calc_ma, beijing_today
    from .fetch_data import fetch_one, compute_derived, build_kline_json
except ImportError:  # Support direct execution from src/.
    from config import ADJUST, PERIOD, MA_WINDOWS, LOOKBACK_DAYS, OFFLINE_MODE, KLINE_DIR
    from utils import setup_logging, validate_ohlcv, calc_ma, beijing_today
    from fetch_data import fetch_one, compute_derived, build_kline_json

logger = setup_logging()
app = Flask(__name__)

DOCS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "docs"))

DEFAULT_CORS_ORIGINS = (
    "https://yuxuanwucn.github.io",
    "http://127.0.0.1:5000",
    "http://localhost:5000",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1:8001",
    "http://localhost:8001",
)
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "CORS_ORIGINS", ",".join(DEFAULT_CORS_ORIGINS)
    ).split(",")
    if origin.strip()
]
WATCHLIST_WRITE_ENABLED = os.environ.get(
    "ALLOW_WATCHLIST_WRITE", "true"
).lower() in ("1", "true", "yes")

# ---- GitHub 自动入库配置（v2.5：网页加的自选股直接提交回仓库） ----
# GITHUB_TOKEN：GitHub Personal Access Token（仅需仓库 contents 读写权限）
# GITHUB_REPO：仓库名，格式 "owner/repo"，如 "yuxuanwucn/stock-dashboard"
# GITHUB_WATCHLIST_PATH：仓库内 watchlist.csv 路径，默认根目录
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_REPO = os.environ.get("GITHUB_REPO", "").strip()
GITHUB_WATCHLIST_PATH = os.environ.get("GITHUB_WATCHLIST_PATH", "watchlist.csv").strip()
GITHUB_SYNC_ENABLED = bool(GITHUB_TOKEN and GITHUB_REPO)

CORS(app, resources={r"/api/*": {"origins": ALLOWED_ORIGINS}})

# ============================================================
# 股票代码 → 大盘指数映射
# ============================================================

CODE_TO_INDEX: dict[str, dict] = {
    "6":   {"code": "000001", "name": "上证指数"},
    "0":   {"code": "399001", "name": "深证成指"},
    "3":   {"code": "399006", "name": "创业板指"},
    "688": {"code": "000688", "name": "科创50"},
}


def get_index_for_code(stock_code: str) -> dict:
    """根据股票代码首字符/前缀返回对应的指数信息。"""
    if stock_code.startswith("688"):
        return CODE_TO_INDEX["688"]
    first = stock_code[0]
    if first in CODE_TO_INDEX:
        return CODE_TO_INDEX[first]
    # 兜底：默认返回上证指数
    return CODE_TO_INDEX["6"]


# ============================================================
# 本地离线高保真缓存数据源 (166 只标的零依赖兜底)
# ============================================================

INDEX_OFFLINE_MAP: dict[str, str] = {
    "000688": "588000",  # 科创50 -> 科创50 ETF
    "000001": "510050",  # 上证指数 -> 上证50 ETF
    "399006": "159915",  # 创业板指 -> 创业板 ETF
    "399001": "159919",  # 深证成指 -> 深证300 ETF
}


def _get_offline_kline(code: str) -> Optional[dict]:
    """安全读取 docs/data/kline/{code}.json 离线缓存数据。"""
    cached_path = os.path.join(KLINE_DIR, f"{code}.json")
    if os.path.exists(cached_path):
        try:
            with open(cached_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and data.get("dates"):
                    return data
        except Exception as e:
            logger.warning("读取离线缓存失败 %s: %s", code, e)
    return None


def _get_offline_index(index_code: str, index_name: str) -> Optional[dict]:
    """安全读取大盘指数离线数据；若无直接指数文件则使用核心基准 ETF 映射。"""
    direct = _get_offline_kline(index_code)
    if direct is not None:
        return direct

    mapped_code = INDEX_OFFLINE_MAP.get(index_code)
    if mapped_code:
        mapped_data = _get_offline_kline(mapped_code)
        if mapped_data is not None:
            idx_copy = dict(mapped_data)
            idx_copy["name"] = index_name
            idx_copy["code"] = index_code
            idx_copy["is_fallback_benchmark"] = True
            return idx_copy
    return None


# ============================================================
# 指数数据抓取
# ============================================================

def fetch_index(
    index_code: str, index_name: str, start_date: str, end_date: str
) -> Optional[dict]:
    """抓取指数日线数据，返回与 build_kline_json 结构兼容的 dict。"""
    start_fmt = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
    end_fmt = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"

    df = None

    # 方法1：stock_zh_index_daily（上证/深证指数专用，返回全部历史再过滤）
    try:
        prefix = "sh" if index_code.startswith(("0", "6", "5", "9")) else "sz"
        df = ak.stock_zh_index_daily(symbol=f"{prefix}{index_code}")
        if df is not None and not df.empty:
            logger.info("指数 %s 使用 stock_zh_index_daily 成功", index_code)
    except Exception:
        logger.debug("stock_zh_index_daily 失败: %s", traceback.format_exc())

    # 方法2：stock_zh_a_hist（把指数当普通股票抓，部分指数可用）
    if df is None or df.empty:
        try:
            df = ak.stock_zh_a_hist(
                symbol=index_code,
                period=PERIOD,
                start_date=start_date,
                end_date=end_date,
                adjust="",  # 指数不复权
            )
            if df is not None and not df.empty:
                logger.info("指数 %s 使用 stock_zh_a_hist 成功", index_code)
        except Exception:
            logger.debug("stock_zh_a_hist 失败: %s", traceback.format_exc())

    if df is None or df.empty:
        logger.warning("指数 %s(%s) 所有接口均返回空", index_name, index_code)
        return None

    # ---- 统一列名映射 ----
    col_map = {
        "日期": "date", "开盘": "open", "收盘": "close",
        "最高": "high", "最低": "low", "成交量": "volume",
        "成交额": "amount",
    }
    df = df.rename(columns=col_map)

    # ---- 日期解析与过滤 ----
    if "date" not in df.columns:
        logger.warning("指数数据缺少日期列")
        return None

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df["date"] = df["date"].dt.date

    start_dt = date.fromisoformat(start_fmt)
    end_dt = date.fromisoformat(end_fmt)
    df = df[(df["date"] >= start_dt) & (df["date"] <= end_dt)]

    if df.empty:
        logger.warning("指数 %s 日期过滤后无数据", index_name)
        return None

    # 数值列转 float
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.sort_values("date").reset_index(drop=True)

    # ---- 构建 JSON 输出（与 build_kline_json 结构一致） ----
    dates = [d.isoformat() if isinstance(d, date) else str(d) for d in df["date"].tolist()]

    kline = []
    for _, row in df.iterrows():
        kline.append([
            round(float(row.get("open", 0) or 0), 2),
            round(float(row.get("close", 0) or 0), 2),
            round(float(row.get("low", 0) or 0), 2),
            round(float(row.get("high", 0) or 0), 2),
        ])

    volume = [
        int(row["volume"]) if pd.notna(row.get("volume")) else 0
        for _, row in df.iterrows()
    ]

    closes = [round(float(row["close"] or 0), 2) for _, row in df.iterrows()]
    ma_data: dict[str, list] = {}
    for w in MA_WINDOWS:
        ma_data[f"ma{w}"] = calc_ma(closes, w)

    return {
        "code": index_code,
        "name": index_name,
        "type": "index",
        "adjust": "",
        "dates": dates,
        "kline": kline,
        "volume": volume,
        "ma5": ma_data["ma5"],
        "ma10": ma_data["ma10"],
        "ma20": ma_data["ma20"],
        "ma60": ma_data["ma60"],
    }


# ============================================================
# 股票代码 → 名称 自动解析（腾讯行情接口，轻量快速）
# ============================================================

_STOCK_NAME_CACHE: dict[str, str] = {}


def resolve_stock_name(code: str) -> str:
    """根据 6 位股票代码自动查询真实名称（如 000021 → 深科技）。

    优先使用内存缓存；查询失败时返回代码本身，保证流程不中断。
    依次尝试腾讯行情接口与 akshare 东方财富接口，任一成功即返回。
    支持 A 股股票与场内 ETF。
    """
    code = (code or "").strip()
    if not code or not code.isdigit() or len(code) != 6:
        return code

    cached = _STOCK_NAME_CACHE.get(code)
    if cached:
        return cached

    # 根据代码前缀判断交易所：6/5/9 开头 → 上海，其余 → 深圳
    if code.startswith(("5", "6", "9")):
        prefix = "sh"
    else:
        prefix = "sz"

    name = _resolve_via_tencent(code, prefix)
    if name == code:
        name = _resolve_via_akshare(code)

    if name != code:
        _STOCK_NAME_CACHE[code] = name
        logger.info("解析股票名称: %s → %s", code, name)
    else:
        logger.warning("股票名称解析失败，回退为代码: %s", code)

    return name


def _resolve_via_tencent(code: str, prefix: str) -> str:
    """通过腾讯行情接口解析名称；失败时返回 code 本身。"""
    try:
        url = f"https://qt.gtimg.cn/q={prefix}{code}"
        resp = _requests.get(url, timeout=10)
        resp.encoding = "gbk"
        text = resp.text or ""
        # 腾讯行情返回格式: v_sz000021="51~深科技~000021~...~...";
        # 名称位于第 2 个字段（按 ~ 分割后下标 1）
        if '~' in text:
            parts = text.split("~")
            if len(parts) > 1 and parts[1].strip():
                candidate = parts[1].strip()
                # 过滤明显无效的占位（避免把代码当名称）
                if candidate.isdigit() is False:
                    return candidate
    except Exception:
        logger.debug("腾讯行情解析股票名称失败 %s: %s", code, traceback.format_exc())
    return code


def _resolve_via_akshare(code: str) -> str:
    """通过 akshare 东方财富接口解析名称；失败时返回 code 本身。"""
    try:
        info_df = ak.stock_individual_info_em(symbol=code)
        if info_df is not None and not info_df.empty:
            item_col = info_df.columns[0]
            val_col = info_df.columns[1]
            for _, row in info_df.iterrows():
                if str(row[item_col]).strip() == "股票简称":
                    candidate = str(row[val_col]).strip()
                    if candidate and candidate.isdigit() is False:
                        return candidate
    except Exception:
        logger.debug("akshare 解析股票名称失败 %s: %s", code, traceback.format_exc())
    return code


# ============================================================
# 自选股管理工具与自动入库
# ============================================================

import csv as _csv
import tempfile as _tempfile
_WATCHLIST_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "watchlist.csv")
_WATCHLIST_HEADER = ["code", "name", "type", "category"]


def _read_watchlist() -> list[dict]:
    items: list[dict] = []
    if not os.path.exists(_WATCHLIST_PATH):
        return items

    with open(_WATCHLIST_PATH, "r", encoding="utf-8-sig") as f:
        reader = _csv.DictReader(f)
        for row in reader:
            if not row or all((value or "").strip() == "" for value in row.values()):
                continue
            code = (row.get("code") or "").strip()
            if not code or code.startswith("#"):
                continue
            items.append({
                "code": code,
                "name": (row.get("name") or code).strip(),
                "type": (row.get("type") or "stock").strip().lower(),
                "category": (row.get("category") or "").strip(),
            })
    return items


def _auto_add_to_watchlist(code: str, name: str, typ: str = "stock", category: str = "搜索自选") -> bool:
    """自动将搜索查询的有效标的加入自选池，使其纳入每晚自动化深度分析流水线。"""
    try:
        existing = _read_watchlist()
        if any(row["code"] == code for row in existing):
            return False

        existing.append({"code": code, "name": name, "type": typ, "category": category})
        watchlist_path = _WATCHLIST_PATH
        os.makedirs(os.path.dirname(watchlist_path), exist_ok=True)
        fd, tmp_path = _tempfile.mkstemp(suffix=".csv", prefix=".tmp_", dir=os.path.dirname(watchlist_path) or ".", text=True)
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as f:
            writer = _csv.DictWriter(f, fieldnames=_WATCHLIST_HEADER, extrasaction="ignore")
            writer.writeheader()
            for row in existing:
                writer.writerow({k: row.get(k, "") for k in _WATCHLIST_HEADER})
        if os.path.exists(watchlist_path):
            os.replace(tmp_path, watchlist_path)
        else:
            os.rename(tmp_path, watchlist_path)
        logger.info("已自动将搜索标的加入自选池: %s(%s)", name, code)
        return True
    except Exception as e:
        logger.warning("自动加入自选池失败 %s: %s", code, e)
        return False


# ============================================================
# API 路由
# ============================================================

@app.route("/api/query", methods=["GET"])
def api_query():
    """查询个股 K 线 + 对应大盘指数 K 线对比数据。"""
    code = request.args.get("code", "").strip()
    start_date_str = request.args.get("start_date", "").strip()

    # ---- 参数校验 ----
    if not code or not code.isdigit() or len(code) != 6:
        return jsonify({"error": "股票代码格式不正确，请输入6位数字代码"}), 400

    if not start_date_str:
        today = beijing_today()
        start_date_str = (today - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    try:
        start_dt = date.fromisoformat(start_date_str)
    except ValueError:
        return jsonify({"error": f"日期格式不正确：{start_date_str}，请使用 YYYY-MM-DD 格式"}), 400

    today = beijing_today()
    if start_dt >= today:
        return jsonify({"error": "起始日期必须在今天之前"}), 400

    start_yyyymmdd = start_dt.strftime("%Y%m%d")
    end_yyyymmdd = today.strftime("%Y%m%d")

    logger.info(
        "查询请求: code=%s start=%s end=%s", code, start_yyyymmdd, end_yyyymmdd
    )

    # ---- 1. 抓取个股（在线 + 离线高弹性容灾） ----
    # 自动识别 ETF（代码以5/1开头），并自动解析真实名称
    if code.startswith(("5", "1")):
        stock_item = {"code": code, "name": resolve_stock_name(code), "type": "etf"}
    else:
        stock_item = {"code": code, "name": resolve_stock_name(code), "type": "stock"}

    stock_json = None
    offline_fallback_active = False

    # 若全局开启离线演示模式，直接优先读取离线预置数据
    if OFFLINE_MODE:
        offline_data = _get_offline_kline(code)
        if offline_data is not None:
            stock_json = offline_data
            offline_fallback_active = True
            logger.info("离线演示模式已激活: 标的 %s 直接读取本地离线数据", code)

    # 在线模式下，若尚未获取数据，尝试在线拉取
    if stock_json is None and not OFFLINE_MODE:
        try:
            df_stock = fetch_one(stock_item, start_yyyymmdd, end_yyyymmdd)
            if df_stock is not None and not df_stock.empty:
                df_stock = compute_derived(df_stock)
                stock_name = stock_item["name"]
                if "name" in df_stock.columns and not df_stock.empty:
                    candidate_name = str(df_stock.iloc[-1].get("name") or "").strip()
                    if candidate_name and candidate_name != code and not candidate_name.isdigit():
                        stock_name = candidate_name
                stock_item = {**stock_item, "name": stock_name}
                stock_json = build_kline_json(stock_item, df_stock)
                # 自动入库到自选池（供每晚 60日/5年 深度自动化分析）
                _auto_add_to_watchlist(code, stock_name, stock_item["type"])
        except Exception:
            logger.error("个股在线抓取异常:\n%s", traceback.format_exc())

    # 若在线抓取失败（无网络/API故障/返回 None），自动无缝降级回退至本地离线预置数据
    if stock_json is None:
        offline_data = _get_offline_kline(code)
        if offline_data is not None:
            stock_json = offline_data
            offline_fallback_active = True
            logger.info("在线抓取不可用，已自动优雅降级为离线预置数据: %s(%s)", stock_json.get("name"), code)

    # 若离线与在线均未找到数据，返回友好提示
    if stock_json is None:
        return jsonify({
            "error": f"未找到股票代码 {code} 的数据（离线缓存未覆盖该代码，且实时行情接口不可用）。\n"
                     f"本地离线演示模式支持 166 只核心标的（如 688525 佰维存储、600519 贵州茅台、300750 宁德时代、510300 沪深300ETF 等）。"
        }), 404

    stock_name = stock_json.get("name") or stock_item["name"]

    # ---- 2. 抓取对应大盘指数 (具备离线弹性容灾) ----
    index_info = get_index_for_code(code)
    index_json = None

    if not OFFLINE_MODE and not offline_fallback_active:
        try:
            index_json = fetch_index(
                index_info["code"], index_info["name"],
                start_yyyymmdd, end_yyyymmdd,
            )
        except Exception as e:
            logger.warning("指数在线抓取异常: %s", e)

    if index_json is None:
        index_json = _get_offline_index(index_info["code"], index_info["name"])

    # ---- 3. 组装返回 ----
    dates = stock_json.get("dates", [])
    s_date = dates[0] if (dates and offline_fallback_active) else start_dt.isoformat()
    e_date = dates[-1] if (dates and offline_fallback_active) else today.isoformat()

    result = {
        "stock": stock_json,
        "index": index_json,
        "meta": {
            "start_date": s_date,
            "end_date": e_date,
            "stock_name": stock_name,
            "stock_code": code,
            "index_name": index_info["name"],
            "index_code": index_info["code"],
            "auto_enqueued_nightly": not offline_fallback_active,
            "offline_demo": offline_fallback_active,
            "message": (
                f"已启用离线演示模式，展示本地预置历史行情（共 {len(dates)} 个交易日）。"
                if offline_fallback_active
                else "实时行情已成功拉取，并已排期每晚自动化分析。"
            ),
        },
    }

    logger.info("查询成功 [%s]: %s(%s) + %s",
                "离线演示" if offline_fallback_active else "在线实时",
                stock_name, code, index_info["name"])
    return jsonify(result), 200


@app.route("/")
def index():
    if request.args.get("format") == "json" or (
        request.headers.get("Accept") == "application/json"
        and not request.accept_mimetypes.accept_html
    ):
        return jsonify({
            "message": "🏠 股票看板 API 已就绪",
            "usage": "GET /api/query?code=<6位代码>&start_date=<YYYY-MM-DD>",
            "example": "/api/query?code=600519&start_date=2025-07-01",
        })
    index_file = os.path.join(DOCS_DIR, "index.html")
    if os.path.isfile(index_file):
        return send_from_directory(DOCS_DIR, "index.html")
    return jsonify({
        "message": "🏠 股票看板 API 已就绪",
        "usage": "GET /api/query?code=<6位代码>&start_date=<YYYY-MM-DD>",
        "example": "/api/query?code=600519&start_date=2025-07-01",
    })


@app.route("/api/health")
def api_health():
    return jsonify({
        "status": "ok",
        "service": "stock-dashboard-api",
        "watchlist_write_enabled": WATCHLIST_WRITE_ENABLED,
    })





@app.route("/api/watchlist")
def api_watchlist():
    """Return configured symbols so the frontend can show newly added rows."""
    return jsonify({
        "items": _read_watchlist(),
        "write_enabled": WATCHLIST_WRITE_ENABLED,
    })


@app.route("/api/watchlist/add", methods=["POST"])
def api_watchlist_add():
    """添加/更新自选股列表。已存在的 code 会更新 name/type/category。

    配置了 GITHUB_TOKEN/GITHUB_REPO 时，会通过 GitHub Contents API
    把最新列表提交回仓库（v2.5 自动入库），使新自选股参与每日自动分析。
    """
    if not WATCHLIST_WRITE_ENABLED:
        return jsonify({
            "error": "线上服务不直接修改仓库文件，请使用网页中的 CSV 下载功能"
        }), 503

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "请求体格式不正确，需要 JSON"}), 400

    code = (data.get("code") or "").strip()
    name = (data.get("name") or "").strip()
    typ = (data.get("type") or "stock").strip().lower()
    category = (data.get("category") or "").strip()

    # ---- 校验 ----
    if not code or not code.isdigit() or len(code) != 6:
        return jsonify({"error": "股票代码格式不正确"}), 400

    # 名称未填写时，自动从行情接口解析真实名称（如 000021 → 深科技）
    if not name or name == code:
        name = resolve_stock_name(code)
    if not name:
        return jsonify({"error": "股票名称不能为空"}), 400
    if typ not in ("stock", "etf"):
        typ = "stock"

    logger.info("添加自选股: %s(%s) type=%s category=%s", name, code, typ, category)

    # ---- 读取现有 watchlist ----
    existing = _read_watchlist()
    found = False
    watchlist_path = _WATCHLIST_PATH

    for index, row in enumerate(existing):
        if row["code"] == code:
            existing[index] = {
                "code": code,
                "name": name,
                "type": typ,
                "category": category,
            }
            found = True
            break

    if not found:
        existing.append({"code": code, "name": name, "type": typ, "category": category})

    # ---- 原子写入 ----
    os.makedirs(os.path.dirname(watchlist_path), exist_ok=True)
    fd, tmp_path = _tempfile.mkstemp(suffix=".csv", prefix=".tmp_", dir=os.path.dirname(watchlist_path) or ".", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as f:
            writer = _csv.DictWriter(f, fieldnames=_WATCHLIST_HEADER, extrasaction="ignore")
            writer.writeheader()
            for row in existing:
                writer.writerow({k: row.get(k, "") for k in _WATCHLIST_HEADER})
        if os.path.exists(watchlist_path):
            os.replace(tmp_path, watchlist_path)
        else:
            os.rename(tmp_path, watchlist_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise

    action = "updated" if found else "added"
    logger.info("自选股 %s %s: %s(%s)", code, action, name, category)

    # ---- v2.5：同步提交 GitHub 仓库（自动入库） ----
    if GITHUB_SYNC_ENABLED:
        github_sync = _sync_watchlist_to_github(existing)
        if not github_sync.get("success"):
            logger.warning("GitHub 自选股同步失败: %s", github_sync.get("error"))
    else:
        github_sync = {"success": False, "error": "github_sync_not_configured"}

    return jsonify({
        "success": True,
        "action": action,
        "item": {"code": code, "name": name, "type": typ, "category": category},
        "items": existing,
        "github_sync": github_sync,
    })


def _sync_watchlist_to_github(rows: list[dict]) -> dict:
    """通过 GitHub Contents API 把最新自选股列表提交回仓库。

    用 GET 读取当前文件 SHA，再 PUT 提交（避免覆盖他人并发修改）。
    返回 {"success": bool, "commit_sha": 或 "error": ...}
    """
    if not GITHUB_SYNC_ENABLED:
        return {"success": False, "error": "github_sync_not_configured"}

    import io

    buf = io.StringIO()
    writer = _csv.DictWriter(buf, fieldnames=_WATCHLIST_HEADER, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in _WATCHLIST_HEADER})
    content = buf.getvalue()

    api = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_WATCHLIST_PATH}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    # 先读现有 SHA
    sha = None
    try:
        get_resp = _requests.get(api, headers=headers, timeout=15)
        if get_resp.status_code == 200:
            sha = get_resp.json().get("sha")
        elif get_resp.status_code != 404:
            return {"success": False, "error": f"read_failed:{get_resp.status_code}"}
    except Exception as exc:
        return {"success": False, "error": f"read_exception:{exc.__class__.__name__}"}

    import base64

    payload = {
        "message": f"chore(watchlist): update watchlist ({len(rows)} items)",
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
    }
    if sha:
        payload["sha"] = sha
    try:
        put_resp = _requests.put(api, json=payload, headers=headers, timeout=30)
        if put_resp.status_code in (200, 201):
            commit_sha = put_resp.json().get("commit", {}).get("sha", "")
            logger.info("GitHub 自选股已同步，commit=%s", commit_sha[:12])
            return {"success": True, "commit_sha": commit_sha}
        return {"success": False, "error": f"write_failed:{put_resp.status_code}"}
    except Exception as exc:
        return {"success": False, "error": f"write_exception:{exc.__class__.__name__}"}


# ============================================================
# 系统可视化配置中心与 API 密钥管理 (C 端开箱即用)
# ============================================================

import tempfile
import threading
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE_PATH = os.path.join(BASE_DIR, ".env")
ENV_EXAMPLE_FILE_PATH = os.path.join(BASE_DIR, ".env.example")
_ENV_PATH = ENV_FILE_PATH

MANAGED_CONFIG_KEYS = [
    "OFFLINE_MODE", "DEMO_MODE", "LLM_ENABLED", "LLM_BACKEND",
    "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL",
    "DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL", "DASHSCOPE_MODEL",
    "GEMINI_API_KEY", "GOOGLE_GEMINI_BASE_URL", "GEMINI_MODEL",
    "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL",
    "TUSHARE_TOKEN", "DAILY_UPDATE_ENABLED", "DAILY_UPDATE_TIME",
]


def _mask_secret(secret: Optional[str]) -> str:
    """脱敏敏感密钥，保留前 3 位和后 4 位，如 sk-••••••••cdef。"""
    if not secret:
        return ""
    secret = str(secret).strip()
    if len(secret) <= 8:
        return "••••••••"
    prefix = secret[:3]
    suffix = secret[-4:]
    return f"{prefix}••••••••{suffix}"


def _read_env_dict(path: Optional[Any] = None) -> dict[str, str]:
    """读取 .env 文件中的键值字典。"""
    res = {}
    target = str(path or _ENV_PATH or ENV_FILE_PATH)
    path_to_read = target if os.path.exists(target) else ENV_EXAMPLE_FILE_PATH
    if os.path.exists(path_to_read):
        try:
            with open(path_to_read, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    res[k.strip()] = v.strip().strip("'\"")
        except Exception as e:
            logger.warning("读取环境配置文件异常: %s", e)
    return res


def _save_env_dict(updates: dict[str, str], path: Optional[Any] = None) -> bool:
    """安全原子写入 .env 文件，并同步热更新当前进程环境变量。"""
    target = str(path or _ENV_PATH or ENV_FILE_PATH)
    # 忽略包含掩码 •••• 的值，避免把真实密钥覆写成掩码
    filtered_updates = {
        k: str(v) for k, v in updates.items()
        if "••••" not in str(v)
    }

    lines = []
    seen_keys = set()
    source_path = target if os.path.exists(target) else ENV_EXAMPLE_FILE_PATH

    if os.path.exists(source_path):
        with open(source_path, "r", encoding="utf-8") as f:
            for raw_line in f:
                stripped = raw_line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    k, _ = stripped.split("=", 1)
                    k = k.strip()
                    if k in filtered_updates:
                        new_val = filtered_updates[k]
                        lines.append(f"{k}={new_val}\n")
                        seen_keys.add(k)
                        continue
                lines.append(raw_line)

    for k, v in filtered_updates.items():
        if k not in seen_keys:
            lines.append(f"{k}={v}\n")

    # 原子写入
    dir_name = os.path.dirname(target) or "."
    fd, tmp_file = tempfile.mkstemp(suffix=".env.tmp", dir=dir_name, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.writelines(lines)
        if os.path.exists(target):
            os.replace(tmp_file, target)
        else:
            os.rename(tmp_file, target)
    except Exception as exc:
        if os.path.exists(tmp_file):
            os.remove(tmp_file)
        logger.error("写入 .env 异常: %s", exc)
        return False

    # 热重载当前环境变量
    global OFFLINE_MODE
    for k, v in filtered_updates.items():
        os.environ[k] = str(v)
    if "OFFLINE_MODE" in filtered_updates:
        OFFLINE_MODE = filtered_updates["OFFLINE_MODE"].lower() in ("1", "true", "yes")

    logger.info("系统环境变量与 .env 配置已热重载生效")
    return True


@app.route("/api/config", methods=["GET"])
def api_get_config():
    """获取当前系统 API 与运行配置状态 (敏感 Key 自动脱敏)。"""
    env_dict = _read_env_dict()
    merged = {**env_dict, **{k: os.environ[k] for k in MANAGED_CONFIG_KEYS if k in os.environ}}

    deepseek_key = merged.get("DEEPSEEK_API_KEY", "").strip()
    dashscope_key = merged.get("DASHSCOPE_API_KEY", "").strip()
    gemini_key = merged.get("GEMINI_API_KEY", "").strip()
    openai_key = merged.get("OPENAI_API_KEY", "").strip()
    tushare_token = merged.get("TUSHARE_TOKEN", "").strip()

    active_provider = (merged.get("LLM_BACKEND") or "deepseek").strip().lower()
    provider_map = {
        "deepseek": (deepseek_key, merged.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"), merged.get("DEEPSEEK_MODEL", "deepseek-chat")),
        "dashscope": (dashscope_key, merged.get("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"), merged.get("DASHSCOPE_MODEL", "qwen-plus")),
        "gemini": (gemini_key, merged.get("GOOGLE_GEMINI_BASE_URL", "https://uuapi.shop/v1"), merged.get("GEMINI_MODEL", "gemini-1.5-flash")),
        "openai": (openai_key, merged.get("OPENAI_BASE_URL", "https://api.openai.com/v1"), merged.get("OPENAI_MODEL", "gpt-4o-mini")),
    }
    cur_info = provider_map.get(active_provider, (deepseek_key, "https://api.deepseek.com/v1", "deepseek-chat"))

    data = {
        "status": "ok",
        "success": True,
        "provider": active_provider,
        "api_key": _mask_secret(cur_info[0]),
        "has_api_key": bool(cur_info[0]),
        "base_url": cur_info[1],
        "model": cur_info[2],
        "offline_mode": OFFLINE_MODE or merged.get("OFFLINE_MODE", "false").lower() in ("1", "true", "yes"),
        "scheduler_enabled": merged.get("DAILY_UPDATE_ENABLED", "true").lower() in ("1", "true", "yes"),
        "llm_enabled": merged.get("LLM_ENABLED", "true").lower() in ("1", "true", "yes"),
        "llm_backend": active_provider,
        # DeepSeek
        "has_deepseek_key": bool(deepseek_key),
        "deepseek_key_masked": _mask_secret(deepseek_key),
        "deepseek_base_url": merged.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        "deepseek_model": merged.get("DEEPSEEK_MODEL", "deepseek-chat"),
        # DashScope / 通义千问
        "has_dashscope_key": bool(dashscope_key),
        "dashscope_key_masked": _mask_secret(dashscope_key),
        "dashscope_base_url": merged.get("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        "dashscope_model": merged.get("DASHSCOPE_MODEL", "qwen-plus"),
        # Gemini
        "has_gemini_key": bool(gemini_key),
        "gemini_key_masked": _mask_secret(gemini_key),
        "gemini_base_url": merged.get("GOOGLE_GEMINI_BASE_URL", "https://uuapi.shop/v1"),
        "gemini_model": merged.get("GEMINI_MODEL", "gemini-1.5-flash"),
        # OpenAI
        "has_openai_key": bool(openai_key),
        "openai_key_masked": _mask_secret(openai_key),
        "openai_base_url": merged.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        "openai_model": merged.get("OPENAI_MODEL", "gpt-4o-mini"),
        # Tushare
        "has_tushare_token": bool(tushare_token),
        "tushare_token_masked": _mask_secret(tushare_token),
        # 每日更新
        "daily_update_enabled": merged.get("DAILY_UPDATE_ENABLED", "true").lower() in ("1", "true", "yes"),
        "daily_update_time": merged.get("DAILY_UPDATE_TIME", "17:30"),
        "env_file_exists": os.path.exists(_ENV_PATH or ENV_FILE_PATH),
    }
    return jsonify({**data, "config": data})


@app.route("/api/config", methods=["POST"])
def api_save_config():
    """保存用户在前端修改的 API 密钥及系统配置。"""
    payload = request.get_json(silent=True) or {}
    updates = {}

    provider = (payload.get("provider") or payload.get("llm_backend") or "deepseek").strip().lower()
    if "provider" in payload or "llm_backend" in payload:
        updates["LLM_BACKEND"] = provider

    def _resolve_val(field_key: str, env_key: str):
        if field_key in payload:
            raw_v = str(payload[field_key]).strip()
            if "••••" in raw_v:
                return
            updates[env_key] = raw_v

    # 通用 api_key / model / base_url 对应选定的 provider
    if "api_key" in payload:
        key_env_map = {
            "deepseek": "DEEPSEEK_API_KEY",
            "dashscope": "DASHSCOPE_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "openai": "OPENAI_API_KEY",
        }
        target_key_env = key_env_map.get(provider, "DEEPSEEK_API_KEY")
        raw_key = str(payload["api_key"]).strip()
        if "••••" not in raw_key and raw_key:
            updates[target_key_env] = raw_key

    if "model" in payload:
        model_env_map = {
            "deepseek": "DEEPSEEK_MODEL",
            "dashscope": "DASHSCOPE_MODEL",
            "gemini": "GEMINI_MODEL",
            "openai": "OPENAI_MODEL",
        }
        target_model_env = model_env_map.get(provider, "DEEPSEEK_MODEL")
        raw_model = str(payload["model"]).strip()
        if raw_model:
            updates[target_model_env] = raw_model
            updates["LLM_MODEL"] = raw_model

    if "base_url" in payload:
        url_env_map = {
            "deepseek": "DEEPSEEK_BASE_URL",
            "dashscope": "DASHSCOPE_BASE_URL",
            "gemini": "GOOGLE_GEMINI_BASE_URL",
            "openai": "OPENAI_BASE_URL",
        }
        target_url_env = url_env_map.get(provider, "DEEPSEEK_BASE_URL")
        raw_url = str(payload["base_url"]).strip()
        if raw_url:
            updates[target_url_env] = raw_url

    if "offline_mode" in payload:
        updates["OFFLINE_MODE"] = "true" if payload["offline_mode"] else "false"
        updates["DEMO_MODE"] = updates["OFFLINE_MODE"]
    if "llm_enabled" in payload:
        updates["LLM_ENABLED"] = "true" if payload["llm_enabled"] else "false"
    if "scheduler_enabled" in payload or "daily_update_enabled" in payload:
        flag = payload.get("scheduler_enabled", payload.get("daily_update_enabled"))
        updates["DAILY_UPDATE_ENABLED"] = "true" if flag else "false"
    if "daily_update_time" in payload:
        updates["DAILY_UPDATE_TIME"] = str(payload["daily_update_time"]).strip()

    # 兼容特定字段名称
    _resolve_val("deepseek_api_key", "DEEPSEEK_API_KEY")
    _resolve_val("deepseek_base_url", "DEEPSEEK_BASE_URL")
    _resolve_val("deepseek_model", "DEEPSEEK_MODEL")
    _resolve_val("dashscope_api_key", "DASHSCOPE_API_KEY")
    _resolve_val("dashscope_base_url", "DASHSCOPE_BASE_URL")
    _resolve_val("dashscope_model", "DASHSCOPE_MODEL")
    _resolve_val("gemini_api_key", "GEMINI_API_KEY")
    _resolve_val("gemini_base_url", "GOOGLE_GEMINI_BASE_URL")
    _resolve_val("gemini_model", "GEMINI_MODEL")
    _resolve_val("openai_api_key", "OPENAI_API_KEY")
    _resolve_val("openai_base_url", "OPENAI_BASE_URL")
    _resolve_val("openai_model", "OPENAI_MODEL")
    _resolve_val("tushare_token", "TUSHARE_TOKEN")

    ok = _save_env_dict(updates)
    if ok:
        return jsonify({
            "status": "ok",
            "success": True,
            "message": "配置已成功保存并立即热生效！",
            "updated_keys": list(updates.keys()),
        }), 200
    return jsonify({"status": "error", "success": False, "error": "保存配置文件失败"}), 500


@app.route("/api/config/test", methods=["POST"])
def api_test_connectivity():
    """实时测试指定大模型供应商/API密钥的网络连通性。"""
    payload = request.get_json(silent=True) or {}
    provider = (payload.get("provider") or "deepseek").strip().lower()
    api_key = (payload.get("api_key") or "").strip()
    base_url = (payload.get("base_url") or "").strip()
    model = (payload.get("model") or "").strip()

    # 若输入包含掩码，读取实际环境已配置的 key
    if "••••" in api_key or not api_key:
        env_key_map = {
            "deepseek": "DEEPSEEK_API_KEY",
            "dashscope": "DASHSCOPE_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "openai": "OPENAI_API_KEY",
        }
        target_env = env_key_map.get(provider, "DEEPSEEK_API_KEY")
        api_key = os.environ.get(target_env) or _read_env_dict().get(target_env, "")

    if not api_key:
        return jsonify({
            "status": "error",
            "success": False,
            "error": f"请先输入 {provider.upper()} 的 API 密钥后再测试连通性",
        }), 200

    # 默认 URL 回退
    default_urls = {
        "deepseek": "https://api.deepseek.com/v1",
        "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "gemini": "https://uuapi.shop/v1",
        "openai": "https://api.openai.com/v1",
    }
    if not base_url:
        base_url = default_urls.get(provider, "https://api.deepseek.com/v1")

    base_url = base_url.rstrip("/")
    test_endpoint = f"{base_url}/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    test_model = model or ("deepseek-chat" if provider == "deepseek" else ("qwen-turbo" if provider == "dashscope" else "gpt-4o-mini"))
    test_body = {
        "model": test_model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 5,
    }

    start_t = time.monotonic()
    try:
        resp = _requests.post(test_endpoint, json=test_body, headers=headers, timeout=10.0)
        elapsed_ms = int((time.monotonic() - start_t) * 1000)

        if resp.status_code == 200:
            return jsonify({
                "status": "ok",
                "success": True,
                "message": f"✓ 连通成功！{provider.upper()} API 响应正常",
                "latency_ms": elapsed_ms,
                "model": test_model,
            }), 200
        elif resp.status_code in (401, 403):
            return jsonify({
                "status": "error",
                "success": False,
                "error": f"认证失败 (HTTP {resp.status_code})：API Key 无效或未开通相应权限",
                "latency_ms": elapsed_ms,
            }), 200
        elif resp.status_code == 404:
            return jsonify({
                "status": "error",
                "success": False,
                "error": f"模型或端点未找到 (404)：请检查 Base URL 与 Model 名称是否正确",
                "latency_ms": elapsed_ms,
            }), 200
        else:
            return jsonify({
                "status": "error",
                "success": False,
                "error": f"服务返回异常状态码 {resp.status_code}: {resp.text[:120]}",
                "latency_ms": elapsed_ms,
            }), 200
    except _requests.exceptions.Timeout:
        return jsonify({
            "status": "error",
            "success": False,
            "error": "连接超时 (10秒)：请检查网络代理设置或该供应商服务可用性",
        }), 200
    except Exception as e:
        return jsonify({
            "status": "error",
            "success": False,
            "error": f"网络请求失败: {str(e)}",
        }), 200


# ============================================================
# 每日自主更新调度引擎 (DailyAutoScheduler)
# ============================================================

class DailyAutoScheduler:
    """全自动每日行情数据与策略自主更新调度器。"""

    def __init__(self):
        self.is_updating = False
        self.last_update_time = None
        self.last_update_date = None
        self.last_status = "idle"
        self.progress_pct = 0
        self.current_step = "待命"
        self.logs = []
        self._lock = threading.Lock()
        self._thread = None
        self._stop_event = threading.Event()
        self._load_cached_meta()

    def _load_cached_meta(self):
        summary_file = os.path.join(BASE_DIR, "docs", "data", "summary.json")
        if os.path.exists(summary_file):
            try:
                with open(summary_file, "r", encoding="utf-8") as f:
                    sdata = json.load(f)
                    items = sdata.get("items", [])
                    if items:
                        self.last_update_date = items[0].get("last_date")
                        self.last_update_time = f"{self.last_update_date} (已入库)"
                        self.last_status = "success"
            except Exception:
                pass

    def add_log(self, msg: str):
        stamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{stamp}] {msg}"
        self.logs.append(line)
        if len(self.logs) > 100:
            self.logs = self.logs[-100:]
        logger.info(f"[AutoScheduler] {msg}")

    def trigger_update_now(self, trigger_reason: str = "manual") -> bool:
        """公有触发方法，供 API 或外部调用。"""
        return self.run_update_job(trigger_reason)

    def run_update_job(self, trigger_reason: str = "manual") -> bool:
        with self._lock:
            if self.is_updating:
                return False
            self.is_updating = True
            self.last_status = "running"
            self.progress_pct = 5
            self.current_step = f"正在启动更新流程 ({trigger_reason})..."
            self.logs.clear()

        def _worker():
            try:
                self.add_log(f"开始执行每日自主更新流水线 (触发原因: {trigger_reason})")
                self.progress_pct = 20
                self.current_step = "正在拉取全市场自选股最新行情与K线数据..."

                # 异步调用 fetch_data
                try:
                    from .fetch_data import main as fetch_main
                except ImportError:
                    from fetch_data import main as fetch_main

                self.add_log("调用 fetch_data 模块刷新 166 支标的行情...")
                code = fetch_main()

                if code == 0:
                    self.progress_pct = 80
                    self.current_step = "正在刷新行情摘要与市场指标缓存..."
                    self._load_cached_meta()
                    self.last_update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    self.last_status = "success"
                    self.progress_pct = 100
                    self.current_step = "✓ 今日数据已全部成功更新并入库"
                    self.add_log("每日自主更新任务圆满完成，看板数据已刷新！")
                else:
                    self.last_status = "failed"
                    self.current_step = f"更新流程异常退出 (退出码: {code})"
                    self.add_log(f"警告：fetch_data 返回异常码 {code}")
            except Exception as exc:
                self.last_status = "failed"
                self.current_step = f"更新失败: {str(exc)}"
                self.add_log(f"异常: {traceback.format_exc()}")
            finally:
                with self._lock:
                    self.is_updating = False

        t = threading.Thread(target=_worker, daemon=True, name="daily-update-worker")
        t.start()
        return True

    def _compute_next_run_time(self) -> datetime:
        target_time_str = os.environ.get("DAILY_UPDATE_TIME", "17:30").strip()
        try:
            th, tm = [int(x) for x in target_time_str.split(":")]
        except Exception:
            th, tm = 17, 30

        now = datetime.now()
        target = now.replace(hour=th, minute=tm, second=0, microsecond=0)
        if now >= target or now.weekday() >= 5:
            days_ahead = 1
            cand = now + timedelta(days=days_ahead)
            while cand.weekday() >= 5:  # 跳过周末
                days_ahead += 1
                cand = now + timedelta(days=days_ahead)
            target = cand.replace(hour=th, minute=tm, second=0, microsecond=0)
        return target

    def calculate_next_scheduled_time(self) -> str:
        return self._compute_next_run_time().strftime("%Y-%m-%d %H:%M:%S")

    def _loop(self):
        logger.info("DailyAutoScheduler 后台守护调度线程已启动")
        time.sleep(8)
        try:
            self._check_stale_data_on_startup()
        except Exception as e:
            logger.warning("开机自检陈旧数据异常: %s", e)

        while not self._stop_event.is_set():
            time.sleep(30)
            enabled = os.environ.get("DAILY_UPDATE_ENABLED", "true").lower() in ("1", "true", "yes")
            if not enabled or self.is_updating:
                continue

            now = datetime.now()
            if now.weekday() >= 5:
                continue

            target_time_str = os.environ.get("DAILY_UPDATE_TIME", "17:30").strip()
            try:
                th, tm = [int(x) for x in target_time_str.split(":")]
            except Exception:
                th, tm = 17, 30

            if now.hour == th and now.minute == tm:
                today_str = now.strftime("%Y-%m-%d")
                if self.last_update_date != today_str:
                    logger.info(f"到达每日自动更新时间 {target_time_str}，正在触发自动更新...")
                    self.run_update_job("daily_auto_cron")
                    time.sleep(65)

    def _check_stale_data_on_startup(self):
        """开机自检：若当前已是工作日收盘后(16:00以后)，但数据仍为过去日期，自动静默补漏。"""
        now = datetime.now()
        if now.weekday() < 5 and now.hour >= 16:
            today_str = now.strftime("%Y-%m-%d")
            if self.last_update_date and self.last_update_date < today_str:
                logger.info(f"开机检测发现当前已收盘但数据仍为 {self.last_update_date}，正在自动拉取补漏...")
                self.run_update_job("startup_catchup")

    def start(self):
        if self._thread is None or not self._thread.is_alive():
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True, name="daily-scheduler-daemon")
            self._thread.start()

    def stop(self):
        self._stop_event.set()


# 全局单例调度器与别名
scheduler = DailyAutoScheduler()
daily_scheduler = scheduler


@app.route("/api/system/update-status", methods=["GET"])
def api_update_status():
    """获取每日自主更新与调度状态。"""
    enabled = os.environ.get("DAILY_UPDATE_ENABLED", "true").lower() in ("1", "true", "yes")
    return jsonify({
        "status": "ok",
        "success": True,
        "is_running": scheduler.is_updating,
        "is_updating": scheduler.is_updating,
        "last_update_time": scheduler.last_update_time,
        "last_update_date": scheduler.last_update_date,
        "last_status": scheduler.last_status,
        "progress_pct": scheduler.progress_pct,
        "current_stage": scheduler.current_step,
        "current_step": scheduler.current_step,
        "recent_logs": scheduler.logs,
        "logs": scheduler.logs,
        "daily_update_enabled": enabled,
        "next_scheduled_time": scheduler.calculate_next_scheduled_time(),
    })


@app.route("/api/system/run-update", methods=["POST"])
def api_trigger_update():
    """手动立即触发每日行情数据更新。"""
    if scheduler.is_updating:
        return jsonify({
            "status": "busy",
            "success": False,
            "error": "更新任务正在后台运行中，请勿重复触发",
        }), 409

    ok = scheduler.trigger_update_now("manual_web_click")
    if ok:
        return jsonify({
            "status": "ok",
            "success": True,
            "message": "已在后台启动每日行情更新流水线，请关注控制台进度",
        }), 200
    return jsonify({"status": "error", "success": False, "error": "启动更新任务失败"}), 500


# ============================================================
# 前端静态看板托管路由
# ============================================================

@app.route("/portfolio.html")
def serve_portfolio():
    """托管量化组合实盘看板页面。"""
    return send_from_directory(DOCS_DIR, "portfolio.html")


@app.route("/<path:filename>")
def serve_static(filename):
    """托管 docs 目录下的前端静态资源（JS/CSS/JSON等）。"""
    if filename.startswith("api/"):
        return jsonify({"status": "error", "error": "API route not found"}), 404
    file_path = os.path.join(DOCS_DIR, filename)
    if os.path.isfile(file_path):
        return send_from_directory(DOCS_DIR, filename)
    return jsonify({"status": "error", "error": "Not Found"}), 404


# 启动后台调度守护线程
try:
    scheduler.start()
except Exception as _sch_e:
    logger.warning("启动后台自动更新调度器异常: %s", _sch_e)



# ============================================================
# 启动入口
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("API_PORT") or os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() in (
        "1", "true", "yes"
    )
    logger.info("=" * 50)
    logger.info("🏠 股票看板 API 与前端服务启动中...")
    logger.info("智能看板主页: http://127.0.0.1:%d/", port)
    logger.info("量化组合实盘: http://127.0.0.1:%d/portfolio.html", port)
    logger.info("访问 http://127.0.0.1:%d/api/health 确认服务状态", port)
    logger.info("=" * 50)
    app.run(host="0.0.0.0", port=port, debug=debug)
