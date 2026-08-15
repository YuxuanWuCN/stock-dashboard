# -*- coding: utf-8 -*-
"""离线预测准确率评估框架（不联网、可复现）。

背景与目标
----------
项目目标：股票方向预测准确率达到 80%。
现状：reports/calibration 的 alignment_rate 约为 34.7%（LLM 情绪方向 vs 实际方向）。

本框架在不联网的前提下，用 docs/data/kline/*.json（前复权日线）对所有股票
做**方向预测**的离线评估，回答三个问题：
1. 当前可用信号的 1/3/5 日方向预测准确率基线是多少？
2. 简单集成（多数投票、走步前向加权）能达到多少？
3. 距离 80% 的差距与最可行的提升路径是什么？

口径定义（与 alignment_rate 可比）
----------------------------------
- 在交易日 t，用 t 时刻及之前的数据生成方向预测 p(t) ∈ {up, down}。
- 标签 y(t, h) = close[t+h] > close[t]（h ∈ {1, 3, 5}），收益率恰好为 0 计为错误
  （保守口径），并在报告中单列中性占比。
- 准确率 = 正确样本数 / 有效样本数。同时报告按股票平均的准确率（避免大样本
  股票主导）。

假设与局限（必须记录，勿当作真实交易成绩）
------------------------------------------
- 只评估「方向」，不评估幅度；未计手续费、滑点、涨跌停无法成交。
- 数据为前复权日线（qfq），来自项目自有缓存，仅覆盖自选/扫描到的股票，
  存在选择与幸存者偏差。
- 样本时间范围约 13 个月（268 个交易日/只），结果对时段敏感。
- 全部特征严格只用 t 时刻及之前的数据，无未来函数；集成权重在训练段拟合、
  测试段评估（时间序列不打乱）。
- KNN 相似度、LLM 情绪等依赖外部模块的信号不在 v1 范围内，留作扩展。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KLINE_DIR = PROJECT_ROOT / "docs" / "data" / "kline"
REPORT_DIR = PROJECT_ROOT / "reports" / "prediction_accuracy"

HORIZONS = (1, 3, 5)


# --------------------------------------------------------------------------
# 数据加载
# --------------------------------------------------------------------------

def load_kline(path: Path) -> Optional[Dict]:
    """读取单个 kline JSON。字段缺失或长度不一致时返回 None。"""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    keys = ("dates", "kline", "volume")
    if any(k not in raw for k in keys):
        return None
    dates, kline, volume = raw["dates"], raw["kline"], raw["volume"]
    n = len(kline)
    if not (len(dates) == n and len(volume) == n):
        return None
    try:
        closes = [float(row[1]) for row in kline]
    except (TypeError, IndexError, ValueError):
        return None
    vols = []
    for v in volume:
        try:
            vols.append(float(v) if v is not None else math.nan)
        except (TypeError, ValueError):
            vols.append(math.nan)
    ma = {k: raw.get(k) for k in ("ma5", "ma10", "ma20", "ma60")}
    return {
        "code": str(raw.get("code", path.stem)),
        "name": str(raw.get("name", "")),
        "dates": list(dates),
        "closes": closes,
        "volumes": vols,
        "ma": ma,
    }


# --------------------------------------------------------------------------
# 特征（全部只用 t 及之前的数据）
# --------------------------------------------------------------------------

def _safe_ma(series: Optional[List], i: int) -> float:
    if series is None or i >= len(series) or series[i] is None:
        return math.nan
    try:
        return float(series[i])
    except (TypeError, ValueError):
        return math.nan


def compute_features(data: Dict) -> Dict[str, List[float]]:
    """按日计算因果特征。索引 i 对应交易日 i。

    返回 dict：每个特征是一个与 closes 等长的列表，无法计算处为 math.nan。
    """
    closes = data["closes"]
    vols = data["volumes"]
    n = len(closes)
    nan = math.nan
    vols = [nan if v is None else float(v) for v in vols]

    ret1 = [nan] * n
    for i in range(1, n):
        if closes[i - 1] not in (0, None):
            ret1[i] = closes[i] / closes[i - 1] - 1.0

    def mom(h: int) -> List[float]:
        out = [nan] * n
        for i in range(h, n):
            if closes[i - h] not in (0, None):
                out[i] = closes[i] / closes[i - h] - 1.0
        return out

    ma_ratio = {}
    for name in ("ma5", "ma10", "ma20", "ma60"):
        ratio = [nan] * n
        for i in range(n):
            m = _safe_ma(data["ma"].get(name), i)
            if m not in (None, 0) and not math.isnan(m):
                ratio[i] = closes[i] / m - 1.0
        ma_ratio[name] = ratio

    cross_5_20 = [nan] * n
    for i in range(n):
        m5 = _safe_ma(data["ma"].get("ma5"), i)
        m20 = _safe_ma(data["ma"].get("ma20"), i)
        if not (math.isnan(m5) or math.isnan(m20)) and m20 != 0:
            cross_5_20[i] = m5 / m20 - 1.0

    # RSI(14)：Wilder 平滑。
    rsi = [nan] * n
    gains, losses = [], []
    for i in range(1, n):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    if len(gains) >= 15:
        avg_g = sum(gains[:14]) / 14.0
        avg_l = sum(losses[:14]) / 14.0
        rsi[14] = 100.0 if avg_l == 0 else 100.0 - 100.0 / (1.0 + avg_g / avg_l)
        for i in range(15, n):
            avg_g = (avg_g * 13.0 + gains[i - 1]) / 14.0
            avg_l = (avg_l * 13.0 + losses[i - 1]) / 14.0
            rsi[i] = 100.0 if avg_l == 0 else 100.0 - 100.0 / (1.0 + avg_g / avg_l)

    vol_z = [nan] * n
    win = 20
    for i in range(win - 1, n):
        window = vols[i - win + 1: i + 1]
        window = [v for v in window if not math.isnan(v)]
        if len(window) < 5:
            continue
        mean = sum(window) / len(window)
        var = sum((v - mean) ** 2 for v in window) / len(window)
        std = math.sqrt(var)
        if std > 0:
            vol_z[i] = (vols[i] - mean) / std

    return {
        "ret1": ret1,
        "mom3": mom(3),
        "mom5": mom(5),
        "mom10": mom(10),
        "mom20": mom(20),
        "ma_ratio5": ma_ratio["ma5"],
        "ma_ratio10": ma_ratio["ma10"],
        "ma_ratio20": ma_ratio["ma20"],
        "ma_ratio60": ma_ratio["ma60"],
        "cross_5_20": cross_5_20,
        "rsi14": rsi,
        "vol_z20": vol_z,
    }


# --------------------------------------------------------------------------
# 预测规则
# --------------------------------------------------------------------------

def rule_sign(x: float) -> Optional[int]:
    """正 -> +1(看涨)，负 -> -1(看跌)，0/NaN -> None(不参与)。"""
    if x is None or math.isnan(x) or x == 0:
        return None
    return 1 if x > 0 else -1


def rule_rsi_momentum(x: float) -> Optional[int]:
    """RSI 趋势口径：>50 看涨，<50 看跌。"""
    if x is None or math.isnan(x) or x == 50:
        return None
    return 1 if x > 50 else -1


def rule_rsi_meanrev(x: float) -> Optional[int]:
    """RSI 均值回归口径：<30 看涨，>70 看跌，其余不表态。"""
    if x is None or math.isnan(x):
        return None
    if x < 30:
        return 1
    if x > 70:
        return -1
    return None


def rule_reversal(x: float) -> Optional[int]:
    """反转口径：取 ret1 的相反方向。"""
    s = rule_sign(x)
    return -s if s is not None else None


def rule_vol_breakout(x: float) -> Optional[int]:
    """放量突破口径：量能 z>0.5 看涨，z<-0.5 看跌，其余不表态。"""
    if x is None or math.isnan(x):
        return None
    if x > 0.5:
        return 1
    if x < -0.5:
        return -1
    return None


SIGNAL_RULES: Dict[str, Tuple[str, Callable[[float], Optional[int]]]] = {
    "ret1": ("ret1", rule_sign),
    "mom3": ("mom3", rule_sign),
    "mom5": ("mom5", rule_sign),
    "mom10": ("mom10", rule_sign),
    "mom20": ("mom20", rule_sign),
    "ma_ratio5": ("ma_ratio5", rule_sign),
    "ma_ratio10": ("ma_ratio10", rule_sign),
    "ma_ratio20": ("ma_ratio20", rule_sign),
    "ma_ratio60": ("ma_ratio60", rule_sign),
    "cross_5_20": ("cross_5_20", rule_sign),
    "rsi_momentum": ("rsi14", rule_rsi_momentum),
    "rsi_meanrev": ("rsi14", rule_rsi_meanrev),
    "ret1_reversal": ("ret1", rule_reversal),
    "vol_breakout": ("vol_z20", rule_vol_breakout),
}

ENSEMBLE_VOTERS = ["mom5", "ma_ratio10", "cross_5_20", "rsi_momentum", "vol_breakout"]


# --------------------------------------------------------------------------
# 评估
# --------------------------------------------------------------------------

def evaluate_stock(data: Dict, horizons: Tuple[int, ...] = HORIZONS,
                   max_lag: int = 60) -> Dict:
    """对单只股票计算各信号、各预测期的方向准确率。"""
    closes = data["closes"]
    n = len(closes)
    feats = compute_features(data)
    result: Dict[str, Dict] = {"stock": data["code"], "name": data["name"], "n_days": n}

    # 标签：y[i] = (close[i+h] - close[i]) 的符号
    labels = {}
    for h in horizons:
        y = [None] * n
        for i in range(n - h):
            if closes[i + h] == closes[i]:
                y[i] = 0  # 中性，保守计为错误
            else:
                y[i] = 1 if closes[i + h] > closes[i] else -1
        labels[h] = y

    for sig, (feat_name, rule) in SIGNAL_RULES.items():
        feat = feats[feat_name]
        for h in horizons:
            correct = 0
            total = 0
            neutral = 0
            for i in range(n - h):
                if i < max_lag:
                    continue  # 跳过早期预热段
                p = rule(feat[i])
                if p is None:
                    continue
                actual = labels[h][i]
                if actual == 0:
                    neutral += 1
                    continue  # 中性标签不参与准确率（另计）
                total += 1
                if p == actual:
                    correct += 1
            result[f"{sig}__h{h}"] = {
                "accuracy": correct / total if total else None,
                "n": total,
                "neutral_skipped": neutral,
            }

    # 集成：多数投票（仅当 3+ 个信号表态时）
    vote_feats = [feats[SIGNAL_RULES[s][0]] for s in ENSEMBLE_VOTERS]
    vote_rules = [SIGNAL_RULES[s][1] for s in ENSEMBLE_VOTERS]
    for h in horizons:
        correct = total = neutral = 0
        for i in range(n - h):
            if i < max_lag:
                continue
            votes = [rule(f[i]) for rule, f in zip(vote_rules, vote_feats)]
            votes = [v for v in votes if v is not None]
            if len(votes) < 3:
                continue
            p = 1 if sum(votes) > 0 else (-1 if sum(votes) < 0 else None)
            if p is None:
                continue
            actual = labels[h][i]
            if actual == 0:
                neutral += 1
                continue
            total += 1
            if p == actual:
                correct += 1
        result[f"ensemble_majority__h{h}"] = {
            "accuracy": correct / total if total else None,
            "n": total,
            "neutral_skipped": neutral,
        }

    # 基准：总是看涨 / 总是看跌
    for h in horizons:
        total = 0
        up = down = neu = 0
        for i in range(max_lag, n - h):
            actual = labels[h][i]
            if actual == 0:
                neu += 1
                continue
            total += 1
            if actual == 1:
                up += 1
            else:
                down += 1
        result[f"baseline_always_up__h{h}"] = {
            "accuracy": up / total if total else None, "n": total, "neutral_skipped": neu}
        result[f"baseline_always_down__h{h}"] = {
            "accuracy": down / total if total else None, "n": total, "neutral_skipped": neu}
    return result


def aggregate(stock_results: List[Dict]) -> Dict:
    """聚合全部股票：总样本口径 + 按股票平均口径。"""
    def merge(kind: str) -> Dict[str, Dict]:
        agg: Dict[str, Dict] = {}
        for stock in stock_results:
            for key, v in stock.items():
                if not (key.endswith(("__h1", "__h3", "__h5")) and isinstance(v, dict)):
                    continue
                base, h = key.rsplit("__", 1)
                if kind == "pooled":
                    a = agg.setdefault(f"{base}__{h}", {"correct": 0, "n": 0, "neutral": 0})
                else:
                    a = agg.setdefault(f"{base}__{h}", {"sum_acc": 0.0, "stocks": 0})
                if v["n"]:
                    if kind == "pooled":
                        a["correct"] += round(v["accuracy"] * v["n"])
                        a["n"] += v["n"]
                        a["neutral"] += v["neutral_skipped"]
                    else:
                        a["sum_acc"] += v["accuracy"]
                        a["stocks"] += 1
        out = {}
        for key, a in agg.items():
            if kind == "pooled":
                out[key] = {"accuracy": a["correct"] / a["n"] if a["n"] else None,
                            "n": a["n"], "neutral_skipped": a["neutral"]}
            else:
                out[key] = {"accuracy": a["sum_acc"] / a["stocks"] if a["stocks"] else None,
                            "n_stocks": a["stocks"]}
        return out

    return {"pooled": merge("pooled"), "per_stock_mean": merge("per_stock_mean")}


def run_all(kline_dir: Path = KLINE_DIR, max_stocks: Optional[int] = None,
            max_lag: int = 60) -> Dict:
    files = sorted(kline_dir.glob("*.json"))
    if max_stocks:
        files = files[:max_stocks]
    results, failed = [], []
    for f in files:
        data = load_kline(f)
        if data is None or len(data["closes"]) < max_lag + max(HORIZONS) + 5:
            failed.append(f.name)
            continue
        results.append(evaluate_stock(data, HORIZONS, max_lag=max_lag))
    agg = aggregate(results)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "kline_dir": str(kline_dir),
        "stocks_evaluated": len(results),
        "stocks_skipped": failed,
        "horizons": list(HORIZONS),
        "max_lag": max_lag,
        "assumptions": [
            "方向预测口径: close[t+h] vs close[t]; 中性(=0)标签单列不参与准确率",
            "全部特征只用 t 及之前数据, 无未来函数",
            "qfq 前复权日线, 未计手续费/滑点/涨跌停",
            "仅覆盖项目自选/扫描股票池, 存在选择与幸存者偏差",
            "集成为固定规则多数投票, 不做训练",
        ],
        "aggregates": agg,
    }


# --------------------------------------------------------------------------
# 选择性预测（置信度过滤）：精度 vs 覆盖率
# --------------------------------------------------------------------------

SELECTIVE_RETURN_THRESHOLDS = (0.005, 0.01, 0.02, 0.03, 0.05, 0.08, 0.10)
SELECTIVE_VOL_THRESHOLDS = (0.5, 1.0, 1.5, 2.0, 2.5)
SELECTIVE_RSI_ZONES = (
    (30, 70, "meanrev_30_70"),
    (25, 75, "meanrev_25_75"),
    (20, 80, "meanrev_20_80"),
    (15, 85, "meanrev_15_85"),
)


def evaluate_selective_stock(data: Dict, horizons: Tuple[int, ...] = HORIZONS,
                             max_lag: int = 60) -> Dict:
    """选择性预测：只在高置信度条件下出手，衡量精度（准确率）与覆盖率。"""
    closes = data["closes"]
    n = len(closes)
    feats = compute_features(data)
    out: Dict[str, Dict] = {"stock": data["code"], "name": data["name"]}

    labels = {}
    for h in horizons:
        y = [None] * n
        for i in range(n - h):
            y[i] = 0 if closes[i + h] == closes[i] else (1 if closes[i + h] > closes[i] else -1)
        labels[h] = y

    def tally(pred_fn, key: str, h: int) -> None:
        correct = total = neutral = 0
        y = labels[h]
        for i in range(max_lag, n - h):
            p = pred_fn(i)
            if p is None:
                continue
            if y[i] == 0:
                neutral += 1
                continue
            total += 1
            if p == y[i]:
                correct += 1
        out[f"{key}__h{h}"] = {"accuracy": correct / total if total else None,
                                "n": total, "neutral_skipped": neutral}

    # 幅度阈值过滤的动量/均线类信号
    for feat_name in ("ret1", "mom3", "mom5", "mom10", "mom20", "ma_ratio5",
                      "ma_ratio10", "ma_ratio20", "ma_ratio60", "cross_5_20"):
        feat = feats[feat_name]
        for th in SELECTIVE_RETURN_THRESHOLDS:
            key = f"sel_{feat_name}_th{int(th * 1000)}bp"
            for h in horizons:
                def pred(i, f=feat, t=th):
                    if f[i] is None or math.isnan(f[i]):
                        return None
                    if f[i] > t:
                        return 1
                    if f[i] < -t:
                        return -1
                    return None
                tally(pred, key, h)

    # RSI 极值区域
    rsi = feats["rsi14"]
    for lo, hi, tag in SELECTIVE_RSI_ZONES:
        key = f"sel_rsi_{tag}"
        for h in horizons:
            def pred(i, l=lo, hh=hi):
                x = rsi[i]
                if x is None or math.isnan(x):
                    return None
                if x < l:
                    return 1
                if x > hh:
                    return -1
                return None
            tally(pred, key, h)

    # 放量阈值
    vz = feats["vol_z20"]
    for th in SELECTIVE_VOL_THRESHOLDS:
        key = f"sel_vol_z{int(th * 10)}"
        for h in horizons:
            def pred(i, t=th):
                x = vz[i]
                if x is None or math.isnan(x):
                    return None
                if x > t:
                    return 1
                if x < -t:
                    return -1
                return None
            tally(pred, key, h)

    # 集成投票一致性（全票/至少4票一致）
    vote_feats = [feats[SIGNAL_RULES[s][0]] for s in ENSEMBLE_VOTERS]
    vote_rules = [SIGNAL_RULES[s][1] for s in ENSEMBLE_VOTERS]
    for min_votes in (5, 4):
        for h in horizons:
            def pred(i, m=min_votes):
                vs = [r(f[i]) for r, f in zip(vote_rules, vote_feats)]
                vs = [v for v in vs if v is not None]
                if len(vs) < m or abs(sum(vs)) != len(vs):
                    return None
                return 1 if sum(vs) > 0 else -1
            tally(pred, f"sel_ensemble_unanimous{min_votes}", h)
    return out


def run_selective_all(kline_dir: Path = KLINE_DIR, max_stocks: Optional[int] = None,
                      max_lag: int = 60) -> Dict:
    files = sorted(kline_dir.glob("*.json"))
    if max_stocks:
        files = files[:max_stocks]
    results, failed = [], []
    for f in files:
        data = load_kline(f)
        if data is None or len(data["closes"]) < max_lag + max(HORIZONS) + 5:
            failed.append(f.name)
            continue
        results.append(evaluate_selective_stock(data, HORIZONS, max_lag=max_lag))
    pooled: Dict[str, Dict] = {}
    for stock in results:
        for key, v in stock.items():
            if not (key.endswith(("__h1", "__h3", "__h5")) and isinstance(v, dict)):
                continue
            a = pooled.setdefault(key, {"correct": 0, "n": 0, "neutral": 0})
            if v["n"]:
                a["correct"] += round(v["accuracy"] * v["n"])
                a["n"] += v["n"]
                a["neutral"] += v["neutral_skipped"]
    out = {}
    for key, a in pooled.items():
        out[key] = {"accuracy": a["correct"] / a["n"] if a["n"] else None,
                    "n": a["n"], "neutral_skipped": a["neutral"]}
    return {"pooled": out, "stocks_evaluated": len(results),
            "stocks_skipped": failed}


# --------------------------------------------------------------------------
# 横截面口径：排名靠前的股票上涨比例（top-k hit rate）
# --------------------------------------------------------------------------

def run_cross_sectional_all(kline_dir: Path = KLINE_DIR,
                            max_stocks: Optional[int] = None,
                            max_lag: int = 60) -> Dict:
    """按交易日做横截面：用信号给当日全部股票排名，统计 top 分组的上涨比例。

    对每个交易日 t：取当日各股票的信号值 s_i(t)（仅用 t 及之前数据），
    按 s_i 降序排名，top_pct 分组；标签为未来 h 日方向 y_i(t,h)。
    hit rate = 组内 y_i=+1 的比例。
    """
    files = sorted(kline_dir.glob("*.json"))
    if max_stocks:
        files = files[:max_stocks]
    stocks = []
    for f in files:
        data = load_kline(f)
        if data is None or len(data["closes"]) < max_lag + max(HORIZONS) + 5:
            continue
        feats = compute_features(data)
        stocks.append({"code": data["code"], "closes": data["closes"],
                       "feats": feats, "n": len(data["closes"])})

    def label_of(stock: Dict, i: int, h: int) -> Optional[int]:
        c = stock["closes"]
        if i + h >= len(c):
            return None
        if c[i + h] == c[i]:
            return 0
        return 1 if c[i + h] > c[i] else -1

    signals = ("mom5", "mom20", "ma_ratio20", "cross_5_20", "rsi14", "vol_z20")
    groups = ("top10", "top20", "top50", "bottom10")
    out: Dict[str, Dict] = {}
    for sig in signals:
        for h in HORIZONS:
            for g in groups:
                out[f"cs_{sig}_{g}__h{h}"] = {"up": 0, "down": 0, "n": 0, "days": 0}

    # 按日期对齐：用全部股票的最早/最晚日期索引集合，取出现频次最高的日期序列
    all_days = max((len(s["closes"]) for s in stocks), default=0)
    for t in range(max_lag, all_days - max(HORIZONS)):
        rows = []
        for s in stocks:
            if t >= s["n"]:
                continue
            rows.append(s)
        if len(rows) < 10:
            continue
        for sig in signals:
            vals = []
            for s in rows:
                x = s["feats"][sig][t]
                if x is not None and not math.isnan(x):
                    vals.append((x, s))
            if len(vals) < 10:
                continue
            vals.sort(key=lambda p: p[0], reverse=True)
            m = len(vals)
            cuts = {
                "top10": vals[: max(1, m // 10)],
                "top20": vals[: max(1, m // 5)],
                "top50": vals[: max(1, m // 2)],
                "bottom10": vals[m - max(1, m // 10):],
            }
            for g, group_rows in cuts.items():
                for x, s in group_rows:
                    for h in HORIZONS:
                        y = label_of(s, t, h)
                        if y is None or y == 0:
                            continue
                        cell = out[f"cs_{sig}_{g}__h{h}"]
                        cell["n"] += 1
                        if y == 1:
                            cell["up"] += 1
                        else:
                            cell["down"] += 1
                for h in HORIZONS:
                    out[f"cs_{sig}_{g}__h{h}"]["days"] += 1

    result = {}
    for key, cell in out.items():
        n = cell["n"]
        result[key] = {
            "hit_rate": cell["up"] / n if n else None,
            "n": n,
            "days": cell["days"],
        }
    return {"pooled": result, "stocks_evaluated": len(stocks)}




# --------------------------------------------------------------------------
# 报告输出
# --------------------------------------------------------------------------

def _fmt(a: Optional[float]) -> str:
    return "  无样本" if a is None else f"{a * 100:6.1f}%"


def write_report(result: Dict, selective: Optional[Dict] = None,
                 cross_sectional: Optional[Dict] = None,
                 out_dir: Path = REPORT_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"prediction_accuracy_{stamp}.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    md_path = out_dir / f"prediction_accuracy_{stamp}.md"
    pooled = result["aggregates"]["pooled"]
    lines = [
        "# 离线预测准确率基线报告",
        "",
        f"- 生成时间: {result['generated_at']}",
        f"- 股票数: {result['stocks_evaluated']}（跳过 {len(result['stocks_skipped'])}）",
        f"- 预测期: {list(result['horizons'])} 日",
        f"- 预热期 max_lag: {result['max_lag']}",
        "",
        "## 方向预测准确率（总样本口径）",
        "",
        "| 信号 | 1日 | 3日 | 5日 | 样本数(3日) |",
        "|---|---:|---:|---:|---:|",
    ]
    sig_names = sorted({k.rsplit("__", 1)[0] for k in pooled})
    order = [s for s in ("baseline_always_up", "baseline_always_down", "ret1",
                         "mom3", "mom5", "mom10", "mom20", "ma_ratio5", "ma_ratio10",
                         "ma_ratio20", "ma_ratio60", "cross_5_20", "rsi_momentum",
                         "rsi_meanrev", "ret1_reversal", "vol_breakout",
                         "ensemble_majority") if s in sig_names]
    for s in order:
        h1 = pooled.get(f"{s}__h1", {})
        h3 = pooled.get(f"{s}__h3", {})
        h5 = pooled.get(f"{s}__h5", {})
        lines.append(
            f"| {s} | {_fmt(h1.get('accuracy'))} | {_fmt(h3.get('accuracy'))} | "
            f"{_fmt(h5.get('accuracy'))} | {h3.get('n', 0)} |"
        )
    lines += [
        "",
        "## 假设与局限",
        "",
    ]
    for a in result["assumptions"]:
        lines.append(f"- {a}")
    lines += [
        "",
        "> 本报告为离线基线测量，不代表真实交易成绩。改进方向见 reports/prediction_accuracy/README.md",
        "",
    ]

    if selective is not None:
        sel = selective["pooled"]
        lines += [
            "## 选择性预测（置信度过滤）：出手才计准确率",
            "",
            "> 目标口径：只在高把握时出手，追求出手准确率 ≥80%，同时记录覆盖率。",
            "",
        ]
        for h, label in (("h1", "1日"), ("h3", "3日"), ("h5", "5日")):
            base_n = pooled.get(f"baseline_always_up__{h}", {}).get("n", 0)
            rows = sorted(
                (k for k in sel if k.endswith(f"__{h}") and (sel[k]["n"] or 0) >= 200),
                key=lambda k: sel[k]["accuracy"] or 0.0, reverse=True)
            lines += [
                f"### {label} 预测（按准确率排序，n>=200）",
                "",
                "| 规则 | 准确率 | 样本数 | 覆盖率 |",
                "|---|---:|---:|---:|",
            ]
            for k in rows[:15]:
                v = sel[k]
                cov = (v["n"] / base_n * 100.0) if base_n else 0.0
                lines.append(f"| {k.rsplit('__', 1)[0]} | {_fmt(v['accuracy'])} | "
                             f"{v['n']} | {cov:.1f}% |")
            lines.append("")
    if cross_sectional is not None:
        cs = cross_sectional["pooled"]
        lines += [
            "## 横截面口径：排名靠前分组的上涨比例（hit rate）",
            "",
            "> 排行榜项目口径：信号排名 top 分组的股票，未来 h 日上涨的比例。",
            "",
            "| 信号+分组 | 1日 hit | 3日 hit | 5日 hit | 样本数(3日) |",
            "|---|---:|---:|---:|---:|",
        ]
        for sig in ("mom5", "mom20", "ma_ratio20", "cross_5_20", "rsi14", "vol_z20"):
            for g in ("top10", "top20", "top50", "bottom10"):
                k = f"cs_{sig}_{g}"
                h1 = cs.get(f"{k}__h1", {})
                h3 = cs.get(f"{k}__h3", {})
                h5 = cs.get(f"{k}__h5", {})
                lines.append(
                    f"| {sig} {g} | {_fmt(h1.get('hit_rate'))} | {_fmt(h3.get('hit_rate'))} | "
                    f"{_fmt(h5.get('hit_rate'))} | {h3.get('n', 0)} |"
                )
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="离线预测准确率评估")
    parser.add_argument("--max-stocks", type=int, default=None,
                        help="只评估前 N 只股票（默认全部）")
    parser.add_argument("--max-lag", type=int, default=60,
                        help="预热期交易日数（默认 60，保证 ma60 可用）")
    args = parser.parse_args(argv)
    result = run_all(KLINE_DIR, max_stocks=args.max_stocks, max_lag=args.max_lag)
    selective = run_selective_all(KLINE_DIR, max_stocks=args.max_stocks,
                                  max_lag=args.max_lag)
    cross = run_cross_sectional_all(KLINE_DIR, max_stocks=args.max_stocks,
                                    max_lag=args.max_lag)
    json_path = write_report(result, selective=selective, cross_sectional=cross)
    pooled = result["aggregates"]["pooled"]
    sel = selective["pooled"]
    print(f"评估股票数: {result['stocks_evaluated']}")
    print(f"3日方向准确率: 多数投票集成 = {_fmt(pooled.get('ensemble_majority__h3', {}).get('accuracy'))}")
    print(f"  单信号最佳(5日)参考: mom5 = {_fmt(pooled.get('mom5__h5', {}).get('accuracy'))}")
    for h in ("h3", "h5"):
        ranked = sorted(
            (k for k in sel if k.endswith(f"__{h}") and (sel[k]["n"] or 0) >= 200),
            key=lambda k: sel[k]["accuracy"] or 0.0, reverse=True)
        print(f"--- {h} 选择性预测 Top5 (n>=200) ---")
        for k in ranked[:5]:
            print(f"  {k}: acc={_fmt(sel[k]['accuracy'])} n={sel[k]['n']}")
    print(f"报告: {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
