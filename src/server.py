"""
Flask API 后端：实时查询个股 K 线 + 大盘指数 K 线对比数据

启动方式：python src/server.py
默认端口：5000
API: GET /api/query?code=<6位代码>&start_date=<YYYY-MM-DD>
"""

import os
import sys
import traceback
from datetime import date, datetime, timedelta
from typing import Optional

# 确保 src/ 在 path 中，方便 import 同目录模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ---- 清除系统代理 ----
for _key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
             "ALL_PROXY", "all_proxy", "FTP_PROXY", "ftp_proxy"):
    os.environ.pop(_key, None)
os.environ["NO_PROXY"] = "*"

import requests as _requests

_orig_init = _requests.Session.__init__


def _patched_session_init(self, *args, **kwargs):
    _orig_init(self, *args, **kwargs)
    self.trust_env = False


_requests.Session.__init__ = _patched_session_init  # type: ignore[method-assign]

from flask import Flask, request, jsonify
from flask_cors import CORS
import akshare as ak
import pandas as pd

try:
    from .config import ADJUST, PERIOD, MA_WINDOWS, LOOKBACK_DAYS
    from .utils import setup_logging, validate_ohlcv, calc_ma, beijing_today
    from .fetch_data import fetch_one, compute_derived, build_kline_json
except ImportError:  # Support direct execution from src/.
    from config import ADJUST, PERIOD, MA_WINDOWS, LOOKBACK_DAYS
    from utils import setup_logging, validate_ohlcv, calc_ma, beijing_today
    from fetch_data import fetch_one, compute_derived, build_kline_json

logger = setup_logging()
app = Flask(__name__)

DEFAULT_CORS_ORIGINS = (
    "https://yuxuanwucn.github.io",
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

    # ---- 1. 抓取个股 ----
    # 自动识别 ETF（代码以5/1开头）
    if code.startswith(("5", "1")):
        stock_item = {"code": code, "name": code, "type": "etf"}
    else:
        stock_item = {"code": code, "name": code, "type": "stock"}

    try:
        df_stock = fetch_one(stock_item, start_yyyymmdd, end_yyyymmdd)
    except Exception:
        logger.error("个股抓取异常:\n%s", traceback.format_exc())
        return jsonify({"error": f"个股 {code} 数据抓取时发生内部错误，请稍后重试"}), 500

    if df_stock is None:
        return jsonify({
            "error": f"未找到股票代码 {code} 的数据。请检查：\n"
                     f"1. 代码是否为6位数字\n"
                     f"2. 该代码是否有效（非退市/非新三板股票）\n"
                     f"3. 网络是否正常"
        }), 404

    df_stock = compute_derived(df_stock)
    stock_json = build_kline_json(stock_item, df_stock)

    # 尝试从数据中获取更多信息
    stock_name = stock_item["name"]
    if "name" in df_stock.columns and df_stock.iloc[-1].get("name"):
        stock_name = str(df_stock.iloc[-1]["name"])

    # ---- 2. 抓取对应大盘指数 ----
    index_info = get_index_for_code(code)
    index_json = fetch_index(
        index_info["code"], index_info["name"],
        start_yyyymmdd, end_yyyymmdd,
    )

    if index_json is None:
        logger.warning(
            "指数 %s(%s) 抓取失败", index_info["name"], index_info["code"]
        )

    # ---- 3. 组装返回 ----
    result = {
        "stock": stock_json,
        "index": index_json,
        "meta": {
            "start_date": start_dt.isoformat(),
            "end_date": today.isoformat(),
            "stock_name": stock_name,
            "stock_code": code,
            "index_name": index_info["name"],
            "index_code": index_info["code"],
        },
    }

    logger.info("查询成功: %s(%s) + %s", stock_name, code, index_info["name"])
    return jsonify(result)


@app.route("/")
def index():
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


# ============================================================
# 自选股管理 API
# ============================================================

import csv as _csv
import tempfile as _tempfile
_WATCHLIST_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "watchlist.csv")
_WATCHLIST_HEADER = ["code", "name", "type", "category"]


@app.route("/api/watchlist/add", methods=["POST"])
def api_watchlist_add():
    """添加/更新自选股列表。已存在的 code 会更新 name/type/category。"""
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
    if not name:
        return jsonify({"error": "股票名称不能为空"}), 400
    if typ not in ("stock", "etf"):
        typ = "stock"

    logger.info("添加自选股: %s(%s) type=%s category=%s", name, code, typ, category)

    # ---- 读取现有 watchlist ----
    existing: list[dict] = []
    found = False
    watchlist_path = _WATCHLIST_PATH

    if os.path.exists(watchlist_path):
        with open(watchlist_path, "r", encoding="utf-8-sig") as f:
            reader = _csv.DictReader(f)
            raw_fields = reader.fieldnames or []
            for row in reader:
                if not row or all(v.strip() == "" for v in row.values()):
                    continue
                c = (row.get("code") or "").strip()
                if c.startswith("#") or not c:
                    continue
                n = (row.get("name") or "").strip()
                t = (row.get("type") or "stock").strip().lower()
                cat = (row.get("category") or "").strip()
                if c == code:
                    # 更新现有
                    existing.append({"code": c, "name": name, "type": typ, "category": category})
                    found = True
                else:
                    existing.append({"code": c, "name": n, "type": t, "category": cat})
    else:
        # 文件不存在，从现有数据目录中推断已有代码
        pass

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
    return jsonify({"success": True, "action": action, "code": code, "name": name})


# ============================================================
# 启动入口
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() in (
        "1", "true", "yes"
    )
    logger.info("=" * 50)
    logger.info("🏠 股票看板 API 服务启动中...")
    logger.info("访问 http://127.0.0.1:%d/api/health 确认服务状态", port)
    logger.info("查询示例: http://127.0.0.1:%d/api/query?code=600519&start_date=2025-07-01", port)
    logger.info("=" * 50)
    app.run(host="0.0.0.0", port=port, debug=debug)
