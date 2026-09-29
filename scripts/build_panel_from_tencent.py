#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scripts/build_panel_from_tencent.py

背景：CSMAR 个人账号当日下载额度用尽，且东财/网易不可达、腾讯 K 线触发 WAF。
可用源：新浪日 K（不复权 OHLCV，成交量单位=股）+ 腾讯 qt.gtimg.cn 实时快照（股本）。
新浪/腾讯收盘价此前均与 CSMAR 交叉验证过：偏差 0.0000%。

本脚本合成与 TRD_Dalyr 同构的原始行情，再复用
build_csmar_daily_panel_factors.build_factors() 生成面板，
使换手率单位修复后的面板今天就能重建。

与 CSMAR 原生数据的差异（须在交付说明中披露）：
  1. Dretwd 用不复权收盘价 pct_change 近似——除权除息日会有跳空
     （额度恢复后可用 CSMAR Dretwd 精确重建）；
  2. Dnvaltrd(成交额) 用典型价 (O+H+L+C)/4 × 成交量 近似；
  3. 流通/总股本取当前快照值，历史股本变动未回溯（多数标的期间内股本稳定）；
  4. Trdsta 恒为 1（停牌日天然无记录）；
  5. LimitStatus 由涨跌幅+收盘价位置近似判定。

额度恢复后可用 build_csmar_daily_panel_factors.py 重跑 CSMAR 版本。
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "scripts"))

from build_csmar_daily_panel_factors import (  # noqa: E402
    DEFAULT_END, DEFAULT_START, FIELDS, ROOT_DIR as _ROOT,
    build_factors, COHORT_FILES,
)

RAW_OUT = _ROOT / "data" / "_raw_cache" / "TENCENT_TRD_Dalyr_full.csv"
EXPECTED_MISSING = {"600317"}   # 营口港：2022 年退市，任务窗口内无行情属正常

UA = {"User-Agent": "Mozilla/5.0"}


def sym(code: str) -> str:
    return ("sh" if code.startswith("6") else "sz") + code


def fetch_json(url: str, retry: int = 4) -> dict:
    last = None
    for i in range(retry):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = e
            time.sleep(2.0 * (2 ** i))   # 指数退避：2/4/8/16s，应对限流
    raise last


PARTS_DIR = _ROOT / "data" / "_raw_cache" / "tencent_parts"


def fetch_kline(code: str, start: str, end: str, fq: str = "") -> pd.DataFrame:
    """新浪日 K（不复权）：date,open,high,low,close,volume(股)。

    说明：腾讯 web.ifzq.gtimg.cn 已触发 WAF 封禁，改用新浪公开接口。
    不复权价与 CSMAR Clsprc 口径一致（交叉验证偏差 0.0000%）。
    """
    s = sym(code)
    url = ("https://quotes.sina.cn/cn/api/jsonp_v2.php/var/"
           f"CN_MarketDataService.getKLineData?symbol={s}&scale=240&ma=no&datalen=700")
    req = urllib.request.Request(url, headers={**UA, "Referer": "https://finance.sina.com.cn/"})
    last = None
    for i in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                txt = r.read().decode("utf-8", errors="ignore")
            m = re.search(r"\[.*\]", txt, re.S)
            rows = json.loads(m.group()) if m else []
            break
        except Exception as e:
            last = e
            time.sleep(2.0 * (2 ** i))
    else:
        raise last
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([{
        "date": r["day"], "open": float(r["open"]), "close": float(r["close"]),
        "high": float(r["high"]), "low": float(r["low"]),
        "vol_shares": float(r["volume"]),
    } for r in rows])
    return df[(df["date"] >= start) & (df["date"] <= end)]


def fetch_shares(codes: list[str]) -> dict[str, dict]:
    """qt.gtimg.cn 实时快照（批量）：解析流通/总市值(亿)与现价 → 股本。"""
    out: dict[str, dict] = {}
    for i in range(0, len(codes), 50):
        chunk = codes[i:i + 50]
        q = ",".join(sym(c) for c in chunk)
        url = f"https://qt.gtimg.cn/q={q}"
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            txt = r.read().decode("gbk", errors="ignore")
        for line in txt.splitlines():
            if "=" not in line:
                continue
            name_part, body = line.split("=", 1)
            # name_part 形如 v_sz300750，取末尾 6 位纯代码
            code = name_part.strip()[-6:]
            f = body.strip(';"').split("~")
            try:
                price = float(f[3])
                float_cap = float(f[44])   # 流通市值（亿元）
                total_cap = float(f[45])   # 总市值（亿元）
            except (ValueError, IndexError):
                continue
            if price <= 0:
                continue
            out[code] = {
                "float_shares": float_cap * 1e8 / price,
                "total_shares": total_cap * 1e8 / price,
            }
        time.sleep(0.3)
    return out


def board_limit(code: str) -> float:
    return 0.20 if code.startswith(("300", "301", "688", "689")) else 0.10


