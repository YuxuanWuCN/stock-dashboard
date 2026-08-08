# src/llm/sentiment.py —— 金融文本情感分析
#
# 第一阶段采用规则词典基线：中文金融情感词典 + 否定词检测 + 程度词加权。
# 不依赖外部模型，离线可复现。后续可在不改变接口的情况下增加模型增强。

from dataclasses import dataclass, field
from typing import Optional

from .config import SENTIMENT_POSITIVE_THRESHOLD, SENTIMENT_NEGATIVE_THRESHOLD

# 正向词典（金融语境）
POSITIVE_WORDS = frozenset({
    "增长", "上涨", "盈利", "净利", "超预期", "利好", "突破", "新高", "中标",
    "获批", "扩张", "回暖", "回升", "改善", "增持", "回购", "分红", "高增",
    "加速", "放量", "提价", "涨价", "需求旺盛", "订单饱满", "产能利用率高",
    "景气", "转好", "扭亏", "翻倍", "创纪录", "领先", "优势", "强势", "走强",
    "看涨", "推荐", "买入", "增持", "利好", "积极", "乐观", "复苏",
})

# 负向词典（金融语境）
NEGATIVE_WORDS = frozenset({
    "下跌", "亏损", "减值", "计提", "下滑", "下降", "利空", "违约", "退市",
    "处罚", "立案", "调查", "诉讼", "诉讼缠身", "跌破", "新低", "减持", "质押",
    "爆雷", "暴雷", "风险", "警示", "警示函", "退市风险", "商誉", "存货跌价",
    "需求疲软", "订单下滑", "产能过剩", "收缩", "放缓", "走弱", "看跌", "卖出",
    "减持", "悲观", "恶化", "透支", "虚增", "造假", "处罚", "整改", "跌停",
})

# 否定词：翻转情感
NEGATION_WORDS = frozenset({
    "不", "未", "没有", "无", "并非", "难", "难以", "不足", "未能", "尚未",
    "不会", "不看好", "不及预期", "低于", "低于预期", "差于", "不及",
})

# 程度词：放大情感权重
INTENSIFIERS = frozenset({
    "大幅", "明显", "显著", "强烈", "急剧", "迅猛", "快速", "稳步", "持续",
    "创", "历史", "巨额", "严重", "重大", "重大影响", "极度", "非常", "十分",
})


@dataclass
class SentimentResult:
    """单条文本的情感分析结果。"""
    text: str
    label: str          # "positive" | "negative" | "neutral"
    score: float        # 0.0 ~ 1.0，越接近 1 越正面
    positive_hits: list[str] = field(default_factory=list)
    negative_hits: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "score": round(self.score, 3),
            "positive_hits": self.positive_hits,
            "negative_hits": self.negative_hits,
        }


def _apply_negation(sentences: list[str], hits: list[str]) -> list[str]:
    """若句子在否定词后紧跟命中词，则移除该命中。"""
    filtered = []
    for word in hits:
        kept = True
        for s in sentences:
            idx = s.find(word)
            if idx <= 0:
                continue
            prefix = s[max(0, idx - 4):idx]
            if any(neg in prefix for neg in NEGATION_WORDS):
                kept = False
                break
        if kept:
            filtered.append(word)
    return filtered


def _has_negation_prefix(text: str, word: str) -> bool:
    idx = text.find(word)
    if idx <= 0:
        return False
    prefix = text[max(0, idx - 5):idx]
    return any(neg in prefix for neg in NEGATION_WORDS)


def analyze_sentiment(text: str) -> SentimentResult:
    """
    分析单条金融文本情感。

    返回 label: positive/negative/neutral，score 0~1。
    空文本返回 neutral，score 0.5。
    """
    if not text or not text.strip():
        return SentimentResult(text or "", "neutral", 0.5)

    # 从句子维度统计命中（用于否定检测）
    sentences = [s for s in text.replace("\n", " ").split("。") if s.strip()]

    pos_hits = [w for w in POSITIVE_WORDS if w in text and not _has_negation_prefix(text, w)]
    neg_hits = [w for w in NEGATIVE_WORDS if w in text and not _has_negation_prefix(text, w)]

    # 否定检测：若否定词紧邻某命中词，将该词从对立词表移除
    if sentences:
        pos_hits = _apply_negation(sentences, pos_hits)
        neg_hits = _apply_negation(sentences, neg_hits)

    # 去重且保持顺序
    pos_hits = list(dict.fromkeys(pos_hits))
    neg_hits = list(dict.fromkeys(neg_hits))

    # 程度词加权
    intensifier_count = sum(1 for w in INTENSIFIERS if w in text)

    pos_weight = len(pos_hits) * 1.0 + intensifier_count * 0.3
    neg_weight = len(neg_hits) * 1.0 + intensifier_count * 0.3

    total = pos_weight + neg_weight
    if total == 0:
        return SentimentResult(text, "neutral", 0.5)

    score = pos_weight / total

    if score >= SENTIMENT_POSITIVE_THRESHOLD:
        label = "positive"
    elif score <= SENTIMENT_NEGATIVE_THRESHOLD:
        label = "negative"
    else:
        label = "neutral"

    return SentimentResult(
        text=text,
        label=label,
        score=score,
        positive_hits=pos_hits,
        negative_hits=neg_hits,
    )


def analyze_batch(texts: list[str]) -> list[SentimentResult]:
    """批量分析，保持输入顺序。"""
    return [analyze_sentiment(t) for t in texts]
