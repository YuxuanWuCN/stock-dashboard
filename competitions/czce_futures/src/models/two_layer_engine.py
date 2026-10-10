"""
定性命题与代码统计检验两层解耦引擎 (ADR-0001)
Two-Layer Decoupling Engine for Qualitative Proposition & Quantitative Gate

核心设计规约:
1. 定性层 (Qualitative Layer):
   - LLM 仅负责从研报与行业资讯中提取结构化 QualitativeProposition
   - 带有 [FACT], [OPINION], [INFERENCE] 三元事实标签
   - 严禁 LLM 输出数值 Alpha、概率估值乘数或直接决定仓位权重
2. 定量检验层 (Quantitative Layer):
   - 基于 Fama-MacBeth 2-Stage 时间序列/截面回归
   - Newey-West (1987) 自适应 HAC 带宽阶数选择: q = max(1, floor(4 * (T / 100)^(2/9)))
   - 双重硬门禁: 要求 p < 0.05 且 IR >= 0.30，违者坚决一票否决 (100% Veto)
   - 分母防爆除零保护: sigma(eps) <= 1e-9 -> IR = 0.0
   - 样本量防伪门禁: T < 30 抛出 ValueError
   - 方差膨胀因子 (VIF) 共线性诊断
"""

import re
from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np


def _to_clean_float(val: Any, default: float = 0.0) -> float:
    """确保数值转换为合规的有限浮点数，杜绝 NaN / Inf 破坏 RFC 8259 JSON 序列化"""
    try:
        f = float(val)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except (ValueError, TypeError):
        return default


@dataclass
class QualitativeProposition:
    """
    第一层：定性结构化命题数据实体 (ADR-0001 / ADR-0004)
    严格禁止包含任何数值 Alpha 或数值收益率预测
    """
    proposition_id: str
    symbol: str
    node_id: str
    driver_logic: str                       # 例如: "天然碱装置投产冲击", "光伏压延玻璃装机拉动"
    direction: str                          # "LONG", "SHORT", "NEUTRAL"
    evidence_tags: List[str] = field(default_factory=list) # ["[FACT] ...", "[OPINION] ...", "[INFERENCE] ..."]
    source_title: str = ""
    publish_date: str = ""
    target_commodities: List[str] = field(default_factory=list)

    def __post_init__(self):
        # 强制方向标准化
        self.direction = self.direction.strip().upper()
        if self.direction not in {"LONG", "SHORT", "NEUTRAL"}:
            raise ValueError(f"Invalid proposition direction '{self.direction}'. Must be LONG, SHORT, or NEUTRAL.")
        self.validate_no_numerical_alpha()

    def validate_no_numerical_alpha(self) -> None:
        """
        硬约束校验: 严格禁止 LLM 在定性命题中伪造或生成数值 Alpha
        采用正则匹配与空白容差，防止任何空格、冒号、等号或下划线规避
        """
        patterns = [
            r"ALPHA\s*[:=]",
            r"ALPHA\s*==",
            r"PREDICTED\s*RETURN",
            r"TARGET\s*RETURN",
            r"EXPECTED\s*RETURN",
            r"CONFIDENCE\s*PROBABILITY",
        ]
        text_payload = f"{self.driver_logic} {self.source_title} {' '.join(self.evidence_tags)}".upper()
        text_norm = re.sub(r"_", " ", text_payload)
        for pat in patterns:
            if re.search(pat, text_payload) or re.search(pat, text_norm):
                raise ValueError(
                    f"Integrity Violation: LLM is strictly prohibited from generating numerical Alpha ({pat}) in QualitativeProposition."
                )

    def has_fact_tag(self) -> bool:
        """检查命题中是否包含至少一个经过核验的 [FACT] 事实标签"""
        if not self.evidence_tags:
            return False
        return any(str(tag).strip().upper().startswith("[FACT]") for tag in self.evidence_tags)

    def validate_evidence_gate(self) -> None:
        """严格证据链门禁: 若仅有 [OPINION] 或未知标签，坚决抛出异常或驳回"""
        if not self.has_fact_tag():
            raise ValueError("REJECT_UNGROUNDED_RUMOR: Proposition lacks at least one verified [FACT] tag.")

    def has_valid_foi_tags(self) -> bool:
        """检查是否具备有效的 [FACT], [OPINION], [INFERENCE] 三元事实标签"""
        if not self.evidence_tags:
            return False
        has_fact = any("[FACT]" in tag.upper() for tag in self.evidence_tags)
        has_opinion_or_inf = any("[OPINION]" in tag.upper() or "[INFERENCE]" in tag.upper() for tag in self.evidence_tags)
        return has_fact or has_opinion_or_inf


