# -*- coding: utf-8 -*-
"""tests/sector_rotation/test_m2_challenger_stress.py —— M2 对抗性压力与经验证伪测试套件

由 Challenger M2 (Instance 1) 编写并执行：
1. 1,000 次 SectorRotationEngine.evaluate() 纯量化执行延迟压力基准测试（均值严格 < 1.0ms，硬顶 < 100ms）
2. 1,000 次 LLMDecisionAdvisor.advise() 纯量化降级路径执行延迟基准测试（均值严格 < 1.0ms，硬顶 < 100ms）
3. LLM 极端故障对抗压力测试：
   - 30s 超时 / TimeoutError
   - 服务端故障 (API 500, 502 Bad Gateway, 503, 504, 429 Rate Limit)
   - 网络底层故障 (ConnectionResetError, RemoteDisconnected, ConnectionRefusedError)
   - 结构损坏输出 (截断 Markdown 块, 缺失关键字段, 语法错误, 非 dict 根节点, 空文本, HTML 报错)
   - ReDoS / 超大负载 (100KB+ 文本, 超长 1000 字 reason 自动裁剪)
   - 异常客户端返回值 (None, 数字类型, 非字符串)
4. 多线程高并发压力测试 (20 线程并发 evaluate 与 advise)
5. 内存泄漏与稳定性追踪 (tracemalloc 1,000 次迭代内存驻留监控)
6. 浮点边界与极限情况 (精确阈值临界点、大小写宽容度、空字典防御)
7. 对抗性发现与脆弱点经验证伪 (Empirical Bug Findings):
   - 发现 1: should_rotate 字段松散类型转换漏洞 (非法字符串 "maybe", "unknown" 被隐式转为 False 并否决量化决策，未触发降级)
   - 发现 2: should_rotate 接受嵌套字典/列表漏洞 (如 {"status": "error"} 被 bool() 强制转为 True)
   - 发现 3: should_rotate=True 却 target_sector=None 时未补全目标板块漏洞
"""

from __future__ import annotations

import gc
import json
import math
import statistics
import threading
import time
import tracemalloc
from typing import Any, Dict, List, Optional

import pytest

from src.sector_rotation.config import (
    COOLDOWN_DAYS,
    DEFENSIVE_SECTOR,
    MAX_ROTATION_PER_MONTH,
    MIN_HOLDING_DAYS,
    MIN_TARGET_SENTIMENT,
    SENTIMENT_DECLINE_THRESHOLD,
    TREND_DECLINING,
    TREND_RISING,
    TREND_STABLE,
)
from src.sector_rotation.llm_decision_advisor import (
    AuditRecord,
    LLMDecisionAdvisor,
)
from src.sector_rotation.sector_rotation_engine import (
    RotationDecision,
    SectorRotationEngine,
)
from src.sector_rotation.utils.sector_utils import SectorState


# ============================================================================
# 模拟客户端辅助类
# ============================================================================

class MockEchoOrThrowClient:
    """可配置异常抛出或响应的模拟客户端"""

    def __init__(self, response_or_exception: Any) -> None:
        self.target = response_or_exception
        self.call_count = 0

    @property
    def is_available(self) -> bool:
        return True

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: Optional[int] = None,
        temperature: float = 0.2,
    ) -> Any:
        self.call_count += 1
        if isinstance(self.target, BaseException):
            raise self.target
        return self.target


# ============================================================================
# 1. 延迟压力基准测试 (1,000 次迭代)
# ============================================================================

