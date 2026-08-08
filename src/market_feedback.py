# src/market_feedback.py —— 市场反馈标签与 RLSP 奖励信号
#
# 融入 FinGPT 方法论：
#   1. RLSP 奖励信号：reward = sign(pred_sentiment) * actual_return
#      用于过滤数据、排序验证、生成软标签，不进行在线学习。
#   2. 排序验证：按情感分数排序 → 对比 top-K vs bottom-K 实际收益。
#   3. 软标签：正负样本按奖励绝对值加权，替代硬二分类。
#
# 当前仅用于积累评估样本，不参与实时排序。不连接证券账户，不自动交易。

import json
import logging
import math
import os
from collections import defaultdict
from datetime import date
from typing import Optional

try:
    from .llm.config import FEEDBACK_PATH
except ImportError:
    from llm.config import FEEDBACK_PATH  # pragma: no cover

logger = logging.getLogger("stock-dashboard.market_feedback")


# ============================================================
# RLSP 核心公式（来自 FinGPT 论文 Section 2.3）
# ============================================================

def compute_rlsp_reward(
    sentiment: float,
    actual_return: Optional[float],
) -> Optional[float]:
    """
    RLSP 奖励信号。

    FinGPT 论文公式:
        reward = sign(predicted_sentiment) * actual_return

    其中 predicted_sentiment: +1 (正面), -1 (负面), 0 (中性)
    连续版本: reward = sentiment_score * actual_return

    返回 None 当 actual_return 不可用。
    """
    if actual_return is None:
        return None
    if sentiment == 0:
        return 0.0
    sign = 1.0 if sentiment > 0 else -1.0
    return round(sign * actual_return, 4)


def compute_rlsp_reward_continuous(
    sentiment_score: float,
    actual_return: Optional[float],
) -> Optional[float]:
    """
    RLSP 奖励的连续版本：用 [-1, 1] 的情感分数代替三分类 sign。
    情感分数越极端，对收益的敏感性越高。
    """
    if actual_return is None:
        return None
    return round(sentiment_score * actual_return, 4)


# ============================================================
# 排序验证（FinGPT 的评估指标）
# ============================================================

def compute_ranking_discrimination(
    items: list[dict],
    sentiment_key: str = "sentiment_score",
    return_key: str = "excess_5d_pct",
    top_k: int = 5,
) -> dict:
    """
    按情感分数排序，验证 top-K vs bottom-K 的实际收益区分度。

    这是 FinGPT RLSP 的评估框架核心：好的情感分析应能把正收益和负收益样本分开。

    Returns:
        {
            "top_k_avg_return": float,       # 情感最高 K 只的平均收益
            "bottom_k_avg_return": float,    # 情感最低 K 只的平均收益
            "spread": float,                 # 区分度 = top - bottom
            "rank_ic": float,                # 情感分数与实际收益的秩相关系数（简化版）
            "top_k_codes": list,
            "bottom_k_codes": list,
            "total_items": int,
        }
    """
    valid = [it for it in items if it.get(sentiment_key) is not None and it.get(return_key) is not None]
    if not valid:
        return {
            "top_k_avg_return": None,
            "bottom_k_avg_return": None,
            "spread": None,
            "rank_ic": None,
            "top_k_codes": [],
            "bottom_k_codes": [],
            "total_items": 0,
        }

    sorted_items = sorted(valid, key=lambda x: x[sentiment_key], reverse=True)
    k = min(top_k, len(sorted_items))
    top = sorted_items[:k]
    bottom = sorted_items[-k:]

    top_avg = sum(it[return_key] for it in top) / k
    bottom_avg = sum(it[return_key] for it in bottom) / k

    # 简化 Rank IC：情感分数排位 vs 收益排位的 Pearson r
    sentiments = [it[sentiment_key] for it in valid]
    returns = [it[return_key] for it in valid]
    rank_ic = _pearson_r(sentiments, returns)

    return {
        "top_k_avg_return": round(top_avg, 4),
        "bottom_k_avg_return": round(bottom_avg, 4),
        "spread": round(top_avg - bottom_avg, 4),
        "rank_ic": round(rank_ic, 4),
        "top_k_codes": [it.get("code", "") for it in top],
        "bottom_k_codes": [it.get("code", "") for it in bottom],
        "total_items": len(valid),
    }


# ============================================================
# 软标签生成（FinGPT 数据过滤模式）
# ============================================================

