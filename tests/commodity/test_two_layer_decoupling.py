# -*- coding: utf-8 -*-
"""
定性定量两层解耦引擎测试套件 (tests/test_two_layer_decoupling.py)
------------------------------------------------------------------
验证 ADR-0001 架构契约与 M2 核心功能:
1. 结构化定性假设实体 (QualitativeProposition) 规约校验
2. 严禁 LLM 生成数值 Alpha 的硬防线拦截 (Integrity Violation)
3. 方向标准化与三元事实标签 ([FACT]/[OPINION]/[INFERENCE]) 校验
4. Newey-West (1987) 自适应 HAC 带宽阶数计算 q = max(1, floor(4 * (T / 100)^(2/9)))
5. 方差膨胀因子 (VIF) 共线性诊断
6. 样本量下限门禁 (T < 30 抛出 ValueError)
7. 双重硬门禁 (p < 0.05 且 IR >= 0.30) 与一票否决机制 (100% Veto)
8. 残差分母防爆除零保护 (sigma(eps) <= 1e-9 -> IR = 0.0)
9. SHORT/LONG 方向校准与投资确信度评级 (conviction_level)
"""

import math
import numpy as np
import pytest

from src.intelligence.two_layer_engine import (
    QualitativeProposition,
    GateVerdict,
    DecoupledTwoLayerEngine,
    compute_newey_west_bandwidth,
    calculate_vif
)


@pytest.fixture(scope="module")
def gate_engine() -> DecoupledTwoLayerEngine:
    """初始化双层解耦门禁引擎实例"""
    return DecoupledTwoLayerEngine(p_threshold=0.05, ir_threshold=0.30)


# ==============================================================================
# 1. 定性命题实体规范与硬防线拦截测试
# ==============================================================================

def test_qualitative_proposition_valid_creation():
    """验证合规的定性命题实体能够正常创建与方向标准化"""
    prop = QualitativeProposition(
        proposition_id="PROP_SA701_01",
        symbol="SA701",
        node_id="NODE_03_SODA_SYN",
        driver_logic="天然碱低成本产能冲击",
        direction="short",  # 小写应自动转为大写
        evidence_tags=["[FACT] 阿拉善一期达产", "[INFERENCE] 现货纯碱价格承压"]
    )
    assert prop.direction == "SHORT"
    assert prop.has_valid_foi_tags() is True


def test_qualitative_proposition_invalid_direction_raises_error():
    """验证非法交易方向抛出 ValueError"""
    with pytest.raises(ValueError, match="Invalid proposition direction"):
        QualitativeProposition(
            proposition_id="PROP_FAIL_DIR",
            symbol="600328",
            node_id="NODE_03_SODA_SYN",
            driver_logic="无序竞争",
            direction="INVALID_DIR"
        )


def test_qualitative_proposition_prohibits_numerical_alpha():
    """
    【诚信红线硬拦截】
    严格禁止 LLM 在定性命题任何文本域中直接伪造或生成数值 Alpha，
    触发时必须抛出 Integrity Violation 异常
    """
    forbidden_cases = [
        ("天然碱投产带来超额收益 ALPHA=0.08", "LONG", ["[FACT] 产能释放"]),
        ("天然碱投产带来超额收益 ALPHA = 0.08", "LONG", ["[FACT] 产能释放"]),
        ("天然碱投产带来超额收益 ALPHA : 0.08", "LONG", ["[FACT] 产能释放"]),
        ("天然碱投产带来超额收益 ALPHA == 0.08", "LONG", ["[FACT] 产能释放"]),
        ("纯碱暴跌预期", "SHORT", ["[FACT] 库存累积", "PREDICTED_RETURN=+12.5%"]),
        ("纯碱暴跌预期", "SHORT", ["[FACT] 库存累积", "PREDICTED RETURN: +12.5%"]),
        ("目标收益率研判", "LONG", ["TARGET_RETURN_PCT: 5.5%"]),
        ("目标收益率研判", "LONG", ["TARGET RETURN: +8.0%"]),
        ("预期超额", "LONG", ["[FACT] 事实研报", "EXPECTED RETURN: +10%"]),
        ("模型置信概率研判", "LONG", ["CONFIDENCE_PROBABILITY=0.95"]),
        ("模型置信概率研判", "LONG", ["CONFIDENCE PROBABILITY: 0.95"])
    ]

    for logic, direction, tags in forbidden_cases:
        with pytest.raises(ValueError, match="Integrity Violation.*strictly prohibited from generating numerical Alpha"):
            QualitativeProposition(
                proposition_id="PROP_VIOLATION",
                symbol="SA701",
                node_id="NODE_03_SODA_SYN",
                driver_logic=logic,
                direction=direction,
                evidence_tags=tags
            )


