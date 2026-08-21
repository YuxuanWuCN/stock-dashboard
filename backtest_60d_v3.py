import json
import sys
import math
from pathlib import Path

ROOT = Path(r"D:\股票分析项目\2.0版")
sys.path.insert(0, str(ROOT))

import pandas as pd
import numpy as np
from src.analysis.indicators import compute_all_indicators
from src.analysis.bet_type_classifier import calculate_momentum_half_life, calculate_atr_ratio

KLINE_DIR = ROOT / "docs" / "data" / "kline"
WINDOW_DAYS = 60
REBAL_EVERY = 5
END_DATE = "2026-08-20"
OUT_PATH = ROOT / "docs" / "data" / "paper" / "backtest_60d_v3_rigorous.json"

def calc_vol_ann(closes):
    rets = [closes[i]/closes[i-1]-1 for i in range(1, len(closes)) if closes[i-1]]
    if len(rets) < 5:
        return 0.0
    return float(np.std(np.array(rets[-20:])) * math.sqrt(252))

def tech_score(latest):
    s = 50.0
    c = latest.get("close")
    ma20 = latest.get("ma20")
    ma60 = latest.get("ma60")
    rsi = latest.get("rsi14")
    r5 = latest.get("return_5d")
    r20 = latest.get("return_20d")
    if c and ma20:
        s += 15.0 if c > ma20 else -15.0
    if c and ma60:
        s += 10.0 if c > ma60 else -10.0
    if ma20 and ma60:
        s += 10.0 if ma20 > ma60 else -10.0
    if rsi is not None:
        if 40 <= rsi <= 65:
            s += 5.0
        elif rsi > 80:
            s -= 8.0
        elif rsi < 25:
            s += 3.0
    if r5 is not None:
        s += max(-10.0, min(10.0, r5 * 5))
    if r20 is not None:
        s += max(-10.0, min(10.0, r20 * 2))
    return round(max(0.0, min(100.0, s)), 1)

def risk_score(latest):
    s = 100.0
    vol = latest.get("volatility_20d")
    mdd = latest.get("max_drawdown_60d")
    atr = latest.get("atr14_pct")
    if vol is not None:
        if vol > 0.6:
            s -= 30.0
        elif vol > 0.4:
            s -= 15.0
        elif vol < 0.2:
            s += 10.0
    if mdd is not None and mdd < -15:
        s -= 20.0
    if atr is not None and atr > 7.0:
        s -= 10.0
    return round(max(0.0, min(100.0, s)), 1)

def load_kline_df(code):
    with open(KLINE_DIR / f"{code}.json", encoding="utf-8") as f:
        data = json.load(f)
    dates = data.get("dates", [])
    kline = data.get("kline", [])
    volume = data.get("volume", [])
    rows = []
    for i, d in enumerate(dates):
        bar = kline[i]
        rows.append({
            "date": pd.to_datetime(d),
            "open": bar[0],
            "high": bar[3],
            "low": bar[2],
            "close": bar[1],
            "volume": volume[i] if i < len(volume) else 0
        })
    return pd.DataFrame(rows)

def stock_score(df, cut_date):
    sub = df[df["date"] <= cut_date]
    if len(sub) < 60:
        return None
    ind = compute_all_indicators(sub.copy())
    last = ind.iloc[-1]
    latest = {
        k: (float(last[k]) if pd.notna(last[k]) else None)
        for k in ["close", "ma20", "ma60", "rsi14", "atr14_pct", "volatility_20d", "max_drawdown_60d", "return_5d", "return_20d"]
    }
    t = tech_score(latest)
    r = risk_score(latest)
    closes = sub["close"].tolist()
    highs = sub["high"].tolist()
    lows = sub["low"].tolist()
    vol_ann = calc_vol_ann(closes)
    hl = calculate_momentum_half_life(closes)
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

def pick(scores, mode, k=10):
    items = [(c, v) for c, v in scores.items() if v]
    if mode == "A":
        items.sort(key=lambda kv: -kv[1]["risk_adj"])
    elif mode == "R":
        items.sort(key=lambda kv: kv[1]["risk"])
    else:
        items.sort(key=lambda kv: -kv[1]["monster"])
    return dict(items[:k])

