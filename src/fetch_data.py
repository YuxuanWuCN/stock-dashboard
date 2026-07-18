# fetch_data.py —— 主脚本：抓取 → 计算 → 产出标准化 JSON 数据
#
# 用法：python src/fetch_data.py
# 也可被 GitHub Actions 调用。
#
# 产出：
#   docs/data/kline/{code}.json  每只标的 K 线 + 均线
#   docs/data/summary.json        当日摘要列表
#   docs/data/meta.json           运行元信息

import csv
import json
import os
import sys
import time
import traceback
from datetime import date, datetime
from typing import Optional

# ---- 在 import akshare 之前清除系统代理 ----
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

import akshare as ak
import pandas as pd

from config import (
    LOOKBACK_DAYS,
    ADJUST,
    PERIOD,
    REQUEST_INTERVAL,
    REQUEST_TIMEOUT,
    MAX_RETRIES,
    MIN_VALID_ROWS,
    MA_WINDOWS,
    WATCHLIST_PATH,
    DATA_DIR,
    KLINE_DIR,
    SUMMARY_PATH,
    META_PATH,
)
from utils import (
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

logger = setup_logging()


# ============================================================
# 1. 读自选股列表
# ============================================================

def read_watchlist(path: str) -> list[dict]:
    """
    读取 watchlist.csv，返回标的列表。
    做健壮校验：跳过空行/注释行、代码非 6 位数字警告、type 非法时默认 stock。
    """
    if not os.path.exists(path):
        logger.error("自选股文件不存在: %s", path)
        sys.exit(1)

    items = []
    with open(path, "r", encoding="utf-8-sig") as f:  # utf-8-sig 兼容 BOM
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            logger.error("watchlist.csv 内容为空或格式错误")
            sys.exit(1)

        # 标准化表头（去空格）
        reader.fieldnames = [h.strip() for h in reader.fieldnames]

        for line_no, row in enumerate(reader, start=2):  # 第 1 行是表头
            # 跳过空行
            if not row or all(v.strip() == "" for v in row.values()):
                continue

            code = row.get("code", "").strip()
            name = row.get("name", "").strip()
            typ = row.get("type", "").strip().lower()

            # 跳过注释行
            if code.startswith("#"):
                continue

            # 代码校验
            if not code.isdigit() or len(code) != 6:
                logger.warning(
                    "第 %d 行代码 '%s' 不是 6 位数字，跳过", line_no, code
                )
                continue

            # 类型校验
            if typ not in ("stock", "etf"):
                logger.warning(
                    "第 %d 行 type='%s' 非法，按 stock 处理", line_no, typ
                )
                typ = "stock"

            # 名称兜底
            if not name:
                name = code

            items.append({"code": code, "name": name, "type": typ})

    if not items:
        logger.error("watchlist.csv 中没有有效标的")
        sys.exit(1)

    logger.info("读取自选股列表：共 %d 只标的", len(items))
    return items


# ============================================================
# 2. 抓取单只标的
# ============================================================

def fetch_one(
    item: dict, start_date: str, end_date: str
) -> Optional[pd.DataFrame]:
    """
    抓取一只标的的历史日线数据，返回清洗后的 DataFrame。
    失败 / 超时 / 数据不足均返回 None。
    支持 stock 和 etf 两种类型，失败时自动重试备用源。
    """
    code = item["code"]
    typ = item["type"]

    for attempt in range(1 + MAX_RETRIES):
        try:
            if typ == "stock":
                # ---- A 股 ----
                # 主源：东财 stock_zh_a_hist
                df = _fetch_stock_zh_a_hist(code, start_date, end_date, attempt)
                if df is None:
                    continue
            else:
                # ---- ETF / 场内基金 ----
                df = _fetch_etf_hist_em(code, start_date, end_date, attempt)
                if df is None:
                    continue

            # --- 清洗与校验 ---
            df = _clean_and_validate(df, code, item["name"])
            if df is None:
                return None

            # 按日期升序
            df = df.sort_values("date").reset_index(drop=True)

            return df

        except Exception:
            logger.warning(
                "%s(%s) 第 %d 次抓取异常: %s",
                item["name"], code, attempt + 1, traceback.format_exc(),
            )

        if attempt < MAX_RETRIES:
            logger.info("%s(%s) 第 %d 次失败，%d 秒后重试...", item["name"], code, attempt + 1, REQUEST_INTERVAL)
            time.sleep(REQUEST_INTERVAL)

    logger.error("%s(%s) 所有 %d 次尝试均失败", item["name"], code, 1 + MAX_RETRIES)
    return None


def _fetch_stock_zh_a_hist(
    code: str, start_date: str, end_date: str, attempt: int
) -> Optional[pd.DataFrame]:
    """抓取 A 股日线：主源东财，备用源新浪。"""
    # 将 YYYYMMDD 转为 YYYY-MM-DD（备用源需要）
    start_fmt = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
    end_fmt = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"

    if attempt == 0:
        # 主源：东财（使用 YYYYMMDD）
        df = ak.stock_zh_a_hist(
            symbol=code,
            period=PERIOD,
            start_date=start_date,
            end_date=end_date,
            adjust=ADJUST,
        )
    else:
        # 备用源：新浪 stock_zh_a_daily（支持 qfq，日期格式 YYYY-MM-DD）
        logger.info("切换备用源 stock_zh_a_daily 尝试 %s", code)
        df = ak.stock_zh_a_daily(
            symbol=f"sh{code}" if code.startswith("6") else f"sz{code}",
            start_date=start_fmt,
            end_date=end_fmt,
            adjust=ADJUST,
        )

    if df is None or df.empty:
        logger.warning("%s 返回空数据", code)
        return None

    # 统一列名映射
    col_map = {
        "日期": "date", "开盘": "open", "收盘": "close",
        "最高": "high", "最低": "low", "成交量": "volume",
        "成交额": "amount", "振幅": "amplitude", "涨跌幅": "change_pct",
        "涨跌额": "change_amt", "换手率": "turnover",
    }
    df = df.rename(columns=col_map)
    return df


def _fetch_etf_hist_em(
    code: str, start_date: str, end_date: str, attempt: int = 0
) -> Optional[pd.DataFrame]:
    """抓取 ETF 日线：主源 fund_etf_hist_em，备用源 stock_zh_a_daily。

    ETF 在新浪也用 stock_zh_a_daily 接口（加交易所前缀），
    与股票备用源一致，已验证可绕开本机代理问题。
    """
    if attempt == 0:
        # 主源：东财 fund_etf_hist_em
        df = ak.fund_etf_hist_em(
            symbol=code,
            period=PERIOD,
            start_date=start_date,
            end_date=end_date,
            adjust=ADJUST,
        )
    else:
        # 备用源：新浪 stock_zh_a_daily（ETF 也支持）
        logger.info("ETF %s 切换备用源 stock_zh_a_daily", code)
        prefix = "sh" if code.startswith("5") else "sz"
        start_fmt = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
        end_fmt = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
        try:
            df = ak.stock_zh_a_daily(
                symbol=f"{prefix}{code}",
                start_date=start_fmt,
                end_date=end_fmt,
                adjust=ADJUST,
            )
        except Exception:
            df = None

    if df is None or df.empty:
        return None

    # 统一列名映射
    col_map = {
        "日期": "date", "开盘": "open", "收盘": "close",
        "最高": "high", "最低": "low", "成交量": "volume",
        "成交额": "amount", "振幅": "amplitude", "涨跌幅": "change_pct",
        "涨跌额": "change_amt", "换手率": "turnover",
    }
    df = df.rename(columns=col_map)
    return df


def _clean_and_validate(
    df: pd.DataFrame, code: str, name: str
) -> Optional[pd.DataFrame]:
    """清洗 DataFrame：日期解析、OHLCV 校验、剔除异常行。"""
    # 日期列转为 date 类型
    if "date" not in df.columns:
        logger.warning("%s(%s) 缺少日期列", name, code)
        return None

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df["date"] = df["date"].dt.date

    # 数值列转 float/int
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 如果涨跌幅缺失，后面会计算，先不管
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
        logger.warning(
            "%s(%s) 有效行数 %d < %d，视为抓取失败",
            name, code, len(df), MIN_VALID_ROWS,
        )
        return None

    logger.info("%s(%s) 有效数据 %d 行", name, code, len(df))
    return df


# ============================================================
# 3. 衍生指标计算
# ============================================================

def compute_derived(df: pd.DataFrame) -> pd.DataFrame:
    """基于收盘价计算 MA 均线、当日涨跌幅、涨跌额。"""
    df = df.copy()
    closes = df["close"].tolist()

    # 均线
    for w in MA_WINDOWS:
        df[f"ma{w}"] = calc_ma(closes, w)

    # 当日涨跌幅 & 涨跌额（若接口未提供或为空）
    if "change_pct" not in df.columns:
        df["change_pct"] = None
    if "change_amt" not in df.columns:
        df["change_amt"] = None

    # 对缺失的涨跌幅/涨跌额做兜底计算
    prev_close = df["close"].shift(1)
    mask_pct = df["change_pct"].isna()
    mask_amt = df["change_amt"].isna()

    if mask_pct.any():
        df.loc[mask_pct, "change_pct"] = (
            ((df.loc[mask_pct, "close"] - prev_close[mask_pct]) / prev_close[mask_pct]) * 100
        ).round(2)

    if mask_amt.any():
        df.loc[mask_amt, "change_amt"] = (
            (df.loc[mask_amt, "close"] - prev_close[mask_amt])
        ).round(2)

    return df


# ============================================================
# 4. 输出 K 线 JSON
# ============================================================

def build_kline_json(item: dict, df: pd.DataFrame) -> dict:
    """将一只标的的 DataFrame 转为第 6.1 节规定的 JSON 结构。"""
    # 日期格式化为 YYYY-MM-DD 字符串
    dates = [d.isoformat() if isinstance(d, date) else str(d) for d in df["date"].tolist()]

    # kline: [开盘, 收盘, 最低, 最高] —— ECharts candlestick 顺序
    kline = []
    for _, row in df.iterrows():
        kline.append([
            round(float(row["open"]), 2),
            round(float(row["close"]), 2),
            round(float(row["low"]), 2),
            round(float(row["high"]), 2),
        ])

    # volume: 整数
    volume = [int(row["volume"]) if pd.notna(row["volume"]) else 0 for _, row in df.iterrows()]

    # 均线
    ma_data = {}
    for w in MA_WINDOWS:
        col = f"ma{w}"
        vals = []
        for _, row in df.iterrows():
            v = row.get(col)
            if pd.isna(v) or v is None:
                vals.append(None)
            else:
                vals.append(round(float(v), 2))
        ma_data[f"ma{w}"] = vals

    return {
        "code": item["code"],
        "name": item["name"],
        "type": item["type"],
        "adjust": ADJUST,
        "dates": dates,
        "kline": kline,
        "volume": volume,
        "ma5": ma_data["ma5"],
        "ma10": ma_data["ma10"],
        "ma20": ma_data["ma20"],
        "ma60": ma_data["ma60"],
    }


def save_kline_json(item: dict, kline_data: dict) -> None:
    """原子写入单只标的 K 线 JSON 文件。"""
    path = os.path.join(KLINE_DIR, f"{item['code']}.json")
    atomic_write_json(kline_data, path, logger)


# ============================================================
# 5. 摘要 & 元信息
# ============================================================

def build_summary_and_meta(
    watchlist: list[dict],
    results: dict,       # {code: df or None}
    run_start: datetime,
) -> tuple[dict, dict]:
    """
    构建 summary.json 和 meta.json。
    results 中 value 为 None 表示该只抓取失败。
    """
    total = len(watchlist)
    success = sum(1 for v in results.values() if v is not None)
    failed = total - success
    failed_list = [code for code, v in results.items() if v is None]

    # 确定交易日：取所有成功标的中最新日期
    trade_dates = []
    for df in results.values():
        if df is not None and not df.empty:
            max_date = df["date"].max()
            trade_dates.append(max_date)

    trade_date_str = ""
    if trade_dates:
        latest = max(trade_dates)
        trade_date_str = latest.isoformat() if isinstance(latest, date) else str(latest)

    # 判断是否节假日（无新交易数据）
    today = beijing_today()
    is_holiday = False
    if trade_dates and trade_date_str != today.isoformat():
        is_holiday = True
        logger.info(
            "最新交易日 %s 与今天 %s 不一致，可能是节假日/周末，数据视为正常",
            trade_date_str, today.isoformat(),
        )

    # run_status
    if failed == 0:
        run_status = "ok"
    elif success == 0:
        run_status = "failed"
    else:
        run_status = "partial"

    # 节假日且全部成功/部分失败不算失败
    if is_holiday and run_status == "failed":
        # 节假日无新数据是正常的，把之前有旧数据的视为 ok
        if has_existing_data(DATA_DIR):
            run_status = "ok"
            logger.info("节假日无新数据 + 旧数据存在，run_status 设为 ok")

    # ---- summary.json ----
    summary_items = []
    for item in watchlist:
        code = item["code"]
        df = results.get(code)

        # 从已有 kline JSON 读旧数据（如果本次抓取失败）
        if df is None:
            stale_data = _load_existing_kline_summary(code)
            if stale_data:
                stale_data["status"] = "stale"
                summary_items.append(stale_data)
            else:
                summary_items.append({
                    "code": code,
                    "name": item["name"],
                    "type": item["type"],
                    "last_close": None,
                    "change_pct": None,
                    "change_amt": None,
                    "last_date": None,
                    "status": "failed",
                })
            continue

        last_row = df.iloc[-1]
        summary_items.append({
            "code": code,
            "name": item["name"],
            "type": item["type"],
            "last_close": (
                round(float(last_row["close"]), 2)
                if pd.notna(last_row.get("close"))
                else None
            ),
            "change_pct": (
                round(float(last_row["change_pct"]), 2)
                if pd.notna(last_row.get("change_pct"))
                else None
            ),
            "change_amt": (
                round(float(last_row["change_amt"]), 2)
                if pd.notna(last_row.get("change_amt"))
                else None
            ),
            "last_date": trade_date_str,
            "status": "ok",
        })

    summary = {"items": summary_items}

    # ---- meta.json ----
    meta = {
        "updated_at": beijing_datetime_str(),
        "trade_date": trade_date_str,
        "total": total,
        "success": success,
        "failed": failed,
        "failed_list": failed_list,
        "run_status": run_status,
    }

    return summary, meta


def _load_existing_kline_summary(code: str) -> Optional[dict]:
    """从已有的 kline JSON 读取摘要所需信息（用于失败时保留旧数据）。"""
    path = os.path.join(KLINE_DIR, f"{code}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        last_idx = -1
        last_close = data["kline"][last_idx][1]  # close
        last_date = data["dates"][last_idx]

        # 计算涨跌幅（与倒数第二天比）
        if len(data["kline"]) >= 2:
            prev_close = data["kline"][-2][1]
            change_amt = round(last_close - prev_close, 2)
            change_pct = (
                round((last_close - prev_close) / prev_close * 100, 2)
                if prev_close != 0 else None
            )
        else:
            change_amt = None
            change_pct = None

        return {
            "code": code,
            "name": data.get("name", code),
            "type": data.get("type", "stock"),
            "last_close": last_close,
            "change_pct": change_pct,
            "change_amt": change_amt,
            "last_date": last_date,
            "status": "stale",
        }
    except Exception:
        logger.warning("读取 %s 旧 K 线数据失败: %s", code, traceback.format_exc())
        return None


# ============================================================
# 6. 主流程
# ============================================================

def main() -> int:
    """主函数。返回 0 表示成功，非 0 表示需要发失败邮件。"""
    run_start = beijing_now()
    logger.info("=" * 60)
    logger.info("股票看板数据抓取开始 —— %s", run_start.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 60)

    # ---- 6.1 读自选股 ----
    watchlist = read_watchlist(WATCHLIST_PATH)

    # ---- 6.2 确定日期范围 ----
    today = beijing_today()
    start_date = calc_start_date(today, LOOKBACK_DAYS)
    end_date = today.strftime("%Y%m%d")
    logger.info("抓取范围：%s ~ %s（%d 自然日）", start_date, end_date, LOOKBACK_DAYS)

    # ---- 6.3 逐只抓取 ----
    results: dict[str, Optional[pd.DataFrame]] = {}
    for i, item in enumerate(watchlist):
        code = item["code"]
        logger.info(
            "[%d/%d] 开始抓取 %s(%s) ...", i + 1, len(watchlist), item["name"], code
        )

        df = fetch_one(item, start_date, end_date)

        if df is not None:
            # 计算衍生指标
            df = compute_derived(df)
            logger.info(
                "%s(%s) ✓ 抓取成功，%d 行数据",
                item["name"], code, len(df),
            )
        else:
            logger.warning("%s(%s) ✗ 抓取失败", item["name"], code)

        results[code] = df

        # 限流（最后一只不用 sleep）
        if i < len(watchlist) - 1:
            time.sleep(REQUEST_INTERVAL)

    # ---- 6.4 全部失败保护 ----
    success_count = sum(1 for v in results.values() if v is not None)
    if success_count == 0:
        logger.error("所有标的均抓取失败！")
        if has_existing_data(DATA_DIR):
            logger.warning("保留 docs/data/ 旧数据，不覆盖")
            # 仍更新 meta.json 标注失败状态
            meta = {
                "updated_at": beijing_datetime_str(),
                "trade_date": "",
                "total": len(watchlist),
                "success": 0,
                "failed": len(watchlist),
                "failed_list": [item["code"] for item in watchlist],
                "run_status": "failed",
            }
            atomic_write_json(meta, META_PATH, logger)
        return 1  # 非零退出码 → 触发邮件

    # ---- 6.5 写入 K 线 JSON ----
    logger.info("写入 K 线数据...")
    for item in watchlist:
        df = results[item["code"]]
        if df is not None:
            kline_data = build_kline_json(item, df)
            save_kline_json(item, kline_data)

    # ---- 6.6 生成摘要 & 元信息 ----
    logger.info("生成摘要与元信息...")
    summary, meta = build_summary_and_meta(watchlist, results, run_start)

    atomic_write_json(summary, SUMMARY_PATH, logger)
    atomic_write_json(meta, META_PATH, logger)

    # ---- 6.7 汇总日志 ----
    elapsed = (beijing_now() - run_start).total_seconds()
    logger.info("=" * 60)
    logger.info("抓取完成！总 %d / 成功 %d / 失败 %d / 耗时 %.1f 秒",
                meta["total"], meta["success"], meta["failed"], elapsed)
    logger.info("run_status: %s", meta["run_status"])
    logger.info("数据目录: %s", DATA_DIR)
    logger.info("=" * 60)

    # 返回码：全失败 → 非零；partial/ok → 0
    if meta["run_status"] == "failed":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
