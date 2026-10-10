# -*- coding: utf-8 -*-
"""
产业链非对称时空图注意力神经网络 (Temporal NALE: Asymmetric ST-GAT Engine)
-------------------------------------------------------------------------
构建“原料端(煤炭/原盐) -> 纯碱(SA) -> 玻璃(FG) -> 光伏组件”的时空图网络拓扑。
Round 2 Literature Evolution:
1. 非对称时滞脉冲响应核算子 (AsymmetricTemporalKernel):
   刻画“成本推涨传导快(tau_up=10天, theta_up=14天)、降价粘性强(tau_down=28天, theta_down=35天)”的微观物理非对称性。
2. 供需偏离度自适应时空图注意力机制 (SupplyDemandAttentionSTGAT):
   基于微观供需偏离度 (现货库存去化、装置开工率、加工利润走阔/收窄) 动态求解图注意力权重 alpha_ij(t)。
3. 严格因果无前视卷积与向后兼容接口 (compute_chain_response / compute_crush_spread)。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union
import numpy as np
import pandas as pd

from src.data.feature_engineering import (
    calculate_crush_spread,
    DEFAULT_FUEL_COST_PER_TON,
    DEFAULT_SA_STOICHIOMETRIC_RATIO
)


@dataclass
class ChainNode:
    """产业链图拓扑节点定义"""
    name: str
    stage: str  # 'upstream', 'midstream', 'downstream'
    weight: float = 1.0
    half_life_days: float = 20.0  # 信息半衰期 theta (天)
    lead_lag_days: float = 15.0   # 物理传导主峰值 tau_0 (天)


@dataclass
class TemporalNALEConfig:
    """Temporal NALE 模型超参数配置规范"""
    window: int = 60
    sa_to_fg_lag: float = 18.0
    sa_half_life: float = 25.0
    fg_lag: float = 5.0
    fg_half_life: float = 15.0
    use_asymmetric_kernel: bool = True
    tau_up: float = 10.0
    tau_down: float = 28.0
    half_life_up: float = 14.0
    half_life_down: float = 35.0
    sigma_up: float = 4.0
    sigma_down: float = 8.0
    use_stgat_attention: bool = True
    gamma_divergence: float = 1.5
    leaky_relu_alpha: float = 0.2
    fuel_cost_per_ton: float = 350.0
    cost_weight: float = 1.5
    demand_weight: float = 0.8
    inventory_weight: float = 0.0          # 行业微观库存项权重 (无真实源时置 0 优雅降级为纯价差偏离度)
    divergence_ema_span: Optional[int] = 5 # 供需偏离度因果平滑窗口 (抑制日间跳变)
    signal_ema_span: Optional[int] = 5     # NALE 先行信号因果平滑窗口 (保证 std < 0.15)


class TemporalConvolutionKernel:
    """因果无未来时滞卷积核算子 (Causal Gaussian-Exponential Impulse Kernel)"""

    def __init__(
        self,
        lead_lag_days: float = 15.0,
        half_life_days: float = 20.0,
        kernel_window: int = 60,
        sigma: float = 5.0
    ):
        """
        参数:
        - lead_lag_days (tau_0): 物理交割与库存周转时滞主峰值（天）
        - half_life_days (theta): 边际信息衰减半衰期（天）
        - kernel_window (W): 过去滑动窗口长度，必须严格历史对齐（天）
        - sigma: 高斯时滞脉冲扩散宽度（天）
        """
        assert lead_lag_days >= 0, "物理时滞天数必须非负"
        assert half_life_days > 0, "半衰期必须严格大于0"
        assert kernel_window > lead_lag_days, "窗口长度必须大于物理主时滞"
        
        self.tau_0 = lead_lag_days
        self.theta = half_life_days
        self.window = kernel_window
        self.sigma = sigma
        
        # 预计算归一化因果权重 (t_diff in [0, window-1], 0 代表当下，window-1 代表过去)
        dt = np.arange(self.window, dtype=np.float64)
        # 高斯脉冲核 (在 tau_0 处达到响应峰值) * 指数衰减 (信息随时间消散)
        gaussian_pulse = np.exp(-((dt - self.tau_0) ** 2) / (2.0 * (self.sigma ** 2)))
        decay = np.exp(-dt / self.theta)
        weights = gaussian_pulse * decay
        
        # 归一化为有界算子
        sum_w = np.sum(weights)
        self.weights = weights / (sum_w if sum_w > 0 else 1.0)

    def convolve_causal(self, series: np.ndarray) -> np.ndarray:
        """严格因果卷积：每个时间点仅依赖其前 window 天历史，无任何前视信息"""
        n = len(series)
        output = np.zeros(n, dtype=np.float64)
        pad_series = np.pad(series, (self.window - 1, 0), mode='edge')
        
        for i in range(n):
            # 提取历史窗口 [t - window + 1, t]，倒序点乘因果核
            window_slice = pad_series[i : i + self.window][::-1]
            output[i] = np.dot(window_slice, self.weights)
            
        return output


class AsymmetricTemporalKernel:
    """
    非对称因果时滞脉冲响应核算子 (Asymmetric Causal Impulse Response Kernel)
    ------------------------------------------------------------------------
    针对大宗产业链“成本推涨传导快、降价粘性强”的微观物理非对称性：
    - 正向价格冲击 (Delta P >= 0, 成本推涨):
      时滞峰值 tau_up (约 10 天), 半衰期 half_life_up (约 14 天), 扩散宽度 sigma_up (4.0)
    - 负向价格冲击 (Delta P < 0, 价格粘性):
      时滞峰值 tau_down (约 28 天), 半衰期 half_life_down (约 35 天), 扩散宽度 sigma_down (8.0)
    """

    def __init__(
        self,
        tau_up: float = 10.0,
        tau_down: float = 28.0,
        half_life_up: float = 14.0,
        half_life_down: float = 35.0,
        kernel_window: int = 60,
        sigma_up: float = 4.0,
        sigma_down: float = 8.0
    ):
        assert tau_up >= 0, "正向时滞必须非负"
        assert tau_down >= 0, "负向时滞必须非负"
        assert half_life_up > 0, "正向半衰期必须大于0"
        assert half_life_down > 0, "负向半衰期必须大于0"
        assert kernel_window > max(tau_up, tau_down), "窗口长度必须大于最大时滞"

        self.tau_up = tau_up
        self.tau_down = tau_down
        self.half_life_up = half_life_up
        self.half_life_down = half_life_down
        self.window = kernel_window
        self.sigma_up = sigma_up
        self.sigma_down = sigma_down

        dt = np.arange(self.window, dtype=np.float64)

        # 1. 成本推涨正向核 (Cost-push Upward Kernel)
        w_up_raw = np.exp(-((dt - self.tau_up) ** 2) / (2.0 * (self.sigma_up ** 2))) * np.exp(-dt / self.half_life_up)
        sum_up = np.sum(w_up_raw)
        self.weights_up = w_up_raw / (sum_up if sum_up > 0 else 1.0)

        # 2. 降价粘性负向核 (Sticky Downward Kernel)
        w_down_raw = np.exp(-((dt - self.tau_down) ** 2) / (2.0 * (self.sigma_down ** 2))) * np.exp(-dt / self.half_life_down)
        sum_down = np.sum(w_down_raw)
        self.weights_down = w_down_raw / (sum_down if sum_down > 0 else 1.0)

    @property
    def peak_up(self) -> int:
        """正向冲击响应达到极大值的时滞天数"""
        return int(np.argmax(self.weights_up))

    @property
    def peak_down(self) -> int:
        """负向冲击响应达到极大值的时滞天数"""
        return int(np.argmax(self.weights_down))

    def convolve_asymmetric(self, series: np.ndarray, pad_mode: str = 'constant') -> np.ndarray:
        """
        因果非对称卷积：
        根据历史各时点的冲击符号（正向冲击 Delta P >= 0 对应快速成本推涨，
        负向冲击 Delta P < 0 对应慢速价格粘性），分别采用各自的时滞衰减核进行历史加权点乘。
        时刻 t 的输出严格仅由 s <= t 的历史决定，杜绝任何未来信息泄漏。
        """
        n = len(series)
        output = np.zeros(n, dtype=np.float64)

        pos_series = np.maximum(series, 0.0)
        neg_series = np.minimum(series, 0.0)

        pad_pos = np.pad(pos_series, (self.window - 1, 0), mode=pad_mode)
        pad_neg = np.pad(neg_series, (self.window - 1, 0), mode=pad_mode)

        for i in range(n):
            w_pos_slice = pad_pos[i : i + self.window][::-1]
            w_neg_slice = pad_neg[i : i + self.window][::-1]
            output[i] = np.dot(w_pos_slice, self.weights_up) + np.dot(w_neg_slice, self.weights_down)

        return output


class SupplyDemandAttentionSTGAT:
    """
    供需偏离度自适应时空图注意力层 (Supply-Demand Divergence ST-GAT)
    -----------------------------------------------------------------
    在产业链“上游成本推涨 (i -> u)”与“下游需求承接 (i -> d)”的双通道拓扑中，
    引入外生供需偏离度 Divergence_t（高频库存去化、装置开工率、加工裂解利润异动），
    自适应动态计算空间图注意力权重：
    alpha_{ij}(t) = Softmax(LeakyReLU(a^T [h_i || h_j] + gamma * Divergence_t))
    """

    def __init__(
        self,
        in_features: int = 1,
        gamma: float = 1.5,
        leaky_relu_alpha: float = 0.2,
        a_upstream: Optional[np.ndarray] = None,
        a_downstream: Optional[np.ndarray] = None
    ):
        self.in_features = in_features
        self.gamma = gamma
        self.leaky_relu_alpha = leaky_relu_alpha

        dim = 2 * in_features
        if a_upstream is not None:
            self.a_upstream = np.asarray(a_upstream, dtype=np.float64).reshape(dim, 1)
        else:
            self.a_upstream = np.ones((dim, 1), dtype=np.float64) * 0.5

        if a_downstream is not None:
            self.a_downstream = np.asarray(a_downstream, dtype=np.float64).reshape(dim, 1)
        else:
            self.a_downstream = np.ones((dim, 1), dtype=np.float64) * 0.5

    def _leaky_relu(self, x: np.ndarray) -> np.ndarray:
        return np.where(x > 0.0, x, self.leaky_relu_alpha * x)

    def compute_attention(
        self,
        h_upstream: np.ndarray,
        h_downstream: np.ndarray,
        h_target: Optional[np.ndarray] = None,
        divergence: Optional[np.ndarray] = None
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        计算上游成本通道与下游需求通道的注意力权重 (alpha_upstream, alpha_downstream)。
        保证:
        1. alpha_upstream[t] + alpha_downstream[t] == 1.0 (严格 Softmax 归一化)
        2. alpha_upstream[t] >= 0, alpha_downstream[t] >= 0
        3. 下游供需偏离度 (divergence) 越高，下游需求注意力 alpha_downstream 显著提升。
        """
        n = len(h_upstream)
        hu = h_upstream.reshape(n, self.in_features)
        hd = h_downstream.reshape(n, self.in_features)

        if h_target is not None:
            ht = h_target.reshape(n, self.in_features)
        else:
            ht = 0.5 * (hu + hd)

        if divergence is not None:
            div = np.asarray(divergence, dtype=np.float64).reshape(n, 1)
        else:
            div = np.zeros((n, 1), dtype=np.float64)

        feat_u = np.hstack([ht, hu])
        feat_d = np.hstack([ht, hd])

        logit_u = feat_u @ self.a_upstream - self.gamma * div
        logit_d = feat_d @ self.a_downstream + self.gamma * div

        e_u = self._leaky_relu(logit_u)
        e_d = self._leaky_relu(logit_d)

        e = np.hstack([e_u, e_d])
        e_max = np.max(e, axis=-1, keepdims=True)
        exp_e = np.exp(e - e_max)
        alpha = exp_e / np.sum(exp_e, axis=-1, keepdims=True)

        return alpha[:, 0], alpha[:, 1]


