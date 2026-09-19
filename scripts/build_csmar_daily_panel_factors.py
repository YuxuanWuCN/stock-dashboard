#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scripts/build_csmar_daily_panel_factors.py

用 CSMAR 真实日频行情为指定组员（student_A / student_B / student_C）构建
标准日频面板因子数据，替代 768 维离线兜底（该兜底路径产出的向量近乎退化，
两两余弦相似度均值约 0.79，无法用于截面回归）。

数据源：CSMAR《股票市场交易》- TRD_Dalyr（日个股回报率文件）

交付格式（任务单「格式 A：面板格式」）：
    date,ticker,factor_1,factor_2,...

数据质量红线：
  1. ticker 统一 6 位字符串（保留前导 0）；
  2. 缺失值只在单只股票内部 ffill，绝不跨股票填充；
  3. 停牌日不产生记录，由 ffill 在个股内部顺延。

用法：
    # 需要 CSMAR 个人注册账号（环境变量或 CSMAR_USERNAME/CSMAR_PASSWORD）
    python scripts/build_csmar_daily_panel_factors.py --cohort student_A
    python scripts/build_csmar_daily_panel_factors.py --cohort student_A --limit-codes 3  # 试跑
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

COHORT_FILES = {
    "student_A": "data/task_split/student_A_tech_manufacturing_100.csv",
    "student_B": "data/task_split/student_B_energy_materials_100.csv",
    "student_C": "data/task_split/student_C_finance_consumer_100.csv",
}

# 原始行情缓存目录（避免重复消耗 CSMAR 每日下载额度）
CACHE_DIR = ROOT_DIR / "data" / "_raw_cache"

# 已核实真实退市、任务窗口内本就无行情的标的（不触发安全阀）
EXPECTED_MISSING = {"600317"}   # 营口港：2022 年被吸收合并退市

# 默认时间范围（任务单要求）
DEFAULT_START = "2024-01-02"
DEFAULT_END = "2026-08-28"

FIELDS = [
    "Stkcd", "Trddt", "Opnprc", "Hiprc", "Loprc", "Clsprc",
    "Dnshrtrd", "Dnvaltrd", "Dsmvosd", "Dsmvtll",
    "Dretwd", "Dretnd", "Adjprcwd", "Trdsta", "ChangeRatio", "LimitStatus",
]


# ---------------------------------------------------------------- CSMAR 接入
def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip("'\"")
        if k and k not in os.environ:
            os.environ[k] = v


def build_client():
    """构造 CSMAR 客户端。SDK 位置可用 CSMAR_SDK_PATH 指定。"""
    for env_file in (ROOT_DIR / ".env", ROOT_DIR.parent / "csmar" / ".env"):
        load_dotenv(env_file)

    sdk_path = os.environ.get("CSMAR_SDK_PATH", "")
    if sdk_path:
        sys.path.insert(0, str(Path(sdk_path).parent if Path(sdk_path).name == "csmarapi" else sdk_path))
    else:
        # 常见位置兜底：与仓库同级的 csmar 工作目录
        guess = ROOT_DIR.parent / "csmar" / "sdk"
        if (guess / "csmarapi").is_dir():
            sys.path.insert(0, str(guess))

    try:
        from csmarapi.CsmarService import CsmarService
    except ImportError as e:
        raise SystemExit(
            "未找到 CSMAR SDK（csmarapi）。请设置环境变量 CSMAR_SDK_PATH 指向 csmarapi 所在目录，\n"
            f"或把 SDK 放进 {ROOT_DIR.parent / 'csmar' / 'sdk' / 'csmarapi'}。\n原始错误: {e}"
        )

    # CSMAR_ACCOUNT 为 CSMAR_USERNAME 的兼容别名（实测有同学按此键名配置）
    user = (os.environ.get("CSMAR_USERNAME") or os.environ.get("CSMAR_ACCOUNT", "")).strip()
    pwd = os.environ.get("CSMAR_PASSWORD", "").strip()
    lang = os.environ.get("CSMAR_LANG", "0").strip()
    if not user or not pwd:
        raise SystemExit("缺少 CSMAR 账号：请设置 CSMAR_USERNAME（或别名 CSMAR_ACCOUNT）/ CSMAR_PASSWORD 环境变量。")

    svc = CsmarService()
    svc.login(user, pwd, lang)
    print("[csmar] 登录成功")
    return svc


def _cache_path(codes: list[str], start: str, end: str) -> Path:
    key = hashlib.md5(("|".join(codes) + start + end).encode("utf-8")).hexdigest()[:16]
    return CACHE_DIR / f"TRD_Dalyr_{key}.csv"


