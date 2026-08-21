# -*- coding: utf-8 -*-
"""60天历史回测引擎 v2 - 全池A股, 3策略 + 等权基准, 每周再平衡, 保存净值历史"""
import json, sys, math
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import numpy as np
from src.analysis.indicators import compute_all_indicators
from src.analysis.bet_type_classifier import calculate_momentum_half_life, calculate_atr_ratio

KLINE_DIR = ROOT / "docs" / "data" / "kline"
WINDOW_DAYS = 60
REBAL_EVERY = 5
END_DATE = "2026-08-20"
OUT = ROOT / "docs" / "data" / "paper" / "backtest_60d_result.json"

def calc_vol_ann(closes):
    rets = [closes[i]/closes[i-1]-1 for i in range(1, len(closes)) if closes[i-1]]
    if len(rets) < 5: return 0.0
    return float(np.std(np.array(rets[-20:])) * math.sqrt(252))

def tech_score(latest):
    s = 50.0
    c = latest.get("close"); ma20 = latest.get("ma20"); ma60 = latest.get("ma60")
    rsi = latest.get("rsi14"); r5 = latest.get("return_5d"); r20 = latest.get("return_20d")
    if c and ma20: s += 15.0 if c > ma20 else -15.0
    if c and ma60: s += 10.0 if c > ma60 else -10.0
    if ma20 and ma60: s += 10.0 if ma20 > ma60 else -10.0
    if rsi is not None:
        if 40 <= rsi <= 65: s += 5.0
        elif rsi > 80: s -= 8.0
        elif rsi < 25: s += 3.0
    if r5 is not None: s += max(-10.0, min(10.0, r5 * 5))
    if r20 is not None: s += max(-10.0, min(10.0, r20 * 2))
    return round(max(0.0, min(100.0, s)), 1)

def risk_score(latest):
    s = 100.0
    vol = latest.get("volatility_20d"); mdd = latest.get("max_drawdown_60d"); atr = latest.get("atr14_pct")
    if vol is not None:
        if vol > 0.6: s -= 30.0
        elif vol > 0.4: s -= 15.0
        elif vol < 0.2: s += 10.0
    if mdd is not None and mdd < -15: s -= 20.0
    if atr is not None and atr > 7.0: s -= 10.0
    return round(max(0.0, min(100.0, s)), 1)

def load_kline_df(code):
    with open(KLINE_DIR / (code + ".json"), encoding="utf-8") as f:
        data = json.load(f)
    dates, kline, volume = data.get("dates", []), data.get("kline", []), data.get("volume", [])
    rows = []
    for i, d in enumerate(dates):
        bar = kline[i]
        rows.append({"date": pd.to_datetime(d), "open": bar[0], "high": bar[3],
                     "low": bar[2], "close": bar[1],
                     "volume": volume[i] if i < len(volume) else 0})
    return pd.DataFrame(rows)

def stock_score(df, cut_date):
    sub = df[df["date"] <= cut_date]
    if len(sub) < 60: return None
    ind = compute_all_indicators(sub.copy())
    last = ind.iloc[-1]
    latest = {k: (float(last[k]) if pd.notna(last[k]) else None)
              for k in ["close","ma20","ma60","rsi14","atr14_pct","volatility_20d","max_drawdown_60d","return_5d","return_20d"]}
    t = tech_score(latest); r = risk_score(latest)
    closes = sub["close"].tolist(); highs = sub["high"].tolist(); lows = sub["low"].tolist()
    vol_ann = calc_vol_ann(closes); hl = calculate_momentum_half_life(closes)
    atr = calculate_atr_ratio(closes, highs, lows)
    vp = min(50.0, max(0.0, (vol_ann - 0.4) / 0.8 * 50.0))
    ap = min(35.0, max(0.0, (atr - 0.04) / 0.08 * 35.0))
    hp = 15.0 if (hl is not None and hl <= 3.0) else (7.5 if (hl is not None and hl <= 5.0) else 0.0)
    monster = round(min(100.0, max(0.0, vp + ap + hp)), 1)
    risk_adj = round(0.6 * t + 0.4 * (100 - r), 1)
    return {"close": float(last["close"]), "tech": t, "risk": r, "monster": monster, "risk_adj": risk_adj}

