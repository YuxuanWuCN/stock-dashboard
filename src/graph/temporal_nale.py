# -*- coding: utf-8 -*-
r"""src/graph/temporal_nale.py —— Temporal-NALE (T-NALE) 时空连续图扩散量化模型

理论参考文献：
1. Menzly, L., & Ozbas, O. (2010). Market Segmentation and Cross-Industry Information Diffusion.
   The Journal of Finance, 65(5), 1555-1593.
2. Cohen, L., & Frazzini, A. (2008). Economic Links and Predictable Returns.
   The Journal of Finance, 63(4), 1977-2011.
3. Rossi, E., et al. (2020). Temporal Graph Networks for Deep Learning on Dynamic Graphs.
   ICLR / NeurIPS Dynamic Graphs Workshop.
4. Yılkı, M. (2026). Network-Augmented LLM Embeddings (NALE) in Financial Markets.

数学原理：
将静态一阶随机游走升级为时空连续卷积算子：
S_i(t, h) = (1 - \alpha) * [S_{0, i}(t) * exp(-\lambda_i * h)]
          + \alpha * \sum_{j} W_{ji} * K_{lag}(h - \tau_{ji}, \sigma_{ji}) * [S_{0, j}(t_j) * exp(-\lambda_j * (t - t_j))]
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import scipy.sparse as sp

from src.graph.temporal_constants import (
    DEFAULT_LAG_CONFIG,
    INFORMATION_HALF_LIVES,
    SupplyChainLagConfig,
    get_half_life,
    get_supply_chain_lag,
)
from src.graph.dynamic_temporal_alpha import DynamicTemporalAlpha


@dataclass
class TemporalNALEResult:
    """T-NALE 单个预测视界下的标的增强得分。"""
    ticker: str
    horizon_days: float               # 预测向前视界天数 h
    raw_self_score: float             # 标的原生事实得分 S_0
    self_decayed_score: float         # 自身动能经半衰期衰减后得分
    propagated_impulse: float         # 上游/同盟经时滞高斯卷积传入的冲击强度
    final_score: float                # 最终 T-NALE 综合评分 [-1.0, 1.0]
    alpha: float                      # 网络扩散权重
    peak_horizon_days: Optional[float] = None  # 冲击波峰值预计抵达天数 h*
    peak_score: Optional[float] = None         # 峰值预计强度


@dataclass
class TrajectoryResult:
    """标的在未来全景时域 [h_1, ..., h_m] 上的推演轨迹。"""
    ticker: str
    horizons: List[float]
    scores: List[float]
    peak_horizon: float
    peak_score: float
    immediate_impact_1d: float
    swing_impact_5d: float
    trend_impact_20d: float


class TemporalNALEEngine:
    """Temporal-NALE (T-NALE) 时空连续图扩散计算引擎。"""

    def __init__(
        self,
        alpha: float = 0.4,
        default_tau: float = 14.0,
        default_sigma: float = 5.0,
        enable_clipping: bool = True,
        use_dynamic_alpha: bool = False,
        dynamic_alpha_engine: Optional[DynamicTemporalAlpha] = None
    ):
        self.alpha = alpha
        self.default_tau = default_tau
        self.default_sigma = default_sigma
        self.enable_clipping = enable_clipping
        self.use_dynamic_alpha = use_dynamic_alpha
        self.dynamic_alpha_engine = dynamic_alpha_engine or DynamicTemporalAlpha()

    @staticmethod
    def gaussian_impulse_kernel(
        h: float,
        tau: float,
        sigma: float,
        attenuation: float = 0.85
    ) -> float:
        r"""计算物理库存流转与订单传递的高斯脉冲卷积核。

        K_{lag}(h - \tau, \sigma) = \eta * \exp( - (h - \tau)^2 / (2 * \sigma^2) )
        当 h = \tau 时，冲击波峰值抵达，传导效率达到最大值 \eta。
        """
        if sigma <= 1e-6:
            # 退化为狄拉克脉冲
            return attenuation if abs(h - tau) < 1e-3 else 0.0
        exponent = -((h - tau) ** 2) / (2.0 * (sigma ** 2))
        return float(attenuation * math.exp(exponent))

    @staticmethod
    def exponential_decay_kernel(delta_t: float, half_life_days: float) -> float:
        r"""计算金融信息的指数半衰期衰减核。

        \kappa(\Delta t) = \exp( - \frac{\ln 2}{H} \cdot \Delta t )
        """
        if delta_t <= 0.0 or half_life_days <= 0.0:
            return 1.0
        decay_rate = math.log(2.0) / half_life_days
        return float(math.exp(-decay_rate * delta_t))

    def calculate_temporal_nale(
        self,
        node_scores: Dict[str, float],
        adjacency_matrix: Union[np.ndarray, sp.spmatrix],
        ticker_list: List[str],
        horizon_days: float = 5.0,
        node_ages_days: Optional[Dict[str, float]] = None,
        node_source_types: Optional[Dict[str, str]] = None,
        edge_lag_matrix: Optional[np.ndarray] = None,
        edge_sigma_matrix: Optional[np.ndarray] = None,
        edge_attenuation_matrix: Optional[np.ndarray] = None,
        ticker_categories: Optional[Dict[str, str]] = None,
        alpha: Optional[float] = None,
        use_dynamic_alpha: Optional[bool] = None
    ) -> Dict[str, TemporalNALEResult]:
        r"""计算指定未来预测视界 h (horizon_days) 处的 T-NALE 连续时空扩散得分。

        参数：
        - node_scores: 各标的原始事实得分 S_0 (来自 LLM/基本面/高频行情)
        - adjacency_matrix: N x N 归一化有向经济邻接矩阵 W (行和为 1，W_{ij} 表示信息从 j 传向 i)
        - ticker_list: 标的代码有序列表
        - horizon_days: 向前推演天数 h >= 0 (如 h=5.0)
        - node_ages_days: 各标的原始事件距今已过去的天数 (t - t_j)，默认为 0.0
        - node_source_types: 各标的数据源类别 (用于自动匹配半衰期 H)
        - edge_lag_matrix: N x N 物理时滞矩阵 \tau_{ji}
        - edge_sigma_matrix: N x N 高斯脉冲带宽矩阵 \sigma_{ji}
        - edge_attenuation_matrix: N x N 能量损耗衰减矩阵 \eta_{ji}
        - ticker_categories: 各标的所属产业链板块 (用于若未指定矩阵时自动从先验库构建)
        - alpha: 图扩散权重 (若显式传入则强制使用静态值，否则根据 use_dynamic_alpha 决定)
        - use_dynamic_alpha: 是否启用方案 B 双波峰时效性动态 alpha(t) 动力学
        """
        enable_dyn_alpha = use_dynamic_alpha if use_dynamic_alpha is not None else self.use_dynamic_alpha
        N = len(ticker_list)
        if N == 0:
            return {}

        # 校验邻接矩阵维度
        if adjacency_matrix.shape != (N, N):
            raise ValueError(f"邻接矩阵维度 {adjacency_matrix.shape} 与标的数 {N} 不匹配。")

        # 转换为密集矩阵便于运算
        if sp.issparse(adjacency_matrix):
            W = adjacency_matrix.toarray()
        else:
            W = np.array(adjacency_matrix, dtype=float)

        # 归一化邻接矩阵行和 (随机游走马尔可夫转移矩阵)
        row_sums = W.sum(axis=1, keepdims=True)
        W = np.divide(W, row_sums, out=np.zeros_like(W), where=row_sums != 0)

        # 1. 计算各节点自身信息向未来 horizon 的衰减
        node_ages = node_ages_days or {}
        source_types = node_source_types or {}
        categories = ticker_categories or {}

        S0_vec = np.zeros(N, dtype=float)
        self_decay_vec = np.zeros(N, dtype=float)
        past_decayed_source_vec = np.zeros(N, dtype=float)

        for i, ticker in enumerate(ticker_list):
            s0 = float(node_scores.get(ticker, 0.0))
            S0_vec[i] = s0

            stype = source_types.get(ticker, "default")
            hl_cfg = get_half_life(stype)
            H = hl_cfg.half_life_days

            # 自身动能向未来 h 天的衰减系数
            self_decay_factor = self.exponential_decay_kernel(horizon_days, H)
            self_decay_vec[i] = s0 * self_decay_factor

            # 历史事件距今过去时间 (t - t_j) 的陈旧度衰减
            age = float(node_ages.get(ticker, 0.0))
            hist_decay_factor = self.exponential_decay_kernel(age, H)
            past_decayed_source_vec[i] = s0 * hist_decay_factor

        # 2. 计算上游向各节点的时滞高斯卷积核矩阵 K_{lag}(h - \tau_{ji}, \sigma_{ji})
        K_lag = np.zeros((N, N), dtype=float)

        for i in range(N):
            tgt_cat = categories.get(ticker_list[i], "")
            for j in range(N):
                if W[i, j] <= 0.0:
                    continue
                # 获取边上时滞参数
                if edge_lag_matrix is not None:
                    tau = float(edge_lag_matrix[i, j])
                    sigma = float(edge_sigma_matrix[i, j]) if edge_sigma_matrix is not None else self.default_sigma
                    eta = float(edge_attenuation_matrix[i, j]) if edge_attenuation_matrix is not None else 0.85
                else:
                    src_cat = categories.get(ticker_list[j], "")
                    lag_cfg = get_supply_chain_lag(src_cat, tgt_cat)
                    tau = lag_cfg.tau_days
                    sigma = lag_cfg.sigma_days
                    eta = lag_cfg.attenuation_factor

                K_lag[i, j] = self.gaussian_impulse_kernel(horizon_days, tau, sigma, eta)

        # 3. 计算时空卷积传播向量: P = (W \odot K_lag) @ past_decayed_source_vec
        effective_W = W * K_lag
        propagated_vec = effective_W @ past_decayed_source_vec

        # 4. 融合自身衰减与时滞卷积传播 (支持静态 alpha 与方案 B 时效性双峰动态 alpha)
        if alpha is not None:
            node_alphas = np.full(N, float(alpha))
        elif enable_dyn_alpha:
            node_alphas = np.zeros(N, dtype=float)
            for i, ticker in enumerate(ticker_list):
                tgt_cat = categories.get(ticker, "")
                lag_cfg = get_supply_chain_lag(tgt_cat, tgt_cat)
                tau_val = float(lag_cfg.tau_days)
                sigma_val = float(lag_cfg.sigma_days)
                age_val = float(node_ages.get(ticker, 0.0))
                t_total = age_val + float(horizon_days)
                has_event = bool(abs(past_decayed_source_vec[i]) > 1e-4 or (np.max(np.abs(propagated_vec)) > 1e-4))
                node_alphas[i] = self.dynamic_alpha_engine.compute_alpha(
                    t=t_total,
                    tau=tau_val,
                    sigma=sigma_val,
                    has_limit_up_or_event=has_event
                )
        else:
            node_alphas = np.full(N, float(self.alpha))

        final_scores = (1.0 - node_alphas) * self_decay_vec + node_alphas * propagated_vec

        if self.enable_clipping:
            final_scores = np.clip(final_scores, -1.0, 1.0)

        results: Dict[str, TemporalNALEResult] = {}
        for i, ticker in enumerate(ticker_list):
            results[ticker] = TemporalNALEResult(
                ticker=ticker,
                horizon_days=horizon_days,
                raw_self_score=float(S0_vec[i]),
                self_decayed_score=float(self_decay_vec[i]),
                propagated_impulse=float(propagated_vec[i]),
                final_score=float(final_scores[i]),
                alpha=float(node_alphas[i])
            )

        return results

    def predict_trajectory(
        self,
        node_scores: Dict[str, float],
        adjacency_matrix: Union[np.ndarray, sp.spmatrix],
        ticker_list: List[str],
        horizons: Optional[List[float]] = None,
        node_ages_days: Optional[Dict[str, float]] = None,
        node_source_types: Optional[Dict[str, str]] = None,
        ticker_categories: Optional[Dict[str, str]] = None,
        alpha: Optional[float] = None,
        use_dynamic_alpha: Optional[bool] = None
    ) -> Dict[str, TrajectoryResult]:
        r"""推演各标的在未来全景时域 [h_1, ..., h_m] 上的连续冲击扩散轨迹，标定峰值启动视界。"""
        if horizons is None:
            horizons = [1.0, 3.0, 5.0, 7.0, 10.0, 15.0, 20.0, 30.0]

        horizon_results: Dict[float, Dict[str, TemporalNALEResult]] = {}
        for h in horizons:
            res_h = self.calculate_temporal_nale(
                node_scores=node_scores,
                adjacency_matrix=adjacency_matrix,
                ticker_list=ticker_list,
                horizon_days=h,
                node_ages_days=node_ages_days,
                node_source_types=node_source_types,
                ticker_categories=ticker_categories,
                alpha=alpha,
                use_dynamic_alpha=use_dynamic_alpha
            )
            horizon_results[h] = res_h

        trajectories: Dict[str, TrajectoryResult] = {}
        for ticker in ticker_list:
            scores_over_time = [horizon_results[h][ticker].final_score for h in horizons]
            # 寻找波峰 (最高得分时窗)
            max_idx = int(np.argmax(scores_over_time))
            peak_h = horizons[max_idx]
            peak_s = scores_over_time[max_idx]

            # 提取典型周期切片 (1d, 5d, 20d)
            s_1d = horizon_results.get(1.0, {}).get(ticker, horizon_results[horizons[0]][ticker]).final_score
            s_5d = horizon_results.get(5.0, {}).get(ticker, horizon_results[horizons[min(2, len(horizons)-1)]][ticker]).final_score
            s_20d = horizon_results.get(20.0, {}).get(ticker, horizon_results[horizons[-1]][ticker]).final_score

            trajectories[ticker] = TrajectoryResult(
                ticker=ticker,
                horizons=horizons,
                scores=scores_over_time,
                peak_horizon=peak_h,
                peak_score=peak_s,
                immediate_impact_1d=round(s_1d, 4),
                swing_impact_5d=round(s_5d, 4),
                trend_impact_20d=round(s_20d, 4)
            )

        return trajectories

    def verify_asymptotic_equivalence(
        self,
        node_scores: Dict[str, float],
        adjacency_matrix: np.ndarray,
        ticker_list: List[str],
        alpha: float = 0.4,
        tolerance: float = 1e-6
    ) -> Tuple[bool, float]:
        r"""数学定理渐近一致性检验：
        当 h=0, \tau_{ji}=0, \lambda=0 且脉冲卷积核衰减等于 1 时，
        T-NALE 数学上严格退化为经典静态 NALE 方程：
        S_{NALE} = (1 - \alpha) S_0 + \alpha (W S_0)
        """
        N = len(ticker_list)
        S0_vec = np.array([node_scores.get(t, 0.0) for t in ticker_list])
        W = np.array(adjacency_matrix, dtype=float)

        # 经典静态 NALE
        static_nale = (1.0 - alpha) * S0_vec + alpha * (W @ S0_vec)
        if self.enable_clipping:
            static_nale = np.clip(static_nale, -1.0, 1.0)

        # T-NALE 在退化极限条件下的求解
        zero_lags = np.zeros((N, N))
        huge_sigmas = np.ones((N, N)) * 1e6  # 极大带宽使得高斯核恒等于 1.0
        full_attenuation = np.ones((N, N))   # 无损耗

        t_res = self.calculate_temporal_nale(
            node_scores=node_scores,
            adjacency_matrix=adjacency_matrix,
            ticker_list=ticker_list,
            horizon_days=0.0,
            node_ages_days={t: 0.0 for t in ticker_list},
            edge_lag_matrix=zero_lags,
            edge_sigma_matrix=huge_sigmas,
            edge_attenuation_matrix=full_attenuation,
            alpha=alpha
        )

        tnale_vec = np.array([t_res[t].final_score for t in ticker_list])
        max_diff = float(np.max(np.abs(static_nale - tnale_vec)))
        is_equivalent = max_diff <= tolerance
        return is_equivalent, max_diff
