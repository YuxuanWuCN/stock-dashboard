# -*- coding: utf-8 -*-
"""src/graph/temporal_constants.py —— 产业链物理流转时滞与信息半衰期先验库

理论参考文献：
1. Menzly, L., & Ozbas, O. (2010). Market Segmentation and Cross-Industry Information Diffusion.
   The Journal of Finance, 65(5), 1555-1593.
2. Cohen, L., & Frazzini, A. (2008). Economic Links and Predictable Returns.
   The Journal of Finance, 63(4), 1977-2011.
3. Yılkı, M. (2026). Network-Augmented LLM Embeddings (NALE) in Financial Markets.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class SupplyChainLagConfig:
    """产业链物理库存流转与价格传导时滞配置。"""
    source_category: str
    target_category: str
    tau_days: float          # 冲击波峰抵达典型天数 τ
    sigma_days: float        # 冲击波在时域上的高斯扩散宽度 σ
    attenuation_factor: float = 0.85  # 沿产业链物理损耗与能量衰减系数 [0.0, 1.0]
    rationale: str = ""


@dataclass(frozen=True)
class InformationHalfLifeConfig:
    """不同信息来源的天然有效性半衰期。"""
    source_type: str
    half_life_days: float    # 半衰期天数 H
    decay_rate: float        # 指数衰减率 λ = ln(2) / H
    description: str = ""


# ---------------------------------------------------------------------------
# 1. 信息源时间衰减参数矩阵 (Information Half-Life Priors)
# ---------------------------------------------------------------------------

INFORMATION_HALF_LIVES: Dict[str, InformationHalfLifeConfig] = {
    # 超高频现货、大宗期货、盘口涨停异动：衰减极快，半衰期仅 3 天
    "spot_quote": InformationHalfLifeConfig(
        source_type="spot_quote",
        half_life_days=3.0,
        decay_rate=math.log(2.0) / 3.0,
        description="大宗现货价格异动与高频订单流，时效性极强"
    ),
    "limit_up_impulse": InformationHalfLifeConfig(
        source_type="limit_up_impulse",
        half_life_days=3.0,
        decay_rate=math.log(2.0) / 3.0,
        description="龙头股单日封死涨停板的情绪与身位冲击脉冲"
    ),
    "order_flow": InformationHalfLifeConfig(
        source_type="order_flow",
        half_life_days=5.0,
        decay_rate=math.log(2.0) / 5.0,
        description="大宗交易与机构订单前沿流水"
    ),
    # 卖方深度研报与舆情事件：半衰期中等，约 10 天
    "analyst_report": InformationHalfLifeConfig(
        source_type="analyst_report",
        half_life_days=10.0,
        decay_rate=math.log(2.0) / 10.0,
        description="券商深度行业调研与盈利预测调整"
    ),
    "news_sentiment": InformationHalfLifeConfig(
        source_type="news_sentiment",
        half_life_days=7.0,
        decay_rate=math.log(2.0) / 7.0,
        description="主流财经媒体与行业热点事件舆情"
    ),
    # 政策出台与地缘博弈：半衰期较长，约 20 天
    "policy_event": InformationHalfLifeConfig(
        source_type="policy_event",
        half_life_days=20.0,
        decay_rate=math.log(2.0) / 20.0,
        description="国家产业政策支持、关税壁垒或央行地缘配置"
    ),
    # 定期财报与基本面财报：半衰期最长，约 45 天 (覆盖半个季度)
    "financial_statement": InformationHalfLifeConfig(
        source_type="financial_statement",
        half_life_days=45.0,
        decay_rate=math.log(2.0) / 45.0,
        description="季度报告/年度财务审计数据，构成底层基本面支撑"
    ),
    # 默认兜底半衰期：14 天 (2 周)
    "default": InformationHalfLifeConfig(
        source_type="default",
        half_life_days=14.0,
        decay_rate=math.log(2.0) / 14.0,
        description="通用常规因子与未知类型数据的基准半衰期"
    ),
}


# ---------------------------------------------------------------------------
# 2. 战略产业链物理流转时滞先验矩阵 (Industrial Lead-Lag Priors)
# ---------------------------------------------------------------------------

INDUSTRY_LAG_PRIORS: Dict[Tuple[str, str], SupplyChainLagConfig] = {
    # 半导体存储链：上游海外晶圆/原厂 DRAM/NAND 现货提价 -> 下游模组及封测厂 (德明利/佰维存储/江波龙)
    ("存储原厂", "存储模组"): SupplyChainLagConfig(
        source_category="存储原厂",
        target_category="存储模组",
        tau_days=20.0,
        sigma_days=5.0,
        attenuation_factor=0.88,
        rationale="芯片晶圆进货、贴片封测、成品检验到调价传导周期约 15~25 天"
    ),
    ("存储芯片", "存储模组"): SupplyChainLagConfig(
        source_category="存储芯片",
        target_category="存储模组",
        tau_days=20.0,
        sigma_days=5.0,
        attenuation_factor=0.88,
        rationale="存储颗粒成本向模组出货价格的传导周期"
    ),
    ("半导体设备", "晶圆代工"): SupplyChainLagConfig(
        source_category="半导体设备",
        target_category="晶圆代工",
        tau_days=30.0,
        sigma_days=7.0,
        attenuation_factor=0.80,
        rationale="半导体设备交付、安装调试到晶圆厂产能爬坡周期较长"
    ),

    # 新能源锂电链：上游锂精矿/碳酸锂期货现货 -> 中游正极材料/电解液 -> 下游动力储能电芯 (宁德时代/亿纬锂能)
    ("碳酸锂原料", "锂电正极"): SupplyChainLagConfig(
        source_category="碳酸锂原料",
        target_category="锂电正极",
        tau_days=15.0,
        sigma_days=4.0,
        attenuation_factor=0.85,
        rationale="化工烧结提纯与合同调价窗口约 2 周"
    ),
    ("锂电正极", "动力电池"): SupplyChainLagConfig(
        source_category="锂电正极",
        target_category="动力电池",
        tau_days=25.0,
        sigma_days=6.0,
        attenuation_factor=0.82,
        rationale="电芯卷绕、注液化成、老化测试与装机交付周转"
    ),
    ("碳酸锂原料", "动力电池"): SupplyChainLagConfig(
        source_category="碳酸锂原料",
        target_category="动力电池",
        tau_days=35.0,
        sigma_days=8.0,
        attenuation_factor=0.75,
        rationale="端到端锂精矿至整车动力电池系统总时滞约 5~6 周"
    ),

    # AI 算力与通信链：上游光芯片/DSP -> 中游 800G/1.6T 光模块 (中际旭创/新易盛) -> 下游 AI 服务器 (中科曙光/工业富联)
    ("光通信芯片", "光模块"): SupplyChainLagConfig(
        source_category="光通信芯片",
        target_category="光模块",
        tau_days=18.0,
        sigma_days=4.5,
        attenuation_factor=0.90,
        rationale="EML/VCSEL 芯片封装与高频光电测试流转时滞"
    ),
    ("光模块", "AI服务器"): SupplyChainLagConfig(
        source_category="光模块",
        target_category="AI服务器",
        tau_days=22.0,
        sigma_days=5.5,
        attenuation_factor=0.86,
        rationale="云厂商采购光模块并集成至机柜集群的验收周期"
    ),
    ("光通信芯片", "AI服务器"): SupplyChainLagConfig(
        source_category="光通信芯片",
        target_category="AI服务器",
        tau_days=28.0,
        sigma_days=6.5,
        attenuation_factor=0.80,
        rationale="底层元器件向终极算力整机交付的综合滞后期"
    ),

    # 铜箔基板与电子元器件链：
    ("铜箔原料", "PCB电路板"): SupplyChainLagConfig(
        source_category="铜箔原料",
        target_category="PCB电路板",
        tau_days=14.0,
        sigma_days=4.0,
        attenuation_factor=0.85,
        rationale="覆铜板备货与钻孔压合排产周期"
    ),
}

DEFAULT_LAG_CONFIG = SupplyChainLagConfig(
    source_category="通用上游",
    target_category="通用下游",
    tau_days=14.0,
    sigma_days=5.0,
    attenuation_factor=0.75,
    rationale="产业链通用平均物理库存与订单传导周转期"
)


def get_supply_chain_lag(source_cat: str, target_cat: str) -> SupplyChainLagConfig:
    """根据产业链上下游分类获取先验物理时滞参数。"""
    s = source_cat.strip()
    t = target_cat.strip()
    key = (s, t)
    if key in INDUSTRY_LAG_PRIORS:
        return INDUSTRY_LAG_PRIORS[key]
    # 尝试倒置匹配（若为同一产业链但标签反向）
    rev_key = (t, s)
    if rev_key in INDUSTRY_LAG_PRIORS:
        rev = INDUSTRY_LAG_PRIORS[rev_key]
        return SupplyChainLagConfig(
            source_category=s,
            target_category=t,
            tau_days=rev.tau_days,
            sigma_days=rev.sigma_days,
            attenuation_factor=rev.attenuation_factor * 0.9,
            rationale=f"由反向拓扑引申先验: {rev.rationale}"
        )
    # 核心战略产业链模糊匹配
    if "存储" in s or "存储" in t:
        return INDUSTRY_LAG_PRIORS[("存储原厂", "存储模组")]
    if "锂" in s or "锂" in t or "新能源" in s or "新能源" in t:
        return INDUSTRY_LAG_PRIORS[("碳酸锂原料", "动力电池")]
    if "光模块" in s or "光模块" in t or "算力" in s or "算力" in t or "服务器" in s or "服务器" in t:
        return INDUSTRY_LAG_PRIORS[("光通信芯片", "AI服务器")]
    if "科技" in s or "科技" in t:
        return SupplyChainLagConfig(
            source_category=s,
            target_category=t,
            tau_days=18.0,
            sigma_days=5.0,
            attenuation_factor=0.85,
            rationale="泛科技硬件产业链订单与出货流转时滞"
        )
    return DEFAULT_LAG_CONFIG


def get_half_life(source_type: Optional[str]) -> InformationHalfLifeConfig:
    """根据数据源类型获取信息半衰期先验。"""
    if not source_type:
        return INFORMATION_HALF_LIVES["default"]
    key = source_type.strip().lower()
    return INFORMATION_HALF_LIVES.get(key, INFORMATION_HALF_LIVES["default"])