def test_engine_evaluate_latency_1000_iterations_benchmark() -> None:
    """实测 SectorRotationEngine.evaluate() 1,000 次调用的延迟统计分布。
    
    严苛验证指标：
    - 平均执行延迟严格 < 1.0ms (远优于规格书 < 100ms 要求)
    - 中位数 (p50) 延迟 < 0.5ms
    - 99分位数 (p99) 延迟 < 5.0ms
    - 最大单次延迟 (max) 严格 < 100.0ms
    - 1,000 次混合场景累计执行时间 < 1.0 秒
    """
    engine = SectorRotationEngine()

    scenario_trigger = {
        "green": SectorState(sector="green", sentiment_score=-0.45, sentiment_trend=TREND_DECLINING, confidence=0.88),
        "storage": SectorState(sector="storage", sentiment_score=0.72, sentiment_trend=TREND_RISING, confidence=0.91, volatility=0.12),
        "gold": SectorState(sector="gold", sentiment_score=0.35, sentiment_trend=TREND_STABLE, confidence=0.80),
    }

    scenario_fallback = {
        "green": SectorState(sector="green", sentiment_score=-0.40, sentiment_trend=TREND_DECLINING, confidence=0.85),
        "storage": SectorState(sector="storage", sentiment_score=0.20, sentiment_trend=TREND_DECLINING, confidence=0.70),
        "gold": SectorState(sector="gold", sentiment_score=-0.10, sentiment_trend=TREND_DECLINING, confidence=0.75),
    }

    scenario_healthy = {
        "green": SectorState(sector="green", sentiment_score=0.30, sentiment_trend=TREND_RISING, confidence=0.85),
        "storage": SectorState(sector="storage", sentiment_score=0.60, sentiment_trend=TREND_STABLE, confidence=0.88),
        "gold": SectorState(sector="gold", sentiment_score=0.20, sentiment_trend=TREND_STABLE, confidence=0.80),
    }

    scenarios = [
        ("green", scenario_trigger, 10, 0, 15),     # 正常触发
        ("green", scenario_fallback, 10, 0, 15),    # 降级防御
        ("green", scenario_healthy, 10, 0, 15),     # 健康维持
        ("green", scenario_trigger, 2, 0, 15),      # 最短持仓拦截
        ("green", scenario_trigger, 10, 4, 15),     # 月频次拦截
        ("green", scenario_trigger, 10, 0, 3),      # 冷却期拦截
    ]

    latencies_ms: List[float] = []
    total_start = time.perf_counter()

    iterations = 1000
    for i in range(iterations):
        curr_sec, states, holding, monthly, cooldown = scenarios[i % len(scenarios)]
        t0 = time.perf_counter()
        dec = engine.evaluate(
            current_sector=curr_sec,
            sector_states=states,
            holding_days=holding,
            monthly_rotations=monthly,
            days_since_last_rotation=cooldown,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies_ms.append(elapsed_ms)
        assert dec is not None
        assert isinstance(dec, RotationDecision)

    total_duration = time.perf_counter() - total_start

    mean_ms = statistics.mean(latencies_ms)
    median_ms = statistics.median(latencies_ms)
    sorted_lats = sorted(latencies_ms)
    p95_ms = sorted_lats[int(0.95 * iterations)]
    p99_ms = sorted_lats[int(0.99 * iterations)]
    max_ms = max(latencies_ms)

    print(
        f"\n[M2 Engine Latency Benchmark] 1,000 iterations: "
        f"Mean={mean_ms:.4f}ms, Median={median_ms:.4f}ms, P95={p95_ms:.4f}ms, "
        f"P99={p99_ms:.4f}ms, Max={max_ms:.4f}ms, Total={total_duration:.4f}s"
    )

    assert mean_ms < 1.0, f"Mean latency {mean_ms:.4f}ms exceeds 1.0ms limit!"
    assert p99_ms < 5.0, f"P99 latency {p99_ms:.4f}ms exceeds 5.0ms limit!"
    assert max_ms < 100.0, f"Max latency {max_ms:.4f}ms violates 100ms hard requirement!"
    assert total_duration < 1.0, f"Total benchmark execution time {total_duration:.4f}s exceeds 1.0s!"


def test_advisor_pure_quantitative_path_latency_1000_iterations() -> None:
    """实测 LLMDecisionAdvisor 在纯量化降级路径下的 1,000 次执行延迟。
    
    当未提供客户端或客户端处于禁用状态时，必须以零开销即时返回，不拖慢量化管线。
    """
    advisor = LLMDecisionAdvisor(llm_client=None)
    states = {
        "green": SectorState(sector="green", sentiment_score=-0.40, sentiment_trend=TREND_DECLINING, confidence=0.85),
        "storage": SectorState(sector="storage", sentiment_score=0.70, sentiment_trend=TREND_RISING, confidence=0.90),
    }
    quant_dec = RotationDecision(
        should_rotate=True,
        current_sector="green",
        target_sector="storage",
        reason="Quant trigger",
        confidence=0.88,
    )

    latencies_ms: List[float] = []
    iterations = 1000
    t_start = time.perf_counter()

    for _ in range(iterations):
        t0 = time.perf_counter()
        res = advisor.advise(
            current_sector="green",
            sector_states=states,
            quantitative_decision=quant_dec,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies_ms.append(elapsed_ms)
        assert res.is_fallback is True
        assert res.should_rotate is True
        assert res.target_sector == "storage"

    total_time = time.perf_counter() - t_start
    mean_ms = statistics.mean(latencies_ms)
    max_ms = max(latencies_ms)

    print(
        f"\n[M2 Advisor Pure Quant Benchmark] 1,000 iterations: "
        f"Mean={mean_ms:.4f}ms, Max={max_ms:.4f}ms, Total={total_time:.4f}s"
    )

    assert mean_ms < 1.0, f"Advisor quantitative fallback mean latency {mean_ms:.4f}ms exceeds 1.0ms"
    assert max_ms < 100.0, f"Advisor quantitative fallback max latency {max_ms:.4f}ms exceeds 100ms"
    assert len(advisor.audit_log) == iterations


def test_engine_scalability_large_sector_universe() -> None:
    """压力测试：当板块候选池扩展至 100 个合成板块时，多因子排序与决策延迟保持在 5ms 以内。"""
    engine = SectorRotationEngine()
    large_states: Dict[str, SectorState] = {
        "green": SectorState(sector="green", sentiment_score=-0.50, sentiment_trend=TREND_DECLINING, confidence=0.80)
    }
    for i in range(100):
        sec_name = f"sector_{i:03d}"
        score = -0.5 + (i * 0.015)
        large_states[sec_name] = SectorState(
            sector=sec_name,
            sentiment_score=score,
            sentiment_trend=TREND_RISING if i % 2 == 0 else TREND_STABLE,
            confidence=0.75 + (i % 25) * 0.01,
            volatility=0.05 + (i % 10) * 0.02,
        )

    t0 = time.perf_counter()
    dec = engine.evaluate("green", large_states, holding_days=10, monthly_rotations=0, days_since_last_rotation=15)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert dec.should_rotate is True
    assert dec.target_sector is not None
    assert dec.target_sector.startswith("sector_")
    assert elapsed_ms < 5.0, f"Evaluating 100 candidate sectors took {elapsed_ms:.4f}ms (> 5.0ms)"


# ============================================================================
# 2. 大模型超时与各种异常对抗测试 (Fallback Stress)
# ============================================================================

@pytest.mark.parametrize(
    "simulated_error",
    [
        TimeoutError("Connection to LLM provider timed out after 30.0s"),
        ConnectionResetError("Connection reset by peer [Errno 104]"),
        ConnectionRefusedError("Connection refused by gateway"),
        RuntimeError("Internal Server Error 500: Model service unavailable"),
        KeyError("Missing expected completion payload"),
        TypeError("Unsupported operand type in external library"),
        IndexError("List index out of range in tokenizer"),
        ZeroDivisionError("Division by zero in sampling layer"),
        SystemError("OS socket error"),
        ValueError("Invalid SSL certificate verification"),
    ],
)
def test_advisor_robust_fallback_under_diverse_network_and_system_exceptions(
    simulated_error: Exception,
) -> None:
    """针对 10 类底层网络、系统与业务异常注入，验证 100% 优雅降级。
    
    断言标准：
    - 不抛出任何未捕获异常
    - 维持原始量化决策的方向与目标板块
    - 标记 is_fallback=True
    - 记录准确的审计追踪日志
    """
    failing_client = MockEchoOrThrowClient(simulated_error)
    advisor = LLMDecisionAdvisor(llm_client=failing_client)

    states = {
        "green": SectorState(sector="green", sentiment_score=-0.45, sentiment_trend=TREND_DECLINING, confidence=0.85),
        "storage": SectorState(sector="storage", sentiment_score=0.75, sentiment_trend=TREND_RISING, confidence=0.92),
    }
    quant_dec = RotationDecision(
        should_rotate=True,
        current_sector="green",
        target_sector="storage",
        reason="Quant decline trigger",
        confidence=0.85,
    )

    decision = advisor.advise("green", states, quant_dec)
    assert decision.should_rotate is True
    assert decision.current_sector == "green"
    assert decision.target_sector == "storage"
    assert decision.is_fallback is True
    assert type(simulated_error).__name__ in decision.llm_rationale

    last_audit = advisor.last_audit_record
    assert last_audit is not None
    assert last_audit.success is False
    assert type(simulated_error).__name__ in str(last_audit.fallback_reason)


# ============================================================================
# 3. 畸变 Payload 与对抗性内容测试 (Corrupt & Adversarial Payloads)
# ============================================================================

@pytest.mark.parametrize(
    "corrupt_payload",
    [
        "",  # 完全为空
        "   \n\t  ",  # 仅含空白字符
        "<!DOCTYPE html><html><body><h1>502 Bad Gateway</h1></body></html>",  # HTML 报错页面
        "Error: rate limit exceeded. Please try again later.",  # 纯文本非 JSON
        "```json\n",  # 截断的 Markdown 起始标记
        "```json\n{\"should_rotate\": true",  # 截断且未闭合的 JSON
        "{\"should_rotate\": true, \"target_sector\": 'storage'}",  # 单引号非法 JSON
        "{\"should_rotate\": true, \"target_sector\": \"storage\",}",  # 尾随逗号非法 JSON
        "[1, 2, 3]",  # 非字典列表根节点
        "\"should_rotate\": true",  # 裸字符串
        "123456",  # 裸数字
        "true",  # 裸布尔值
        "null",  # 裸 null
        "{}",  # 缺失 should_rotate 必填字段
        "{\"target_sector\": \"storage\", \"reason\": \"ok\"}",  # 缺失 should_rotate
        "[{\"broken\": 1}, {\"broken\": 2}]",  # 无法单层闭合提取的列表
    ],
)
def test_advisor_fallback_under_syntax_and_structure_corruption(corrupt_payload: str) -> None:
    """验证语法损坏、截断代码块、HTML报错页面及字段缺失均不会导致崩溃，100% 回退量化决策。"""
    client = MockEchoOrThrowClient(corrupt_payload)
    advisor = LLMDecisionAdvisor(llm_client=client)

    states = {
        "green": SectorState(sector="green", sentiment_score=-0.40, sentiment_trend=TREND_DECLINING, confidence=0.85),
        "storage": SectorState(sector="storage", sentiment_score=0.68, sentiment_trend=TREND_RISING, confidence=0.89),
    }
    quant_dec = RotationDecision(
        should_rotate=True,
        current_sector="green",
        target_sector="storage",
        reason="Quant trigger",
        confidence=0.80,
    )

    decision = advisor.advise("green", states, quant_dec)
    assert decision.is_fallback is True
    assert decision.should_rotate is True
    assert decision.target_sector == "storage"
    assert advisor.last_audit_record.success is False


def test_advisor_parses_markdown_with_surrounding_text() -> None:
    """验证包含前后冗余文字的合法 Markdown 代码块能被精准提取并正常处理。"""
    payloads = [
        "```json\n{\"should_rotate\": true, \"target_sector\": \"storage\", \"reason\": \"ok\"}\n```\nExtra garbage text",
        "Some prefix text\n```json\n{\"should_rotate\": false, \"reason\": \"hold\"}\n```\nSome suffix text",
    ]
    for p in payloads:
        client = MockEchoOrThrowClient(p)
        advisor = LLMDecisionAdvisor(llm_client=client)
        states = {"green": SectorState(sector="green", sentiment_score=-0.40)}
        quant_dec = RotationDecision(should_rotate=True, current_sector="green", target_sector="storage", reason="Quant", confidence=0.8)
        dec = advisor.advise("green", states, quant_dec)
        assert dec.is_fallback is False
        assert advisor.last_audit_record.success is True


def test_advisor_handles_non_string_client_outputs() -> None:
    """测试客户端返回 None、整型或自定义对象（无 .strip() 方法）时的容错。"""
    for weird_output in [None, 12345, 3.1415, ["unexpected", "list"], {"unexpected": "dict"}]:
        client = MockEchoOrThrowClient(weird_output)
        advisor = LLMDecisionAdvisor(llm_client=client)

        states = {
            "green": SectorState(sector="green", sentiment_score=-0.40, sentiment_trend=TREND_DECLINING, confidence=0.85),
            "storage": SectorState(sector="storage", sentiment_score=0.68, sentiment_trend=TREND_RISING, confidence=0.89),
        }
        quant_dec = RotationDecision(
            should_rotate=True,
            current_sector="green",
            target_sector="storage",
            reason="Quant trigger",
            confidence=0.80,
        )

        dec = advisor.advise("green", states, quant_dec)
        assert dec.is_fallback is True
        assert dec.should_rotate is True
        assert dec.target_sector == "storage"


def test_advisor_handles_extremely_large_payload_and_long_reason() -> None:
    """测试当 LLM 返回超过 100KB 的冗长内容及包含 1,000 字的原因时，能否安全截断至 150 字并正常处理。"""
    long_reason = "行业景气" * 500  # 2,000 字
    json_body = {
        "should_rotate": True,
        "target_sector": "storage",
        "reason": long_reason,
        "confidence": 0.95,
    }
    payload_str = "A" * 50000 + "\n```json\n" + json.dumps(json_body, ensure_ascii=False) + "\n```\n" + "B" * 50000

    client = MockEchoOrThrowClient(payload_str)
    advisor = LLMDecisionAdvisor(llm_client=client)

    states = {
        "green": SectorState(sector="green", sentiment_score=-0.40, sentiment_trend=TREND_DECLINING, confidence=0.85),
        "storage": SectorState(sector="storage", sentiment_score=0.68, sentiment_trend=TREND_RISING, confidence=0.89),
    }
    quant_dec = RotationDecision(
        should_rotate=True,
        current_sector="green",
        target_sector="storage",
        reason="Quant trigger",
        confidence=0.80,
    )

    t0 = time.perf_counter()
    decision = advisor.advise("green", states, quant_dec)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert decision.is_fallback is False
    assert decision.should_rotate is True
    assert decision.target_sector == "storage"
    assert len(decision.reason) <= 150
    assert decision.reason.endswith("...")
    assert elapsed_ms < 50.0


# ============================================================================
# 4. 对抗性发现与脆弱点经验证伪 (Empirical Bug Findings)
# ============================================================================

def test_advisor_vulnerability_loose_boolean_coercion_blocks_quant_rotation() -> None:
    """[Vulnerability Finding 1] should_rotate 字段松散类型转换缺陷。
    
    现象：
    当 LLM 返回模糊/非标的字符串（如 "maybe", "unknown", "server error", "pending"）时，
    代码实现使用：
        should_rotate = raw_rotate.strip().lower() in ("true", "1", "yes", "是")
    直接将所有未匹配字符串隐式断定为 False，而未对非 ("false", "0", "no", "否") 进行格式报错！
    结果：
    系统将 LLM 无法给出的明确判断误认为是 "明确否决轮动"，导致 is_fallback=False，
    并将量化引擎强烈推荐的轮动信号强行覆写为 should_rotate=False，违反了
    "LLM 故障时不阻断量化执行管线" 的核心契约！
    """
    advisor = LLMDecisionAdvisor()

    # 实证：当 LLM 返回非标准布尔值时
    for ambiguous_str in ["maybe", "unknown", "failed", "pending", "error: no decision"]:
        raw_json = json.dumps({"should_rotate": ambiguous_str, "reason": "Not sure"})
        parsed = advisor._parse_llm_response(raw_json)
        # 当前缺陷行为：parsed["should_rotate"] 变成了 False，且未触发异常
        assert parsed["should_rotate"] is False, "Empirical proof: ambiguous string was silently coerced to False"

    # 实证：在 advise 中阻断了量化轮动
    client = MockEchoOrThrowClient(json.dumps({"should_rotate": "I cannot decide", "reason": "Uncertain"}))
    advisor_with_client = LLMDecisionAdvisor(llm_client=client)
    states = {"green": SectorState(sector="green", sentiment_score=-0.40)}
    quant_dec = RotationDecision(should_rotate=True, current_sector="green", target_sector="storage", reason="Quant Trigger", confidence=0.85)

    res = advisor_with_client.advise("green", states, quant_dec)
    # 实证结果：is_fallback=False（误以为 LLM 成功决策），但 should_rotate 被篡改为 False！
    assert res.is_fallback is False
    assert res.should_rotate is False  # 阻断了量化推荐


def test_advisor_vulnerability_dict_in_should_rotate() -> None:
    """[Vulnerability Finding 2] should_rotate 为非字符串、非布尔对象时由 bool() 强制转为 True。
    
    现象：
    若 LLM 吐出结构体错误信息：{"should_rotate": {"error": "quota_exhausted"}}，
    代码中 else: should_rotate = bool(raw_rotate) 会将非空 dict 判定为 True！
    """
    advisor = LLMDecisionAdvisor()
    raw_json = '{"should_rotate": {"error": "rate limit"}, "reason": "rate limited"}'
    parsed = advisor._parse_llm_response(raw_json)
    # 证明：字典被 bool() 隐式转成了 True
    assert parsed["should_rotate"] is True


def test_advisor_vulnerability_none_target_sector_when_rotate_true() -> None:
    """[Vulnerability Finding 3] 当 LLM 返回 should_rotate=True 但 target_sector 为 None 时，
    最终决策生成了 should_rotate=True 且 target_sector=None 的不完整决策。
    
    由于未从 quantitative_decision.target_sector 兜底回填，下游 PositionManager 将无法获得轮动目标板块！
    """
    client = MockEchoOrThrowClient(json.dumps({"should_rotate": True, "target_sector": None, "reason": "Rotate but forgot sector"}))
    advisor = LLMDecisionAdvisor(llm_client=client)
    states = {"green": SectorState(sector="green", sentiment_score=-0.40)}
    quant_dec = RotationDecision(should_rotate=True, current_sector="green", target_sector="storage", reason="Quant Trigger", confidence=0.85)

    res = advisor.advise("green", states, quant_dec)
    assert res.should_rotate is True
    # 实证：目标板块丢失，变成了 None！
    assert res.target_sector is None


# ============================================================================
# 5. 多线程高并发压力测试
# ============================================================================

def test_concurrent_multi_threaded_evaluations_and_advising() -> None:
    """测试 20 个工作线程并发调用 SectorRotationEngine 与 LLMDecisionAdvisor。
    
    验证无竞态条件、无共享状态污染、决策一致性与审计日志稳定性。
    """
    engine = SectorRotationEngine()
    advisor = LLMDecisionAdvisor(llm_client=None)

    states = {
        "green": SectorState(sector="green", sentiment_score=-0.45, sentiment_trend=TREND_DECLINING, confidence=0.85),
        "storage": SectorState(sector="storage", sentiment_score=0.72, sentiment_trend=TREND_RISING, confidence=0.91),
        "gold": SectorState(sector="gold", sentiment_score=0.20, sentiment_trend=TREND_STABLE, confidence=0.80),
    }

    results: List[RotationDecision] = []
    lock = threading.Lock()

    def worker_task(thread_id: int) -> None:
        for _ in range(50):
            dec = engine.evaluate(
                current_sector="green",
                sector_states=states,
                holding_days=10,
                monthly_rotations=0,
                days_since_last_rotation=12,
            )
            advised = advisor.advise(
                current_sector="green",
                sector_states=states,
                quantitative_decision=dec,
            )
            with lock:
                results.append(advised)

    num_threads = 20
    threads = [threading.Thread(target=worker_task, args=(i,)) for i in range(num_threads)]

    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - t0

    assert len(results) == num_threads * 50
    for r in results:
        assert r.should_rotate is True
        assert r.target_sector == "storage"
        assert r.current_sector == "green"

    print(f"\n[M2 Concurrency] 20 threads x 50 iterations (1,000 total) finished in {elapsed:.4f}s")


# ============================================================================
# 6. 内存稳定性与泄漏追踪
# ============================================================================

def test_memory_stability_1000_iterations() -> None:
    """使用 tracemalloc 监控 1,000 次引擎与顾问执行前后的常驻内存。
    
    确保无隐式全局缓存、无引用循环堆积，内存在合理界限内（增量 < 5.0 MB）。
    """
    gc.collect()
    tracemalloc.start()

    engine = SectorRotationEngine()
    advisor = LLMDecisionAdvisor(llm_client=None)

    states = {
        "green": SectorState(sector="green", sentiment_score=-0.40, sentiment_trend=TREND_DECLINING, confidence=0.85),
        "storage": SectorState(sector="storage", sentiment_score=0.65, sentiment_trend=TREND_RISING, confidence=0.88),
    }

    snapshot1 = tracemalloc.take_snapshot()

    for _ in range(1000):
        dec = engine.evaluate("green", states, holding_days=10, monthly_rotations=0, days_since_last_rotation=10)
        _ = advisor.advise("green", states, dec)

    snapshot2 = tracemalloc.take_snapshot()
    tracemalloc.stop()

    top_stats = snapshot2.compare_to(snapshot1, "lineno")
    total_diff_kb = sum(stat.size_diff for stat in top_stats) / 1024.0

    print(f"\n[M2 Memory Tracking] 1,000 iterations memory delta: {total_diff_kb:.2f} KB")
    assert total_diff_kb < 5120.0, f"Memory grew by {total_diff_kb:.2f} KB (> 5 MB), potential memory leak!"


# ============================================================================
# 7. 极端临界浮点值与鲁棒边界测试
# ============================================================================

def test_engine_exact_threshold_micro_epsilon_boundaries() -> None:
    """高精度微扰动测试：验证浮点精度在阈值上下 1e-9 时的行为绝对确定。"""
    engine = SectorRotationEngine()

    # 1. 下沉阈值临界点 (-0.3)
    s_just_above = SectorState(sector="green", sentiment_score=-0.3 + 1e-9, sentiment_trend=TREND_DECLINING, confidence=0.8)
    states_above = {"green": s_just_above, "storage": SectorState(sector="storage", sentiment_score=0.7, sentiment_trend=TREND_RISING, confidence=0.9)}
    d_above = engine.evaluate("green", states_above, 5, 0, 10)
    assert d_above.should_rotate is False

    s_just_below = SectorState(sector="green", sentiment_score=-0.3 - 1e-9, sentiment_trend=TREND_DECLINING, confidence=0.8)
    states_below = {"green": s_just_below, "storage": SectorState(sector="storage", sentiment_score=0.7, sentiment_trend=TREND_RISING, confidence=0.9)}
    d_below = engine.evaluate("green", states_below, 5, 0, 10)
    assert d_below.should_rotate is True

    # 2. 候选目标阈值临界点 (0.5)
    s_declining = SectorState(sector="green", sentiment_score=-0.4, sentiment_trend=TREND_DECLINING, confidence=0.8)
    s_cand_under = SectorState(sector="storage", sentiment_score=0.5 - 1e-9, sentiment_trend=TREND_RISING, confidence=0.9)
    states_cand_under = {"green": s_declining, "storage": s_cand_under, "gold": SectorState(sector="gold", sentiment_score=0.2, sentiment_trend=TREND_STABLE, confidence=0.8)}
    d_cand_under = engine.evaluate("green", states_cand_under, 5, 0, 10)
    assert d_cand_under.should_rotate is True
    assert d_cand_under.target_sector == "gold"
    assert d_cand_under.is_fallback is True

    s_cand_over = SectorState(sector="storage", sentiment_score=0.5 + 1e-9, sentiment_trend=TREND_RISING, confidence=0.9)
    states_cand_over = {"green": s_declining, "storage": s_cand_over, "gold": SectorState(sector="gold", sentiment_score=0.2, sentiment_trend=TREND_STABLE, confidence=0.8)}
    d_cand_over = engine.evaluate("green", states_cand_over, 5, 0, 10)
    assert d_cand_over.should_rotate is True
    assert d_cand_over.target_sector == "storage"
    assert d_cand_over.is_fallback is False


def test_engine_empty_dict_and_whitespace_sector_names() -> None:
    """测试空字典输入与包含大小写、前后空白的板块名称鲁棒性。"""
    engine = SectorRotationEngine()

    d_empty = engine.evaluate("green", {}, holding_days=5, monthly_rotations=0, days_since_last_rotation=10)
    assert d_empty.should_rotate is False
    assert "missing" in d_empty.reason.lower()

    states = {
        "green": SectorState(sector="Green", sentiment_score=-0.4, sentiment_trend=TREND_DECLINING, confidence=0.8),
        "storage": SectorState(sector="STORAGE ", sentiment_score=0.6, sentiment_trend=TREND_RISING, confidence=0.9),
    }
    d_norm = engine.evaluate(" GREEN  ", states, holding_days=5, monthly_rotations=0, days_since_last_rotation=10)
    assert d_norm.should_rotate is True
    assert d_norm.current_sector == "green"
    assert d_norm.target_sector == "storage"
