# -*- coding: utf-8 -*-
"""tests/sector_rotation/test_aggregator.py —— 板块情绪聚合器全量单元测试与质量验证

覆盖：
1. 成分股加权平均情绪计算（正向值、负向值、浮点精度）
2. 成分股情绪离散度/波动率计算（样本标准差 ddof=1）
3. 板块置信度算法（覆盖广度因子、观点一致性惩罚）
4. 3日情绪趋势动态探测（rising / stable / declining）与历史边界
5. 全市场多板块批量聚合与缺失板块中性保底
6. v2.6 LLMSentimentResult 与通用字典适配
7. 交易日历工具与非交易日跨越
8. 极端值、零权值、单票、空输入等边界条件
9. 毫秒级执行时延验证（< 100ms 要求）
"""

import math
import statistics
import time
import pytest

from src.llm.llm_sentiment import LLMSentimentResult
from src.sector_rotation.config import (
    BENCHMARK_MAPPINGS,
    COOLDOWN_DAYS,
    MAX_ROTATION_PER_MONTH,
    MIN_HOLDING_DAYS,
    MIN_TARGET_SENTIMENT,
    ROTATION_EXECUTION_DAYS,
    SECTORS,
    SENTIMENT_DECLINE_THRESHOLD,
    TRANSACTION_COST_RATE,
    TREND_CONFIRM_DAYS,
    TREND_DECLINING,
    TREND_RISING,
    TREND_STABLE,
    get_all_sector_ids,
    get_all_tickers,
    get_sector_config,
    get_sector_for_ticker,
)
from src.sector_rotation.sector_sentiment_aggregator import SectorSentimentAggregator
from src.sector_rotation.utils.sector_utils import (
    SectorState,
    StockSentimentInput,
    add_trading_days,
    from_v26_sentiment,
    is_trading_day,
    trading_days_between,
    validate_confidence,
    validate_news_count,
    validate_sector,
    validate_sentiment_score,
    validate_stock_input,
)


# ============================================================================
# 1. 常规功能单元测试
# ============================================================================

def test_aggregate_weighted_sentiment_math(aggregator: SectorSentimentAggregator, sample_green_stocks: list[StockSentimentInput]) -> None:
    """验证板块加权平均情绪计算符合数学公式 w_i = c_i * max(v_i, 1)。"""
    state = aggregator.aggregate(stocks=sample_green_stocks, sector="green")

    # 手动按公式计算预期值
    weights = [s.sentiment_confidence * max(s.news_count, 1) for s in sample_green_stocks]
    total_w = sum(weights)
    expected_score = sum(w * s.sentiment_score for w, s in zip(weights, sample_green_stocks)) / total_w

    assert state.sector == "green"
    assert state.sector_id == "green"
    assert state.stock_count == 6
    assert state.sentiment_score == pytest.approx(round(expected_score, 4), abs=1e-4)
    assert -1.0 <= state.sentiment_score <= 1.0


def test_calculate_volatility_sample_stdev(aggregator: SectorSentimentAggregator, sample_green_stocks: list[StockSentimentInput]) -> None:
    """验证样本标准差计算 ddof=1 且与标准库 statistics.stdev 完全一致。"""
    scores = [s.sentiment_score for s in sample_green_stocks]
    vol = aggregator.calculate_volatility(scores)
    expected_vol = statistics.stdev(scores)

    assert vol == pytest.approx(expected_vol, abs=1e-5)
    assert vol > 0.0


def test_calculate_confidence_mechanics(aggregator: SectorSentimentAggregator) -> None:
    """验证板块置信度计算模型（覆盖广度因子与离散度一致性扣减）。"""
    weights = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0]  # 6只标的，刚好达到 expected_stocks=6
    confidences = [0.9, 0.9, 0.9, 0.9, 0.9, 0.9]
    volatility = 0.2  # 较低波动率

    conf = aggregator.calculate_confidence(
        weights=weights,
        confidences=confidences,
        volatility=volatility,
        stock_count=6,
    )

    # c_base = 0.9
    # c_breadth = min(1.0, sqrt(6/6)) = 1.0
    # c_consistency = max(0.2, 1.0 - 0.5 * 0.2) = 0.9
    # raw_c = 0.9 * 1.0 * 0.9 = 0.81
    assert conf == pytest.approx(0.81, abs=1e-4)