def pick(scores, mode, k=8):
    items = [(c, v) for c, v in scores.items() if v]
    if mode == "A": items.sort(key=lambda kv: -kv[1]["risk_adj"])
    elif mode == "R": items.sort(key=lambda kv: kv[1]["risk"])
    else: items.sort(key=lambda kv: -kv[1]["monster"])
    return dict(items[:k])

def run():
    codes = [f.stem for f in KLINE_DIR.glob("*.json")]
    codes = [c for c in codes if c.isdigit() and (c.startswith("00") or c.startswith("30") or c.startswith("60") or c.startswith("68"))]
    all_df = {}
    for c in codes:
        try: all_df[c] = load_kline_df(c)
        except Exception: pass
    print("加载A股:", len(all_df))

    trade_set = set()
    for c, df in all_df.items():
        trade_set.update(df["date"].dt.strftime("%Y-%m-%d"))
    trade_dates = sorted(d for d in trade_set if d <= END_DATE)[-WINDOW_DAYS:]
    if not trade_dates:
        print("无交易日"); return
    print("回测窗口:", trade_dates[0], "~", trade_dates[-1], "(", len(trade_dates), "日 )")
    rebal = set(trade_dates[::REBAL_EVERY])

    modes = {"aggressive": "A", "balanced": "R", "monster": "M"}
    holds = {k: {} for k in modes}
    nav_hist = {k: [] for k in modes}
    nav_hist["equal_weight"] = []
    # 等权基准: 全池买入持有, 用第一个再平衡日的可用股票
    equal_pool = None

    for d in trade_dates:
        d_dt = pd.to_datetime(d)
        if d in rebal:
            scores = {}
            for c in all_df:
                v = stock_score(all_df[c], d_dt)
                if v: scores[c] = v
            for name, mode in modes.items():
                holds[name] = pick(scores, mode, 8)
            if equal_pool is None:
                equal_pool = list(all_df.keys())
        # 估值
        for name, h in holds.items():
            total = 0.0
            if h:
                for c, v in h.items():
                    df = all_df[c]
                    row = df[df["date"] <= d_dt]
                    if len(row) > 0:
                        total += (1000000.0 / len(h)) / v["close"] * float(row["close"].iloc[-1])
            nav_hist[name].append(total if total > 0 else 1000000.0)
        # 等权基准: 每只股票首日收盘买入等额, 每日按(当日价/首日价)估值
        if equal_pool:
            total_ew = 0.0
            cnt_ew = 0
            for c in equal_pool:
                df = all_df[c]
                start_row = df[df["date"] <= pd.to_datetime(trade_dates[0])]
                row = df[df["date"] <= d_dt]
                if len(start_row) > 0 and len(row) > 0:
                    base_px = float(start_row["close"].iloc[-1])
                    cur_px = float(row["close"].iloc[-1])
                    if base_px > 0:
                        total_ew += (cur_px / base_px)
                        cnt_ew += 1
            nav_hist["equal_weight"].append(1000000.0 * (total_ew / cnt_ew) if cnt_ew else 1000000.0)

    # 结果统计
    result = {}
    print("\n===== 60天回测结果 (2026-05-29 ~ 2026-08-20) =====")
    for name, hist in nav_hist.items():
        if len(hist) < 2: continue
        total = (hist[-1]/hist[0] - 1) * 100
        peak = hist[0]; max_dd = 0.0
        for v in hist:
            peak = max(peak, v)
            dd = (v/peak - 1) * 100
            max_dd = min(max_dd, dd)
        # 胜率(相对等权)
        print(f"{name}: 累计 {total:+.2f}% | 期末 {hist[-1]:.0f} | 最大回撤 {abs(max_dd):.1f}%")
        result[name] = {"total_return_pct": round(total,2), "final_nav": round(hist[-1],1),
                        "max_drawdown_pct": round(abs(max_dd),1), "nav_hist": [round(x,1) for x in hist]}
    result["dates"] = trade_dates
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    print("\n结果已保存:", OUT)

if __name__ == "__main__":
    run()