@dataclass
class GateVerdict:
    """第二层：代码统计硬门禁检验裁决实体"""
    passed: bool                  # 仅当 (p < 0.05 AND IR >= 0.30) 时为 True
    decision: str                 # "APPROVE" | "REJECT_NON_SIGNIFICANT" | "REJECT_LOW_IR"
    alpha_hat: float              # 经因子剥离后的年化/标称特质超额 Alpha
    p_value: float                # Newey-West HAC 稳健双侧检验 p 值
    information_ratio: float      # 年化信息比率 IR = (alpha / sigma_eps) * sqrt(252)
    bandwidth: int                # Newey-West 自适应滞后阶数 q
    reason: str                   # 详细决策归因解释
    conviction_level: str = "NONE" # "HIGH_CONVICTION", "ATTRACTIVE", "INTERESTING_SMALL", "REJECTED"
    vif_max: float = 1.0          # 最大方差膨胀因子
    residual_std: float = 0.0     # 残差标准差


def compute_newey_west_bandwidth(n_obs: int) -> int:
    """
    计算 Newey-West (1987, 1994) 自适应滞后阶数/带宽 q:
    q = max(1, floor(4.0 * (T / 100.0)^(2/9)))
    
    验证锚点:
    - T = 10   -> q = 2
    - T = 100  -> q = 4
    - T = 250  -> q = 4
    - T = 1650 -> q = 7
    """
    if n_obs <= 0:
        return 1
    q = int(math.floor(4.0 * math.pow(float(n_obs) / 100.0, 2.0 / 9.0)))
    return max(1, q)


def calculate_vif(factor_matrix: np.ndarray) -> np.ndarray:
    """
    计算因子矩阵各维度的方差膨胀因子 (Variance Inflation Factor, VIF)
    用于检测多因子共线性，防止参数估计严重失真
    """
    X = np.asarray(factor_matrix, dtype=float)
    if X.ndim == 1:
        return np.array([1.0])
    
    n_samples, n_features = X.shape
    if n_features <= 1:
        return np.ones(n_features)

    vifs = np.ones(n_features)
    for i in range(n_features):
        y_i = X[:, i]
        X_others = np.delete(X, i, axis=1)
        # 添加常数项
        X_design = np.column_stack([np.ones(n_samples), X_others])
        try:
            beta, residuals, rank, s = np.linalg.lstsq(X_design, y_i, rcond=None)
            y_pred = X_design @ beta
            ss_tot = np.sum((y_i - np.mean(y_i)) ** 2)
            ss_res = np.sum((y_i - y_pred) ** 2)
            if ss_tot <= 1e-12:
                r_squared = 0.0
            else:
                r_squared = max(0.0, min(1.0, 1.0 - (ss_res / ss_tot)))
            
            denom = 1.0 - r_squared
            vifs[i] = 1.0 / denom if denom > 1e-6 else 1e6
        except Exception:
            vifs[i] = 1.0

    return vifs