def test_update_trend_detection_states(aggregator: SectorSentimentAggregator) -> None:
    """验证 3 日情绪趋势动态检测（上升、下沉、平稳、数据不足）。"""
    # 连续下沉：0.2 -> 0.0 -> -0.2 (两端变动 -0.4 < -0.05)
    declining_trend = aggregator.update_trend("storage", -0.2, [0.2, 0.0])
    assert declining_trend == TREND_DECLINING

    # 连续上升：-0.1 -> 0.1 -> 0.35 (两端变动 +0.45 > 0.05)
    rising_trend = aggregator.update_trend("gold", 0.35, [-0.1, 0.1])
    assert rising_trend == TREND_RISING

    # 平稳微调：0.40 -> 0.41 -> 0.42 (两端变动 0.02 <= 0.05)
    stable_trend = aggregator.update_trend("green", 0.42, [0.40, 0.41])
    assert stable_trend == TREND_STABLE

    # 历史观测不足 3 日
    insufficient_trend = aggregator.update_trend("storage", 0.50, [0.30])
    assert insufficient_trend == TREND_STABLE

    # 无历史数据
    none_history_trend = aggregator.update_trend("gold", 0.10, None)
    assert none_history_trend == TREND_STABLE


def test_aggregate_market_batch(
    aggregator: SectorSentimentAggregator,
    sample_green_stocks: list[StockSentimentInput],
    sample_storage_stocks: list[StockSentimentInput],
    sample_gold_stocks: list[StockSentimentInput],
) -> None:
    """验证批量全市场聚合与板块分组。"""
    universe = sample_green_stocks + sample_storage_stocks + sample_gold_stocks
    history_map = {
        "storage": [0.40, 0.55],
        "gold": [0.50, 0.45],
    }

    result = aggregator.aggregate_market(universe, history_map=history_map)

    assert "green" in result
    assert "storage" in result
    assert "gold" in result

    assert result["green"].stock_count == 6
    assert result["storage"].stock_count == 6
    assert result["gold"].stock_count == 7

    # 存储处于高景气态 (得分 > 0.5)
    assert result["storage"].sentiment_score > 0.5
    assert result["storage"].sentiment_trend == TREND_RISING


def test_aggregate_market_missing_sector_fills_neutral(
    aggregator: SectorSentimentAggregator,
    sample_green_stocks: list[StockSentimentInput],
) -> None:
    """验证全市场输入中缺失某个板块时，自动填充中性默认状态。"""
    # 仅提供绿色新能源，缺存储和黄金
    result = aggregator.aggregate_market(sample_green_stocks)

    assert "green" in result
    assert "storage" in result
    assert "gold" in result

    # 缺失板块填充中性状态
    storage_state = result["storage"]
    assert storage_state.stock_count == 0
    assert storage_state.sentiment_score == 0.0
    assert storage_state.volatility == 0.0
    assert storage_state.confidence == 0.0
    assert storage_state.sentiment_trend == TREND_STABLE


# ============================================================================
# 2. 边界条件与极端异常测试
# ============================================================================

def test_empty_constituent_stocks_neutral_state(aggregator: SectorSentimentAggregator) -> None:
    """边界测试：成分股列表为空时返回标准中性状态。"""
    state = aggregator.aggregate(stocks=[], sector="green")

    assert state.sector == "green"
    assert state.stock_count == 0
    assert state.sentiment_score == 0.0
    assert state.volatility == 0.0
    assert state.confidence == 0.0
    assert state.sentiment_trend == TREND_STABLE
    assert state.stock_sentiments == []


def test_single_stock_volatility_zero_and_breadth_penalty(aggregator: SectorSentimentAggregator) -> None:
    """边界测试：单票 (N=1) 时波动率为 0，且置信度受样本覆盖广度惩罚。"""
    single_stock = [
        StockSentimentInput(
            code="688525",
            name="佰维存储",
            sector="storage",
            sentiment_score=0.8,
            sentiment_confidence=0.9,
            news_count=3,
        )
    ]
    state = aggregator.aggregate(stocks=single_stock, sector="storage")

    assert state.stock_count == 1
    assert state.sentiment_score == 0.8
    assert state.volatility == 0.0
    # 广度因子 = sqrt(1 / 6) ≈ 0.4082, 置信度远低于原始 0.9
    assert state.confidence < 0.5
    assert state.confidence > 0.0