def test_nan_returns_raise_value_error(gate_engine: DecoupledTwoLayerEngine):
    """验证输入包含 NaN/Inf 时严格抛出 ValueError，防止污染下游 JSON"""
    prop = QualitativeProposition("P_NAN", "SA701", "NODE_03_SODA_SYN", "正常逻辑", "LONG", ["[FACT] 正常标签"])
    y_nan = np.array([0.01, np.nan, 0.02] * 15)
    with pytest.raises(ValueError, match="Asset return series contains NaN or Inf values"):
        gate_engine.verify_proposition(prop, y_nan)


def test_qualitative_proposition_foi_tag_validation():
    """验证三元事实标签 ([FACT]/[OPINION]/[INFERENCE]) 的识别"""
    # 含有 [FACT]
    p1 = QualitativeProposition("P1", "SA", "N2", "logic", "LONG", ["[FACT] 注册仓单"])
    assert p1.has_valid_foi_tags() is True

    # 含有 [OPINION]
    p2 = QualitativeProposition("P2", "FG", "N3", "logic", "LONG", ["[OPINION] 预期好转"])
    assert p2.has_valid_foi_tags() is True

    # 含有 [INFERENCE]
    p3 = QualitativeProposition("P3", "000683", "N1", "logic", "LONG", ["[INFERENCE] 逻辑推导"])
    assert p3.has_valid_foi_tags() is True

    # 无三元标签
    p4 = QualitativeProposition("P4", "601636", "N4", "logic", "LONG", ["无标签的普通陈述"])
    assert p4.has_valid_foi_tags() is False


# ==============================================================================
# 2. 计量经济学算法与带宽测试
# ==============================================================================

def test_newey_west_adaptive_bandwidth_formula():
    """
    验证 Newey-West (1987) 自适应带宽滞后阶数 q = max(1, floor(4 * (T / 100)^(2/9))):
    - T = 10   -> floor(4 * (0.10)^0.222) = floor(4 * 0.599) = floor(2.39) = 2
    - T = 100  -> floor(4 * (1.00)^0.222) = 4
    - T = 250  -> floor(4 * (2.50)^0.222) = floor(4 * 1.226) = floor(4.90) = 4
    - T = 1650 -> floor(4 * (16.5)^0.222) = floor(4 * 1.865) = floor(7.46) = 7
    - T <= 0   -> 1
    """
    assert compute_newey_west_bandwidth(10) == 2
    assert compute_newey_west_bandwidth(100) == 4
    assert compute_newey_west_bandwidth(250) == 4
    assert compute_newey_west_bandwidth(1650) == 7
    assert compute_newey_west_bandwidth(0) == 1
    assert compute_newey_west_bandwidth(-100) == 1


def test_vif_multicollinearity_calculation():
    """验证方差膨胀因子 (VIF) 的多重共线性识别能力"""
    rng = np.random.RandomState(42)
    T = 200

    # 1. 独立因子: VIF 应接近 1.0
    f1 = rng.normal(0, 1, T)
    f2 = rng.normal(0, 1, T)
    vifs_indep = calculate_vif(np.column_stack([f1, f2]))
    assert len(vifs_indep) == 2
    assert all(0.8 < v < 1.5 for v in vifs_indep)

    # 2. 严重线性相关因子: VIF 应显著飙升 (> 10.0)
    f_collinear = f1 * 0.999 + rng.normal(0, 0.001, T)
    vifs_collinear = calculate_vif(np.column_stack([f1, f_collinear]))
    assert any(v > 10.0 for v in vifs_collinear)

    # 3. 单列因子维度退化
    vif_single = calculate_vif(f1)
    assert len(vif_single) == 1 and vif_single[0] == 1.0


