# -*- coding: utf-8 -*-
"""src/graph/sector_graph_engine.py —— NALE 网络增强型板块协同与涨停龙头溢出共振引擎 (Spec 015)

职责：
1. 双重拓扑图构建：同板块题材分类 + 近 60 交易日走势相关度 (ρ > 0.40)；
2. 板块协同广度计算 (Sector Breadth = N_up / N_total)；
3. 涨停龙头身位识别 (Limit-Up Leader Detection: 20% 科创/创业板, 10% 主板)；
4. NALE 消息传递与涨停溢出算子：当板块内出现涨停板时，向同盟军注入龙头扩散收益与看涨胜率加成；
5. 板块四级梯队定性划分 (leader / core_mid / follower_catchup / divergent)。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.graph.temporal_constants import get_supply_chain_lag
from src.graph.dynamic_temporal_alpha import compute_temporal_alpha


def is_limit_up(code: str, change_pct: Optional[float]) -> bool:
    """判定是否触及或封死涨停板。"""
    if change_pct is None or not np.isfinite(change_pct):
        return False
    # 科创板 (688) / 创业板 (300/301) 涨跌幅限制为 20%
    if code.startswith(("688", "300", "301")):
        return change_pct >= 19.5
    # 北交所 (43/83/87/92) 涨跌幅限制为 30%
    elif code.startswith(("43", "83", "87", "92", "88")):
        return change_pct >= 29.5
    # 主板 (600/601/603/605/000/001/002/003) 与 ETF 限制为 10%
    else:
        return change_pct >= 9.5


@dataclass
class SectorPeer:
    code: str
    name: str
    corr: float
    role: str
    change_pct: Optional[float] = None
    is_limit_up: bool = False


@dataclass
class SectorGraphState:
    sector_name: str
    total_count: int
    up_count: int
    breadth_pct: float
    avg_change_pct: float
    has_limit_up: bool
    leader: Optional[Dict[str, Any]] = None
    peers: List[SectorPeer] = field(default_factory=list)


class SectorGraphEngine:
    """NALE 板块图谱与涨停龙头溢出计算引擎。"""

    def __init__(self, corr_threshold: float = 0.40):
        self.corr_threshold = corr_threshold
        self.category_groups: Dict[str, List[Dict[str, Any]]] = {}
        self.returns_df: Optional[pd.DataFrame] = None
        self.corr_matrix: Optional[pd.DataFrame] = None
        self.sector_states: Dict[str, SectorGraphState] = {}

    def build_graph(
        self,
        stocks: List[Dict[str, Any]],
        kline_map: Dict[str, Any],
        lookback_days: int = 60
    ) -> None:
        """根据自选池与 K 线数据构建板块网络与相关性矩阵。"""
        self.category_groups.clear()
        
        # 1. 按题材/分类聚合
        for s in stocks:
            cat = s.get("category") or "通用"
            self.category_groups.setdefault(cat, []).append(s)

        # 2. 提取近 60 日收益率序列构建相关性矩阵
        returns_dict = {}
        for s in stocks:
            code = s.get("code")
            k_data = kline_map.get(code)
            if not k_data:
                continue
            
            # 兼容 DataFrame 或 kline dict
            if isinstance(k_data, pd.DataFrame) and "close" in k_data:
                closes = k_data["close"].dropna().values
            elif isinstance(k_data, dict) and "kline" in k_data:
                kline_arr = k_data.get("kline", [])
                closes = [bar[1] for bar in kline_arr if len(bar) >= 2]
            else:
                closes = []

            if len(closes) >= 10:
                ret_series = np.diff(closes[-lookback_days:]) / np.maximum(closes[-lookback_days:-1], 1e-4)
                returns_dict[code] = pd.Series(ret_series)

        if returns_dict:
            self.returns_df = pd.DataFrame(returns_dict)
            self.corr_matrix = self.returns_df.corr(min_periods=10)
        else:
            self.returns_df = pd.DataFrame()
            self.corr_matrix = pd.DataFrame()

        # 3. 计算每个板块的内部广度与龙头身位
        self._analyze_all_sectors(stocks, kline_map)

    def _analyze_all_sectors(
        self,
        stocks: List[Dict[str, Any]],
        kline_map: Dict[str, Any]
    ) -> None:
        """分析所有板块的协同度与龙头。"""
        self.sector_states.clear()

        # 构建最新涨跌幅字典
        latest_changes: Dict[str, float] = {}
        for s in stocks:
            code = s.get("code")
            k_data = kline_map.get(code)
            chg = None
            if isinstance(k_data, pd.DataFrame) and "close" in k_data and len(k_data) >= 2:
                c1, c0 = k_data["close"].iloc[-1], k_data["close"].iloc[-2]
                chg = (c1 - c0) / c0 * 100 if c0 > 0 else 0.0
            elif isinstance(k_data, dict) and "kline" in k_data:
                bars = k_data.get("kline", [])
                if len(bars) >= 2:
                    c1, c0 = bars[-1][1], bars[-2][1]
                    chg = (c1 - c0) / c0 * 100 if c0 > 0 else 0.0
            latest_changes[code] = chg if chg is not None else 0.0

        for cat, group in self.category_groups.items():
            total = len(group)
            if total == 0:
                continue

            up_count = sum(1 for s in group if latest_changes.get(s["code"], 0.0) > 0.0)
            breadth_pct = round(up_count / total * 100.0, 1)
            changes = [latest_changes.get(s["code"], 0.0) for s in group]
            avg_chg = round(float(np.mean(changes)), 2) if changes else 0.0

            # 寻找涨停龙头
            limit_up_stocks = []
            for s in group:
                code = s["code"]
                chg = latest_changes.get(code, 0.0)
                if is_limit_up(code, chg):
                    limit_up_stocks.append({"code": code, "name": s.get("name", code), "change_pct": chg, "is_limit_up": True})

            has_limit_up = len(limit_up_stocks) > 0
            leader = None
            if has_limit_up:
                # 涨幅最高的涨停板为身位龙头
                limit_up_stocks.sort(key=lambda x: x["change_pct"], reverse=True)
                leader = limit_up_stocks[0]
            elif group:
                # 若无涨停，将板块内涨幅最高且 > 4.0% 的设为领涨先锋
                sorted_group = sorted(group, key=lambda s: latest_changes.get(s["code"], 0.0), reverse=True)
                top = sorted_group[0]
                top_chg = latest_changes.get(top["code"], 0.0)
                if top_chg >= 4.0:
                    leader = {"code": top["code"], "name": top.get("name", top["code"]), "change_pct": top_chg, "is_limit_up": False}

            self.sector_states[cat] = SectorGraphState(
                sector_name=cat,
                total_count=total,
                up_count=up_count,
                breadth_pct=breadth_pct,
                avg_change_pct=avg_chg,
                has_limit_up=has_limit_up,
                leader=leader,
                peers=[]
            )

    def get_nale_network_payload(
        self,
        stock_code: str,
        category: str,
        single_forecast: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """为单只股票生成 NALE 网络增强结构体。"""
        sector_state = self.sector_states.get(category)
        if not sector_state:
            return {
                "sector_name": category or "通用",
                "sector_breadth_pct": 50.0,
                "tier_role": "neutral",
                "leader_stock": None,
                "spillover_return_5d_pct": 0.0,
                "spillover_prob_5d_pct": 0.0,
                "has_limit_up_resonance": False,
                "co_movement_peers": []
            }

        # 提取同板块盟友及相关系数
        peers = []
        group = self.category_groups.get(category, [])
        leader = sector_state.leader

        stock_corr_with_leader = 0.5
        for s in group:
            peer_code = s.get("code")
            if peer_code == stock_code:
                continue
            
            corr = 0.5
            if self.corr_matrix is not None and stock_code in self.corr_matrix.columns and peer_code in self.corr_matrix.columns:
                val = self.corr_matrix.loc[stock_code, peer_code]
                if np.isfinite(val):
                    corr = round(float(val), 2)
            
            if corr >= self.corr_threshold:
                peers.append({
                    "code": peer_code,
                    "name": s.get("name", peer_code),
                    "corr": corr
                })

            if leader and peer_code == leader["code"]:
                stock_corr_with_leader = corr

        # 判定梯队角色与溢出增量
        is_curr_leader = bool(leader and leader["code"] == stock_code)
        has_limit_up = sector_state.has_limit_up

        spillover_ret = 0.0
        spillover_prob = 0.0
        role = "core_mid"

        if is_curr_leader:
            role = "leader"
            spillover_ret = 0.0  # 龙头自身是溢出源
            spillover_prob = 0.0
        elif has_limit_up and leader:
            # 龙头涨停触发强力扩散机制
            if stock_corr_with_leader >= self.corr_threshold:
                role = "follower_catchup"
                leader_ret = leader.get("change_pct", 10.0)
                # ΔR = clamp(LeaderRet * corr * 0.25, +0.5%, +3.0%)
                spillover_ret = round(float(np.clip(leader_ret * stock_corr_with_leader * 0.25, 0.5, 3.0)), 2)
                # ΔProb = clamp(10.0 * corr, +5.0%, +12.0%)
                spillover_prob = round(float(np.clip(10.0 * stock_corr_with_leader, 5.0, 12.0)), 1)
            else:
                role = "divergent"
        else:
            # 无涨停时的常态
            if sector_state.breadth_pct >= 75.0:
                role = "core_mid"
                spillover_ret = 0.3
                spillover_prob = 2.0
            else:
                role = "neutral"

        # 产业链物理流转时滞与波峰共振计算 (T-NALE 时空扩展与方案 B 动态 alpha)
        lag_cfg = get_supply_chain_lag(category, category)
        tau_days = float(lag_cfg.tau_days)
        sigma_days = float(lag_cfg.sigma_days)
        peak_horizon = round(tau_days)
        peak_impulse = round(float(spillover_ret * lag_cfg.attenuation_factor * 1.15), 2) if spillover_ret > 0 else 0.0

        # 计算时效性双波峰动态 alpha 权重
        alpha_t0 = compute_temporal_alpha(t=0.0, tau=tau_days, sigma=sigma_days, has_event=has_limit_up)
        alpha_peak = compute_temporal_alpha(t=tau_days, tau=tau_days, sigma=sigma_days, has_event=has_limit_up)

        temporal_dynamics = {
            "physical_lag_tau_days": tau_days,
            "physical_lag_sigma_days": sigma_days,
            "peak_horizon_days": peak_horizon,
            "peak_spillover_return_pct": peak_impulse,
            "optimal_holding_days": peak_horizon if role == "follower_catchup" else 5.0,
            "is_temporal_enhanced": True,
            "dynamic_alpha_sentiment_t0": round(alpha_t0, 3),
            "dynamic_alpha_physical_peak": round(alpha_peak, 3),
        }

        return {
            "sector_name": category,
            "sector_breadth_pct": sector_state.breadth_pct,
            "tier_role": role,
            "leader_stock": leader,
            "spillover_return_5d_pct": spillover_ret,
            "spillover_prob_5d_pct": spillover_prob,
            "has_limit_up_resonance": has_limit_up,
            "co_movement_peers": sorted(peers, key=lambda x: x["corr"], reverse=True)[:5],
            "temporal_dynamics": temporal_dynamics
        }