def test_all_identical_scores_zero_volatility(aggregator: SectorSentimentAggregator) -> None:
    """边界测试：所有成分股得分完全一致时波动率为 0。"""
    identical_stocks = [
        StockSentimentInput(code=f"00000{i}", sector="storage", sentiment_score=0.5, sentiment_confidence=0.8)
        for i in range(1, 6)
    ]
    state = aggregator.aggregate(stocks=identical_stocks, sector="storage")

    assert state.sentiment_score == 0.5
    assert state.volatility == 0.0
    assert state.stock_count == 5


def test_zero_news_volume_and_zero_confidence(aggregator: SectorSentimentAggregator) -> None:
    """边界测试：新闻篇数为0或置信度为0时降级为等权算术平均。"""
    zero_weight_stocks = [
        StockSentimentInput(code="001", sector="gold", sentiment_score=0.2, sentiment_confidence=0.0, news_count=0),
        StockSentimentInput(code="002", sector="gold", sentiment_score=0.6, sentiment_confidence=0.0, news_count=0),
    ]
    state = aggregator.aggregate(stocks=zero_weight_stocks, sector="gold")

    # 退化为等权平均 (0.2 + 0.6) / 2 = 0.4
    assert state.sentiment_score == pytest.approx(0.4, abs=1e-4)
    assert state.stock_count == 2


def test_extreme_scores_clipped_to_bounds(aggregator: SectorSentimentAggregator) -> None:
    """边界测试：极大值与极小值被安全截断在 [-1.0, 1.0]。"""
    extreme_stocks = [
        {"code": "001", "sector": "gold", "score": 2.5, "confidence": 0.8},
        {"code": "002", "sector": "gold", "score": -3.0, "confidence": 0.8},
    ]
    input1 = validate_stock_input(extreme_stocks[0])
    input2 = validate_stock_input(extreme_stocks[1])

    assert input1.sentiment_score == 1.0
    assert input2.sentiment_score == -1.0


def test_conflicting_sentiment_dispersion(aggregator: SectorSentimentAggregator) -> None:
    """边界测试：观点极端对立（一半 +1.0，一半 -1.0）时均值归零、波动率极高、置信度惩罚。"""
    polarized_stocks = [
        StockSentimentInput(code=f"pos_{i}", sector="green", sentiment_score=1.0, sentiment_confidence=0.9, news_count=2)
        for i in range(3)
    ] + [
        StockSentimentInput(code=f"neg_{i}", sector="green", sentiment_score=-1.0, sentiment_confidence=0.9, news_count=2)
        for i in range(3)
    ]

    state = aggregator.aggregate(stocks=polarized_stocks, sector="green")

    assert state.sentiment_score == pytest.approx(0.0, abs=1e-4)
    assert state.volatility > 1.0  # 离散度极高
    assert state.confidence < 0.6  # 一致性受重度惩罚


def test_mixed_sectors_in_stocks_partitioned(
    aggregator: SectorSentimentAggregator,
    sample_green_stocks: list[StockSentimentInput],
    sample_storage_stocks: list[StockSentimentInput],
) -> None:
    """边界测试：传入混杂板块成分股时，仅聚合目标板块标的。"""
    mixed = sample_green_stocks + sample_storage_stocks
    green_state = aggregator.aggregate(stocks=mixed, sector="green")
    storage_state = aggregator.aggregate(stocks=mixed, sector="storage")

    assert green_state.stock_count == 6
    assert storage_state.stock_count == 6
    assert green_state.sector == "green"
    assert storage_state.sector == "storage"


# ============================================================================
# 3. v2.6 兼容转换与多格式数据适配
# ============================================================================

def test_v26_dict_input_adapter(sample_v26_dict_stocks: list[dict], aggregator: SectorSentimentAggregator) -> None:
    """验证 v2.6 原始字典能够被无缝解析并聚合。"""
    state = aggregator.aggregate(stocks=sample_v26_dict_stocks, sector="storage")

    assert state.sector == "storage"
    assert state.stock_count == 2
    assert state.sentiment_score > 0.5