class DecoupledTwoLayerEngine:
    """
    定性定量两层解耦引擎中枢 (ADR-0001)
    承接定性命题输入，执行 Fama-MacBeth 2-Stage OLS 回归与 Newey-West HAC 双重硬门禁
    """

    def __init__(self, p_threshold: float = 0.05, ir_threshold: float = 0.30):
        self.p_threshold = p_threshold
        self.ir_threshold = ir_threshold

    def verify_proposition(
        self,
        prop: QualitativeProposition,
        asset_returns: np.ndarray,
        factor_returns: Optional[np.ndarray] = None,
        annualize: bool = True
    ) -> GateVerdict:
        """
        对定性命题执行独立的计量统计硬门禁检验
        
        Args:
            prop: 结构化定性假设 (包含标的、假设方向、证据标签)
            asset_returns: 标的收益率时间序列 (有效数据行数需 >= 30)
            factor_returns: 基准因子收益率矩阵 (shape: (T, K) 或 (T,))，若为 None 则退化为单资产均值检验
            annualize: 是否按 252 交易日对 Alpha 与 IR 进行年化
            
        Returns:
            GateVerdict: 门禁检验裁决实体 (包含 passed, decision, alpha_hat, p_value, IR, reason)
        """
        # 1. 样本容量与数值有效性硬门禁 (NaN / Inf / T < 30)
        y = np.asarray(asset_returns, dtype=float).flatten()
        if np.isnan(y).any() or np.isinf(y).any():
            raise ValueError("Asset return series contains NaN or Inf values")
        T = len(y)
        if T < 30:
            raise ValueError(f"Insufficient common data points: T={T} < 30")

        # 2. 定性证据链事实硬门禁 (必须包含至少一个 [FACT] 标签)
        if not prop.has_fact_tag():
            return GateVerdict(
                passed=False,
                decision="REJECT_UNGROUNDED_RUMOR",
                alpha_hat=0.0,
                p_value=1.0,
                information_ratio=0.0,
                bandwidth=1,
                reason="Proposition rejected: No verified [FACT] evidence tag provided (ungrounded rumor).",
                conviction_level="REJECTED",
                vif_max=1.0,
                residual_std=0.0
            )

        # 3. 因子对齐与共线性诊断
        if factor_returns is not None:
            X_raw = np.asarray(factor_returns, dtype=float)
            if X_raw.ndim == 1:
                X_raw = X_raw.reshape(-1, 1)
            if len(X_raw) != T:
                raise ValueError(f"Mismatched data lengths: asset_returns={T}, factor_returns={len(X_raw)}")
            vifs = calculate_vif(X_raw)
            max_vif = float(np.max(vifs))
        else:
            X_raw = np.zeros((T, 0))
            max_vif = 1.0

        # 4. 构造回归设计矩阵 [1, X]
        X_design = np.column_stack([np.ones(T), X_raw])
        K_factors = X_raw.shape[1]

        # 5. Fama-MacBeth Stage 1 OLS 回归
        try:
            # 使用伪逆以防御奇异矩阵完全共线性 (Edge Case E6)
            beta_hat, residuals, rank, s = np.linalg.lstsq(X_design, y, rcond=None)
            y_pred = X_design @ beta_hat
            eps = y - y_pred
        except Exception as e:
            return GateVerdict(
                passed=False,
                decision="REJECT_NON_SIGNIFICANT",
                alpha_hat=0.0,
                p_value=1.0,
                information_ratio=0.0,
                bandwidth=1,
                reason=f"OLS Regression failed due to singular matrix: {str(e)}",
                conviction_level="REJECTED",
                vif_max=_to_clean_float(round(max_vif, 2), default=1.0),
                residual_std=0.0
            )

        # 6. 残差方差与除零防爆保护 (Edge Case E5)
        df_denom = max(1, T - K_factors - 1)
        ss_res = np.sum(eps ** 2)
        sigma_eps = math.sqrt(ss_res / df_denom)

        raw_alpha = float(beta_hat[0])

        # 7. 方向校准: 若命题为 SHORT，标的下跌带来正向做空超额收益
        effective_alpha = -raw_alpha if prop.direction == "SHORT" else raw_alpha

        # 8. Newey-West (1987) 自适应 HAC 稳健协方差估计 (Edge Case E2)
        q = compute_newey_west_bandwidth(T)
        
        # 计算 OLS 矩条件得分 u_t = X_design[t] * eps[t]
        u = X_design * eps[:, np.newaxis]  # shape: (T, K+1)
        
        # Gamma_0
        gamma_0 = (u.T @ u) / float(T)
        s_hac = gamma_0.copy()
        
        # Bartlett 核加权求和
        for j in range(1, q + 1):
            weight = 1.0 - (float(j) / float(q + 1))
            u_t = u[j:]
            u_t_minus_j = u[:-j]
            gamma_j = (u_t.T @ u_t_minus_j) / float(T)
            s_hac += weight * (gamma_j + gamma_j.T)

        # HAC 参数协方差矩阵: V_HAC = T * (X'X)^(-1) * S_HAC * (X'X)^(-1)
        try:
            xtx_inv = np.linalg.pinv(X_design.T @ X_design)
            v_hac = float(T) * (xtx_inv @ s_hac @ xtx_inv)
            var_alpha = float(v_hac[0, 0])
            se_alpha = math.sqrt(max(1e-12, var_alpha))
        except Exception:
            se_alpha = 1.0

        # 9. 双侧 t 检验与 p 值计算
        t_stat = effective_alpha / se_alpha
        # 标准正态分布双侧 p 值: p = 2 * (1 - Phi(|t|))
        abs_t = abs(t_stat)
        p_val = math.erfc(abs_t / math.sqrt(2.0))
        p_val = max(0.0, min(1.0, p_val))

        # 10. 信息比率 (Information Ratio, IR) 与除零防爆
        if sigma_eps <= 1e-9:
            # 严格强制为 0.0，杜绝伪造为大正数
            ir_val = 0.0
        else:
            daily_ir = effective_alpha / sigma_eps
            ir_val = daily_ir * math.sqrt(252.0) if annualize else daily_ir

        # 年化 Alpha 标称值
        display_alpha = effective_alpha * 252.0 if annualize else effective_alpha

        # 11. 双重门禁一票否决决策状态机 (Edge Cases E3, E4)
        if p_val >= self.p_threshold:
            # 统计显著性不达标，一票否决
            passed = False
            decision = "REJECT_NON_SIGNIFICANT"
            reason = (
                f"Alpha is not statistically significant (p={p_val:.4f} >= {self.p_threshold:.2f}). "
                f"One-vote veto enforced on noise/spurious proposition."
            )
            conviction = "REJECTED"
        elif ir_val < self.ir_threshold:
            # 经济显著性不达标，一票否决
            passed = False
            decision = "REJECT_LOW_IR"
            reason = (
                f"Information Ratio too low (IR={ir_val:.4f} < {self.ir_threshold:.2f}) - "
                f"Alpha not economically meaningful despite p={p_val:.4f}."
            )
            conviction = "REJECTED"
        else:
            # 双门禁完全通过
            passed = True
            decision = "APPROVE"
            if ir_val >= 1.0:
                conviction = "HIGH_CONVICTION"
            elif ir_val >= 0.50:
                conviction = "ATTRACTIVE"
            else:
                conviction = "INTERESTING_SMALL"

            reason = (
                f"Approved ({conviction}) - Statistically significant (p={p_val:.4f} < {self.p_threshold:.2f}) "
                f"and economically robust (IR={ir_val:.4f} >= {self.ir_threshold:.2f})."
            )

        return GateVerdict(
            passed=passed,
            decision=decision,
            alpha_hat=_to_clean_float(round(display_alpha, 4)),
            p_value=_to_clean_float(round(p_val, 6), default=1.0),
            information_ratio=_to_clean_float(round(ir_val, 4)),
            bandwidth=int(q),
            reason=reason,
            conviction_level=conviction,
            vif_max=_to_clean_float(round(max_vif, 2), default=1.0),
            residual_std=_to_clean_float(round(sigma_eps, 6))
        )