def generate_soft_label(
    sentiment_score: float,
    actual_return: Optional[float],
    confidence: float = 1.0,
) -> dict:
    """
    生成带权重的软标签。

    FinGPT 的数据过滤做法：
    - 信号一致（情感方向与收益方向相同）的样本保留并加权
    - 信号矛盾的样本降低权重，用于防止过拟合
    - 置信度低的预测降低权重

    Returns:
        {
            "hard_label": "positive" | "negative" | "neutral",
            "soft_label": float,     # [-1, 1] 连续值
            "weight": float,         # 训练权重，0~1
            "aligned": bool,         # 方向是否一致
        }
    """
    if actual_return is None:
        return {
            "hard_label": "neutral",
            "soft_label": 0.0,
            "weight": 0.0,
            "aligned": False,
        }

    # 硬标签
    if sentiment_score > 0.1:
        hard = "positive"
    elif sentiment_score < -0.1:
        hard = "negative"
    else:
        hard = "neutral"

    # 软标签：情感分数
    soft = sentiment_score

    # 方向一致性
    if (sentiment_score > 0 and actual_return > 0) or (sentiment_score < 0 and actual_return < 0):
        aligned = True
        weight = min(1.0, abs(actual_return) * 10.0 + 0.5) * confidence
    elif abs(sentiment_score) < 0.1:
        aligned = False
        weight = 0.02 * confidence
    else:
        aligned = False
        weight = max(0.05, 0.3 - abs(actual_return) * 5.0) * confidence

    return {
        "hard_label": hard,
        "soft_label": round(soft, 4),
        "weight": round(weight, 4),
        "aligned": aligned,
    }


# ============================================================
# MarketFeedbackTracker（增强版：融入 RLSP）
# ============================================================