class TemporalNALE:
    """产业链时空图卷积与注意力网络引擎 (Temporal NALE Engine)"""

    def __init__(
        self,
        config: Optional[TemporalNALEConfig] = None,
        window: int = 60,
        sa_to_fg_lag: float = 18.0,
        sa_half_life: float = 25.0,
        use_asymmetric_kernel: bool = True,
        tau_up: float = 10.0,
        tau_down: float = 28.0,
        half_life_up: float = 14.0,
        half_life_down: float = 35.0,
        use_stgat_attention: bool = True,
        **kwargs
    ):
        if config is not None:
            self.config = config
        else:
            self.config = TemporalNALEConfig(
                window=window,
                sa_to_fg_lag=sa_to_fg_lag,
                sa_half_life=sa_half_life,
                use_asymmetric_kernel=use_asymmetric_kernel,
                tau_up=tau_up,
                tau_down=tau_down,
                half_life_up=half_life_up,
                half_life_down=half_life_down,
                use_stgat_attention=use_stgat_attention,
                **kwargs
            )

        self.window = self.config.window
        self.sa_to_fg_lag = self.config.sa_to_fg_lag
        self.sa_half_life = self.config.sa_half_life

        # 1. 传统对称时滞因果卷积核 (保留向后兼容)
        self.sa_kernel = TemporalConvolutionKernel(
            lead_lag_days=self.sa_to_fg_lag,
            half_life_days=self.sa_half_life,
            kernel_window=self.window,
            sigma=6.0
        )
        self.fg_kernel = TemporalConvolutionKernel(
            lead_lag_days=self.config.fg_lag,
            half_life_days=self.config.fg_half_life,
            kernel_window=self.window,
            sigma=3.0
        )

        # 2. 非对称时空脉冲响应核 (Round 2 Evolution: Cost-push vs Sticky-down)
        self.asym_kernel = AsymmetricTemporalKernel(
            tau_up=self.config.tau_up,
            tau_down=self.config.tau_down,
            half_life_up=self.config.half_life_up,
            half_life_down=self.config.half_life_down,
            kernel_window=self.window,
            sigma_up=self.config.sigma_up,
            sigma_down=self.config.sigma_down
        )
        self.asym_fg_kernel = AsymmetricTemporalKernel(
            tau_up=self.config.fg_lag,
            tau_down=self.config.fg_lag * 2.0,
            half_life_up=self.config.fg_half_life,
            half_life_down=self.config.fg_half_life * 2.0,
            kernel_window=self.window,
            sigma_up=3.0,
            sigma_down=6.0
        )

        # 3. 供需偏离度自适应图注意力层 (Round 2 Evolution: ST-GAT)
        self.stgat = SupplyDemandAttentionSTGAT(
            gamma=self.config.gamma_divergence,
            leaky_relu_alpha=self.config.leaky_relu_alpha
        )

    def compute_chain_response(
        self,
        df: pd.DataFrame,
        pure_soda_col: str = "close_sa",
        glass_col: str = "close_fg",
        inventory_col: str = "inventory_sa",
        divergence_series: Optional[Union[np.ndarray, pd.Series]] = None,
        fuel_cost_per_ton: Optional[float] = None
    ) -> pd.DataFrame:
        """
        计算产业链时空非对称因果响应与供需注意力指标 (Temporal NALE ST-GAT):
        
        输出包含:
        - conv_upstream_cost: 对称上游成本冲击响应
        - conv_downstream_demand: 对称下游需求响应
        - asym_upstream_cost: 非对称上游成本推涨/粘性卷积响应
        - asym_downstream_demand: 非对称下游需求卷积响应
        - stgat_divergence_attention: 供需偏离度注意力权重 alpha_downstream
        - ncsi: 产业链净成本冲击标准化指数 (Normalized Chain Shock Index, [-1.0, 1.0])
        - crush_spread / crush_margin_ratio: 虚拟加工毛利及利润率
        - convolved_sa_shock / convolved_fg_trend: 兼容旧版卷积响应字段
        - margin_pressure_index / nale_leading_signal: 兼容旧版利润压力与先行信号字段
        """
        res = pd.DataFrame(index=df.index)

        # 提取价格序列与容错处理
        if pure_soda_col in df.columns:
            p_sa = df[pure_soda_col].values.astype(np.float64)
        elif "spot_sa" in df.columns:
            p_sa = df["spot_sa"].values.astype(np.float64)
        elif "close" in df.columns:
            p_sa = df["close"].values.astype(np.float64)
        else:
            raise KeyError(f"纯碱价格列未在数据中找到: {pure_soda_col}")

        if glass_col in df.columns:
            p_fg = df[glass_col].values.astype(np.float64)
        elif "spot_fg" in df.columns:
            p_fg = df["spot_fg"].values.astype(np.float64)
        else:
            p_fg = p_sa * 0.9 + 50.0

        p_sa_safe = np.maximum(p_sa, 1.0)
        p_fg_safe = np.maximum(p_fg, 1.0)

        # 计算对数收益率因果输入 (第一日设定为 0.0)
        sa_returns = np.diff(np.log(p_sa_safe), prepend=np.log(p_sa_safe[0]))
        fg_returns = np.diff(np.log(p_fg_safe), prepend=np.log(p_fg_safe[0]))

        # 1. 传统对称因果卷积
        conv_upstream_cost = self.sa_kernel.convolve_causal(sa_returns)
        conv_downstream_demand = self.fg_kernel.convolve_causal(fg_returns)

        # 2. 非对称时空脉冲核卷积
        asym_upstream_cost = self.asym_kernel.convolve_asymmetric(sa_returns)
        asym_downstream_demand = self.asym_fg_kernel.convolve_asymmetric(fg_returns)

        # 3. 供需偏离度 (Divergence_t) 因果构建
        if divergence_series is not None:
            div = np.asarray(divergence_series, dtype=np.float64)
        else:
            fuel = fuel_cost_per_ton if fuel_cost_per_ton is not None else self.config.fuel_cost_per_ton
            if "crush_spread" in df.columns:
                spread = df["crush_spread"].values.astype(np.float64)
            else:
                spread = calculate_crush_spread(p_fg, p_sa, 0.20, fuel)

            s_diff = pd.Series(spread, index=df.index).diff().fillna(0.0)
            s_std = s_diff.rolling(self.config.window, min_periods=1).std().fillna(1.0).replace(0.0, 1.0)
            norm_spread = np.clip(s_diff.values / s_std.values, -3.0, 3.0)

            w_inv = getattr(self.config, "inventory_weight", 0.0)
            has_valid_inv = (
                w_inv > 0.0 and
                inventory_col in df.columns and
                not df[inventory_col].isna().all() and
                df[inventory_col].std() > 1e-6
            )
            if has_valid_inv:
                inv_diff = pd.Series(df[inventory_col].values.astype(np.float64), index=df.index).diff().fillna(0.0)
                inv_std = inv_diff.rolling(self.config.window, min_periods=1).std().fillna(1.0).replace(0.0, 1.0)
                norm_inv = np.clip(-inv_diff.values / inv_std.values, -3.0, 3.0)
                div = (1.0 - w_inv) * norm_spread + w_inv * norm_inv
            else:
                div = norm_spread

            # 供需偏离度因果 EMA 平滑，抑制单日极端随机扰动引起的 Softmax 注意力巨震
            div_span = getattr(self.config, "divergence_ema_span", None)
            if div_span is not None and div_span > 1:
                div = pd.Series(div, index=df.index).ewm(span=div_span, adjust=False).mean().values

        # 4. ST-GAT 图注意力计算
        if self.config.use_stgat_attention:
            h_target = 0.5 * (asym_upstream_cost + asym_downstream_demand)
            alpha_up, alpha_down = self.stgat.compute_attention(
                h_upstream=asym_upstream_cost,
                h_downstream=asym_downstream_demand,
                h_target=h_target,
                divergence=div
            )
            stgat_divergence_attention = alpha_down
        else:
            alpha_up = np.full(len(df), 0.5, dtype=np.float64)
            alpha_down = np.full(len(df), 0.5, dtype=np.float64)
            stgat_divergence_attention = alpha_down

        # 5. 产业链净成本冲击指数 NCSI 综合与标准化
        eff_upstream = asym_upstream_cost if self.config.use_asymmetric_kernel else conv_upstream_cost
        eff_downstream = asym_downstream_demand if self.config.use_asymmetric_kernel else conv_downstream_demand

        margin_pressure = (
            alpha_up * self.config.cost_weight * eff_upstream -
            alpha_down * self.config.demand_weight * eff_downstream
        )

        mp_series = pd.Series(margin_pressure, index=df.index)
        rolling_mean = mp_series.rolling(self.config.window, min_periods=1).mean().fillna(0.0)
        rolling_std = mp_series.rolling(self.config.window, min_periods=1).std().fillna(1.0).replace(0.0, 1.0)
        ncsi = np.clip((margin_pressure - rolling_mean.values) / (rolling_std.values * 2.0), -1.0, 1.0)

        # 对 NALE 先行信号实施递归因果 EMA 平滑，消除假数据跳变并保持因果截断不变性 (std < 0.15)
        sig_span = getattr(self.config, "signal_ema_span", None)
        if sig_span is not None and sig_span > 1:
            ncsi = pd.Series(ncsi, index=df.index).ewm(span=sig_span, adjust=False).mean().values
            ncsi = np.clip(ncsi, -1.0, 1.0)

        # 6. 构建并返回完整结果 DataFrame
        fuel = fuel_cost_per_ton if fuel_cost_per_ton is not None else self.config.fuel_cost_per_ton
        crush_spread = calculate_crush_spread(p_fg, p_sa, 0.20, fuel)

        res["conv_upstream_cost"] = conv_upstream_cost
        res["conv_downstream_demand"] = conv_downstream_demand
        res["asym_upstream_cost"] = asym_upstream_cost
        res["asym_downstream_demand"] = asym_downstream_demand
        res["stgat_divergence_attention"] = stgat_divergence_attention
        res["ncsi"] = ncsi

        # 向后兼容字段
        res["crush_spread"] = crush_spread
        res["crush_margin_ratio"] = crush_spread / np.maximum(p_fg, 1.0)
        res["convolved_sa_shock"] = conv_upstream_cost
        res["convolved_fg_trend"] = conv_downstream_demand
        res["margin_pressure_index"] = margin_pressure
        res["nale_leading_signal"] = ncsi

        return res

    def compute_virtual_crush_spread(
        self,
        price_fg: Union[float, np.ndarray, pd.Series],
        price_sa: Union[float, np.ndarray, pd.Series],
        sa_stoichiometric_ratio: float = DEFAULT_SA_STOICHIOMETRIC_RATIO,
        fuel_cost_per_ton: Optional[float] = None
    ) -> Union[float, np.ndarray, pd.Series]:
        """
        计算产业链虚拟裂解吨玻璃加工毛利 (Virtual Crush Spread)。
        全权复用 src.data.feature_engineering.calculate_crush_spread 保持唯一单一定义。
        """
        fuel = fuel_cost_per_ton if fuel_cost_per_ton is not None else self.config.fuel_cost_per_ton
        return calculate_crush_spread(
            price_fg=price_fg,
            price_sa=price_sa,
            sa_stoichiometric_ratio=sa_stoichiometric_ratio,
            fuel_cost=fuel
        )

    def compute_crush_spread(
        self,
        df: pd.DataFrame,
        pure_soda_col: str = "close_sa",
        glass_col: str = "close_fg",
        fuel_cost_per_ton: float = 350.0
    ) -> pd.DataFrame:
        """
        计算产业链虚拟裂解加工毛利 (Virtual Crush Spread) 与先行利润压力指标。
        向后兼容既有接口，内部全权委托给 compute_chain_response。
        """
        return self.compute_chain_response(
            df=df,
            pure_soda_col=pure_soda_col,
            glass_col=glass_col,
            fuel_cost_per_ton=fuel_cost_per_ton
        )

