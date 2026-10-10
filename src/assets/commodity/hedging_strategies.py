# -*- coding: utf-8 -*-
"""
套保策略与金融工程核心模型 (hedging_strategies.py)
--------------------------------------------------
结合郑商所纯碱实际期现基差（Basis Risk）校准，包含四大方案：
1. UnhedgedStrategy: 裸暴露（纯现货库存基准）
2. NaiveFuturesHedge: 传统 1:1 机械式期货空头套保（暴露于深贴水基差收敛风险）
3. OLSMinimumVarianceHedge: 经典滚动 OLS 最小方差对冲
4. TrendGateCollarHedge: 本课题核心创新——自适应趋势门控 + 零成本期权 Collar 领子动态对冲
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
import numpy as np
import pandas as pd

from src.models.basis_term_structure import BasisConvergenceEngine
from src.models.option_collar import AdaptiveOptionCollarEngine, Black76Greeks, CollarConfig
from src.models.temporal_nale import TemporalNALE
from src.models.trend_gate import TrendGateMachine


@dataclass
class OptionPosition:
    """场内期权持仓账本条目 (Scheme D Option Position Ledger)"""
    open_idx: int
    open_date: str
    expiry_idx: int
    expiry_date: str
    strike_put: float
    strike_call: float
    put_iv: float
    call_iv: float
    premium_put: float
    premium_call: float
    current_value: float       # 逐日盯市净价值 (元/吨, put_val - call_val)
    tons: float                # 对冲现货吨数
    margin_per_ton: float      # 保证金需求 (元/吨)
    days_held: int = 0
    tenor_days: int = 30
    close_date: Optional[str] = None
    close_reason: Optional[str] = None
    settled_payoff: Optional[float] = None


class HedgingEngine:
    """结合真实基差风险（Basis Risk）的套期保值全真回测模拟引擎"""

    def __init__(
        self,
        df: pd.DataFrame,
        inventory_tons: float = 10000.0,
        contract_multiplier: float = 20.0,
        margin_ratio: float = 0.12,
        commission_rate: float = 0.0002,
        annual_risk_free_rate: float = 0.03,
        random_seed: int = 42,
        collar_config: Optional[CollarConfig] = None
    ):
        self.df = df.copy().sort_values("date").reset_index(drop=True)
        self.inventory_tons = inventory_tons
        self.multiplier = contract_multiplier
        self.margin_ratio = margin_ratio
        self.commission_rate = commission_rate
        self.rf = annual_risk_free_rate
        self.seed = random_seed
        self.collar_engine = AdaptiveOptionCollarEngine(collar_config)
        self.option_ledger = pd.DataFrame()
        
        # 构建基于郑商所实际校准的现货序列与基差序列
        self._construct_spot_and_basis()

    def _detect_rollover_days(self) -> pd.Series:
        """
        识别主力合约移仓换月交易日:
        1. 优先使用真实主力合约代码变更 (如 dominant_contract / dominant_contract_sa)
        2. 若无合约代码字段，则按月度移仓规则识别 (每个自然月首个交易日，忽略第一天)
        """
        if "dominant_contract" in self.df.columns:
            contracts = self.df["dominant_contract"]
            is_roll = (contracts != contracts.shift(1)) & (self.df.index > 0)
        elif "dominant_contract_sa" in self.df.columns:
            contracts = self.df["dominant_contract_sa"]
            is_roll = (contracts != contracts.shift(1)) & (self.df.index > 0)
        else:
            dates = pd.to_datetime(self.df["date"])
            is_roll = (dates.dt.month != dates.dt.month.shift(1)) & (self.df.index > 0)
        return is_roll.fillna(False)

    def _construct_spot_and_basis(self) -> None:
        """
        根据郑商所纯碱实测基差数据校验现货价格与基差:
        - 必须包含真实 spot_sa 与 basis_sa，直接复用以保证端到端一致性与数据真实性
        - 严禁回退至任何假数据或模拟生成路径
        """
        if "spot_sa" in self.df.columns and "basis_sa" in self.df.columns:
            self.df["p_futures"] = self.df["close_sa"].values
            self.df["basis"] = self.df["basis_sa"].values
            self.df["p_spot"] = self.df["spot_sa"].values
            if "basis_convergence_speed_sa" in self.df.columns:
                self.df["lambda_convergence"] = self.df["basis_convergence_speed_sa"].values
        else:
            raise ValueError("输入数据缺失真实 spot_sa 与 basis_sa 特征，严禁回退至模拟数据！")

    def run_unhedged(self) -> pd.DataFrame:
        """方案 A: 裸暴露（企业未开展任何衍生品套保，全额承担现货库存跌价）"""
        res = pd.DataFrame({"date": self.df["date"]})
        p_spot = self.df["p_spot"]
        initial_val = self.inventory_tons * p_spot.iloc[0]
        
        delta_spot_pnl = self.inventory_tons * (p_spot - p_spot.shift(1)).fillna(0.0)
        
        res["contracts"] = 0
        res["residual_exposure"] = float(self.inventory_tons)
        res["spot_pnl"] = delta_spot_pnl
        res["futures_pnl"] = 0.0
        res["option_pnl"] = 0.0
        res["collar_pnl"] = 0.0
        res["hedge_pnl"] = 0.0
        res["fee_trade"] = 0.0
        res["fee_roll"] = 0.0
        res["fee_option"] = 0.0
        res["capital_cost"] = 0.0
        res["cost"] = 0.0
        res["net_pnl"] = delta_spot_pnl
        res["total_equity"] = initial_val + res["net_pnl"].cumsum()
        res["net_worth"] = res["total_equity"] / initial_val
        res["hedge_ratio"] = 0.0
        res["margin_used"] = 0.0
        return res

    def run_naive_hedge(self) -> pd.DataFrame:
        """方案 B: 传统 Naïve 1:1 静态套保（机械式满额做空期货）"""
        res = pd.DataFrame({"date": self.df["date"]})
        p_spot = self.df["p_spot"]
        p_fut = self.df["p_futures"]
        initial_val = self.inventory_tons * p_spot.iloc[0]
        
        delta_spot = (p_spot - p_spot.shift(1)).fillna(0.0)
        delta_fut = (p_fut - p_fut.shift(1)).fillna(0.0)
        
        h = 1.0
        contracts_scalar = int(np.floor((self.inventory_tons * h) / self.multiplier))
        contracts = pd.Series(contracts_scalar, index=self.df.index, dtype=int)
        residual_exposure = pd.Series(
            self.inventory_tons - contracts * self.multiplier, index=self.df.index, dtype=float
        )
        
        spot_pnl = self.inventory_tons * delta_spot
        futures_pnl = - (contracts * self.multiplier) * delta_fut
        
        # 逐日盯市保证金与资金成本
        margin_used = contracts * self.multiplier * p_fut * self.margin_ratio
        capital_cost = margin_used * (self.rf / 250.0)
        
        # 完整成本结构: 开平仓手续费 + 主力移仓换月成本
        fee_trade = pd.Series(0.0, index=res.index)
        fee_trade.iloc[0] = contracts.iloc[0] * self.multiplier * p_fut.iloc[0] * self.commission_rate
        
        is_roll = self._detect_rollover_days()
        fee_roll = pd.Series(0.0, index=res.index)
        fee_roll.loc[is_roll] = (
            2.0 * contracts.loc[is_roll] * self.multiplier * p_fut.loc[is_roll] * self.commission_rate
        )
        
        total_cost = fee_trade + fee_roll + capital_cost
        
        res["contracts"] = contracts
        res["residual_exposure"] = residual_exposure
        res["spot_pnl"] = spot_pnl
        res["futures_pnl"] = futures_pnl
        res["option_pnl"] = 0.0
        res["collar_pnl"] = 0.0
        res["hedge_pnl"] = futures_pnl
        res["fee_trade"] = fee_trade
        res["fee_roll"] = fee_roll
        res["fee_option"] = 0.0
        res["capital_cost"] = capital_cost
        res["cost"] = total_cost
        res["net_pnl"] = spot_pnl + futures_pnl - total_cost
        res["total_equity"] = initial_val + res["net_pnl"].cumsum()
        res["net_worth"] = res["total_equity"] / initial_val
        res["hedge_ratio"] = h
        res["margin_used"] = margin_used
        return res

    def run_ols_hedge(self, window: int = 60) -> pd.DataFrame:
        """方案 C: 经典 OLS 滚动最小方差套期保值"""
        res = pd.DataFrame({"date": self.df["date"]})
        p_spot = self.df["p_spot"]
        p_fut = self.df["p_futures"]
        initial_val = self.inventory_tons * p_spot.iloc[0]
        
        delta_spot = (p_spot - p_spot.shift(1)).fillna(0.0)
        delta_fut = (p_fut - p_fut.shift(1)).fillna(0.0)
        
        # 滚动计算最优对冲比率 h*
        rolling_cov = delta_spot.rolling(window).cov(delta_fut)
        rolling_var = delta_fut.rolling(window).var()
        h_star = (rolling_cov / rolling_var).clip(lower=0.2, upper=1.3).fillna(0.8)
        
        # T8: 手数向下取整，记录残差
        contracts = np.floor((self.inventory_tons * h_star) / self.multiplier).astype(int)
        residual_exposure = pd.Series(
            self.inventory_tons - contracts * self.multiplier, index=self.df.index, dtype=float
        )
        
        spot_pnl = self.inventory_tons * delta_spot
        futures_pnl = - (contracts * self.multiplier) * delta_fut
        
        # 逐日盯市保证金与资金成本
        margin_used = contracts * self.multiplier * p_fut * self.margin_ratio
        capital_cost = margin_used * (self.rf / 250.0)
        
        # 完整交易摩擦: 首日建仓 + 调仓变动平开仓 + 换月移仓
        delta_c = (contracts - contracts.shift(1)).abs()
        delta_c.iloc[0] = contracts.iloc[0]
        fee_trade = delta_c * self.multiplier * p_fut * self.commission_rate
        
        is_roll = self._detect_rollover_days()
        fee_roll = pd.Series(0.0, index=res.index)
        held_on_roll = pd.concat([contracts, contracts.shift(1)], axis=1).min(axis=1).fillna(0)
        fee_roll.loc[is_roll] = (
            2.0 * held_on_roll.loc[is_roll] * self.multiplier * p_fut.loc[is_roll] * self.commission_rate
        )
        
        total_cost = fee_trade + fee_roll + capital_cost
        
        res["contracts"] = contracts
        res["residual_exposure"] = residual_exposure
        res["spot_pnl"] = spot_pnl
        res["futures_pnl"] = futures_pnl
        res["option_pnl"] = 0.0
        res["collar_pnl"] = 0.0
        res["hedge_pnl"] = futures_pnl
        res["fee_trade"] = fee_trade
        res["fee_roll"] = fee_roll
        res["fee_option"] = 0.0
        res["capital_cost"] = capital_cost
        res["cost"] = total_cost
        res["net_pnl"] = spot_pnl + futures_pnl - total_cost
        res["total_equity"] = initial_val + res["net_pnl"].cumsum()
        res["net_worth"] = res["total_equity"] / initial_val
        res["hedge_ratio"] = h_star
        res["margin_used"] = margin_used
        return res

    def run_trend_gate_collar(
        self,
        trend_gate_config: Optional[Dict] = None,
        nale_config: Optional[Dict] = None,
        fast_span: Optional[int] = None,
        slow_span: Optional[int] = None,
        hysteresis_window: Optional[int] = None,
        nale_weight: Optional[float] = None,
        tsmom_weight: Optional[float] = None,
        threshold: Optional[float] = None,
        active_defense: Optional[bool] = None,
        sa_to_fg_lag: Optional[float] = None,
        sa_half_life: Optional[float] = None,
        nale_signals: Optional[pd.Series] = None
    ) -> pd.DataFrame:
        """
        方案 D: 本课题核心创新方案
        Trend Gate™ 状态机 + 场内期权 Collar 领子动态对冲

        参数化支持:
        - trend_gate_config: 可选字典配置 (如 fast_span, slow_span, hysteresis_window, nale_weight, tsmom_weight, threshold, active_defense)
        - nale_config: 可选字典配置 (如 window, sa_to_fg_lag, sa_half_life)
        - 也支持直接传入对应关键字参数；未指定的参数采用默认基准值
        - nale_signals: 可选直接传入预先计算的先行信号序列，加速敏感性分析
        """
        tg_cfg = trend_gate_config.copy() if trend_gate_config else {}
        nl_cfg = nale_config.copy() if nale_config else {}

        # 解析 NALE 参数
        nl_window = nl_cfg.get("window", 60)
        nl_lag = sa_to_fg_lag if sa_to_fg_lag is not None else nl_cfg.get("sa_to_fg_lag", 18.0)
        nl_hl = sa_half_life if sa_half_life is not None else nl_cfg.get("sa_half_life", 25.0)

        # 解析 TrendGate 参数
        tg_fast = fast_span if fast_span is not None else tg_cfg.get("fast_span", 20)
        tg_slow = slow_span if slow_span is not None else tg_cfg.get("slow_span", 60)
        tg_hys = hysteresis_window if hysteresis_window is not None else tg_cfg.get("hysteresis_window", 3)
        tg_nw = nale_weight if nale_weight is not None else tg_cfg.get("nale_weight", 0.35)
        tg_tsw = tsmom_weight if tsmom_weight is not None else tg_cfg.get("tsmom_weight", 0.20)
        tg_pw = tg_cfg.get("price_weight", None)
        tg_act = active_defense if active_defense is not None else tg_cfg.get("active_defense", True)
        tg_thresh = threshold if threshold is not None else tg_cfg.get("threshold", 0.50)

        res = pd.DataFrame({"date": self.df["date"]})
        p_spot = self.df["p_spot"]
        p_fut = self.df["p_futures"]
        initial_val = self.inventory_tons * p_spot.iloc[0]
        
        delta_spot = (p_spot - p_spot.shift(1)).fillna(0.0)
        delta_fut = (p_fut - p_fut.shift(1)).fillna(0.0)
        
        # 1. 运行 Temporal NALE 时空图卷积提取产业链先行利润挤压信号
        if nale_signals is None:
            nale_engine = TemporalNALE(window=nl_window, sa_to_fg_lag=nl_lag, sa_half_life=nl_hl)
            crush_df = nale_engine.compute_crush_spread(self.df)
            nale_signals = crush_df["nale_leading_signal"]
        
        # 2. 运行 Trend Gate 因果门控状态机 (注入 TSMOM 期限结构动量与主动防御)
        gate_machine = TrendGateMachine(
            fast_span=tg_fast,
            slow_span=tg_slow,
            hysteresis_window=tg_hys,
            nale_weight=tg_nw,
            tsmom_weight=tg_tsw,
            price_weight=tg_pw,
            active_defense=tg_act,
            threshold=tg_thresh
        )
        tsmom_signals = self.df["tsmom_sa"] if "tsmom_sa" in self.df.columns else None
        eval_df = gate_machine.evaluate_regime(
            pd.Series(p_fut, index=self.df.index),
            nale_signals=nale_signals,
            tsmom_signals=tsmom_signals
        )
        trend_gate = eval_df["trend_gate"]
        dynamic_h = eval_df["dynamic_hedge_ratio"]
        
        contracts = np.floor((self.inventory_tons * dynamic_h) / self.multiplier).astype(int)
        residual_exposure = pd.Series(
            self.inventory_tons - contracts * self.multiplier, index=self.df.index, dtype=float
        )
        futures_pnl = - (contracts * self.multiplier) * delta_fut
        spot_pnl = self.inventory_tons * delta_spot
        
        # 3. 自适应场内期权 Collar 领子动态对冲账本 (仅在震荡期 TG=0 时生效，确保总敞口严格平衡在 100% 以内)
        iv_series = self.df["iv_atm_sa"] if "iv_atm_sa" in self.df.columns else (self.df["vol_20d_sa"] + 0.02 if "vol_20d_sa" in self.df.columns else pd.Series(0.25, index=self.df.index))
        skew_series = self.df["collar_skew_sa"] if "collar_skew_sa" in self.df.columns else pd.Series(-0.03, index=self.df.index)
        
        n_days = len(self.df)
        option_pnl_arr = np.zeros(n_days)
        option_fee_arr = np.zeros(n_days)
        collar_margin_used = np.zeros(n_days)
        strike_put_arr = np.zeros(n_days)
        strike_call_arr = np.zeros(n_days)
        
        p_spot_vals = p_spot.values
        tg_vals = trend_gate.values
        iv_vals = iv_series.values
        skew_vals = skew_series.values
        dates = pd.to_datetime(self.df["date"])
        
        active_pos: Optional[OptionPosition] = None
        ledger_records: List[Dict] = []
        tenor_days = 30
        
        for i in range(n_days):
            tg_curr = tg_vals[i]
            s_curr = p_spot_vals[i]
            iv_curr = iv_vals[i]
            skew_curr = skew_vals[i]
            dt_curr_str = str(dates.iloc[i])[:10]
            unh_tons_curr = float(residual_exposure.iloc[i])
            
            # --- 步骤 3.1: 结算/盯市既有期权持仓 ---
            if active_pos is not None:
                is_regime_flip = (tg_curr == 1)
                is_expired = (i >= active_pos.expiry_idx)
                is_last_day = (i == n_days - 1)
                
                if is_regime_flip or is_expired or is_last_day:
                    if is_expired:
                        # 到期行权结算: 严格使用 Intrinsic Payoff 结算
                        payoff_put = max(0.0, active_pos.strike_put - s_curr)
                        payoff_call = max(0.0, s_curr - active_pos.strike_call)
                        v_settle = payoff_put - payoff_call
                        daily_opt_pnl = active_pos.tons * (v_settle - active_pos.current_value)
                        fee_close = 0.0  # 到期自动交割结算无交易手续费
                        close_reason = "expiry"
                    else:
                        # 翻转主跌浪提前平仓或回测终点: 按当前 Black-76 理论市值平仓
                        rem_tau = max(1.0 / 252.0, (active_pos.expiry_idx - i) / 252.0)
                        p_iv = self.collar_engine.skew_model.get_iv(
                            active_pos.strike_put, s_curr, rem_tau, iv_atm=iv_curr, beta_skew=skew_curr
                        )
                        c_iv = self.collar_engine.skew_model.get_iv(
                            active_pos.strike_call, s_curr, rem_tau, iv_atm=iv_curr, beta_skew=skew_curr
                        )
                        p_val = Black76Greeks.put_price(s_curr, active_pos.strike_put, rem_tau, self.rf, p_iv)
                        c_val = Black76Greeks.call_price(s_curr, active_pos.strike_call, rem_tau, self.rf, c_iv)
                        v_settle = p_val - c_val
                        daily_opt_pnl = active_pos.tons * (v_settle - active_pos.current_value)
                        fee_close = active_pos.tons * (p_val + c_val) * self.commission_rate
                        close_reason = "regime_change_to_tg1" if is_regime_flip else "backtest_end"
                    
                    option_pnl_arr[i] += daily_opt_pnl
                    option_fee_arr[i] += fee_close
                    
                    # 归档至期权账本
                    active_pos.close_date = dt_curr_str
                    active_pos.close_reason = close_reason
                    active_pos.settled_payoff = v_settle
                    active_pos.current_value = v_settle
                    ledger_records.append(active_pos.__dict__.copy())
                    active_pos = None
                else:
                    # 正常持有期: 严格逐日盯市 (Mark-to-Market)，严禁每日重复计提 Payoff
                    active_pos.days_held += 1
                    rem_tau = max(1.0 / 252.0, (active_pos.expiry_idx - i) / 252.0)
                    p_iv = self.collar_engine.skew_model.get_iv(
                        active_pos.strike_put, s_curr, rem_tau, iv_atm=iv_curr, beta_skew=skew_curr
                    )
                    c_iv = self.collar_engine.skew_model.get_iv(
                        active_pos.strike_call, s_curr, rem_tau, iv_atm=iv_curr, beta_skew=skew_curr
                    )
                    p_val = Black76Greeks.put_price(s_curr, active_pos.strike_put, rem_tau, self.rf, p_iv)
                    c_val = Black76Greeks.call_price(s_curr, active_pos.strike_call, rem_tau, self.rf, c_iv)
                    v_today = p_val - c_val
                    daily_opt_pnl = active_pos.tons * (v_today - active_pos.current_value)
                    active_pos.current_value = v_today
                    
                    option_pnl_arr[i] += daily_opt_pnl
                    strike_put_arr[i] = active_pos.strike_put
                    strike_call_arr[i] = active_pos.strike_call
                    collar_margin_used[i] = active_pos.tons * active_pos.margin_per_ton
            
            # --- 步骤 3.2: 若处于 TG=0 且无活跃期权持仓，则开仓/展期建仓 ---
            if active_pos is None and tg_curr == 0 and unh_tons_curr > 0:
                col_res = self.collar_engine.compute_adaptive_collar(
                    spot_price=s_curr,
                    iv=iv_curr,
                    skew=skew_curr,
                    tau=tenor_days / 252.0
                )
                exp_idx = i + tenor_days
                exp_date_str = str(dates.iloc[min(exp_idx, n_days - 1)])[:10]
                init_val = col_res.put_premium - col_res.call_premium
                fee_open = unh_tons_curr * (col_res.put_premium + col_res.call_premium) * self.commission_rate
                
                active_pos = OptionPosition(
                    open_idx=i,
                    open_date=dt_curr_str,
                    expiry_idx=exp_idx,
                    expiry_date=exp_date_str,
                    strike_put=col_res.strike_put,
                    strike_call=col_res.strike_call,
                    put_iv=col_res.put_iv,
                    call_iv=col_res.call_iv,
                    premium_put=col_res.put_premium,
                    premium_call=col_res.call_premium,
                    current_value=init_val,
                    tons=unh_tons_curr,
                    margin_per_ton=col_res.margin_requirement,
                    days_held=0,
                    tenor_days=tenor_days
                )
                option_fee_arr[i] += fee_open
                strike_put_arr[i] = col_res.strike_put
                strike_call_arr[i] = col_res.strike_call
                collar_margin_used[i] = unh_tons_curr * col_res.margin_requirement
        
        self.option_ledger = pd.DataFrame(ledger_records)
        res.attrs["option_ledger"] = self.option_ledger
        
        # 4. 完整期货手续费与移仓摩擦
        delta_c = (contracts - contracts.shift(1)).abs()
        delta_c.iloc[0] = contracts.iloc[0]
        fee_trade = delta_c * self.multiplier * p_fut * self.commission_rate
        
        is_roll = self._detect_rollover_days()
        fee_roll = pd.Series(0.0, index=res.index)
        held_on_roll = pd.concat([contracts, contracts.shift(1)], axis=1).min(axis=1).fillna(0)
        fee_roll.loc[is_roll] = (
            2.0 * held_on_roll.loc[is_roll] * self.multiplier * p_fut.loc[is_roll] * self.commission_rate
        )
        
        futures_margin = contracts * self.multiplier * p_fut * self.margin_ratio
        total_margin = futures_margin + collar_margin_used
        capital_cost = total_margin * (self.rf / 250.0)
        
        total_cost = fee_trade + fee_roll + option_fee_arr + capital_cost
        net_pnl = spot_pnl + futures_pnl + option_pnl_arr - total_cost
        
        res["contracts"] = contracts
        res["residual_exposure"] = residual_exposure
        res["spot_pnl"] = spot_pnl
        res["futures_pnl"] = futures_pnl
        res["option_pnl"] = option_pnl_arr
        res["collar_pnl"] = option_pnl_arr
        res["hedge_pnl"] = futures_pnl + option_pnl_arr
        res["fee_trade"] = fee_trade
        res["fee_roll"] = fee_roll
        res["fee_option"] = option_fee_arr
        res["capital_cost"] = capital_cost
        res["cost"] = total_cost
        res["net_pnl"] = net_pnl
        res["total_equity"] = initial_val + net_pnl.cumsum()
        res["net_worth"] = res["total_equity"] / initial_val
        res["hedge_ratio"] = dynamic_h
        res["trend_gate"] = trend_gate
        res["margin_used"] = total_margin
        res["collar_strike_put"] = strike_put_arr
        res["collar_strike_call"] = strike_call_arr
        return res


def compute_performance_metrics(res_dict: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """计算学术级套期保值绩效评估对比矩阵"""
    unhedged_pnl = res_dict["方案A(裸暴露)"]["net_pnl"]
    var_unhedged = np.var(unhedged_pnl)
    
    records = []
    for name, df in res_dict.items():
        net_worth = df["net_worth"]
        net_pnl = df["net_pnl"]
        
        final_nw = net_worth.iloc[-1]
        total_ret_pct = (final_nw - 1.0) * 100.0
        
        # 套保有效性指数 (HE)
        var_hedged = np.var(net_pnl)
        he = 1.0 - (var_hedged / var_unhedged) if var_unhedged > 0 else 0.0
        he_pct = he * 100.0 if "方案A" not in name else 0.0
        
        # 最大回撤
        cummax = net_worth.cummax()
        drawdown = (net_worth - cummax) / cummax
        max_dd_pct = drawdown.min() * 100.0
        
        # 年化波动率
        daily_ret = net_worth.pct_change().dropna()
        ann_vol_pct = daily_ret.std() * np.sqrt(250) * 100.0
        
        # 资金占用 (万元)
        avg_margin_wan = df["margin_used"].mean() / 10000.0
        peak_margin_wan = df["margin_used"].max() / 10000.0
        
        records.append({
            "方案名称": name,
            "最终资产净值": round(final_nw, 4),
            "累计收益率(%)": round(total_ret_pct, 2),
            "套保有效性HE(%)": round(he_pct, 2),
            "最大回撤(%)": round(max_dd_pct, 2),
            "年化波动率(%)": round(ann_vol_pct, 2),
            "平均保证金占用(万元)": round(avg_margin_wan, 2),
            "峰值保证金占用(万元)": round(peak_margin_wan, 2),
        })
        
    return pd.DataFrame(records)
