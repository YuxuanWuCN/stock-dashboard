# -*- coding: utf-8 -*-
"""
60天历史回测引擎 v4 (大盘市场温度动态仓位联动版)
===================================================
核心升级：
1. 每日基于全池191只股票计算宏观市场温度 (Market Temperature)
   - 涨跌家数比 (35%) + 跌停家数 (35%) + 强势股动量 (20%) + 成交额 (10%)
2. 市场温度与总股票仓位强力联动：
   - 活跃 (>=80度): 仓位 100%
   - 正常 (65~80度): 仓位 80%
   - 偏冷 (50~65度): 仓位 50%
   - 寒冷 (30~50度): 仓位 25% (其余75%保留现金)
   - 冰封 (<30度):   仓位 10% (其余90%保留现金)
3. 结合单股 -8% 严格止损 + 浮盈回撤锁定利润
"""
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
OUT_PATH = ROOT / "docs" / "data" / "paper" / "backtest_60d_v4_temp_gated.json"

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

def calculate_daily_market_temp(all_df, current_date):
    """历史无前视计算当日宏观市场温度 (0~100)"""
    daily_rets = []
    for c, df in all_df.items():
        sub = df[df["date"] <= current_date]
        if len(sub) >= 2:
            c_now = float(sub["close"].iloc[-1])
            c_prev = float(sub["close"].iloc[-2])
            if c_prev > 0:
                daily_rets.append((c_now / c_prev - 1) * 100)
    if not daily_rets:
        return 50.0, 0.5, "正常"
    
    arr = np.array(daily_rets)
    up_count = int((arr > 0).sum())
    down_count = int((arr < 0).sum())
    tot = up_count + down_count
    ratio = up_count / tot if tot > 0 else 0.5
    ratio_score = max(0.0, min(100.0, (ratio - 0.3) / 0.7 * 100.0))
    
    limit_down_count = int((arr <= -9.5).sum())
    limit_down_score = max(0.0, 100.0 - limit_down_count * 15.0)
    
    top20_avg = float(np.sort(arr)[-20:].mean()) if len(arr) >= 20 else 0.0
    top_perf_score = max(0.0, min(100.0, 50.0 + top20_avg * 6.0))
    
    # 综合温度
    temp = 0.40 * ratio_score + 0.35 * limit_down_score + 0.25 * top_perf_score
    temp = round(temp, 1)
    
    if temp >= 80:
        pos_ratio = 1.0; status = "活跃"
    elif temp >= 65:
        pos_ratio = 0.8; status = "正常"
    elif temp >= 50:
        pos_ratio = 0.5; status = "偏冷"
    elif temp >= 30:
        pos_ratio = 0.25; status = "寒冷"
    elif temp >= 15:
        pos_ratio = 0.10; status = "冰封"
    else:
        pos_ratio = 0.0; status = "极端"
        
    return temp, pos_ratio, status

def pick(scores, mode, k=10):
    items = [(c, v) for c, v in scores.items() if v]
    if mode == "A": items.sort(key=lambda kv: -kv[1]["risk_adj"])
    elif mode == "R": items.sort(key=lambda kv: kv[1]["risk"])
    else: items.sort(key=lambda kv: -kv[1]["monster"])
    return dict(items[:k])

class GatedPortfolioAccount:
    def __init__(self, name, initial_capital=1000000.0):
        self.name = name
        self.cash = initial_capital
        self.holdings = {}
        self.nav_history = []

    def rebalance(self, picked_stocks, target_pos_ratio, current_date, all_df):
        # 1. 全部平仓变现
        for code, h in list(self.holdings.items()):
            if code in all_df:
                df = all_df[code]
                row = df[df["date"] <= current_date]
                if len(row) > 0:
                    sell_px = float(row["close"].iloc[-1])
                    self.cash += h["shares"] * sell_px * (1 - 0.001)
        self.holdings.clear()

        if not picked_stocks or target_pos_ratio <= 0:
            return

        # 2. 根据温度决定的目标总股票仓位 (例如 25% 仓位买股票，75% 留现金)
        investable = self.cash * target_pos_ratio * 0.98
        self.cash -= investable

        # 波动率倒数加权
        inv_vols = {c: 1.0 / picked_stocks[c]["vol_ann"] for c in picked_stocks}
        total_inv = sum(inv_vols.values())
        weights = {c: inv_vols[c] / total_inv for c in picked_stocks}

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

                    drop_from_cost = (cur_px - h["cost_price"]) / h["cost_price"]
                    gain_peak = (h["highest_price"] - h["cost_price"]) / h["cost_price"]
                    drop_from_peak = (cur_px - h["highest_price"]) / h["highest_price"]

                    # 单股止损 (-8%) 或 止盈锁定
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
        try: all_df[c] = load_kline_df(c)
        except Exception: pass

    trade_set = set()
    for c, df in all_df.items():
        trade_set.update(df["date"].dt.strftime("%Y-%m-%d"))
    trade_dates = sorted(d for d in trade_set if d <= END_DATE)[-WINDOW_DAYS:]
    rebal = set(trade_dates[::REBAL_EVERY])

    accounts = {
        "妖股_温度联动版": GatedPortfolioAccount("妖股_温度联动版", 1000000.0),
        "激进_温度联动版": GatedPortfolioAccount("激进_温度联动版", 1000000.0),
        "稳健_温度联动版": GatedPortfolioAccount("稳健_温度联动版", 1000000.0),
    }
    modes = {
        "妖股_温度联动版": "M",
        "激进_温度联动版": "A",
        "稳健_温度联动版": "R",
    }

    equal_pool = list(all_df.keys())
    equal_weight_history = []
    temp_records = []

    for d in trade_dates:
        d_dt = pd.to_datetime(d)
        temp, pos_ratio, status = calculate_daily_market_temp(all_df, d_dt)
        temp_records.append({"date": d, "temp": temp, "pos_ratio": pos_ratio, "status": status})

        if d in rebal:
            scores = {}
            for c in all_df:
                v = stock_score(all_df[c], d_dt)
                if v: scores[c] = v
            for name, acc in accounts.items():
                mode = modes[name]
                picked = pick(scores, mode, k=10)
                acc.rebalance(picked, pos_ratio, d_dt, all_df)

        for name, acc in accounts.items():
            acc.update_daily(d_dt, all_df)

        # 等权基准
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

    print("===== 60天【市场温度联动】回测结果 (2026-05-29 ~ 2026-08-20) =====")
    results = {}
    for name, acc in accounts.items():
        hist = acc.nav_history
        total = (hist[-1] / hist[0] - 1) * 100
        peak = hist[0]; max_dd = 0.0
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
    ew_peak = equal_weight_history[0]; ew_max_dd = 0.0
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