def test_v26_llm_sentiment_result_adapter(
    aggregator: SectorSentimentAggregator,
    sample_llm_result_stocks: list[tuple[str, LLMSentimentResult]],
) -> None:
    """验证直接接收 LLMSentimentResult 实例并自动通过股票代码匹配板块。"""
    adapted_inputs: list[StockSentimentInput] = []
    for ticker, res in sample_llm_result_stocks:
        inp = from_v26_sentiment(res, code=ticker)
        adapted_inputs.append(inp)

    # 603986 兆易创新 与 688008 澜起科技 均属于 storage 板块
    assert adapted_inputs[0].sector == "storage"
    assert adapted_inputs[0].sentiment_score == 0.82
    assert adapted_inputs[1].sector == "storage"
    assert adapted_inputs[1].sentiment_score == 0.15

    state = aggregator.aggregate(stocks=adapted_inputs, sector="storage")
    assert state.stock_count == 2
    assert state.sector == "storage"


def test_from_v26_sentiment_stock_input_passthrough() -> None:
    """验证 from_v26_sentiment 接收已有 StockSentimentInput 时正常传递与字段覆盖。"""
    original = StockSentimentInput(code="001258", name="立新能源", sector="green", sentiment_score=0.4)
    copied = from_v26_sentiment(original, name="覆盖名称")

    assert copied.code == "001258"
    assert copied.name == "覆盖名称"
    assert copied.sector == "green"
    assert copied.sentiment_score == 0.4


# ============================================================================
# 4. 交易日历辅助工具验证
# ============================================================================

def test_calendar_helpers_trading_days() -> None:
    """验证交易日判断（跳过周六周日）。"""
    # 2026-10-12 为周一，2026-10-16 为周五，2026-10-17 为周六
    assert is_trading_day("2026-10-12") is True
    assert is_trading_day("2026-10-16") is True
    assert is_trading_day("2026-10-17") is False
    assert is_trading_day("2026-10-18") is False


def test_calendar_helpers_diff_and_add() -> None:
    """验证交易日差值计算与交易日累加函数。"""
    # 从周五 2026-10-16 增加 1 个交易日应到达周一 2026-10-19
    next_day = add_trading_days("2026-10-16", 1)
    assert next_day == "2026-10-19"

    # 增加 5 个交易日
    plus_5 = add_trading_days("2026-10-12", 5)
    assert plus_5 == "2026-10-19"

    # 差值计算
    days = trading_days_between("2026-10-12", "2026-10-19")
    assert days == 5

    # 相同日期
    assert trading_days_between("2026-10-12", "2026-10-12") == 0


# ============================================================================
# 5. 配置与校验工具验证
# ============================================================================

def test_config_constants_integrity() -> None:
    """验证所有核心配置常量与阈值符合项目规范。"""
    assert SENTIMENT_DECLINE_THRESHOLD == -0.3
    assert TREND_CONFIRM_DAYS == 3
    assert MIN_TARGET_SENTIMENT == 0.5
    assert ROTATION_EXECUTION_DAYS == 3
    assert TRANSACTION_COST_RATE == 0.001
    assert MIN_HOLDING_DAYS == 5
    assert MAX_ROTATION_PER_MONTH == 3
    assert COOLDOWN_DAYS == 7

    assert len(SECTORS) == 3
    assert len(SECTORS["green"].tickers) == 6
    assert len(SECTORS["storage"].tickers) == 6
    assert len(SECTORS["gold"].tickers) == 7

    assert BENCHMARK_MAPPINGS["green"] == "000688"
    assert BENCHMARK_MAPPINGS["storage"] == "000688"
    assert BENCHMARK_MAPPINGS["gold"] == "000001"


def test_config_query_functions() -> None:
    """验证板块查询辅助函数。"""
    all_sectors = get_all_sector_ids()
    assert all_sectors == ["green", "storage", "gold"]

    all_tickers = get_all_tickers()
    assert len(all_tickers) == 19  # 6 + 6 + 7

    cfg = get_sector_config("storage")
    assert cfg.name == "存储芯片"
    assert cfg.benchmark == "000688"

    assert get_sector_for_ticker("688525") == "storage"
    assert get_sector_for_ticker("001258") == "green"
    assert get_sector_for_ticker("600547") == "gold"
    assert get_sector_for_ticker("999999") is None

    with pytest.raises(KeyError):
        get_sector_config("invalid_sector")


