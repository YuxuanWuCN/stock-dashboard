#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scripts/quick_test_pc5.py - PC5因子快速验证脚本

Week 1 Day 5使用，验证PC5因子是否修好

验证内容:
1. 数值合理性 - 新S₀在[-1,1], 区分度高
2. 时效性 - horizon越大衰减越明显
3. 板块共振 - 涨停日P4>0
4. 与旧S₀对比 - 相关性在0.5-0.8
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.graph.pc5_fusion import PC5Fusion, PC5Extractor

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("quick_test_pc5")


# ========== 测试样本 ==========
SAMPLE_TICKERS = [
    "000001.SZ",  # 平安银行
    "000002.SZ",  # 万科A
    "000333.SZ",  # 美的集团
    "000858.SZ",  # 五粮液
    "002415.SZ",  # 海康威视
    "001309.SZ",  # 德明利
    "600519.SH",  # 贵州茅台
    "600036.SH",  # 招商银行
    "601318.SH",  # 中国平安
    "688981.SH",  # 中芯国际
]

TEST_DATE = "2026-08-01"


# ========== 测试1: 数值合理性 ==========
def test1_numerical_validity(extractor, fusion):
    """测试新S₀的数值合理性"""
    logger.info("\n" + "="*60)
    logger.info("测试1: 数值合理性")
    logger.info("="*60)
    
    results = []
    
    for ticker in SAMPLE_TICKERS[:10]:
        pc5 = extractor.extract(ticker, TEST_DATE)
        s0_new = fusion.fuse(pc5, horizon_days=5.0)
        
        results.append({
            "ticker": ticker,
            "P1": pc5.get("P1", 0.0),
            "P2": pc5.get("P2", 0.0),
            "P3": pc5.get("P3", 0.0),
            "P4": pc5.get("P4", 0.0),
            "P5": pc5.get("P5", 0.0),
            "S0_new": s0_new
        })
        
        logger.info(
            f"  {ticker}: "
            f"P1={pc5['P1']:.3f}, P3={pc5['P3']:.3f}, "
            f"P4={pc5['P4']:.3f}, P5={pc5['P5']:.3f} "
            f"→ S₀={s0_new:.3f}"
        )
    
    df = pd.DataFrame(results)
    
    # 检查1: 所有值在[-1, 1]
    for col in ["P1", "P2", "P3", "P4", "P5", "S0_new"]:
        if col == "P2":
            continue  # P2可能都是0
        assert df[col].between(-1.0, 1.0).all(), f"{col}超出[-1,1]"
    logger.info("  ✅ 所有值在[-1, 1]范围内")
    
    # 检查2: S₀的区分度 (标准差应该>0.1)
    std = df["S0_new"].std()
    logger.info(f"  S₀标准差: {std:.4f}")
    if std < 0.1:
        logger.warning("  ⚠️ 区分度低 (std<0.1)，建议检查权重设置")
    else:
        logger.info("  ✅ 区分度合理")
    
    # 检查3: S₀的均值
    mean = df["S0_new"].mean()
    logger.info(f"  S₀均值: {mean:.4f}")
    if abs(mean) > 0.3:
        logger.warning(f"  ⚠️ 均值接近{mean:.2f}，可能存在系统性偏向")
    
    return df


# ========== 测试2: 时效性 ==========
def test2_temporal_decay(fusion):
    """测试时效衰减机制"""
    logger.info("\n" + "="*60)
    logger.info("测试2: 时效性衰减")
    logger.info("="*60)
    
    # 使用一组固定的PC5向量
    pc5 = {"P1": 0.5, "P2": 0.3, "P3": 0.6, "P4": 0.7, "P5": 0.2}
    
    horizons = [0, 1, 3, 5, 10, 20, 30, 60]
    results = []
    
    for h in horizons:
        s0 = fusion.fuse(pc5, horizon_days=h)
        results.append({"horizon": h, "S0": s0})
        logger.info(f"  horizon={h:2d}d: S₀={s0:.4f}")
    
    # 检查: 随着horizon增大，S₀应该单调递减
    s0_values = [r["S0"] for r in results]
    is_decreasing = all(s0_values[i] >= s0_values[i+1] for i in range(len(s0_values)-1))
    
    if is_decreasing:
        logger.info("  ✅ 时效衰减正确: horizon越大，S₀越小")
    else:
        logger.warning("  ⚠️ 时效衰减不单调，检查半衰期设置")
    
    # 计算衰减率
    decay_rate = s0_values[-1] / s0_values[0] if s0_values[0] != 0 else 0
    logger.info(f"  60天衰减率: {decay_rate:.2%}")
    
    return pd.DataFrame(results)