class PortfolioAccount:
    def __init__(self, name, initial_capital=1000000.0, enable_stop_loss=True, enable_vol_sizing=True):
        self.name = name
        self.cash = initial_capital
        self.holdings = {}
        self.nav_history = []
        self.enable_stop_loss = enable_stop_loss
        self.enable_vol_sizing = enable_vol_sizing

    def rebalance(self, picked_stocks, current_date, all_df):
        for code, h in list(self.holdings.items()):
            if code in all_df:
                df = all_df[code]
                row = df[df["date"] <= current_date]
                if len(row) > 0:
                    sell_px = float(row["close"].iloc[-1])
                    sell_amt = h["shares"] * sell_px
                    self.cash += sell_amt * (1 - 0.001)
        self.holdings.clear()

        if not picked_stocks:
            return

        if self.enable_vol_sizing:
            inv_vols = {c: 1.0 / picked_stocks[c]["vol_ann"] for c in picked_stocks}
            total_inv = sum(inv_vols.values())
            weights = {c: inv_vols[c] / total_inv for c in picked_stocks}
        else:
            weights = {c: 1.0 / len(picked_stocks) for c in picked_stocks}

        investable = self.cash * 0.98
        self.cash -= investable

        for c, weight in weights.items():
            alloc = investable * weight
            buy_px = picked_stocks[c]["close"]
            if buy_px > 0:
                shares = (alloc * (1 - 0.0003)) / buy_px
                self.holdings[c] = {
                    "shares": shares,
                    "cost_price": buy_px,
                    "highest_price": buy_px
                }

    def update_daily(self, current_date, all_df):
        market_val = 0.0
        for code, h in list(self.holdings.items()):
            if code in all_df:
                df = all_df[code]
                row = df[df["date"] <= current_date]
                if len(row) > 0:
                    cur_px = float(row["close"].iloc[-1])
                    if cur_px > h["highest_price"]:
                        h["highest_price"] = cur_px

                    if self.enable_stop_loss:
                        drop_from_cost = (cur_px - h["cost_price"]) / h["cost_price"]
                        gain_peak = (h["highest_price"] - h["cost_price"]) / h["cost_price"]
                        drop_from_peak = (cur_px - h["highest_price"]) / h["highest_price"]

                        if drop_from_cost <= -0.08 or (gain_peak >= 0.15 and drop_from_peak <= -0.05):
                            sell_amt = h["shares"] * cur_px * (1 - 0.001)
                            self.cash += sell_amt
                            del self.holdings[code]
                            continue

                    market_val += h["shares"] * cur_px

        total_nav = self.cash + market_val
        self.nav_history.append(total_nav)
        return total_nav

def run():
    codes = [f.stem for f in KLINE_DIR.glob("*.json")]
    codes = [c for c in codes if c.isdigit() and (c.startswith("00") or c.startswith("30") or c.startswith("60") or c.startswith("68"))]
    all_df = {}
    for c in codes:
        try:
            all_df[c] = load_kline_df(c)
        except Exception:
            pass

    trade_set = set()
    for c, df in all_df.items():
        trade_set.update(df["date"].dt.strftime("%Y-%m-%d"))
    trade_dates = sorted(d for d in trade_set if d <= END_DATE)[-WINDOW_DAYS:]
    rebal = set(trade_dates[::REBAL_EVERY])

    accounts = {
        "妖股_风控增强": PortfolioAccount("妖股_风控增强", 1000000.0, enable_stop_loss=True, enable_vol_sizing=True),
        "妖股_原始无控": PortfolioAccount("妖股_原始无控", 1000000.0, enable_stop_loss=False, enable_vol_sizing=False),
        "激进_风控增强": PortfolioAccount("激进_风控增强", 1000000.0, enable_stop_loss=True, enable_vol_sizing=True),
        "稳健_风控增强": PortfolioAccount("稳健_风控增强", 1000000.0, enable_stop_loss=True, enable_vol_sizing=True),
    }
    modes = {
        "妖股_风控增强": "M",
        "妖股_原始无控": "M",
        "激进_风控增强": "A",
        "稳健_风控增强": "R",
    }

    equal_pool = list(all_df.keys())
    equal_weight_history = []

    for d in trade_dates:
        d_dt = pd.to_datetime(d)
        if d in rebal:
            scores = {}
            for c in all_df:
                v = stock_score(all_df[c], d_dt)
                if v:
                    scores[c] = v
            for name, acc in accounts.items():
                mode = modes[name]
                k = 10 if "风控" in name else 8
                picked = pick(scores, mode, k=k)
                acc.rebalance(picked, d_dt, all_df)

        for name, acc in accounts.items():
            acc.update_daily(d_dt, all_df)

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

    print("===== 60天严谨账户风控回测结果 (2026-05-29 ~ 2026-08-20) =====")
    results = {}
    for name, acc in accounts.items():
        hist = acc.nav_history
        total = (hist[-1] / hist[0] - 1) * 100
        peak = hist[0]
        max_dd = 0.0
        for v in hist:
            peak = max(peak, v)
            dd = (v / peak - 1) * 100
            max_dd = min(max_dd, dd)
        print(f"{name:<14}: 累计收益 {total:+6.2f}% | 期末资产 {hist[-1]:>9.0f} | 最大回撤 {abs(max_dd):>5.1f}%")
        results[name] = {
            "total_return_pct": round(total, 2),
            "final_nav": round(hist[-1], 0),
            "max_drawdown_pct": round(abs(max_dd), 1),
            "nav_history": [round(x, 1) for x in hist]
        }

    ew_total = (equal_weight_history[-1] / equal_weight_history[0] - 1) * 100
    ew_peak = equal_weight_history[0]
    ew_max_dd = 0.0
    for v in equal_weight_history:
        ew_peak = max(ew_peak, v)
        dd = (v / ew_peak - 1) * 100
        ew_max_dd = min(ew_max_dd, dd)
    print(f"{'等权基准(全池)':<14}: 累计收益 {ew_total:+6.2f}% | 期末资产 {equal_weight_history[-1]:>9.0f} | 最大回撤 {abs(ew_max_dd):>5.1f}%")
    results["等权基准"] = {
        "total_return_pct": round(ew_total, 2),
        "final_nav": round(equal_weight_history[-1], 0),
        "max_drawdown_pct": round(abs(ew_max_dd), 1),
        "nav_history": [round(x, 1) for x in equal_weight_history]
    }

    results["trade_dates"] = trade_dates
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"结果已保存至: {OUT_PATH}")

if __name__ == "__main__":
    run()