def test_validation_functions_and_error_handling() -> None:
    """验证字段级校验器异常抛出与边界截断。"""
    assert validate_sentiment_score(0.85) == 0.85
    assert validate_sentiment_score(-1.5) == -1.0
    assert validate_sentiment_score(3.0) == 1.0

    with pytest.raises(ValueError):
        validate_sentiment_score("invalid_number")

    with pytest.raises(ValueError):
        validate_sentiment_score(float("nan"))

    assert validate_confidence(0.7) == 0.7
    assert validate_confidence(-0.2) == 0.0
    assert validate_confidence(1.5) == 1.0
    assert validate_confidence("not_a_float") == 0.5

    assert validate_news_count(10) == 10
    assert validate_news_count(-5) == 0
    assert validate_news_count("abc") == 1

    assert validate_sector("GREEN") == "green"
    with pytest.raises(ValueError):
        validate_sector("unknown_sector")
    assert validate_sector("custom_sec", allow_unknown=True) == "custom_sec"


def test_sector_state_dataclass_properties_and_serialization() -> None:
    """验证 SectorState 的 sector / sector_id 双属性访问及 JSON 序列化。"""
    state = SectorState(
        sector_id="storage",
        sentiment_score=0.62,
        sentiment_trend=TREND_RISING,
        volatility=0.15,
        stock_count=6,
        confidence=0.88,
        last_updated="2026-10-12 15:00:00",
        stock_sentiments=[0.6, 0.65, 0.7],
    )

    assert state.sector == "storage"
    assert state.sector_id == "storage"

    # 修改 sector_id 测试同步
    state.sector_id = "gold"
    assert state.sector == "gold"

    # to_dict 序列化检查
    d = state.to_dict()
    assert d["sector"] == "gold"
    assert d["sector_id"] == "gold"
    assert d["sentiment_score"] == 0.62
    assert d["sentiment_trend"] == TREND_RISING
    assert d["stock_count"] == 6
    assert len(d["stock_sentiments"]) == 3


# ============================================================================
# 6. 性能与延迟基准验证
# ============================================================================

def test_aggregation_latency_benchmark(
    aggregator: SectorSentimentAggregator,
    sample_green_stocks: list[StockSentimentInput],
) -> None:
    """验证情绪聚合执行时延远低于 100ms 约束（单次调用 < 1ms）。"""
    # 预热
    _ = aggregator.aggregate(sample_green_stocks, "green")

    start_time = time.perf_counter()
    iterations = 200
    for _ in range(iterations):
        _ = aggregator.aggregate(sample_green_stocks, "green")
    total_elapsed = time.perf_counter() - start_time

    avg_ms = (total_elapsed / iterations) * 1000.0
    # 单次必须严格小于 5ms（通常 < 0.2ms）
    assert avg_ms < 5.0
    assert total_elapsed < 1.0  # 200 次累计在 1 秒以内


# ============================================================================
# 7. 全分支覆盖强化测试 (提升 sector_utils 与 aggregator 覆盖率至 95%+)
# ============================================================================

def test_stock_sentiment_input_to_dict_and_infinities() -> None:
    """验证 StockSentimentInput 序列化与无穷大/无穷小情绪得分截断。"""
    stock = StockSentimentInput(
        code="601012",
        name="隆基绿能",
        sector="green",
        sentiment_score=0.45678,
        sentiment_confidence=0.88888,
        news_count=5,
        timestamp="2026-10-12 10:00:00",
    )
    d = stock.to_dict()
    assert d["code"] == "601012"
    assert d["name"] == "隆基绿能"
    assert d["sector"] == "green"
    assert d["sentiment_score"] == 0.4568
    assert d["sentiment_confidence"] == 0.8889
    assert d["news_count"] == 5
    assert d["timestamp"] == "2026-10-12 10:00:00"

    # 正负无穷大数值截断
    assert validate_sentiment_score(float("inf")) == 1.0
    assert validate_sentiment_score(float("-inf")) == -1.0


def test_date_parsing_variations_and_failures() -> None:
    """验证多种日期类型（datetime, date, 紧凑格式, ISO 格式）与异常抛出。"""
    from datetime import date, datetime

    # datetime 与 date 对象直接解析
    dt = datetime(2026, 10, 12, 14, 30, 0)
    d = date(2026, 10, 12)
    assert is_trading_day(dt) is True
    assert is_trading_day(d) is True

    # 斜杠与紧凑日期格式
    assert is_trading_day("2026/10/12") is True
    assert is_trading_day("20261012") is True
    assert is_trading_day("2026-10-12T08:00:00Z") is True

    # 无法解析的日期抛出 ValueError
    with pytest.raises(ValueError):
        is_trading_day("not-a-valid-date-str")