# ==============================================================================
# 3. 双层门禁核心检验与一票否决测试
# ==============================================================================

def test_sample_size_integrity_guard(gate_engine: DecoupledTwoLayerEngine):
    """
    【样本完整性硬门禁】
    有效样本量 T < 30 时必须抛出 ValueError，杜绝过小样本伪造统计显著性
    """
    prop = QualitativeProposition("P_SMALL", "SA701", "N2", "短期冲击", "LONG", ["[FACT] 短期变动"])
    y_short = np.array([0.01, -0.02, 0.03, 0.01] * 5)  # T = 20 < 30
    with pytest.raises(ValueError, match="Insufficient common data points.*T=20 < 30"):
        gate_engine.verify_proposition(prop, y_short)


def test_dual_hurdle_pass_approve(gate_engine: DecoupledTwoLayerEngine):
    """
    验证显著真实的 Alpha 顺利通过双门禁 (p < 0.05 且 IR >= 0.30):
    生成具备稳定正向超额收益的序列
    """
    rng = np.random.RandomState(101)
    T = 250
    mkt = rng.normal(0.0002, 0.012, T)
    # 真实的日度 Alpha = +0.0020 (年化约 50%), 残差标准差 0.005 -> 年化 IR = (0.002 / 0.005) * sqrt(252) ≈ 6.35
    eps = rng.normal(0.0, 0.005, T)
    y = 0.0020 + 1.0 * mkt + eps

    prop = QualitativeProposition("P_REAL", "000683", "NODE_01_TRONA", "天然碱低成本", "LONG", ["[FACT] 真实低成本"])
    verdict = gate_engine.verify_proposition(prop, y, mkt.reshape(-1, 1), annualize=True)

    assert verdict.passed is True
    assert verdict.decision == "APPROVE"
    assert verdict.p_value < 0.05
    assert verdict.information_ratio >= 0.30
    assert verdict.conviction_level in {"HIGH_CONVICTION", "ATTRACTIVE"}
    assert verdict.bandwidth == 4


def test_one_vote_veto_reject_non_significant(gate_engine: DecoupledTwoLayerEngine):
    """
    【一票否决硬门禁 1】
    对无统计显著性 (p >= 0.05) 的白噪声/谣言假说坚决执行一票否决
    """
    rng = np.random.RandomState(202)
    T = 250
    mkt = rng.normal(0.0002, 0.012, T)
    # 纯白噪声，无任何真实 Alpha (alpha = 0.0)
    eps = rng.normal(0.0, 0.020, T)
    y = 0.85 * mkt + eps

    prop = QualitativeProposition("P_NOISE", "SA701", "NODE_03_SODA_SYN", "小道传言检修", "LONG", ["[FACT] 行业检修研判", "[OPINION] 传言停工"])
    verdict = gate_engine.verify_proposition(prop, y, mkt.reshape(-1, 1), annualize=True)

    assert verdict.passed is False
    assert verdict.decision == "REJECT_NON_SIGNIFICANT"
    assert verdict.p_value >= 0.05
    assert verdict.conviction_level == "REJECTED"
    assert "One-vote veto enforced" in verdict.reason


def test_evidence_gate_ungrounded_rumor_rejection(gate_engine: DecoupledTwoLayerEngine):
    """
    【证据链硬门禁】
    若命题仅有 [OPINION] 标签而缺少 [FACT] 标签，坚决拦截并裁决为 REJECT_UNGROUNDED_RUMOR
    """
    prop = QualitativeProposition(
        proposition_id="P_RUMOR_ONLY",
        symbol="SA701",
        node_id="NODE_03_SODA_SYN",
        driver_logic="未经证实的社交传言",
        direction="LONG",
        evidence_tags=["[OPINION] 股吧传闻", "[OPINION] 微信群小作文"]
    )
    rng = np.random.RandomState(88)
    y = rng.normal(0.002, 0.01, 100)
    verdict = gate_engine.verify_proposition(prop, y)

    assert verdict.passed is False
    assert verdict.decision == "REJECT_UNGROUNDED_RUMOR"
    assert verdict.conviction_level == "REJECTED"
    assert "No verified [FACT] evidence tag" in verdict.reason