class MarketFeedbackTracker:
    """
    市场反馈追踪器（融入 FinGPT RLSP 方法论）。

    用法:
        tracker = MarketFeedbackTracker()
        tracker.record_event(code, name, event_date, event_type,
                             ret_3d, ret_5d, benchmark_ret_3d,
                             sentiment_score=sentiment_score)
        tracker.save()
        samples = tracker.export_training_samples()
    """

    def __init__(self, path: str = FEEDBACK_PATH):
        self.path = path
        self.samples: list[dict] = []
        self._load()

    def _load(self) -> None:
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.samples = data.get("samples", []) if isinstance(data, dict) else []
        except Exception:
            logger.warning("市场反馈数据读取失败，从空集开始", exc_info=True)
            self.samples = []

    def record_event(
        self,
        code: str,
        name: str,
        event_date: str,
        event_type: str,
        ret_3d: Optional[float],
        ret_5d: Optional[float],
        benchmark_ret_3d: Optional[float] = None,
        benchmark_ret_5d: Optional[float] = None,
        sentiment_score: Optional[float] = None,
        sentiment_confidence: float = 1.0,
    ) -> dict:
        """
        记录一次事件及其后续收益，联动 RLSP 奖励和软标签。

        sentiment_score: -1.0 (负面) ~ +1.0 (正面), None 表示无情感数据。
        """
        excess_3d = _excess_return(ret_3d, benchmark_ret_3d)
        excess_5d = _excess_return(ret_5d, benchmark_ret_5d)
        label = _label_from_excess(excess_5d if excess_5d is not None else excess_3d)

        # RLSP 奖励
        rlsp_reward_3d = (
            compute_rlsp_reward_continuous(sentiment_score, excess_3d)
            if sentiment_score is not None else None
        )
        rlsp_reward_5d = (
            compute_rlsp_reward_continuous(sentiment_score, excess_5d)
            if sentiment_score is not None else None
        )

        # 软标签
        soft_label = (
            generate_soft_label(sentiment_score, excess_5d, sentiment_confidence)
            if sentiment_score is not None
            else {"hard_label": "neutral", "soft_label": 0.0, "weight": 0.0, "aligned": False}
        )

        sample = {
            "code": code,
            "name": name,
            "event_date": event_date,
            "event_type": event_type,
            "sentiment_score": sentiment_score,
            "ret_3d_pct": ret_3d,
            "ret_5d_pct": ret_5d,
            "benchmark_ret_3d_pct": benchmark_ret_3d,
            "benchmark_ret_5d_pct": benchmark_ret_5d,
            "excess_3d_pct": excess_3d,
            "excess_5d_pct": excess_5d,
            "rlsp_reward_3d": rlsp_reward_3d,
            "rlsp_reward_5d": rlsp_reward_5d,
            "label": label,
            "soft_label": soft_label,
            "recorded_at": date.today().isoformat(),
        }
        self.samples.append(sample)
        return sample

    def compute_summary(self) -> dict:
        """统计当前样本的标签分布、RLSP 奖励与区分度。"""
        total = len(self.samples)
        if total == 0:
            return {
                "total": 0,
                "positive_surprise": 0,
                "negative_surprise": 0,
                "neutral": 0,
                "avg_excess_3d_pct": None,
                "avg_excess_5d_pct": None,
                "avg_rlsp_reward_5d": None,
                "alignment_rate": None,
            }
        pos = sum(1 for s in self.samples if s["label"] == "positive_surprise")
        neg = sum(1 for s in self.samples if s["label"] == "negative_surprise")
        neu = total - pos - neg

        e3 = [s["excess_3d_pct"] for s in self.samples if s["excess_3d_pct"] is not None]
        e5 = [s["excess_5d_pct"] for s in self.samples if s["excess_5d_pct"] is not None]

        r5 = [s["rlsp_reward_5d"] for s in self.samples if s["rlsp_reward_5d"] is not None]
        aligned = sum(1 for s in self.samples if s.get("soft_label", {}).get("aligned"))

        return {
            "total": total,
            "positive_surprise": pos,
            "negative_surprise": neg,
            "neutral": neu,
            "avg_excess_3d_pct": round(sum(e3) / len(e3), 3) if e3 else None,
            "avg_excess_5d_pct": round(sum(e5) / len(e5), 3) if e5 else None,
            "avg_rlsp_reward_5d": round(sum(r5) / len(r5), 4) if r5 else None,
            "alignment_rate": round(aligned / max(total, 1), 3),
        }

    def compute_ranking_discrimination(
        self,
        sentiment_key: str = "sentiment_score",
        return_key: str = "excess_5d_pct",
        top_k: int = 5,
    ) -> dict:
        """在已有样本上计算排序区分度（用于评估情感分析质量）。"""
        return compute_ranking_discrimination(self.samples, sentiment_key, return_key, top_k)

    def export_training_samples(self, min_weight: float = 0.1) -> list[dict]:
        """
        导出可用于未来模型训练的样本（FinGPT 数据过滤）。

        只导出软标签权重 >= min_weight 的样本，权重低的样本被过滤。
        """
        return [
            {
                "instruction": f"分析以下{s.get('event_type', '金融')}新闻的情感",
                "input": f"股票: {s.get('name', '')} ({s.get('code', '')})\n日期: {s.get('event_date', '')}",
                "output": s.get("soft_label", {}).get("hard_label", "neutral"),
                "soft_label_value": s.get("soft_label", {}).get("soft_label", 0.0),
                "weight": s.get("soft_label", {}).get("weight", 0.0),
                "aligned": s.get("soft_label", {}).get("aligned", False),
                "rlsp_reward_5d": s.get("rlsp_reward_5d"),
            }
            for s in self.samples
            if s.get("soft_label", {}).get("weight", 0.0) >= min_weight
        ]

    def export_aligned_samples(self) -> list[dict]:
        """只导出方向与市场走势一致的样本（FinGPT 数据过滤模式）。"""
        return [
            s for s in self.samples
            if s.get("soft_label", {}).get("aligned", False)
        ]

    def export_samples(self) -> list[dict]:
        """导出全部评估样本。"""
        return list(self.samples)

    def save(self) -> None:
        """原子写入样本到磁盘。"""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        data = {
            "schema_version": "2.1",
            "updated_at": date.today().isoformat(),
            "summary": self.compute_summary(),
            "samples": self.samples,
        }
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)


# ============================================================
# 辅助函数
# ============================================================

def _excess_return(ret: Optional[float], benchmark: Optional[float]) -> Optional[float]:
    if ret is None:
        return None
    if benchmark is None:
        return round(ret, 3)
    return round(ret - benchmark, 3)


def _label_from_excess(excess: Optional[float]) -> str:
    if excess is None:
        return "neutral"
    if excess >= 1.0:
        return "positive_surprise"
    if excess <= -1.0:
        return "negative_surprise"
    return "neutral"


def _pearson_r(x: list, y: list) -> float:
    """简化 Pearson 相关系数。"""
    n = len(x)
    if n < 3:
        return 0.0
    mx = sum(x) / n
    my = sum(y) / n
    sx = math.sqrt(sum((v - mx) ** 2 for v in x))
    sy = math.sqrt(sum((v - my) ** 2 for v in y))
    if sx == 0 or sy == 0:
        return 0.0
    cov = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    return cov / (sx * sy)