def test_calendar_negative_trading_day_steps() -> None:
    """验证反向交易日推移（负数天数）与反向交易日区间计算。"""
    # 反向差值计算（start > end）
    days_back = trading_days_between("2026-10-19", "2026-10-12")
    assert days_back == -5

    # 反向累减交易日（跨越周末到达上周一）
    start_monday = add_trading_days("2026-10-19", -5)
    assert start_monday == "2026-10-12"


def test_from_v26_sentiment_alternative_keys_and_custom_objects() -> None:
    """验证从字典别名键与自定义对象属性中完整提取情绪特征。"""
    # 字典别名测试：sentiment, volume, time
    alias_dict = {
        "ticker": "688525",
        "stock_name": "佰维存储",
        "sector_id": "storage",
        "sentiment": -0.42,
        "sentiment_confidence": 0.85,
        "volume": 7,
        "time": "2026-10-12 16:00:00",
    }
    extracted = from_v26_sentiment(alias_dict)
    assert extracted.code == "688525"
    assert extracted.name == "佰维存储"
    assert extracted.sector == "storage"
    assert extracted.sentiment_score == -0.42
    assert extracted.news_count == 7
    assert extracted.timestamp == "2026-10-12 16:00:00"

    # 自定义通用对象属性提取测试
    class CustomObj:
        def __init__(self) -> None:
            self.code = "600547"
            self.name = "山东黄金"
            self.sector = "gold"
            self.sentiment_score = 0.58
            self.confidence = 0.91
            self.news_count = 6
            self.timestamp = "2026-10-12"

    obj = CustomObj()
    extracted_obj = from_v26_sentiment(obj)
    assert extracted_obj.code == "600547"
    assert extracted_obj.name == "山东黄金"
    assert extracted_obj.sector == "gold"
    assert extracted_obj.sentiment_score == 0.58
    assert extracted_obj.sentiment_confidence == 0.91
    assert extracted_obj.news_count == 6


def test_aggregate_market_extra_sectors_and_untracked_stocks(
    aggregator: SectorSentimentAggregator,
    sample_green_stocks: list[StockSentimentInput],
) -> None:
    """验证批量聚合包含自定义板块与未标记板块的孤立股票。"""
    extra_stock = StockSentimentInput(
        code="999999",
        name="未知概念股",
        sector="custom_tech",
        sentiment_score=0.33,
        sentiment_confidence=0.8,
        news_count=2,
    )
    untracked_stock = StockSentimentInput(
        code="888888",
        name="无板块股",
        sector="",  # 且代码未在任何已知板块中注册
        sentiment_score=0.1,
        sentiment_confidence=0.5,
        news_count=1,
    )
    full_universe = sample_green_stocks + [extra_stock, untracked_stock]

    market_res = aggregator.aggregate_market(full_universe)

    assert "green" in market_res
    assert "custom_tech" in market_res
    assert market_res["custom_tech"].stock_count == 1
    assert market_res["custom_tech"].sentiment_score == 0.33
    # 无板块股不作为独立板块出现
    assert "" not in market_res


def test_calculate_confidence_zero_count_and_zero_weight_fallbacks(
    aggregator: SectorSentimentAggregator,
) -> None:
    """验证板块置信度在 stock_count=0 及全零权重时的安全计算路径。"""
    # stock_count 为 0 时直接返回 0.0
    zero_count_conf = aggregator.calculate_confidence(
        weights=[],
        confidences=[],
        volatility=0.0,
        stock_count=0,
    )
    assert zero_count_conf == 0.0

    # 全零权重时采用置信度等权平均
    zero_weights_conf = aggregator.calculate_confidence(
        weights=[0.0, 0.0],
        confidences=[0.8, 0.8],
        volatility=0.1,
        stock_count=2,
    )
    # c_base = 0.8, c_breadth = sqrt(2/6) ≈ 0.577, c_consistency = 1 - 0.5*0.1 = 0.95
    assert zero_weights_conf > 0.4
    assert zero_weights_conf <= 1.0
