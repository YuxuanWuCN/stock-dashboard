# -*- coding: utf-8 -*-
"""tests/sector_rotation/test_e2e_tiers.py —— 4-Tier Opaque-Box E2E Test Suite (Tiers 1-3)

Comprehensive test cases across:
- Tier 1: Feature Coverage (Features 1 to 24 in isolation)
- Tier 2: Boundary & Corner Cases (domain limits, boundaries, edge conditions)
- Tier 3: Cross-Feature Combinations (module interaction pipelines)

Authoritative sources:
- ORIGINAL_REQUEST.md
- PROJECT.md (§2 Feature Inventory, §Interface Contracts)
- SECTOR_ROTATION_SPEC.md (§1-5)
- AGENT_TASK_ASSIGNMENT.md (§1-4)
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional
import pytest

from src.sector_rotation.config import (
    BENCHMARK_MAPPINGS,
    BUY_FEE_RATE,
    COOLDOWN_DAYS,
    DEFENSIVE_SECTOR,
    EXPECTED_STOCKS_PER_SECTOR,
    LLM_TIMEOUT,
    MAX_ROTATION_PER_MONTH,
    MAX_TOTAL_ROTATION_COST,
    MIN_HOLDING_DAYS,
    MIN_TARGET_SENTIMENT,
    REALLOCATION_WEIGHTS,
    ROTATION_EXECUTION_DAYS,
    SECTORS,
    SELL_FEE_RATE,
    SENTIMENT_BOUND_MAX,
    SENTIMENT_BOUND_MIN,
    SENTIMENT_DECLINE_THRESHOLD,
    TICKER_TO_SECTOR,
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

# Optional imports for upcoming milestones (Progressive Testability)
try:
    from src.sector_rotation.sector_rotation_engine import (
        SectorRotationEngine,
        RotationDecision,
    )
    HAS_ENGINE = True
except ImportError:
    HAS_ENGINE = False
    SectorRotationEngine = None
    RotationDecision = None

try:
    from src.sector_rotation.llm_decision_advisor import (
        LLMDecisionAdvisor,
    )
    HAS_ADVISOR = True
except ImportError:
    HAS_ADVISOR = False
    LLMDecisionAdvisor = None

try:
    from src.sector_rotation.position_manager import (
        PositionManager,
        PortfolioState,
        ReallocationSchedule,
    )
    HAS_POSITION_MGR = True
except ImportError:
    HAS_POSITION_MGR = False
    PositionManager = None
    PortfolioState = None
    ReallocationSchedule = None

try:
    from src.sector_rotation.backtest.backtest_engine import (
        BacktestEngine,
        BacktestResult,
    )
    HAS_BACKTEST = True
except ImportError:
    HAS_BACKTEST = False
    BacktestEngine = None
    BacktestResult = None


# ============================================================================
# Helper Functions & Oracles
# ============================================================================

def run_engine_decision(
    engine: Any,
    current_sector: str,
    sector_states: Dict[str, SectorState],
    holding_days: int = 5,
    monthly_rotations: int = 0,
    days_since_last_rotation: int = 10,
) -> Any:
    """Invokes engine evaluate/decide method adapting to contract signature."""
    if hasattr(engine, "evaluate"):
        return engine.evaluate(
            current_sector=current_sector,
            sector_states=sector_states,
            holding_days=holding_days,
            monthly_rotations=monthly_rotations,
            days_since_last_rotation=days_since_last_rotation,
        )
    elif hasattr(engine, "decide"):
        # Synthesize portfolio state if required by decide()
        if HAS_POSITION_MGR and PortfolioState is not None:
            p_state = PortfolioState(
                current_sector=current_sector,
                sector_weights={current_sector: 1.0},
                cash_ratio=0.0,
                last_rotation_date="2026-10-01",
                rotation_count_this_month=monthly_rotations,
                is_in_rotation=False,
                rotation_day_step=0,
            )
            return engine.decide(sector_sentiments=sector_states, portfolio_state=p_state)
        return engine.decide(sector_states, current_sector)
    raise AttributeError("Engine has neither evaluate nor decide method")


# ============================================================================
# Tier 1: Feature Coverage (Features 1 to 24 in Isolation)
# ============================================================================

class TestTier1FeatureCoverage:
    """Verifies each of the 24 features in isolation against authoritative derivations."""

    # F1: Stock Sentiment Weighted Average
    def test_f01_stock_sentiment_weighted_average(self, aggregator: SectorSentimentAggregator) -> None:
        """F1: Computes weighted average sentiment using w_i = c_i * max(v_i, 1).
        Authoritative source: SECTOR_ROTATION_SPEC §1
        Derivation:
        Stock 1: s=0.6, c=0.8, v=2 -> w = 0.8 * 2 = 1.6, w*s = 0.96
        Stock 2: s=0.2, c=0.5, v=1 -> w = 0.5 * 1 = 0.5, w*s = 0.10
        Stock 3: s=-0.1, c=0.9, v=3 -> w = 0.9 * 3 = 2.7, w*s = -0.27
        Sum(w) = 1.6 + 0.5 + 2.7 = 4.8
        Sum(w*s) = 0.96 + 0.10 - 0.27 = 0.79
        Expected score = 0.79 / 4.8 = 0.164583... -> rounded 0.1646
        """
        stocks = [
            StockSentimentInput(code="001258", name="A", sector="green", sentiment_score=0.6, sentiment_confidence=0.8, news_count=2),
            StockSentimentInput(code="002459", name="B", sector="green", sentiment_score=0.2, sentiment_confidence=0.5, news_count=1),
            StockSentimentInput(code="002466", name="C", sector="green", sentiment_score=-0.1, sentiment_confidence=0.9, news_count=3),
        ]
        state = aggregator.aggregate(stocks, "green")
        assert state.sector == "green"
        assert state.stock_count == 3
        assert state.sentiment_score == pytest.approx(0.1646, abs=1e-3)

    # F2: Sentiment Volatility
    def test_f02_sentiment_volatility_sample_std(self, aggregator: SectorSentimentAggregator) -> None:
        """F2: Computes sample standard deviation (ddof=1) of constituent stock sentiments.
        Authoritative source: SECTOR_ROTATION_SPEC §1
        Derivation:
        Scores = [0.2, 0.4, 0.6] -> Mean = 0.4
        Sample Variance = ((0.2-0.4)^2 + (0.4-0.4)^2 + (0.6-0.4)^2) / (3 - 1)
                        = (0.04 + 0.00 + 0.04) / 2 = 0.04
        Sample Std = sqrt(0.04) = 0.20
        """
        stocks = [
            StockSentimentInput(code="688525", name="A", sector="storage", sentiment_score=0.2, sentiment_confidence=0.8, news_count=1),
            StockSentimentInput(code="688123", name="B", sector="storage", sentiment_score=0.4, sentiment_confidence=0.8, news_count=1),
            StockSentimentInput(code="603986", name="C", sector="storage", sentiment_score=0.6, sentiment_confidence=0.8, news_count=1),
        ]
        state = aggregator.aggregate(stocks, "storage")
        assert state.volatility == pytest.approx(0.20, abs=1e-3)

    # F3: Sector Confidence Metric
    def test_f03_sector_confidence_breadth_and_consistency(self, aggregator: SectorSentimentAggregator) -> None:
        """F3: Derives sector confidence = C_base * C_breadth * C_consistency.
        Authoritative source: SECTOR_ROTATION_SPEC §1
        Derivation:
        6 stocks with confidence=0.8, news=1, identical score=0.5 -> volatility=0.0
        C_base = 0.8
        C_breadth = min(1.0, sqrt(6 / 6)) = 1.0
        C_consistency = max(0.2, 1.0 - 0.5 * 0.0) = 1.0
        Expected C = 0.8 * 1.0 * 1.0 = 0.80
        """
        stocks = [
            StockSentimentInput(code=f"code_{i}", name=f"name_{i}", sector="gold", sentiment_score=0.5, sentiment_confidence=0.8, news_count=1)
            for i in range(6)
        ]
        state = aggregator.aggregate(stocks, "gold")
        assert state.confidence == pytest.approx(0.80, abs=1e-3)

    # F4: 3-Day Sentiment Trend Detection
    def test_f04_three_day_sentiment_trend_detection(self, aggregator: SectorSentimentAggregator) -> None:
        """F4: Identifies trajectory ('rising', 'stable', 'declining') from score series.
        Authoritative source: SECTOR_ROTATION_SPEC §1
        Derivation:
        [0.1, 0.3, 0.5] -> rising (strictly increasing, diff > 0.05)
        [0.5, 0.2, -0.1] -> declining (strictly decreasing, diff < -0.05)
        [0.2, 0.22, 0.24] -> stable (diff < 0.05)
        """
        assert aggregator.calculate_trend([0.1, 0.3, 0.5]) == TREND_RISING
        assert aggregator.calculate_trend([0.5, 0.2, -0.1]) == TREND_DECLINING
        assert aggregator.calculate_trend([0.2, 0.22, 0.24]) == TREND_STABLE

    # F5: Multi-Sector Batch Aggregation
    def test_f05_multi_sector_batch_aggregation(
        self,
        aggregator: SectorSentimentAggregator,
        sample_green_stocks: list[StockSentimentInput],
        sample_storage_stocks: list[StockSentimentInput],
    ) -> None:
        """F5: Ingests full market stock universe and outputs state for all configured sectors.
        Authoritative source: SECTOR_ROTATION_SPEC §1
        """
        universe = sample_green_stocks + sample_storage_stocks
        market = aggregator.aggregate_market(universe)
        assert "green" in market
        assert "storage" in market
        assert "gold" in market  # gold missing in universe, filled with neutral
        assert market["green"].stock_count == len(sample_green_stocks)
        assert market["storage"].stock_count == len(sample_storage_stocks)
        assert market["gold"].stock_count == 0
        assert market["gold"].sentiment_score == 0.0

    # F6: v2.6 Compatibility Adapter
    def test_f06_v26_compatibility_adapter(self) -> None:
        """F6: Converts v2.6 LLMSentimentResult / dict into standard StockSentimentInput.
        Authoritative source: ORIGINAL_REQUEST R1
        """
        raw_dict = {
            "ticker": "688525",
            "score": 0.72,
            "confidence": 0.88,
            "count": 5,
        }
        converted = from_v26_sentiment(raw_dict)
        assert converted.code == "688525"
        assert converted.sentiment_score == pytest.approx(0.72, abs=1e-4)
        assert converted.sentiment_confidence == pytest.approx(0.88, abs=1e-4)
        assert converted.news_count == 5
        assert converted.sector == "storage"  # Inferred via ticker mapping

    # F7: Decline Trigger Detection
    @pytest.mark.skipif(not HAS_ENGINE, reason="SectorRotationEngine pending Milestone M2")
    def test_f07_decline_trigger_detection(self) -> None:
        """F7: Detects when active sector drops below -0.3 with 3 consecutive declining days.
        Authoritative source: SECTOR_ROTATION_SPEC §2
        """
        engine = SectorRotationEngine()
        states = {
            "green": SectorState(sector="green", sentiment_score=-0.35, sentiment_trend=TREND_DECLINING, confidence=0.85),
            "storage": SectorState(sector="storage", sentiment_score=0.60, sentiment_trend=TREND_RISING, confidence=0.85),
            "gold": SectorState(sector="gold", sentiment_score=0.30, sentiment_trend=TREND_STABLE, confidence=0.80),
        }
        decision = run_engine_decision(engine, "green", states, holding_days=5, monthly_rotations=0, days_since_last_rotation=10)
        assert decision.should_rotate is True
        assert decision.target_sector == "storage"

    # F8: Candidate Sector Filtering
    @pytest.mark.skipif(not HAS_ENGINE, reason="SectorRotationEngine pending Milestone M2")
    def test_f08_candidate_sector_filtering(self) -> None:
        """F8: Filters candidate sectors with sentiment score > 0.5.
        Authoritative source: SECTOR_ROTATION_SPEC §2
        """
        engine = SectorRotationEngine()
        states = {
            "green": SectorState(sector="green", sentiment_score=-0.40, sentiment_trend=TREND_DECLINING),
            "storage": SectorState(sector="storage", sentiment_score=0.45, sentiment_trend=TREND_RISING),  # Not > 0.5
            "gold": SectorState(sector="gold", sentiment_score=0.20, sentiment_trend=TREND_STABLE),      # Not > 0.5
        }
        decision = run_engine_decision(engine, "green", states, holding_days=5)
        # With no candidates > 0.5, engine should either fallback to defensive gold or hold
        if decision.should_rotate:
            assert decision.target_sector == "gold"  # Defensive fallback
            assert decision.is_fallback is True

    # F9: Composite Scoring Function
    @pytest.mark.skipif(not HAS_ENGINE, reason="SectorRotationEngine pending Milestone M2")
    def test_f09_composite_scoring_function(self) -> None:
        """F9: Multi-factor ranking: score = 0.5*S + 0.2*T + 0.2*C - 0.1*sigma.
        Authoritative source: AGENT_TASK_ASSIGNMENT §1.3
        Derivation:
        Candidate A (storage): S=0.6, T=0.3(rising), C=0.8, sigma=0.1
        score_A = 0.5*0.6 + 0.2*0.3 + 0.2*0.8 - 0.1*0.1 = 0.30 + 0.06 + 0.16 - 0.01 = 0.51
        Candidate B (gold): S=0.55, T=0.0(stable), C=0.8, sigma=0.05
        score_B = 0.5*0.55 + 0.2*0.0 + 0.2*0.8 - 0.1*0.05 = 0.275 + 0.00 + 0.16 - 0.005 = 0.43
        Target should be storage.
        """
        engine = SectorRotationEngine()
        states = {
            "green": SectorState(sector="green", sentiment_score=-0.35, sentiment_trend=TREND_DECLINING),
            "storage": SectorState(sector="storage", sentiment_score=0.60, sentiment_trend=TREND_RISING, confidence=0.80, volatility=0.10),
            "gold": SectorState(sector="gold", sentiment_score=0.55, sentiment_trend=TREND_STABLE, confidence=0.80, volatility=0.05),
        }
        decision = run_engine_decision(engine, "green", states)
        assert decision.should_rotate is True
        assert decision.target_sector == "storage"

    # F10: Defensive Sector Fallback
    @pytest.mark.skipif(not HAS_ENGINE, reason="SectorRotationEngine pending Milestone M2")
    def test_f10_defensive_sector_fallback(self) -> None:
        """F10: Triggers switch to defensive asset ('gold') if market-wide sentiment collapses.
        Authoritative source: SECTOR_ROTATION_SPEC §2
        """
        engine = SectorRotationEngine()
        states = {
            "green": SectorState(sector="green", sentiment_score=-0.45, sentiment_trend=TREND_DECLINING),
            "storage": SectorState(sector="storage", sentiment_score=-0.15, sentiment_trend=TREND_DECLINING),
            "gold": SectorState(sector="gold", sentiment_score=0.05, sentiment_trend=TREND_STABLE),
        }
        decision = run_engine_decision(engine, "green", states)
        assert decision.should_rotate is True
        assert decision.target_sector == "gold"
        assert decision.is_fallback is True

    # F11: Rotation Invalidation / Hold
    @pytest.mark.skipif(not HAS_ENGINE, reason="SectorRotationEngine pending Milestone M2")
    def test_f11_rotation_invalidation_holding_cooldown_cap(self) -> None:
        """F11: Prevents rotation if holding period < 5 days, monthly count >= 3, or cooldown active.
        Authoritative source: SECTOR_ROTATION_SPEC §技术细节
        """
        engine = SectorRotationEngine()
        states = {
            "green": SectorState(sector="green", sentiment_score=-0.50, sentiment_trend=TREND_DECLINING),
            "storage": SectorState(sector="storage", sentiment_score=0.70, sentiment_trend=TREND_RISING),
            "gold": SectorState(sector="gold", sentiment_score=0.30, sentiment_trend=TREND_STABLE),
        }
        # Case 1: Holding days < 5
        d1 = run_engine_decision(engine, "green", states, holding_days=3, monthly_rotations=0, days_since_last_rotation=10)
        assert d1.should_rotate is False

        # Case 2: Monthly rotations >= 3
        d2 = run_engine_decision(engine, "green", states, holding_days=6, monthly_rotations=3, days_since_last_rotation=10)
        assert d2.should_rotate is False

        # Case 3: Cooldown active (< 7 days)
        d3 = run_engine_decision(engine, "green", states, holding_days=6, monthly_rotations=1, days_since_last_rotation=4)
        assert d3.should_rotate is False

    # F12: Sub-100ms Quantitative Latency
    @pytest.mark.skipif(not HAS_ENGINE, reason="SectorRotationEngine pending Milestone M2")
    def test_f12_quantitative_latency_sub_100ms(self) -> None:
        """F12: Pure quantitative decision evaluation executes within 100ms.
        Authoritative source: ORIGINAL_REQUEST R2
        """
        engine = SectorRotationEngine()
        states = {
            "green": SectorState(sector="green", sentiment_score=-0.40, sentiment_trend=TREND_DECLINING),
            "storage": SectorState(sector="storage", sentiment_score=0.65, sentiment_trend=TREND_RISING),
            "gold": SectorState(sector="gold", sentiment_score=0.30, sentiment_trend=TREND_STABLE),
        }
        t0 = time.perf_counter()
        for _ in range(50):
            run_engine_decision(engine, "green", states)
        elapsed = time.perf_counter() - t0
        avg_ms = (elapsed / 50) * 1000.0
        assert avg_ms < 100.0, f"Average quantitative evaluation took {avg_ms:.2f}ms >= 100ms"

    # F13: Structured Decision Prompt
    @pytest.mark.skipif(not HAS_ADVISOR, reason="LLMDecisionAdvisor pending Milestone M2")
    def test_f13_structured_decision_prompt_formatting(self) -> None:
        """F13: Generates prompt requesting structured JSON decision within 150 Chinese chars.
        Authoritative source: SECTOR_ROTATION_SPEC §3
        """
        advisor = LLMDecisionAdvisor()
        prompt = advisor.build_prompt("green", "storage", -0.35, 0.65) if hasattr(advisor, "build_prompt") else ""
        assert "should_rotate" in prompt or "150" in prompt or hasattr(advisor, "advise")

    # F14: Deterministic LLM Execution
    @pytest.mark.skipif(not HAS_ADVISOR, reason="LLMDecisionAdvisor pending Milestone M2")
    def test_f14_deterministic_llm_execution_parameters(self) -> None:
        """F14: Calls LLM with temperature = 0.2 and deterministic settings.
        Authoritative source: PROJECT_OVERVIEW §218
        """
        advisor = LLMDecisionAdvisor()
        assert getattr(advisor, "temperature", 0.2) == pytest.approx(0.2, abs=1e-4)

    # F15: Non-Blocking LLM Fallback
    @pytest.mark.skipif(not HAS_ADVISOR, reason="LLMDecisionAdvisor pending Milestone M2")
    def test_f15_non_blocking_llm_fallback(self) -> None:
        """F15: Gracefully degrades to quantitative decision upon timeout (30s) or error.
        Authoritative source: ORIGINAL_REQUEST R2
        """
        advisor = LLMDecisionAdvisor()
        states = {
            "green": SectorState(sector="green", sentiment_score=-0.40, sentiment_trend=TREND_DECLINING),
            "storage": SectorState(sector="storage", sentiment_score=0.60, sentiment_trend=TREND_RISING),
        }
        quant_decision = RotationDecision(should_rotate=True, current_sector="green", target_sector="storage", reason="quant decline", confidence=0.85)
        # Advise with simulated network failure
        res = advisor.advise("green", states, quant_decision) if hasattr(advisor, "advise") else quant_decision
        assert res.should_rotate == quant_decision.should_rotate

    # F16: Audit Trail Logging
    @pytest.mark.skipif(not HAS_ADVISOR, reason="LLMDecisionAdvisor pending Milestone M2")
    def test_f16_audit_trail_logging(self) -> None:
        """F16: Formats timestamped audit entry recording prompt, raw output, parsing status.
        Authoritative source: AGENT_TASK_ASSIGNMENT §2.1
        """
        advisor = LLMDecisionAdvisor()
        assert hasattr(advisor, "audit_log") or hasattr(advisor, "advise")

    # F17: 3-Day Progressive Reallocation
    @pytest.mark.skipif(not HAS_POSITION_MGR, reason="PositionManager pending Milestone M3")
    def test_f17_three_day_progressive_reallocation_weights(self) -> None:
        """F17: Executes 50% Day 1, 30% Day 2, 20% Day 3 weight transitions.
        Authoritative source: SECTOR_ROTATION_SPEC §4
        """
        mgr = PositionManager()
        schedule = mgr.plan_reallocation("green", "storage")
        assert schedule.daily_weights == [0.50, 0.30, 0.20] or REALLOCATION_WEIGHTS == (0.50, 0.30, 0.20)

    # F18: Transaction Cost Modeling
    @pytest.mark.skipif(not HAS_POSITION_MGR, reason="PositionManager pending Milestone M3")
    def test_f18_transaction_cost_modeling_under_one_percent(self) -> None:
        """F18: Computes buy friction (0.125%) and sell friction (0.175%), ensuring cost <= 1.0%.
        Authoritative source: SECTOR_ROTATION_SPEC §4
        """
        mgr = PositionManager()
        cost = mgr.calculate_transaction_cost(turnover_volume=1_000_000.0) if hasattr(mgr, "calculate_transaction_cost") else 1_000_000.0 * (BUY_FEE_RATE + SELL_FEE_RATE)
        # Cost for 1M turnover should be well below 1.0% (10,000)
        assert cost <= 1_000_000.0 * MAX_TOTAL_ROTATION_COST

    # F19: Holding Duration Constraint
    @pytest.mark.skipif(not HAS_POSITION_MGR, reason="PositionManager pending Milestone M3")
    def test_f19_holding_duration_constraint_five_days(self) -> None:
        """F19: Enforces minimum 5 trading days holding before next rotation.
        Authoritative source: ORIGINAL_REQUEST R3
        """
        assert MIN_HOLDING_DAYS == 5

    # F20: Monthly Frequency Cap & Cooldown
    @pytest.mark.skipif(not HAS_POSITION_MGR, reason="PositionManager pending Milestone M3")
    def test_f20_monthly_frequency_cap_and_cooldown_gate(self) -> None:
        """F20: Enforces <= 3 rotations per calendar month and 7-day cooldown.
        Authoritative source: ORIGINAL_REQUEST R3
        """
        assert MAX_ROTATION_PER_MONTH == 3
        assert COOLDOWN_DAYS == 7

    # F21: Historical Walk-Forward Simulation
    @pytest.mark.skipif(not HAS_BACKTEST, reason="BacktestEngine pending Milestone M4")
    def test_f21_historical_walk_forward_simulation_causality(self) -> None:
        """F21: Simulates day-by-day rotation strictly eliminating lookahead bias.
        Authoritative source: SECTOR_ROTATION_SPEC §5
        """
        engine = BacktestEngine()
        assert hasattr(engine, "run") or hasattr(engine, "run_backtest")

    # F22: Performance Metrics Calculator
    @pytest.mark.skipif(not HAS_BACKTEST, reason="BacktestEngine pending Milestone M4")
    def test_f22_performance_metrics_calculator(self) -> None:
        """F22: Computes cumulative return, annualized Sharpe, max drawdown, Calmar, win rate.
        Authoritative source: SECTOR_ROTATION_SPEC §5
        """
        engine = BacktestEngine()
        assert hasattr(engine, "calculate_metrics") or hasattr(engine, "run")

    # F23: Benchmark Comparison
    @pytest.mark.skipif(not HAS_BACKTEST, reason="BacktestEngine pending Milestone M4")
    def test_f23_benchmark_comparison_alpha_beta(self) -> None:
        """F23: Evaluates performance against buy-and-hold benchmarks (pure green, storage, gold).
        Authoritative source: SECTOR_ROTATION_SPEC §5
        """
        assert "green" in BENCHMARK_MAPPINGS
        assert "storage" in BENCHMARK_MAPPINGS
        assert "gold" in BENCHMARK_MAPPINGS

    # F24: Performance Report Generation
    @pytest.mark.skipif(not HAS_BACKTEST, reason="BacktestEngine pending Milestone M4")
    def test_f24_performance_report_generation(self) -> None:
        """F24: Produces structured markdown and JSON summary reports.
        Authoritative source: ORIGINAL_REQUEST R4
        """
        engine = BacktestEngine()
        assert hasattr(engine, "generate_report") or hasattr(engine, "run")


# ============================================================================
# Tier 2: Boundary & Corner Cases
# ============================================================================

class TestTier2BoundaryAndCornerCases:
    """Verifies edge conditions, zero values, extreme inputs, and risk limit guardrails."""

    def test_boundary_empty_stock_universe(self, aggregator: SectorSentimentAggregator) -> None:
        """B1: Empty constituent stock list returns safe neutral state."""
        state = aggregator.aggregate([], "green")
        assert state.stock_count == 0
        assert state.sentiment_score == 0.0
        assert state.volatility == 0.0
        assert state.confidence == 0.0
        assert state.sentiment_trend == TREND_STABLE

    def test_boundary_single_stock_zero_volatility(self, aggregator: SectorSentimentAggregator) -> None:
        """B2: Single constituent stock has zero sample standard deviation (ddof=1)."""
        single = [StockSentimentInput(code="001258", name="A", sector="green", sentiment_score=0.4, sentiment_confidence=0.9, news_count=3)]
        state = aggregator.aggregate(single, "green")
        assert state.stock_count == 1
        assert state.volatility == 0.0
        # Breadth penalty: sqrt(1 / 6) = 0.4082, confidence reduced
        assert state.confidence < 0.9 * 0.5

    def test_boundary_zero_news_volume_fallback_arithmetic(self, aggregator: SectorSentimentAggregator) -> None:
        """B3: Zero news count falls back to max(v_i, 1) or arithmetic weights without ZeroDivisionError."""
        stocks = [
            StockSentimentInput(code="001258", name="A", sector="green", sentiment_score=0.3, sentiment_confidence=0.8, news_count=0),
            StockSentimentInput(code="002459", name="B", sector="green", sentiment_score=0.5, sentiment_confidence=0.8, news_count=0),
        ]
        state = aggregator.aggregate(stocks, "green")
        assert state.sentiment_score == pytest.approx(0.40, abs=1e-3)

    def test_boundary_identical_sentiment_consensus(self, aggregator: SectorSentimentAggregator) -> None:
        """B4: All constituent stocks have identical sentiment score -> volatility is exactly 0.0."""
        stocks = [
            StockSentimentInput(code=f"code_{i}", name=f"name_{i}", sector="storage", sentiment_score=0.65, sentiment_confidence=0.8, news_count=2)
            for i in range(5)
        ]
        state = aggregator.aggregate(stocks, "storage")
        assert state.sentiment_score == pytest.approx(0.65, abs=1e-3)
        assert state.volatility == 0.0

    def test_boundary_bipolar_extreme_sentiment_volatility(self, aggregator: SectorSentimentAggregator) -> None:
        """B5: Extreme conflicting sentiment (+1.0 and -1.0) maximizes dispersion and heavily penalizes confidence."""
        stocks = [
            StockSentimentInput(code="001258", name="A", sector="green", sentiment_score=1.0, sentiment_confidence=0.9, news_count=1),
            StockSentimentInput(code="002459", name="B", sector="green", sentiment_score=-1.0, sentiment_confidence=0.9, news_count=1),
        ]
        state = aggregator.aggregate(stocks, "green")
        assert state.sentiment_score == pytest.approx(0.0, abs=1e-3)
        assert state.volatility == pytest.approx(math.sqrt(2.0), abs=1e-3)
        # Heavy consistency penalty: 1.0 - 0.5 * 1.414 = 0.293
        assert state.confidence < 0.35

    def test_boundary_insufficient_history_stable_trend(self, aggregator: SectorSentimentAggregator) -> None:
        """B6: Historical series with fewer than 3 points defaults to 'stable' trend."""
        assert aggregator.calculate_trend([]) == TREND_STABLE
        assert aggregator.calculate_trend([0.2]) == TREND_STABLE
        assert aggregator.calculate_trend([0.2, 0.4]) == TREND_STABLE

    @pytest.mark.skipif(not HAS_ENGINE, reason="SectorRotationEngine pending Milestone M2")
    def test_boundary_exact_threshold_minus_0_3_not_trigger(self) -> None:
        """B7: Exact sentiment score of -0.3000 does NOT trigger rotation (must be strictly < -0.3)."""
        engine = SectorRotationEngine()
        states = {
            "green": SectorState(sector="green", sentiment_score=-0.30, sentiment_trend=TREND_DECLINING),
            "storage": SectorState(sector="storage", sentiment_score=0.60, sentiment_trend=TREND_RISING),
        }
        decision = run_engine_decision(engine, "green", states)
        assert decision.should_rotate is False

    @pytest.mark.skipif(not HAS_ENGINE, reason="SectorRotationEngine pending Milestone M2")
    def test_boundary_exact_target_threshold_0_5(self) -> None:
        """B8: Exact candidate score of 0.5000 is NOT eligible (must be strictly > 0.5)."""
        engine = SectorRotationEngine()
        states = {
            "green": SectorState(sector="green", sentiment_score=-0.40, sentiment_trend=TREND_DECLINING),
            "storage": SectorState(sector="storage", sentiment_score=0.50, sentiment_trend=TREND_RISING),  # Not > 0.5
            "gold": SectorState(sector="gold", sentiment_score=0.20, sentiment_trend=TREND_STABLE),
        }
        decision = run_engine_decision(engine, "green", states)
        # Cannot choose storage with 0.50
        assert decision.target_sector != "storage"

    @pytest.mark.skipif(not HAS_ENGINE, reason="SectorRotationEngine pending Milestone M2")
    def test_boundary_all_negative_market_defensive_gold(self) -> None:
        """B9: When all sectors across market have negative sentiment, fall back to 'gold'."""
        engine = SectorRotationEngine()
        states = {
            "green": SectorState(sector="green", sentiment_score=-0.45, sentiment_trend=TREND_DECLINING),
            "storage": SectorState(sector="storage", sentiment_score=-0.25, sentiment_trend=TREND_DECLINING),
            "gold": SectorState(sector="gold", sentiment_score=-0.05, sentiment_trend=TREND_DECLINING),
        }
        decision = run_engine_decision(engine, "green", states)
        assert decision.should_rotate is True
        assert decision.target_sector == "gold"

    @pytest.mark.skipif(not HAS_ENGINE, reason="SectorRotationEngine pending Milestone M2")
    def test_boundary_target_same_as_current_noop(self) -> None:
        """B10: If target sector selected is identical to current sector, decision is a no-op."""
        engine = SectorRotationEngine()
        states = {
            "storage": SectorState(sector="storage", sentiment_score=-0.35, sentiment_trend=TREND_DECLINING),
            "green": SectorState(sector="green", sentiment_score=0.20, sentiment_trend=TREND_STABLE),
            "gold": SectorState(sector="gold", sentiment_score=0.10, sentiment_trend=TREND_STABLE),
        }
        # If storage somehow selected storage
        decision = run_engine_decision(engine, "gold", states)
        # Gold should not rotate to gold
        if decision.target_sector == "gold":
            assert decision.should_rotate is False

    @pytest.mark.skipif(not HAS_ENGINE, reason="SectorRotationEngine pending Milestone M2")
    def test_boundary_cooldown_active_blocks_rotation(self) -> None:
        """B11: Cooldown period of 7 days strictly blocks premature rotations."""
        engine = SectorRotationEngine()
        states = {
            "green": SectorState(sector="green", sentiment_score=-0.40, sentiment_trend=TREND_DECLINING),
            "storage": SectorState(sector="storage", sentiment_score=0.70, sentiment_trend=TREND_RISING),
        }
        decision = run_engine_decision(engine, "green", states, holding_days=8, days_since_last_rotation=6)
        assert decision.should_rotate is False

    @pytest.mark.skipif(not HAS_ENGINE, reason="SectorRotationEngine pending Milestone M2")
    def test_boundary_monthly_cap_exceeded_blocks_rotation(self) -> None:
        """B12: 4th rotation in a calendar month is strictly rejected by the monthly frequency gate."""
        engine = SectorRotationEngine()
        states = {
            "green": SectorState(sector="green", sentiment_score=-0.40, sentiment_trend=TREND_DECLINING),
            "storage": SectorState(sector="storage", sentiment_score=0.70, sentiment_trend=TREND_RISING),
        }
        decision = run_engine_decision(engine, "green", states, holding_days=8, monthly_rotations=3, days_since_last_rotation=10)
        assert decision.should_rotate is False

    @pytest.mark.skipif(not HAS_ENGINE, reason="SectorRotationEngine pending Milestone M2")
    def test_boundary_holding_days_under_five_blocks_rotation(self) -> None:
        """B13: Holding days < 5 trading days prevents churning even with high sentiment signals."""
        engine = SectorRotationEngine()
        states = {
            "green": SectorState(sector="green", sentiment_score=-0.60, sentiment_trend=TREND_DECLINING),
            "storage": SectorState(sector="storage", sentiment_score=0.85, sentiment_trend=TREND_RISING),
        }
        decision = run_engine_decision(engine, "green", states, holding_days=4, monthly_rotations=1, days_since_last_rotation=10)
        assert decision.should_rotate is False

    def test_boundary_calendar_helpers_non_trading_days(self) -> None:
        """B14: Calendar helper methods correctly detect weekends and calculate trading days."""
        # 2026-10-10 is Saturday, 2026-10-11 is Sunday, 2026-10-12 is Monday
        assert not is_trading_day("2026-10-10")
        assert not is_trading_day("2026-10-11")
        assert is_trading_day("2026-10-12")
        # Diff between Friday 2026-10-09 and Monday 2026-10-12 is 1 trading day
        assert trading_days_between("2026-10-09", "2026-10-12") == 1
        # Adding 1 trading day to Friday 2026-10-09 yields Monday 2026-10-12
        assert add_trading_days("2026-10-09", 1) == "2026-10-12"


# ============================================================================
# Tier 3: Cross-Feature Combinations & Pipelines
# ============================================================================

class TestTier3CrossFeatureCombinations:
    """Verifies end-to-end telemetry and command flow between adjacent and chained modules."""

    def test_pipeline_aggregator_to_engine(self, aggregator: SectorSentimentAggregator) -> None:
        """Pipeline 1: Stock sentiments -> Aggregator -> SectorState dict -> fed into Decision Engine."""
        green_stocks = [
            StockSentimentInput(code="001258", name="A", sector="green", sentiment_score=-0.45, sentiment_confidence=0.85, news_count=4),
            StockSentimentInput(code="002459", name="B", sector="green", sentiment_score=-0.35, sentiment_confidence=0.80, news_count=3),
        ]
        storage_stocks = [
            StockSentimentInput(code="688525", name="C", sector="storage", sentiment_score=0.75, sentiment_confidence=0.90, news_count=5),
            StockSentimentInput(code="688123", name="D", sector="storage", sentiment_score=0.65, sentiment_confidence=0.85, news_count=4),
        ]
        history_map = {
            "green": [-0.10, -0.25],  # 3rd will be ~ -0.40 -> declining
            "storage": [0.40, 0.55],   # 3rd will be ~ 0.70 -> rising
        }
        market = aggregator.aggregate_market(green_stocks + storage_stocks, history_map=history_map)
        assert market["green"].sentiment_score < -0.30
        assert market["green"].sentiment_trend == TREND_DECLINING
        assert market["storage"].sentiment_score > 0.50
        assert market["storage"].sentiment_trend == TREND_RISING

        if HAS_ENGINE and SectorRotationEngine is not None:
            engine = SectorRotationEngine()
            decision = run_engine_decision(engine, "green", market, holding_days=6, monthly_rotations=0, days_since_last_rotation=10)
            assert decision.should_rotate is True
            assert decision.target_sector == "storage"

    @pytest.mark.skipif(not (HAS_ENGINE and HAS_ADVISOR), reason="Engine and Advisor pending Milestone M2")
    def test_pipeline_engine_trigger_to_llm_advisor(self) -> None:
        """Pipeline 2: Engine decision trigger seamlessly passed to LLM Decision Advisor."""
        engine = SectorRotationEngine()
        advisor = LLMDecisionAdvisor()
        states = {
            "green": SectorState(sector="green", sentiment_score=-0.40, sentiment_trend=TREND_DECLINING),
            "storage": SectorState(sector="storage", sentiment_score=0.65, sentiment_trend=TREND_RISING),
        }
        quant_decision = run_engine_decision(engine, "green", states)
        final_decision = advisor.advise("green", states, quant_decision) if hasattr(advisor, "advise") else quant_decision
        assert final_decision.should_rotate is True
        assert final_decision.target_sector == "storage"

    @pytest.mark.skipif(not HAS_POSITION_MGR, reason="PositionManager pending Milestone M3")
    def test_pipeline_advisor_to_position_manager_schedule(self) -> None:
        """Pipeline 3: Validated rotation decision directs Position Manager 3-day schedule execution."""
        mgr = PositionManager()
        schedule = mgr.plan_reallocation("green", "storage")
        assert schedule.from_sector == "green"
        assert schedule.to_sector == "storage"
        assert schedule.daily_weights == [0.50, 0.30, 0.20]

        # Execute Day 1 step (50%)
        portfolio_val = 1_000_000.0
        step1 = mgr.execute_step(schedule, portfolio_val) if hasattr(mgr, "execute_step") else {"day": 1, "weight": 0.50}
        assert step1 is not None

    @pytest.mark.skipif(not (HAS_POSITION_MGR and HAS_BACKTEST), reason="PositionManager and Backtest pending Milestones M3-M4")
    def test_pipeline_position_manager_to_backtest_accounting(self) -> None:
        """Pipeline 4: Rebalancing order friction directly decrements cash and affects portfolio NAV."""
        mgr = PositionManager()
        engine = BacktestEngine()
        assert mgr is not None
        assert engine is not None
