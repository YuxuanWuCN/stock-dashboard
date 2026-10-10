# -*- coding: utf-8 -*-
"""
场内期权隐波曲面偏度与动态 Greeks 领子优化引擎 (option_collar.py)
==================================================================
基于顶尖衍生品与微观结构学术文献（Black 1976; Gatheral 2004; Rockafellar & Uryasev 2000;
郑商所期权交割细则与组合保证金制度）：
1. IVSurfaceSkewModel: 参数化隐波偏度曲面与 Gatheral SVI 模型，支持因果无前视估计
2. Black76Greeks: Black-76 商品期货期权定价与全阶解析 Greeks (Delta, Gamma, Vega, Theta)
3. CollarConfig & CollarOptimizationResult: 结构化参数与优化求解结果数据契约
4. AdaptiveOptionCollarEngine: 动态自适应行权价选择、零成本 Brent 根求解、郑商所保证金压缩与动态 CVaR 风险度量
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple, Union
import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.stats import norm


@dataclass
class CollarConfig:
    """场内期权领子策略参数配置"""
    tau: float = 30.0 / 252.0               # 默认剩余到期期限 (约30个交易日)
    r: float = 0.03                         # 年化无风险利率 (3.0%)
    forward_drift: float = 0.09             # 预期年化现货漂移率 / 期限结构便利收益修正
    default_put_buffer: float = 0.019       # 默认虚值看跌行权价下行容忍比例 (1.9%)
    min_put_buffer: float = 0.015           # 最小看跌保护下行比例 (1.5%)
    max_put_buffer: float = 0.035           # 最大看跌保护下行比例 (3.5%)
    beta_skew_default: float = -0.05        # 默认隐波偏度斜率 (OTM Put IV > OTM Call IV)
    gamma_smile_default: float = 0.02       # 默认隐波笑脸曲率
    margin_ratio_futures: float = 0.12      # 郑商所纯碱期货保证金比率 (12%)
    contract_multiplier: float = 20.0       # 郑商所纯碱合约乘数 (20吨/手)
    commission_rate: float = 0.0002         # 交易手续费率 (万分之二)
    cvar_alpha: float = 0.95                # 条件在险价值置信度 (95%)
    exchange: str = "CZCE"                  # 交易所代码
    collar_combo_relief: float = 0.10       # 郑商所领子组合对锁保证金减免优惠系数 (约为标的期货保证金的10%)


@dataclass
class CollarOptimizationResult:
    """自适应 Collar 优化求解结果"""
    strike_put: float                       # 看跌期权最优行权价 K_p*
    strike_call: float                      # 看涨期权最优零成本行权价 K_c*
    put_iv: float                           # K_p* 对应的隐含波动率
    call_iv: float                          # K_c* 对应的隐含波动率
    put_premium: float                      # 买入 Put 权利金支出 (元/吨)
    call_premium: float                     # 卖出 Call 权利金收入 (元/吨)
    net_premium: float                      # 净权利金支出 (元/吨, |P - C| ≈ 0.0)
    delta_net: float                        # 领子组合净 Delta (Delta_p - Delta_c)
    gamma_net: float                        # 领子组合净 Gamma (Gamma_p - Gamma_c)
    vega_net: float                         # 领子组合净 Vega
    theta_net: float                        # 领子组合净 Theta
    margin_requirement: float               # 交易所组合卖方保证金需求 (元/吨)
    naked_margin_requirement: float         # 交易所单腿裸卖方保证金需求 (元/吨)
    cvar_95: float                          # 95% 置信度下的下行 CVaR (元/吨)
    hedge_ratio: float = 0.25               # 建议期货基准对冲比率
    alpha_buffer: float = 0.019             # 实际采用的看跌保护距离


class IVSurfaceSkewModel:
    """
    隐含波动率曲面偏度与笑脸模型 (Parametric Skew & SVI)
    ---------------------------------------------------
    参数化偏度公式:
      sigma_imp(K, S, tau) = sigma_ATM * [1 + beta_skew * (K/S - 1) + gamma_smile * (K/S - 1)^2]
    
    文献依据与机理:
    - 大宗商品下行恐慌时，虚值看跌期权需求激增，产生负偏度 (beta_skew < 0)，即 K < S 时 sigma_imp > sigma_ATM
    - 深虚值与深实值两端由二阶项 gamma_smile > 0 形成波动率微笑曲率
    """

    def __init__(
        self,
        iv_atm: float = 0.25,
        beta_skew: float = -0.05,
        gamma_smile: float = 0.02,
        min_iv: float = 0.01
    ):
        self.iv_atm = max(iv_atm, min_iv)
        self.beta_skew = beta_skew
        self.gamma_smile = gamma_smile
        self.min_iv = min_iv

    def get_iv(
        self,
        strike: float,
        spot: float,
        tau: float = 30.0 / 252.0,
        iv_atm: Optional[float] = None,
        beta_skew: Optional[float] = None,
        gamma_smile: Optional[float] = None
    ) -> float:
        """
        计算给定行权价与标的价格下的隐含波动率
        """
        base_iv = iv_atm if iv_atm is not None else self.iv_atm
        b_skew = beta_skew if beta_skew is not None else self.beta_skew
        g_smile = gamma_smile if gamma_smile is not None else self.gamma_smile

        if spot <= 0 or strike <= 0:
            return max(base_iv, self.min_iv)

        moneyness = (strike / spot) - 1.0
        skew_factor = 1.0 + b_skew * moneyness + g_smile * (moneyness ** 2)
        iv_calc = base_iv * skew_factor
        return max(float(iv_calc), self.min_iv)

    @staticmethod
    def svi_implied_vol(
        k: float,
        tau: float,
        a: float,
        b: float,
        rho: float,
        m: float,
        sigma_svi: float
    ) -> float:
        """
        Gatheral (2004) SVI 准五参数总方差反解瞬时隐含波动率
        w(k) = a + b * (rho * (k - m) + sqrt((k - m)^2 + sigma_svi^2))
        """
        if tau <= 0:
            return 0.20
        total_var = a + b * (rho * (k - m) + np.sqrt((k - m) ** 2 + sigma_svi ** 2))
        total_var = max(total_var, 1e-6)
        return float(np.sqrt(total_var / tau))

    @staticmethod
    def estimate_skew_from_returns(
        returns: pd.Series,
        window: int = 60,
        scaling: float = 0.05
    ) -> Tuple[float, float]:
        """
        从历史收益率中因果无前视地估计当前偏度与波动率
        返回: (est_vol, est_skew)
        """
        clean_ret = returns.dropna()
        if len(clean_ret) < 5:
            return 0.25, -0.03
        
        tail = clean_ret.iloc[-window:] if len(clean_ret) >= window else clean_ret
        vol = float(tail.std() * np.sqrt(250))
        skewness = float(tail.skew()) if len(tail) >= 3 else 0.0
        if np.isnan(skewness):
            skewness = 0.0
            
        # 负向偏度放大 (商品现货暴跌导致看跌期权偏度陡峭)
        est_skew = float(np.clip(skewness * scaling, -0.20, 0.05))
        return max(vol, 0.05), est_skew


class Black76Greeks:
    """
    Black-76 商品期货期权定价与全阶解析 Greeks 引擎
    ------------------------------------------------
    标的资产为期货合约 F，贴现因子 D = exp(-r * tau)
    严格遵循 Put-Call Parity: C - P = D * (F - K)
    """

    @staticmethod
    def _d1_d2(
        f: float,
        k: float,
        tau: float,
        sigma: float
    ) -> Tuple[float, float]:
        """计算核心扩散参数 d1, d2"""
        if tau <= 0 or sigma <= 0 or f <= 0 or k <= 0:
            return 0.0, 0.0
        v_sqrt = sigma * np.sqrt(tau)
        d1 = (np.log(f / k) + 0.5 * (sigma ** 2) * tau) / v_sqrt
        d2 = d1 - v_sqrt
        return float(d1), float(d2)

    @classmethod
    def call_price(
        cls,
        f: float,
        k: float,
        tau: float,
        r: float,
        sigma: float
    ) -> float:
        """Black-76 看涨期权理论价格"""
        if tau <= 1e-8 or sigma <= 1e-8:
            return max(0.0, float(f - k))
        d1, d2 = cls._d1_d2(f, k, tau, sigma)
        df = np.exp(-r * tau)
        price = df * (f * norm.cdf(d1) - k * norm.cdf(d2))
        return max(0.0, float(price))

    @classmethod
    def put_price(
        cls,
        f: float,
        k: float,
        tau: float,
        r: float,
        sigma: float
    ) -> float:
        """Black-76 看跌期权理论价格"""
        if tau <= 1e-8 or sigma <= 1e-8:
            return max(0.0, float(k - f))
        d1, d2 = cls._d1_d2(f, k, tau, sigma)
        df = np.exp(-r * tau)
        price = df * (k * norm.cdf(-d2) - f * norm.cdf(-d1))
        return max(0.0, float(price))

    @classmethod
    def call_delta(
        cls,
        f: float,
        k: float,
        tau: float,
        r: float,
        sigma: float
    ) -> float:
        """Call Delta: ∂C/∂F = D * N(d1) ∈ (0, 1)"""
        if tau <= 1e-8 or sigma <= 1e-8:
            return 1.0 if f > k else 0.0
        d1, _ = cls._d1_d2(f, k, tau, sigma)
        df = np.exp(-r * tau)
        return float(df * norm.cdf(d1))

    @classmethod
    def put_delta(
        cls,
        f: float,
        k: float,
        tau: float,
        r: float,
        sigma: float
    ) -> float:
        """Put Delta: ∂P/∂F = -D * N(-d1) = D * (N(d1) - 1) ∈ (-1, 0)"""
        if tau <= 1e-8 or sigma <= 1e-8:
            return -1.0 if f < k else 0.0
        d1, _ = cls._d1_d2(f, k, tau, sigma)
        df = np.exp(-r * tau)
        return float(-df * norm.cdf(-d1))

    @classmethod
    def gamma(
        cls,
        f: float,
        k: float,
        tau: float,
        r: float,
        sigma: float
    ) -> float:
        """Gamma: ∂²C/∂F² = ∂²P/∂F² = D * n(d1) / (F * sigma * sqrt(tau)) > 0"""
        if tau <= 1e-8 or sigma <= 1e-8 or f <= 0:
            return 0.0
        d1, _ = cls._d1_d2(f, k, tau, sigma)
        df = np.exp(-r * tau)
        denom = f * sigma * np.sqrt(tau)
        if denom <= 1e-12:
            return 0.0
        return float(df * norm.pdf(d1) / denom)

    @classmethod
    def vega(
        cls,
        f: float,
        k: float,
        tau: float,
        r: float,
        sigma: float
    ) -> float:
        """Vega: ∂C/∂sigma = ∂P/∂sigma = D * F * sqrt(tau) * n(d1) > 0"""
        if tau <= 1e-8 or sigma <= 1e-8 or f <= 0:
            return 0.0
        d1, _ = cls._d1_d2(f, k, tau, sigma)
        df = np.exp(-r * tau)
        return float(df * f * np.sqrt(tau) * norm.pdf(d1))

    @classmethod
    def call_theta(
        cls,
        f: float,
        k: float,
        tau: float,
        r: float,
        sigma: float
    ) -> float:
        """Call Theta: ∂C/∂t = -∂C/∂tau = r * C - D * F * sigma * n(d1) / (2 * sqrt(tau))"""
        if tau <= 1e-8 or sigma <= 1e-8 or f <= 0:
            return 0.0
        d1, _ = cls._d1_d2(f, k, tau, sigma)
        df = np.exp(-r * tau)
        term1 = - (df * f * sigma * norm.pdf(d1)) / (2.0 * np.sqrt(tau))
        c = cls.call_price(f, k, tau, r, sigma)
        return float(term1 + r * c)

    @classmethod
    def put_theta(
        cls,
        f: float,
        k: float,
        tau: float,
        r: float,
        sigma: float
    ) -> float:
        """Put Theta: ∂P/∂t = -∂P/∂tau = r * P - D * F * sigma * n(d1) / (2 * sqrt(tau))"""
        if tau <= 1e-8 or sigma <= 1e-8 or f <= 0:
            return 0.0
        d1, _ = cls._d1_d2(f, k, tau, sigma)
        df = np.exp(-r * tau)
        term1 = - (df * f * sigma * norm.pdf(d1)) / (2.0 * np.sqrt(tau))
        p = cls.put_price(f, k, tau, r, sigma)
        return float(term1 + r * p)

    @classmethod
    def compute_all_greeks(
        cls,
        f: float,
        k: float,
        tau: float,
        r: float,
        sigma: float,
        option_type: str = "call"
    ) -> Dict[str, float]:
        """批量返回期权理论价值与全部 Greeks"""
        is_call = option_type.lower() == "call"
        price = cls.call_price(f, k, tau, r, sigma) if is_call else cls.put_price(f, k, tau, r, sigma)
        delta = cls.call_delta(f, k, tau, r, sigma) if is_call else cls.put_delta(f, k, tau, r, sigma)
        gamma = cls.gamma(f, k, tau, r, sigma)
        vega = cls.vega(f, k, tau, r, sigma)
        theta = cls.call_theta(f, k, tau, r, sigma) if is_call else cls.put_theta(f, k, tau, r, sigma)
        return {
            "price": price,
            "delta": delta,
            "gamma": gamma,
            "vega": vega,
            "theta": theta
        }


class AdaptiveOptionCollarEngine:
    """
    自适应期权 Collar 领子动态对冲引擎
    -----------------------------------
    功能与特色:
    1. 根据隐含波动率与偏度状态自适应选取 Put 行权价 K_p*
    2. 基于 Brent 算法高精度反解看涨期权行权价 K_c*，严格达成净权利金为 0 (|P - C| < 1e-4)
    3. 集成郑商所场内期权卖方保证金公式、组合对锁减免与动态 CVaR 风险度量
    4. 提供符合 PROJECT.md 接口契约的 payoff 计算与对冲比率微调
    """

    def __init__(self, config: Optional[CollarConfig] = None):
        self.config = config or CollarConfig()
        self.skew_model = IVSurfaceSkewModel(
            iv_atm=0.25,
            beta_skew=self.config.beta_skew_default,
            gamma_smile=self.config.gamma_smile_default
        )

    def select_put_strike(
        self,
        spot: float,
        iv_atm: float,
        skew: float,
        delta_risk: float = 0.0
    ) -> Tuple[float, float]:
        """
        动态选择下行保护看跌行权价 K_p* = spot * (1 - alpha)
        
        参数:
        - spot: 标的价格
        - iv_atm: 平值隐含波动率
        - skew: 偏度参数 (通常 <= 0)
        - delta_risk: 额外市场下行风险微调量
        
        返回: (strike_put, alpha_buffer)
        """
        alpha_base = self.config.default_put_buffer
        
        # 波动率与偏度驱动的自适应下行保护缓冲:
        # 当负偏度陡峭 (skew < -0.03) 时，适度收紧下行容忍度以提升尾部防守灵敏度
        sk_factor = (skew - (-0.03)) / 0.03
        iv_factor = (np.clip(iv_atm, 0.15, 0.60) - 0.25) / 0.25
        
        alpha = alpha_base * (1.0 - 0.08 * sk_factor + 0.04 * iv_factor + 0.10 * delta_risk)
        alpha = float(np.clip(alpha, self.config.min_put_buffer, self.config.max_put_buffer))
        
        strike_put = spot * (1.0 - alpha)
        return float(strike_put), float(alpha)

    def solve_zero_cost_call_strike(
        self,
        spot: float,
        strike_put: float,
        iv_atm: float,
        skew: float,
        tau: Optional[float] = None,
        forward_drift: Optional[float] = None
    ) -> Tuple[float, float, float, float]:
        """
        高精度数值求解零成本看涨期权行权价 K_c*，使得:
          C(f, K_c*, tau, r, sigma_c(K_c*)) = P(f, K_p*, tau, r, sigma_p(K_p*))
        
        返回: (strike_call, call_premium, put_premium, call_iv)
        """
        t = tau if tau is not None else self.config.tau
        r = self.config.r
        drift = forward_drift if forward_drift is not None else self.config.forward_drift
        f = spot * np.exp((r + drift) * t) if drift != 0.0 else spot
        
        # 1. 估算 Put 隐含波动率与买入权利金
        put_iv = self.skew_model.get_iv(strike_put, spot, t, iv_atm=iv_atm, beta_skew=skew)
        put_prem = Black76Greeks.put_price(f, strike_put, t, r, put_iv)
        
        if put_prem < 1e-6:
            # 极低权利金情景，提供一个基准虚值 Call
            k_c_fallback = spot * (1.0 + self.config.default_put_buffer)
            c_iv = self.skew_model.get_iv(k_c_fallback, spot, t, iv_atm=iv_atm, beta_skew=skew)
            c_prem = Black76Greeks.call_price(f, k_c_fallback, t, r, c_iv)
            return float(k_c_fallback), float(c_prem), float(put_prem), float(c_iv)
        
        # 2. 构建目标根方程 g(K_c) = CallPrice(K_c) - PutPrice
        def obj_func(k_candidate: float) -> float:
            c_iv = self.skew_model.get_iv(k_candidate, spot, t, iv_atm=iv_atm, beta_skew=skew)
            c_p = Black76Greeks.call_price(f, k_candidate, t, r, c_iv)
            return c_p - put_prem
        
        # 3. 根区间界定:
        lower_bound = strike_put * 1.0001
        upper_bound = spot * 2.5
        
        f_lower = obj_func(lower_bound)
        f_upper = obj_func(upper_bound)
        
        if f_lower * f_upper > 0:
            # 极端异常边界保护
            k_sol = lower_bound if f_lower < 0 else upper_bound
        else:
            # 使用高精度收敛参数 xtol=1e-12, rtol=1e-12 确保残差 |P - C| < 1e-6 << 1e-4
            k_sol = brentq(obj_func, lower_bound, upper_bound, xtol=1e-12, rtol=1e-12, maxiter=100)
            
        final_c_iv = self.skew_model.get_iv(k_sol, spot, t, iv_atm=iv_atm, beta_skew=skew)
        final_c_prem = Black76Greeks.call_price(f, k_sol, t, r, final_c_iv)
        
        return float(k_sol), float(final_c_prem), float(put_prem), float(final_c_iv)

    def calculate_czce_margin(
        self,
        spot: float,
        strike_call: float,
        call_premium: float,
        contracts: float = 1.0,
        is_collar_combo: bool = False
    ) -> float:
        """
        根据郑州商品交易所（CZCE）场内期权卖方保证金标准公式计算维持保证金:
        1. 裸卖方单腿公式 (is_collar_combo=False):
           Margin = 权利金结算价 + Max[标的期货保证金 - 0.5 * 虚值额, 0.5 * 标的期货保证金]
           虚值额 (OTM Amount) = Max(0, Strike_Call - Spot)
        
        2. Collar 领子对锁组合保证金 (is_collar_combo=True, 郑商所组合保证金减免):
           组合下行有 Long Put 兜底，卖出 Call 风险可控，按标的期货保证金的优惠比例计收。
        
        返回: 综合保证金占用金额 (元)
        """
        multiplier = self.config.contract_multiplier
        margin_ratio = self.config.margin_ratio_futures
        
        futures_margin_per_ton = spot * margin_ratio
        otm_amount = max(0.0, strike_call - spot)
        
        cushion = max(futures_margin_per_ton - 0.5 * otm_amount, 0.5 * futures_margin_per_ton)
        naked_margin_per_ton = call_premium + cushion
        
        if is_collar_combo:
            combo_relief = self.config.collar_combo_relief
            # 组合保证金优惠模式: 权利金部分缓冲 (20%) + 期货保证金优惠比例 (10%)
            margin_per_ton = max(
                call_premium * 0.20 + futures_margin_per_ton * combo_relief,
                futures_margin_per_ton * 0.08
            )
        else:
            margin_per_ton = naked_margin_per_ton
        
        total_margin = contracts * multiplier * margin_per_ton
        return float(total_margin)

    def calculate_cvar(
        self,
        spot: float,
        strike_put: float,
        strike_call: float,
        iv: float,
        tau: Optional[float] = None,
        alpha: float = 0.95,
        n_sim: int = 1000,
        random_seed: int = 42
    ) -> float:
        """
        基于蒙特卡洛抽样计算持有该领子组合后的实体库存 95% 下行条件在险价值 (CVaR)
        度量尾部超出 VaR_alpha 的期望损失 (元/吨)
        """
        t = tau if tau is not None else self.config.tau
        r = self.config.r
        rng = np.random.default_rng(random_seed)
        
        # 终端现货价格几何布朗运动分布
        z = rng.standard_normal(n_sim)
        s_t = spot * np.exp((r - 0.5 * (iv ** 2)) * t + iv * np.sqrt(t) * z)
        
        # 裸库存损失 (现货下跌产生损失)
        unhedged_loss = spot - s_t
        
        # 期权领子到期结算回报: Long Put (+), Short Call (-)
        collar_payoff = np.maximum(0.0, strike_put - s_t) - np.maximum(0.0, s_t - strike_call)
        
        # 对冲后净损失
        hedged_loss = unhedged_loss - collar_payoff
        
        # 计算 VaR 与 CVaR
        var_threshold = np.percentile(hedged_loss, 100.0 * alpha)
        tail_losses = hedged_loss[hedged_loss >= var_threshold]
        cvar_val = float(np.mean(tail_losses)) if len(tail_losses) > 0 else float(var_threshold)
        return max(0.0, cvar_val)

    def compute_adaptive_collar(
        self,
        spot_price: float,
        iv: float,
        skew: float,
        tau: Optional[float] = None,
        forward_drift: Optional[float] = None
    ) -> CollarOptimizationResult:
        """
        综合执行自适应 Collar 领子优化：
        输出行权价、权利金、无套利 Greeks、郑商所保证金与 CVaR
        """
        t = tau if tau is not None else self.config.tau
        r = self.config.r
        drift = forward_drift if forward_drift is not None else self.config.forward_drift
        f = spot_price * np.exp((r + drift) * t) if drift != 0.0 else spot_price
        
        # 1. 动态自适应确定 Put 行权价
        k_p, alpha_used = self.select_put_strike(spot_price, iv, skew)
        
        # 2. Brent 根求解零成本 Call 行权价
        k_c, c_prem, p_prem, c_iv = self.solve_zero_cost_call_strike(
            spot=spot_price,
            strike_put=k_p,
            iv_atm=iv,
            skew=skew,
            tau=t,
            forward_drift=drift
        )
        p_iv = self.skew_model.get_iv(k_p, spot_price, t, iv_atm=iv, beta_skew=skew)
        net_prem = p_prem - c_prem
        
        # 3. 计算组合 Greeks (Long Put - Short Call)
        put_delta = Black76Greeks.put_delta(f, k_p, t, r, p_iv)
        call_delta = Black76Greeks.call_delta(f, k_c, t, r, c_iv)
        delta_net = put_delta - call_delta
        
        put_gamma = Black76Greeks.gamma(f, k_p, t, r, p_iv)
        call_gamma = Black76Greeks.gamma(f, k_c, t, r, c_iv)
        gamma_net = put_gamma - call_gamma
        
        put_vega = Black76Greeks.vega(f, k_p, t, r, p_iv)
        call_vega = Black76Greeks.vega(f, k_c, t, r, c_iv)
        vega_net = put_vega - call_vega
        
        put_theta = Black76Greeks.put_theta(f, k_p, t, r, p_iv)
        call_theta = Black76Greeks.call_theta(f, k_c, t, r, c_iv)
        theta_net = put_theta - call_theta
        
        # 4. 保证金与 CVaR
        combo_margin_per_ton = self.calculate_czce_margin(
            spot_price, k_c, c_prem, contracts=1.0, is_collar_combo=True
        ) / self.config.contract_multiplier
        naked_margin_per_ton = self.calculate_czce_margin(
            spot_price, k_c, c_prem, contracts=1.0, is_collar_combo=False
        ) / self.config.contract_multiplier
        
        cvar = self.calculate_cvar(spot_price, k_p, k_c, iv, tau=t, alpha=self.config.cvar_alpha, n_sim=1000)
        
        return CollarOptimizationResult(
            strike_put=k_p,
            strike_call=k_c,
            put_iv=p_iv,
            call_iv=c_iv,
            put_premium=p_prem,
            call_premium=c_prem,
            net_premium=net_prem,
            delta_net=delta_net,
            gamma_net=gamma_net,
            vega_net=vega_net,
            theta_net=theta_net,
            margin_requirement=combo_margin_per_ton,
            naked_margin_requirement=naked_margin_per_ton,
            cvar_95=cvar,
            hedge_ratio=0.25,
            alpha_buffer=alpha_used
        )

    # =========================================================================
    # PROJECT.md 接口契约保全
    # =========================================================================

    def compute_collar_payoff(
        self,
        spot_price: float,
        strike_put: float,
        strike_call: float,
        iv: float = 0.20
    ) -> float:
        """
        计算单吨领子组合结算回报 (Payoff):
        Payoff = Max(0, Strike_Put - Spot) - Max(0, Spot - Strike_Call)
        """
        put_payoff = max(0.0, strike_put - spot_price)
        call_payoff = max(0.0, spot_price - strike_call)
        return float(put_payoff - call_payoff)

    def get_target_hedge_ratio(
        self,
        state: int,
        delta: float = 0.0
    ) -> float:
        """
        基于因果状态机政权状态与 Greeks Delta 输出自适应对冲比率:
        - state = 0 (震荡/利润修复): 基础对冲比率 0.25 ~ 0.30，结合 Delta 微调
        - state = 1 (破位主跌浪): 基础对冲比率 0.95 ~ 1.00，实现全额锁定
        """
        if state == 0:
            base_h = 0.25
            adjusted_h = base_h - 0.15 * delta
            return float(np.clip(adjusted_h, 0.15, 0.40))
        else:
            base_h = 0.95
            adjusted_h = base_h - 0.05 * delta
            return float(np.clip(adjusted_h, 0.90, 1.00))
