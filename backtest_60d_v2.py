# -*- coding: utf-8 -*-
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
OUT_PATH = ROOT / "docs" / "data" / "paper" / "backtest_60d_v2_comparison.json"

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
    return {
        "close": float(last["close"]),
        "tech": t,
        "risk": r,
        "monster": monster,
        "risk_adj": risk_adj,
        "vol_ann": max(0.15, vol_ann),
        "atr": atr
    }

def pick(scores, mode, k=12):
    items = [(c, v) for c, v in scores.items() if v]
    if mode == "A": items.sort(key=lambda kv: -kv[1]["risk_adj"])
    elif mode == "R": items.sort(key=lambda kv: kv[1]["risk"])
    else: items.sort(key=lambda kv: -kv[1]["monster"])
    return dict(items[:k])

def run_simulation(enable_risk_control=True):
    codes = [f.stem for f in KLINE_DIR.glob("*.json")]
    codes = [c for c in codes if c.isdigit() and (c.startswith("00") or c.startswith("30") or c.startswith("60") or c.startswith("68"))]
    all_df = {}
    for c in codes:
        try: all_df[c] = load_kline_df(c)
        except Exception: pass

    trade_set = set()
    for c, df in all_df.items():
        trade_set.update(df["date"].dt.strftime("%Y-%m-%d"))
    trade_dates = sorted(d for d in trade_set if d <= END_DATE)[-WINDOW_DAYS:]
    rebal = set(trade_dates[::REBAL_EVERY])

    modes = {"aggressive": "A", "balanced": "R", "monster": "M"}
    K_STOCKS = 12 if enable_risk_control else 8
    
    portfolio_state = {}
    for name in modes:
        portfolio_state[name] = {
            "cash": 1000000.0,
            "holdings": {},
            "peak_nav": 1000000.0,
            "nav_history": []
        }
    
    equal_weight_history = []
    equal_pool = list(all_df.keys())

    for d_idx, d in enumerate(trade_dates):
        d_dt = pd.to_datetime(d)
        is_rebal_day = (d in rebal)

        if is_rebal_day:
            scores = {}
            for c in all_df:
                v = stock_score(all_df[c], d_dt)
                if v: scores[c] = v

            for name, mode in modes.items():
                p = portfolio_state[name]
                current_nav = p["cash"]
                for code, h in p["holdings"].items():
                    if not h.get("is_stopped", False) and code in all_df:
                        df = all_df[code]
                        r_now = df[df["date"] <= d_dt]
                        if len(r_now) > 0:
                            current_nav += h["shares"] * float(r_now["close"].iloc[-1])
                
                p["cash"] = current_nav
                p["holdings"] = {}

                picked_stocks = pick(scores, mode, k=K_STOCKS)
                if not picked_stocks:
                    continue

                max_invest_ratio = 1.0
                if enable_risk_control:
                    if p["peak_nav"] > 0:
                        dd = (current_nav - p["peak_nav"]) / p["peak_nav"]
                        if dd < -0.08:
                            max_invest_ratio = 0.50

                investable_cash = current_nav * max_invest_ratio
                p["cash"] = current_nav - investable_cash

                if enable_risk_control:
                    inv_vols = {c: 1.0 / picked_stocks[c]["vol_ann"] for c in picked_stocks}
                    total_inv = sum(inv_vols.values())
                    weights = {c: inv_vols[c] / total_inv for c in picked_stocks}
                else:
                    weights = {c: 1.0 / len(picked_stocks) for c in picked_stocks}

                for c, v in picked_stocks.items():
                    alloc = investable_cash * weights[c]
                    buy_px = v["close"]
                    shares = alloc / buy_px if buy_px > 0 else 0
                    p["holdings"][c] = {
                        "shares": shares,
                        "buy_price": buy_px,
                        "highest_price": buy_px,
                        "is_stopped": False
                    }

        for name, p in portfolio_state.items():
            daily_total = p["cash"]
            for code, h in list(p["holdings"].items()):
                if h["is_stopped"]:
                    continue
                if code in all_df:
                    df = all_df[code]
                    r_now = df[df["date"] <= d_dt]
                    if len(r_now) > 0:
                        cur_px = float(r_now["close"].iloc[-1])
                        if cur_px > h["highest_price"]:
                            h["highest_price"] = cur_px

                        if enable_risk_control:
                            drop_from_buy = (cur_px - h["buy_price"]) / h["buy_price"]
                            gain_peak = (h["highest_price"] - h["buy_price"]) / h["buy_price"]
                            drop_from_peak = (cur_px - h["highest_price"]) / h["highest_price"]

                            if drop_from_buy <= -0.08 or (gain_peak >= 0.12 and drop_from_peak <= -0.05):
                                p["cash"] += h["shares"] * cur_px
                                h["is_stopped"] = True
                                continue

                        daily_total += h["shares"] * cur_px

            p["nav_history"].append(daily_total)
            if daily_total > p["peak_nav"]:
                p["peak_nav"] = daily_total

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
        equal_weight_history.append(1000000.0 * (total_ew / cnt_ew) if cnt_ew else 1000000.0)

    summary = {}
    for name, p in portfolio_state.items():
        hist = p["nav_history"]
        total = (hist[-1] / hist[0] - 1) * 100
        peak = hist[0]; max_dd = 0.0
        for v in hist:
            peak = max(peak, v)
            dd = (v / peak - 1) * 100
            max_dd = min(max_dd, dd)
        summary[name] = {
            "total_return_pct": round(total, 2),
            "final_nav": round(hist[-1], 0),
            "max_drawdown_pct": round(abs(max_dd), 1),
            "nav_history": [round(x, 1) for x in hist]
        }

    ew_total = (equal_weight_history[-1] / equal_weight_history[0] - 1) * 100
    ew_peak = equal_weight_history[0]; ew_max_dd = 0.0
    for v in equal_weight_history:
        ew_peak = max(ew_peak, v)
        dd = (v / ew_peak - 1) * 100
        ew_max_dd = min(ew_max_dd, dd)
    summary["equal_weight"] = {
        "total_return_pct": round(ew_total, 2),
        "final_nav": round(equal_weight_history[-1], 0),
        "max_drawdown_pct": round(abs(ew_max_dd), 1),
        "nav_history": [round(x, 1) for x in equal_weight_history]
    }
    summary["trade_dates"] = trade_dates
    return summary

if __name__ == "__main__":
    print("运行60天风控版回测...")
    with_rc = run_simulation(enable_risk_control=True)
    print("===== 60天风控版回测结果 =====")
    for name in ["monster", "aggressive", "balanced", "equal_weight"]:
        res = with_rc[name]
        print(name, ": 累计", ("%+.2f" % res['total_return_pct']), "% | 期末", ("%d" % res['final_nav']), "| 最大回撤", ("%.1f" % res['max_drawdown_pct']), "%")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(with_rc, f, ensure_ascii=False, indent=2)
    print("结果已保存至:", OUT_PATH)