def query_batch(svc, codes: list[str], start: str, end: str,
                use_cache: bool = True) -> pd.DataFrame:
    """按股票代码批量查询日频行情。

    CSMAR 个人账号有「每日下载额度」上限（超后会报
    Downloads has reached the limit today）。因此把每批原始行情落盘缓存，
    后续只改因子逻辑时无需重新取数。
    """
    cp = _cache_path(codes, start, end)
    if use_cache and cp.exists():
        return pd.read_csv(cp, dtype={"Stkcd": str}, encoding="utf-8-sig")

    in_clause = ",".join(f"'{c}'" for c in codes)
    cond = f"Stkcd in ({in_clause})"
    raw = svc.query(FIELDS, cond, "TRD_Dalyr", start, end)
    if raw is None or (isinstance(raw, list) and not raw):
        return pd.DataFrame(columns=FIELDS)
    df = pd.DataFrame(raw if isinstance(raw, list) else raw)

    if use_cache and not df.empty:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        df.to_csv(cp, index=False, encoding="utf-8-sig")
    return df


# ---------------------------------------------------------------- 因子构造
def to_num(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def build_factors(df: pd.DataFrame) -> pd.DataFrame:
    """由原始日频行情构造截面因子（全部在个股内部计算，杜绝跨股票污染）。"""
    num_cols = [c for c in FIELDS if c not in ("Stkcd", "Trddt")]
    df = to_num(df, num_cols)

    df = df.rename(columns={"Stkcd": "ticker", "Trddt": "date"})
    df["ticker"] = df["ticker"].astype(str).str.zfill(6)   # 红线 1：6 位字符串
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "ticker"])

    # 同一 (date, ticker) 可能重复（不同市场类型），保留第一条
    df = df.drop_duplicates(subset=["date", "ticker"], keep="first")
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)

    g = df.groupby("ticker", sort=False)

    # ---- 基础收益与价格 ----
    df["ret"] = df["Dretwd"]                                    # 考虑红利再投资的日收益
    df["close"] = df["Clsprc"]
    df["vwap"] = df["Dnvaltrd"] / df["Dnshrtrd"].replace(0, np.nan)

    # ---- 动量：过去 N 日累计收益（个股内部 rolling）----
    for w in (5, 20, 60):
        df[f"mom_{w}d"] = g["ret"].transform(
            lambda s: (1 + s.fillna(0)).rolling(w).apply(np.prod, raw=True) - 1
        )

    # ---- 波动率：过去 20 日日收益标准差 ----
    df["vol_20d"] = g["ret"].transform(lambda s: s.rolling(20).std())
    df["vol_60d"] = g["ret"].transform(lambda s: s.rolling(60).std())

    # ---- 换手率 ----
    # 单位说明（已实测校验）：Dsmvosd/Dsmvtll 单位为「千元」，
    # Dnshrtrd 为「股」，Dnvaltrd 为「元」。
    # 宁德时代 2024-06-03：Dsmvosd=788708034.83 千元 ÷ 202.50 元 × 1000
    #                    = 38.95 亿股，与实际流通股本一致。
    circ_shares = df["Dsmvosd"] * 1000 / df["Clsprc"].replace(0, np.nan)
    df["turnover"] = df["Dnshrtrd"] / circ_shares.replace(0, np.nan)
    df["turnover_20d"] = g["turnover"].transform(lambda s: s.rolling(20).mean())

    # ---- 流动性与规模（市值换算为「元」后再取对数）----
    df["log_amount"] = np.log1p(df["Dnvaltrd"])
    df["log_mktcap"] = np.log(df["Dsmvtll"] * 1000)
    # Amihud 非流动性：|收益| / 成交金额（百万）
    df["amihud"] = df["ret"].abs() / (df["Dnvaltrd"] / 1e6).replace(0, np.nan)

    # ---- 日内价格结构 ----
    rng = (df["Hiprc"] - df["Loprc"]).replace(0, np.nan)
    df["price_pos"] = (df["Clsprc"] - df["Loprc"]) / rng        # 收盘在当日振幅中的位置
    df["amplitude"] = (df["Hiprc"] - df["Loprc"]) / df["Clsprc"].replace(0, np.nan)
    # 跳空：今开 vs 昨收（在个股内部按日期平移，避免跨股票错位）
    prev_close = df.groupby("ticker", sort=False)["Clsprc"].shift(1)
    df["gap"] = (df["Opnprc"] - prev_close) / prev_close.replace(0, np.nan)

    # ---- 涨跌停标记 ----
    df["hit_limit"] = df["LimitStatus"].fillna(0).ne(0).astype(int)

    # ---- 停牌/异常交易状态标记（Trdsta 非 1 视为非正常交易）----
    df["abnormal_trd"] = df["Trdsta"].fillna(1).ne(1).astype(int)

    factor_cols = [
        "ret", "close", "vwap",
        "mom_5d", "mom_20d", "mom_60d",
        "vol_20d", "vol_60d",
        "turnover", "turnover_20d",
        "log_amount", "log_mktcap", "amihud",
        "price_pos", "amplitude", "gap", "hit_limit", "abnormal_trd",
    ]

    out = df[["date", "ticker"] + factor_cols].copy()

    # 红线 2：缺失值只在单只股票内部向前填充，绝不跨股票
    out[factor_cols] = out.groupby("ticker", sort=False)[factor_cols].ffill()

    # 滚动窗口产生的自然 NaN（前 60 日）不强行填 0，保留为 NaN 由下游处理
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    return out.sort_values(["date", "ticker"]).reset_index(drop=True)


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser(description="CSMAR 日频面板因子构建")
    ap.add_argument("--cohort", default="student_A",
                    choices=["student_A", "student_B", "student_C"])
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--end", default=DEFAULT_END)
    ap.add_argument("--batch-size", type=int, default=10, help="每批查询的股票数")
    ap.add_argument("--limit-codes", type=int, default=None, help="只跑前 N 支（试跑用）")
    ap.add_argument("--no-cache", action="store_true", help="忽略本地原始行情缓存，强制重新取数")
    ap.add_argument("--output", default=None)
    args = ap.parse_args()

    use_cache = not args.no_cache

    cohort_file = ROOT_DIR / COHORT_FILES[args.cohort]
    if not cohort_file.exists():
        raise SystemExit(f"未找到组员清单: {cohort_file}")
    stocks = pd.read_csv(cohort_file, dtype={"code": str}, encoding="utf-8-sig")
    codes = [str(c).zfill(6) for c in stocks["code"].tolist()]
    if args.limit_codes:
        codes = codes[: args.limit_codes]
    print(f"[{args.cohort}] 待处理 {len(codes)} 支标的，时间范围 {args.start} ~ {args.end}")

    batches = [codes[i: i + args.batch_size] for i in range(0, len(codes), args.batch_size)]
    pending = [b for b in batches
               if not (use_cache and _cache_path(b, args.start, args.end).exists())]
    if pending:
        svc = build_client()
    else:
        svc = None
        print("[cache] 全部批次命中本地缓存，本次不消耗 CSMAR 额度")

    frames, failed = [], []
    t0 = time.time()
    for i, batch in enumerate(batches, 1):
        cached = use_cache and _cache_path(batch, args.start, args.end).exists()
        try:
            raw = query_batch(svc, batch, args.start, args.end, use_cache=use_cache)
        except Exception as e:
            print(f"  [失败] 批次 {i} 查询异常: {e}")
            failed.append(batch)
            continue
        if raw.empty:
            print(f"  [失败] 批次 {i} 返回空（可能触发限流或当日额度用尽）")
            failed.append(batch)
            continue
        frames.append(raw)
        print(f"  批次 {i}: {len(batch)} 支 -> {len(raw):,} 行"
              f"{' [缓存]' if cached else ''} ({time.time() - t0:.0f}s)")
        if not cached:
            time.sleep(0.3)

    if not frames:
        raise SystemExit("未取到任何数据，请检查账号权限、当日额度或网络。")

    # 安全阀：取数不全时拒绝落盘，避免写出残缺文件被误用
    got_codes = set()
    for f in frames:
        got_codes |= set(f["Stkcd"].astype(str).str.zfill(6))
    missing_codes = sorted(set(codes) - got_codes)
    unexpected = sorted(set(missing_codes) - EXPECTED_MISSING)
    if unexpected:
        raise SystemExit(
            f"取数不完整：{len(codes)} 支中意外缺 {len(unexpected)} 支 "
            f"（{unexpected[:10]}{'...' if len(unexpected) > 10 else ''}）。\n"
            f"已拒绝写入输出文件，避免产出残缺数据。请稍后重跑（脚本会自动复用已缓存批次）。"
        )
    if missing_codes:
        print(f"[说明] {len(missing_codes)} 支无数据，经核实为真实退市，属预期：{missing_codes}")

    raw_all = pd.concat(frames, ignore_index=True)
    print(f"原始行情总行数: {len(raw_all):,}")

    panel = build_factors(raw_all)

    out_file = Path(args.output) if args.output else \
        ROOT_DIR / "data" / "task_split" / f"factors_daily_panel_{args.cohort}.csv"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(out_file, index=False, encoding="utf-8-sig")

    # 简要体检
    n_stocks = panel["ticker"].nunique()
    n_days = panel["date"].nunique()
    fcols = [c for c in panel.columns if c not in ("date", "ticker")]
    print(f"\n✅ 已生成: {out_file}")
    print(f"   行数 {len(panel):,} | 标的 {n_stocks} | 交易日 {n_days} | 因子 {len(fcols)} 个")
    print(f"   日期范围: {panel['date'].min()} ~ {panel['date'].max()}")
    miss = panel[fcols].isna().mean().sort_values(ascending=False)
    print("   缺失率最高的 5 个因子:")
    for k, v in miss.head(5).items():
        print(f"     {k:<15} {v * 100:5.1f}%")


if __name__ == "__main__":
    main()