def test_one_vote_veto_reject_low_ir(gate_engine: DecoupledTwoLayerEngine):
    """
    【一票否决硬门禁 2】
    对经济意义微弱 (IR < 0.30) 的假说坚决执行一票否决，即使在极大样本下通过了 p 检验 (p < 0.05)
    """
    rng = np.random.RandomState(42)
    T = 70000  # 极大样本使得微小 Alpha 在统计学上极度显著 (p < 0.05)
    mkt = rng.normal(0.0, 0.01, T)
    # 微小 Alpha: 日度 0.00010, 波动率 0.01 -> 年化 IR = (0.00010 / 0.01) * sqrt(252) ≈ 0.16 < 0.30
    eps = rng.normal(0.0, 0.01, T)
    y = 0.00010 + 1.0 * mkt + eps

    prop = QualitativeProposition("P_TINY", "600328", "NODE_03_SODA_SYN", "边际微弱改善", "LONG", ["[FACT] 细微提升"])
    verdict = gate_engine.verify_proposition(prop, y, mkt.reshape(-1, 1), annualize=True)

    assert verdict.passed is False
    assert verdict.decision == "REJECT_LOW_IR"
    assert verdict.p_value < 0.05  # 统计学显著
    assert verdict.information_ratio < 0.30  # 但经济意义不足
    assert verdict.conviction_level == "REJECTED"
    assert "Information Ratio too low" in verdict.reason


def test_division_by_zero_protection(gate_engine: DecoupledTwoLayerEngine):
    """
    【除零防爆保护】
    当残差平方和趋于零 (sigma_eps <= 1e-9) 时，禁止将 IR 判定为正无穷或非法大数，
    必须严格强制置为 0.0 并做除零防爆保护
    """
    T = 100
    mkt = np.linspace(-0.01, 0.01, T)
    # 完全无残差的确定性序列 (eps = 0.0)
    y = 0.001 + 1.0 * mkt

    prop = QualitativeProposition("P_ZERO_RESID", "SA701", "NODE_03_SODA_SYN", "确定性套利", "LONG", ["[FACT] 严格配对"])
    verdict = gate_engine.verify_proposition(prop, y, mkt.reshape(-1, 1), annualize=True)

    # 残差标准差极小
    assert verdict.residual_std <= 1e-6
    # IR 必须防爆保护为 0.0，杜绝 Nan 或 Inf
    assert not math.isinf(verdict.information_ratio)
    assert not math.isnan(verdict.information_ratio)
    assert verdict.information_ratio == 0.0


def test_direction_calibration_short(gate_engine: DecoupledTwoLayerEngine):
    """
    验证 SHORT 方向校准:
    标的下跌 (负收益) 在 SHORT 假设下转换为正向超额 Alpha
    """
    rng = np.random.RandomState(404)
    T = 250
    mkt = rng.normal(0.0002, 0.012, T)
    # 标的持续下跌: 日度收益率漂移 -0.0020
    eps = rng.normal(0.0, 0.005, T)
    y = -0.0020 + 0.9 * mkt + eps

    # SHORT 假设
    prop_short = QualitativeProposition("P_SHORT", "SA701", "NODE_03_SODA_SYN", "纯碱产能过剩破位", "SHORT", ["[FACT] 持续累库"])
    verdict_short = gate_engine.verify_proposition(prop_short, y, mkt.reshape(-1, 1), annualize=True)

    assert verdict_short.passed is True
    assert verdict_short.decision == "APPROVE"
    assert verdict_short.alpha_hat > 0  # 做空产生正向 Alpha
    assert verdict_short.information_ratio >= 0.30

    # 对比: 若方向为 LONG，则由于标的下跌，Alpha 将为负，无法通过门禁
    prop_long = QualitativeProposition("P_LONG_WRONG", "SA701", "NODE_03_SODA_SYN", "逆势做多", "LONG", ["[FACT] 价格统计数据", "[OPINION] 猜测见底"])
    verdict_long = gate_engine.verify_proposition(prop_long, y, mkt.reshape(-1, 1), annualize=True)
    assert verdict_long.passed is False
    assert verdict_long.decision == "REJECT_LOW_IR" or verdict_long.decision == "REJECT_NON_SIGNIFICANT"