# ========== 测试3: 板块共振 ==========
def test3_sector_resonance(extractor, fusion):
    """测试板块共振 (P4) 在涨停日的表现"""
    logger.info("\n" + "="*60)
    logger.info("测试3: 板块共振验证")
    logger.info("="*60)
    
    # 存储板块的股票 (假设)
    storage_tickers = [
        "001309.SZ",  # 德明利 (龙头)
        "603986.SH",  # 兆易创新
        "688525.SH",  # 佰维存储
        "600667.SH",  # 太极实业
        "603160.SH",  # 汇顶科技
    ]
    
    # 假设涨停日
    limit_up_date = "2026-08-15"
    normal_date = "2026-08-01"
    
    logger.info("  涨停日对比:")
    for ticker in storage_tickers:
        try:
            pc5_up = extractor.extract(ticker, limit_up_date)
            pc5_normal = extractor.extract(ticker, normal_date)
            
            logger.info(
                f"  {ticker}: P4涨停日={pc5_up['P4']:.3f}, "
                f"P4普通日={pc5_normal['P4']:.3f}, "
                f"差值={pc5_up['P4'] - pc5_normal['P4']:.3f}"
            )
        except Exception as e:
            logger.warning(f"  {ticker} 测试失败: {e}")
    
    logger.info("  ⚠️ 注意: 由于mock数据，P4值可能不准确")
    logger.info("  ⚠️ 需要替换为实际sector_graph_engine调用")


# ========== 测试4: 与旧S₀对比 ==========
def test4_vs_old_s0(extractor, fusion):
    """测试新S₀与旧GFCA composite_score的对比"""
    logger.info("\n" + "="*60)
    logger.info("测试4: 新S₀ vs 旧S₀对比")
    logger.info("="*60)
    
    # 模拟旧S₀ (实际应该从GFCA获取)
    # TODO: 改为从实际GFCA评分读取
    np.random.seed(42)
    old_s0_scores = np.random.uniform(-0.5, 0.5, len(SAMPLE_TICKERS))
    
    new_s0_scores = []
    
    for i, ticker in enumerate(SAMPLE_TICKERS):
        pc5 = extractor.extract(ticker, TEST_DATE)
        s0_new = fusion.fuse(pc5, horizon_days=5.0)
        new_s0_scores.append(s0_new)
        
        diff = s0_new - old_s0_scores[i]
        logger.info(
            f"  {ticker}: 旧S₀={old_s0_scores[i]:.3f}, "
            f"新S₀={s0_new:.3f}, 差值={diff:+.3f}"
        )
    
    # 计算相关性
    old_s0 = old_s0_scores
    new_s0 = np.array(new_s0_scores)
    
    if len(old_s0) > 1 and len(new_s0) > 1:
        correlation = np.corrcoef(old_s0, new_s0)[0, 1]
        logger.info(f"  新旧S₀相关性: {correlation:.3f}")
        
        if 0.3 <= correlation <= 0.9:
            logger.info("  ✅ 相关性合理: 有改进但不是完全不同")
        elif correlation > 0.9:
            logger.warning("  ⚠️ 相关性过高(>0.9)，PC5可能没有实质改进")
        else:
            logger.warning("  ⚠️ 相关性过低(<0.3)，PC5可能改变太大")
    
    # 区分度对比
    old_std = np.std(old_s0)
    new_std = np.std(new_s0)
    logger.info(f"  旧S₀标准差: {old_std:.4f}, 新S₀标准差: {new_std:.4f}")
    
    if new_std > old_std:
        logger.info("  ✅ 新S₀区分度更高")
    else:
        logger.warning("  ⚠️ 新S₀区分度没有提高")


# ========== 主函数 ==========
def main():
    logger.info("="*60)
    logger.info("PC5因子快速验证脚本")
    logger.info("="*60)
    logger.info("")
    
    # 初始化组件
    # TODO: 替换为实际初始化
    class MockCSMAR:
        pass
    
    class MockSectorEngine:
        def get_sector_state_by_ticker(self, ticker, date):
            return {
                "breadth": 0.65,
                "has_limit_up_leader": False,
                "ticker_relative_rank": 0.5
            }
    
    class MockMarketState:
        def get_current_state(self, date):
            return {"phase": "neutral", "c_wave_blocked": False}
    
    # 创建提取器和融合器
    from src.features.csmar_features import CSMARFeatureExtractor
    
    csmar_extractor = CSMARFeatureExtractor(MockCSMAR())
    sector_engine = MockSectorEngine()
    market_state = MockMarketState()
    
    extractor = PC5Extractor(
        csmar_extractor=csmar_extractor,
        sector_engine=sector_engine,
        market_state_engine=market_state,
        llm_sentiment_api=None  # 暂时关闭P2
    )
    
    fusion = PC5Fusion(enable_p2=False)  # 暂时关闭P2
    
    # 运行测试
    test1_numerical_validity(extractor, fusion)
    test2_temporal_decay(fusion)
    test3_sector_resonance(extractor, fusion)
    test4_vs_old_s0(extractor, fusion)
    
    logger.info("\n" + "="*60)
    logger.info("验证完成!")
    logger.info("="*60)
    logger.info("")
    logger.info("请检查以上结果，判断PC5因子是否修好:")
    logger.info("  1. 数值合理性: 新S₀在[-1,1], 区分度>0.1")
    logger.info("  2. 时效性: horizon越大S₀越小")
    logger.info("  3. 板块共振: 涨停日P4>0")
    logger.info("  4. 与旧S₀相关性: 0.3-0.9")
    logger.info("")
    logger.info("如果以上都通过，PC5因子就修好了!")
    logger.info("如果部分不通过，请调整权重或检查代码bug")


if __name__ == "__main__":
    main()