def synth_trd_dalyr(code: str, raw: pd.DataFrame,
                    shares: dict | None) -> pd.DataFrame:
    df = raw.copy()
    df = df.sort_values("date").reset_index(drop=True)

    df["Stkcd"] = code
    df["Trddt"] = df["date"]
    df["Opnprc"], df["Clsprc"] = df["open"], df["close"]
    df["Hiprc"], df["Loprc"] = df["high"], df["low"]

    df["Dnshrtrd"] = df["vol_shares"]                             # 股（新浪已是股）
    typ = (df["open"] + df["high"] + df["low"] + df["close"]) / 4
    df["Dnvaltrd"] = typ * df["Dnshrtrd"]                         # 元（近似）

    # 新浪无前复权数据：用不复权 pct_change 近似收益。
    # 除权除息日会出现价格跳空，属于已知近似（额度恢复后可用 CSMAR Dretwd 精确重建）。
    df["Adjprcwd"] = np.nan
    df["Dretwd"] = df["close"].pct_change()
    df["Dretnd"] = df["Dretwd"]
    df["ChangeRatio"] = df["Dretwd"] * 100

    # 涨跌停判定需同时满足：涨跌幅接近限制 && 收在当日极值（过滤除权跳空误判）
    lim = board_limit(code)
    pct = df["Dretwd"]
    df["LimitStatus"] = np.where(
        (pct >= lim * 0.998) & (df["close"] >= df["high"] * 0.9999), 1,
        np.where((pct <= -lim * 0.998) & (df["close"] <= df["low"] * 1.0001), -1, 0))
    df["Trdsta"] = 1

    if shares:
        df["Dsmvosd"] = shares["float_shares"] * df["Clsprc"] / 1000.0  # 千元
        df["Dsmvtll"] = shares["total_shares"] * df["Clsprc"] / 1000.0
    else:
        df["Dsmvosd"] = np.nan
        df["Dsmvtll"] = np.nan

    return df[FIELDS]


def main():
    cohort = sys.argv[1] if len(sys.argv) > 1 else "student_A"
    stocks = pd.read_csv(_ROOT / COHORT_FILES[cohort],
                         dtype={"code": str}, encoding="utf-8-sig")
    codes = [str(c).zfill(6) for c in stocks["code"].tolist()]
    print(f"[{cohort}] {len(codes)} 支标的，{DEFAULT_START} ~ {DEFAULT_END}", flush=True)

    shares_map = fetch_shares(codes)
    print(f"[快照] 拿到股本 {len(shares_map)}/{len(codes)} 支", flush=True)

    frames, missing = [], []
    t0 = time.time()
    for i, code in enumerate(codes, 1):
        if code in EXPECTED_MISSING:
            missing.append(code)
            print(f"  [{i:>3}/{len(codes)}] {code} 跳过（预期退市，无数据）")
            continue
        part_file = PARTS_DIR / f"{code}.csv"
        if part_file.exists():                      # 逐股断点缓存：重跑不重复取数
            frames.append(pd.read_csv(part_file, dtype={"Stkcd": str}))
            continue
        try:
            raw = fetch_kline(code, DEFAULT_START, DEFAULT_END)
            time.sleep(1.0)                         # 保守节流，避免触发 WAF
        except Exception as e:
            print(f"  [{i:>3}] {code} 获取失败: {e}", flush=True)
            missing.append(code)
            continue
        if raw.empty:
            print(f"  [{i:>3}] {code} 无 K 线数据", flush=True)
            missing.append(code)
            continue
        synth = synth_trd_dalyr(code, raw, shares_map.get(code))
        PARTS_DIR.mkdir(parents=True, exist_ok=True)
        synth.to_csv(part_file, index=False, encoding="utf-8-sig")
        frames.append(synth)
        if i % 10 == 0 or i == len(codes):
            print(f"  [{i:>3}/{len(codes)}] 累计 {sum(len(f) for f in frames):,} 行 "
                  f"({time.time() - t0:.0f}s)", flush=True)

    extra_missing = sorted(set(missing) - EXPECTED_MISSING)
    if extra_missing:
        raise SystemExit(f"意外缺失 {extra_missing}，拒绝生成（安全阀）。")

    raw_all = pd.concat(frames, ignore_index=True)
    RAW_OUT.parent.mkdir(parents=True, exist_ok=True)
    raw_all.to_csv(RAW_OUT, index=False, encoding="utf-8-sig")
    print(f"原始行情已缓存: {RAW_OUT}  ({len(raw_all):,} 行)")

    panel = build_factors(raw_all)
    out_file = _ROOT / "data" / "task_split" / f"factors_daily_panel_{cohort}.csv"
    panel.to_csv(out_file, index=False, encoding="utf-8-sig")

    fcols = [c for c in panel.columns if c not in ("date", "ticker")]
    print(f"\n✅ 已生成: {out_file}")
    print(f"   行数 {len(panel):,} | 标的 {panel['ticker'].nunique()} | "
          f"交易日 {panel['date'].nunique()} | 因子 {len(fcols)} 个")
    print(f"   日期范围: {panel['date'].min()} ~ {panel['date'].max()}")


if __name__ == "__main__":
    main()
