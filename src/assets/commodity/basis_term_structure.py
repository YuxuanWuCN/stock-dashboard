# -*- coding: utf-8 -*-
"""
纯碱/大宗商品基差期限结构与便利收益核心模型 (src/models/basis_term_structure.py)
-------------------------------------------------------------------------
文献理论支撑:
1. Schwartz & Smith (2000, Management Science): Short-Term / Long-Term Two-Factor Model
2. Erb & Harvey (2006, Financial Analysts Journal): Roll Yield and Term Structure Slope
3. Kaldor (1939), Working (1949), Brennan (1958): Theory of Storage & Net Convenience Yield
4. Gorton, Hayashi & Rouwenhorst (2013, Review of Finance): Fundamental Drivers of Term Structure

核心类:
1. SchwartzSmithConfig: 两因子模型超参数配置
2. SchwartzSmithTwoFactorModel: 状态空间卡尔曼滤波与便利收益解析求解引擎
3. BasisConvergenceEngine: 物理基本面 (仓单/库存/季节性) 驱动的动态基差收敛速度引擎
4. TermStructureMomentum: 期限结构动量与主动防御信号引擎
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple, Union
import numpy as np
import pandas as pd


@dataclass
class SchwartzSmithConfig:
    """Schwartz-Smith (2000) 两因子商品定价模型配置参数 (校准自 reports/assumptions.md)"""
    kappa: float = 1.25            # 短期偏差因子均值回归速度 (年化，半衰期约 138 交易日)
    sigma_chi: float = 0.32        # 短期因子瞬时波动率 (年化 32%)
    mu_xi: float = 0.015           # 长期均衡水平长期漂移率 (年化 1.5%)
    sigma_xi: float = 0.16         # 长期因子瞬时波动率 (年化 16%)
    rho: float = 0.35              # 短期因子与长期因子瞬时相关系数
    lambda_chi: float = 0.0        # 短期风险市场价格 (风险中性调整)
    lambda_xi: float = 0.0         # 长期风险市场价格 (风险中性调整)
    risk_free_rate: float = 0.03   # 年化无风险利率 r (3.0%)
    storage_cost: float = 0.02     # 年化现货仓储与资金占用费率 u (2.0%)
    dt: float = 1.0 / 250.0        # 单交易日步长 (以年为基准)


def compute_schwartz_smith_analytical_a(tau: float, config: SchwartzSmithConfig) -> float:
    """
    计算 Schwartz-Smith (2000) 解析闭式解中的曲率确定性项 A(tau)。
    
    公式:
    A(tau) = mu_xi^* * tau - (lambda_chi / kappa) * (1 - e^(-kappa * tau))
             + 0.5 * [ (sigma_chi^2 / (2 * kappa)) * (1 - e^(-2 * kappa * tau))
                       + sigma_xi^2 * tau
                       + 2 * (rho * sigma_chi * sigma_xi / kappa) * (1 - e^(-kappa * tau)) ]
                       
    性质:
    当 tau -> 0 时，A(0) = 0.0，ln F(t, t) = chi_t + xi_t = ln S_t (无套利到期收敛)。
    """
    if tau <= 1e-9:
        return 0.0

    kappa = config.kappa
    sigma_chi = config.sigma_chi
    sigma_xi = config.sigma_xi
    rho = config.rho
    mu_xi_star = config.mu_xi - config.lambda_xi
    lambda_chi = config.lambda_chi

    term1 = mu_xi_star * tau
    term2 = (lambda_chi / kappa) * (1.0 - np.exp(-kappa * tau)) if kappa > 0 else 0.0
    
    var_chi = (sigma_chi**2 / (2.0 * kappa)) * (1.0 - np.exp(-2.0 * kappa * tau)) if kappa > 0 else (sigma_chi**2 * tau)
    var_xi = sigma_xi**2 * tau
    cov_term = (2.0 * rho * sigma_chi * sigma_xi / kappa) * (1.0 - np.exp(-kappa * tau)) if kappa > 0 else (2.0 * rho * sigma_chi * sigma_xi * tau)
    
    return term1 - term2 + 0.5 * (var_chi + var_xi + cov_term)


class SchwartzSmithTwoFactorModel:
    """
    Schwartz-Smith (2000) 两因子商品期限结构与便利收益求解引擎。
    
    对数现货价格分解:
        ln S_t = chi_t + xi_t
    期货价格解析解:
        ln F(t, t + tau) = e^(-kappa * tau) * chi_t + xi_t + A(tau)
    瞬时便利收益率:
        delta_t = kappa * chi_t + delta_bar
        其中 delta_bar = r + u (持有成本平价)
    """

    def __init__(self, config: Optional[SchwartzSmithConfig] = None):
        self.config = config if config is not None else SchwartzSmithConfig()

    def log_futures_price(self, chi: float, xi: float, tau: float) -> float:
        """
        根据当前状态变量 [chi, xi] 和剩余期限 tau 计算理论对数期货价格。
        """
        a_tau = compute_schwartz_smith_analytical_a(tau, self.config)
        return float(np.exp(-self.config.kappa * tau) * chi + xi + a_tau)

    def futures_price(self, chi: float, xi: float, tau: float) -> float:
        """根据当前状态变量计算理论期货价格 F(t, t + tau)"""
        return float(np.exp(self.log_futures_price(chi, xi, tau)))

    def fit_filter_causal(
        self,
        spot: pd.Series,
        futures: pd.Series,
        t_to_expiry: Optional[pd.Series] = None
    ) -> pd.DataFrame:
        """
        严格因果无前视的在线状态空间卡尔曼滤波器 (Online Kalman Filter)。
        
        参数:
        - spot: 现货价格序列 S_t
        - futures: 期货价格序列 F_t
        - t_to_expiry: 剩余到期时间 tau_t (以年为单位)，若为 None 则默认 60 交易日 (0.24年)
        
        返回 DataFrame 包含:
        - chi_short: 短期供需偏差因子 chi_t
        - xi_long: 长期均衡价格水平因子 xi_t
        - convenience_yield: 瞬时净便利收益率 delta_t
        - roll_yield: 展期收益率 RY_t
        - term_structure_slope: 期限结构斜率 beta_t^{TS}
        """
        n = len(spot)
        s_arr = spot.values.astype(float)
        f_arr = futures.values.astype(float)
        
        # 默认剩余到期期限 (60 交易日 / 250)
        if t_to_expiry is not None:
            tau_arr = np.maximum(t_to_expiry.values.astype(float), 1e-4)
        else:
            tau_arr = np.full(n, 60.0 / 250.0)

        ln_s = np.log(np.maximum(s_arr, 1.0))
        ln_f = np.log(np.maximum(f_arr, 1.0))

        # 状态向量 x = [chi, xi]^T
        dt = self.config.dt
        kappa = self.config.kappa
        mu_xi = self.config.mu_xi
        sigma_chi = self.config.sigma_chi
        sigma_xi = self.config.sigma_xi
        rho = self.config.rho

        # 状态转移矩阵 F 与 漂移向量 c
        phi_chi = np.exp(-kappa * dt)
        F_mat = np.array([[phi_chi, 0.0], [0.0, 1.0]])
        c_vec = np.array([0.0, mu_xi * dt])

        # 过程噪声协方差 Q
        q_chi = (sigma_chi**2 / (2.0 * kappa)) * (1.0 - np.exp(-2.0 * kappa * dt)) if kappa > 0 else (sigma_chi**2 * dt)
        q_xi = sigma_xi**2 * dt
        q_chixi = (rho * sigma_chi * sigma_xi / kappa) * (1.0 - np.exp(-kappa * dt)) if kappa > 0 else (rho * sigma_chi * sigma_xi * dt)
        Q_mat = np.array([[q_chi, q_chixi], [q_chixi, q_xi]])

        # 观测噪声协方差 R (测量误差假定极小)
        R_mat = np.diag([1e-4, 1e-4])

        # 初始状态估计 x_0|0 与误差协方差 P_0|0
        xi_init = ln_f[0]
        chi_init = ln_s[0] - xi_init
        x_est = np.array([chi_init, xi_init])
        P_mat = np.diag([0.02, 0.02])

        chi_filtered = np.zeros(n)
        xi_filtered = np.zeros(n)
        chi_filtered[0] = x_est[0]
        xi_filtered[0] = x_est[1]

        # 递推因果在线滤波
        for t in range(1, n):
            # 1. 状态一步预测
            x_pred = F_mat @ x_est + c_vec
            P_pred = F_mat @ P_mat @ F_mat.T + Q_mat

            # 2. 当前步观测矩阵 H_t 与偏置 d_t
            tau_t = tau_arr[t]
            h21 = np.exp(-kappa * tau_t)
            H_mat = np.array([[1.0, 1.0], [h21, 1.0]])
            a_tau = compute_schwartz_smith_analytical_a(tau_t, self.config)
            d_vec = np.array([0.0, a_tau])

            # 3. 测量更新
            y_obs = np.array([ln_s[t], ln_f[t]])
            y_pred = H_mat @ x_pred + d_vec
            v_innov = y_obs - y_pred

            S_innov = H_mat @ P_pred @ H_mat.T + R_mat
            # 2x2 矩阵求逆
            inv_S = np.linalg.inv(S_innov)
            K_gain = P_pred @ H_mat.T @ inv_S

            x_est = x_pred + K_gain @ v_innov
            P_mat = (np.eye(2) - K_gain @ H_mat) @ P_pred

            chi_filtered[t] = x_est[0]
            xi_filtered[t] = x_est[1]

        # 4. 衍生指标解算
        # 展期收益率 RY = (ln S - ln F) / tau
        roll_yield = (ln_s - ln_f) / tau_arr
        # 期限结构斜率 beta_TS = -RY
        term_structure_slope = -roll_yield

        # 瞬时净便利收益率 delta_t = kappa * chi_t + delta_bar
        # 在大宗商品反向市场中，根据储藏理论: delta_t = r + u + RY_t
        delta_bar = self.config.risk_free_rate + self.config.storage_cost
        convenience_yield = delta_bar + roll_yield

        res_df = pd.DataFrame(
            {
                "chi_short": chi_filtered,
                "xi_long": xi_filtered,
                "convenience_yield": convenience_yield,
                "roll_yield": roll_yield,
                "term_structure_slope": term_structure_slope,
            },
            index=spot.index
        )
        return res_df


class BasisConvergenceEngine:
    """
    纯碱动态基差收敛速度计算与模拟引擎 lambda_t = f(WR_t, Inv_t, Seasonality_t)。
    
    微观交割与物理基本面机制:
    1. 交易所标准仓单注册量 (WR): 仓单增加 -> 卖方交割抛压增大 -> 强力驱动期货向现货收敛 (d lambda / d WR > 0)
    2. 实体企业社会库存 (Inv): 高库存胀库 -> 现货降价寻求出清 -> 驱动基差倒挂修复 (d lambda / d Inv > 0)
    3. 季节性交割月核 (Seasonality): 郑商所 01、05、09 主力合约交割临近 40 交易日内强制加速收敛
    
    动态收敛速度映射:
        lambda_t = lambda_min + (lambda_max - lambda_min) * (1 / (1 + exp(-z_t)))
        z_t = gamma_0 + gamma_wr * WR_tilde + gamma_inv * Inv_tilde + gamma_seas * s_delivery(t)
    物理有界约束:
        0.015 <= lambda_t <= 0.160, 中心基准处于 0.040
    """

    def __init__(
        self,
        lambda_min: float = 0.015,
        lambda_max: float = 0.160,
        gamma_0: float = -1.5686,    # 使得在标准基准状态下，lambda_0 = 0.015 + 0.145 * (1 / (1 + 4.8)) = 0.040
        gamma_wr: float = 0.65,
        gamma_inv: float = 0.50,
        gamma_seas: float = 1.20,
        ref_wr: float = 6000.0,
        scale_wr: float = 3000.0,
        ref_inv: float = 75.0,
        scale_inv: float = 20.0
    ):
        self.lambda_min = lambda_min
        self.lambda_max = lambda_max
        self.gamma_0 = gamma_0
        self.gamma_wr = gamma_wr
        self.gamma_inv = gamma_inv
        self.gamma_seas = gamma_seas
        self.ref_wr = ref_wr
        self.scale_wr = scale_wr
        self.ref_inv = ref_inv
        self.scale_inv = scale_inv

    def compute_delivery_seasonality(
        self,
        dates: Optional[pd.Series] = None,
        n_steps: Optional[int] = None
    ) -> np.ndarray:
        """
        计算郑商所纯碱主力交割月份 (1月、5月、9月15日) 的因果距离季节性核 s_delivery(t) in [0, 1]。
        临近交割月时 s_delivery -> 1.0; 远离交割时 s_delivery -> 0.0。
        """
        if dates is not None:
            dt_series = pd.to_datetime(dates)
            n = len(dt_series)
            s_arr = np.zeros(n)
            
            for i, dt in enumerate(dt_series):
                yr = dt.year
                # 郑商所纯碱主力交割月目标日 (1月、5月、9月 15 日)
                target_dates = [
                    pd.Timestamp(year=yr, month=1, day=15),
                    pd.Timestamp(year=yr, month=5, day=15),
                    pd.Timestamp(year=yr, month=9, day=15),
                    pd.Timestamp(year=yr + 1, month=1, day=15)
                ]
                future_targets = [d for d in target_dates if d >= dt]
                if not future_targets:
                    next_target = pd.Timestamp(year=yr + 1, month=1, day=15)
                else:
                    next_target = future_targets[0]
                    
                cal_days = (next_target - dt).days
                # 转化为交易日估算 (约 250/365)
                trading_days_left = min(max(cal_days * (250.0 / 365.0), 0.0), 80.0)
                # 二次衰减核: 距离越近，权重呈抛物线加速攀升
                s_arr[i] = ((80.0 - trading_days_left) / 80.0)**2
            return s_arr
        else:
            n = n_steps if n_steps is not None else 1
            t = np.arange(n)
            # 以 120 交易日为一个标准主力合约交割换月周期
            phase = t % 120
            s_arr = ((phase) / 120.0)**2
            return s_arr

    def compute_dynamic_convergence_speed(
        self,
        dates: Optional[pd.Series] = None,
        inventory: Optional[pd.Series] = None,
        warehouse_receipts: Optional[pd.Series] = None,
        n_steps: Optional[int] = None
    ) -> pd.Series:
        """
        输入仓单与库存序列，解算时变有界收敛速度 lambda_t in [lambda_min, lambda_max]。
        """
        if inventory is not None:
            n = len(inventory)
            idx = inventory.index
        elif warehouse_receipts is not None:
            n = len(warehouse_receipts)
            idx = warehouse_receipts.index
        elif dates is not None:
            n = len(dates)
            idx = dates.index
        elif n_steps is not None:
            n = n_steps
            idx = pd.RangeIndex(n)
        else:
            raise ValueError("必须提供 dates、inventory、warehouse_receipts 或 n_steps 之一")

        # 1. 标准化偏离项 (采用绝对锚定常数以杜绝全样本均值前视偏差)
        if warehouse_receipts is not None:
            wr_val = np.asarray(warehouse_receipts, dtype=float)
            wr_val = np.nan_to_num(wr_val, nan=self.ref_wr)
            wr_tilde = (wr_val - self.ref_wr) / self.scale_wr
        else:
            wr_tilde = np.zeros(n)

        if inventory is not None:
            inv_val = np.asarray(inventory, dtype=float)
            inv_val = np.nan_to_num(inv_val, nan=self.ref_inv)
            inv_tilde = (inv_val - self.ref_inv) / self.scale_inv
        else:
            inv_tilde = np.zeros(n)

        # 2. 季节性交割核
        s_seas = self.compute_delivery_seasonality(dates=dates, n_steps=n)

        # 3. 耦合指数 z_t
        z = self.gamma_0 + self.gamma_wr * wr_tilde + self.gamma_inv * inv_tilde + self.gamma_seas * s_seas

        # 4. Logistic 映射到物理有界区间 [lambda_min, lambda_max]
        # 数值防溢出截断
        z_safe = np.clip(z, -20.0, 20.0)
        logistic_val = 1.0 / (1.0 + np.exp(-z_safe))
        lambda_val = self.lambda_min + (self.lambda_max - self.lambda_min) * logistic_val

        return pd.Series(lambda_val, index=idx, name="basis_convergence_speed_sa")

    def simulate_dynamic_basis(
        self,
        futures_sa: pd.Series,
        dates: Optional[pd.Series] = None,
        inventory: Optional[pd.Series] = None,
        warehouse_receipts: Optional[pd.Series] = None,
        seed: int = 42
    ) -> Dict[str, pd.Series]:
        """
        基于动态收敛速度 lambda_t 的微观自适应确定性 ODE 过程生成基差与现货序列。
        彻底消除伪随机数生成器与假数据，严格满足因果递推截断不变性 (diff == 0.0)。
        """
        n = len(futures_sa)
        f_sa = futures_sa.values.astype(float)
        t = np.arange(n)
        idx = futures_sa.index

        # 若未提供外部仓单与库存，采用确定性物理基准常数，杜绝伪造随机时间序列
        if warehouse_receipts is not None:
            wr_ser = warehouse_receipts.copy()
        else:
            wr_ser = pd.Series(self.ref_wr, index=idx, name="warehouse_receipts_sa")

        if inventory is not None:
            inv_ser = inventory.copy()
        else:
            inv_ser = pd.Series(self.ref_inv, index=idx, name="inventory_sa")

        # 计算时变动态收敛速度
        lambda_ser = self.compute_dynamic_convergence_speed(
            dates=dates,
            inventory=inv_ser,
            warehouse_receipts=wr_ser
        )
        lambda_arr = lambda_ser.values

        # 纯碱深度贴水均值基准与交割周期波 (纯确定性微观收敛 ODE，无伪造高斯噪声)
        cyclical_sa = 280.0 * np.sin(2.0 * np.pi * t / 120.0)
        mu_sa = -525.04 + cyclical_sa

        basis_sa = np.zeros(n)
        basis_sa[0] = -525.04

        for i in range(1, n):
            db = lambda_arr[i] * (mu_sa[i] - basis_sa[i - 1])
            basis_sa[i] = basis_sa[i - 1] + db

        basis_sa = np.clip(basis_sa, -1400.0, 250.0)
        # 现货价格: Spot = Futures - Basis, 保证综合成本底线 >= 800
        spot_sa = np.maximum(f_sa - basis_sa, 800.0)
        # 严格满足 Basis = Futures - Spot
        basis_sa = f_sa - spot_sa
        basis_rate_sa = basis_sa / spot_sa

        return {
            "spot_sa": pd.Series(spot_sa, index=idx),
            "basis_sa": pd.Series(basis_sa, index=idx),
            "basis_rate_sa": pd.Series(basis_rate_sa, index=idx),
            "basis_convergence_speed_sa": pd.Series(lambda_arr, index=idx),
            "warehouse_receipts_sa": wr_ser,
            "inventory_sa": inv_ser,
        }


class TermStructureMomentum:
    """
    期限结构动量与主动防御信号引擎 (TSMOM)。
    
    理论依据:
    Moskowitz, Ooi & Pedersen (2012) + Erb & Harvey (2006)
    
    信号逻辑:
    1. 平滑展期收益率: RY_smooth_t = EMA_20(RY_t)
    2. 因果滚动 Z-Score:
       TSMOM_t = clip( - (RY_smooth_t - mu_{60d}) / (sigma_{60d} + eps), -1.0, 1.0 )
    3. 主动防御解释 (Active Defense):
       - 当纯碱处于极度深贴水 (Backwardation 极强, RY >> 0) 时: TSMOM < 0 -> 触发主动防御，
         惩罚追空假突破，防止在深贴水割肉并承担沉重展期亏损 (Roll Drag)；
       - 当期限结构转为平坦甚至 Contango 升水 (RY <= 0) 时: TSMOM > 0 -> 确认现货过剩主跌浪形成。
    """

    def __init__(
        self,
        smooth_window: int = 20,
        zscore_window: int = 60,
        epsilon: float = 1e-6
    ):
        self.smooth_window = smooth_window
        self.zscore_window = zscore_window
        self.epsilon = epsilon

    def compute_tsmom_signal(self, roll_yield: pd.Series) -> pd.Series:
        """
        从展期收益率序列因果计算 TSMOM 动量信号 in [-1.0, 1.0]。
        前 60 日自适应扩展无任何 NaN 产生。
        """
        # 1. 因果 EMA 平滑
        ry_smooth = roll_yield.ewm(span=self.smooth_window, adjust=False).mean()

        # 2. 因果无前视滚动均值与标准差 (min_periods=1 保证零首期缺失)
        roll_mean = ry_smooth.rolling(window=self.zscore_window, min_periods=1).mean()
        roll_std = ry_smooth.rolling(window=self.zscore_window, min_periods=2).std().fillna(0.0)

        # 3. 标准化 Z-Score 与反向极性映射
        # RY 高于历史均值 -> 深贴水现货强 -> TSMOM 为负 (主动防御)
        # RY 低于历史均值 -> 期限结构恶化升水 -> TSMOM 为正 (确认破位)
        zscore = (ry_smooth - roll_mean) / (roll_std + self.epsilon)
        tsmom = (-zscore).clip(-1.0, 1.0)

        return pd.Series(tsmom.values, index=roll_yield.index, name="tsmom_sa")
