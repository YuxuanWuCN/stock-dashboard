# -*- coding: utf-8 -*-
"""如何使用PC5Fusion集成到现有系统
"""

# ========== 方法1: 在scoringv3.py中直接替换S₀ ==========
"""
修改位置: src/analysis/scoringv3.py

在GFCAScoringEngine.align_gfca_coordinates()方法中

--- 原来 ---
comp_score = float(np.clip(weighted_sum, -1.0, 1.0))
results[ticker] = GFCACoordinates(
    ticker=ticker,
    coordinates=coords,
    composite_score=comp_score,  # 旧S₀
    raw_loadings=raw_vals
)

--- 改为 ---
comp_score = float(np.clip(weighted_sum, -1.0, 1.0))

# 新增: 计算PC5增强版S₀
pc5_vector = pc5_extractor.extract(ticker, current_date)
s0_enhanced = pc5_fusion.fuse(pc5_vector, horizon_days=5.0)

results[ticker] = GFCACoordinates(
    ticker=ticker,
    coordinates=coords,
    composite_score=s0_enhanced,  # 用新S₀替换
    composite_score_old=comp_score,  # 保留旧S₀用于对比
    pc5_vector=pc5_vector,  # 保存五维向量
    raw_loadings=raw_vals
)
"""


# ========== 方法2: 在build_ranking.py中替换 ==========
"""
修改位置: src/build_ranking.py

在计算NALE payload之前

--- 原来 ---
# 第890行左右
nale_payload = sector_engine.get_nale_network_payload(code, category, final_forecast)
r["nale_network"] = nale_payload

--- 改为 ---

# 初始化PC5组件（在文件顶部或类初始化时）
from src.graph.pc5_fusion import PC5Fusion, PC5Extractor
from src.features.csmar_features import CSMARFeatureExtractor

pc5_fusion = PC5Fusion(enable_p2=False)  # 看情况是否启用P2

# 提取PC5五维向量
pc5_vector = {
    "P1": csmar_extractor.extract_p1_fundamental(code, current_date),
    "P3": csmar_extractor.extract_p3_momentum(code, current_date),
    "P4": extract_p4_sector_resonance(code, current_date, sector_engine),
    "P5": extract_p5_macro_cycle(current_date, market_state_engine)
}

# 融合为增强版S₀
s0_enhanced = pc5_fusion.fuse(pc5_vector, horizon_days=5.0)

# 使用新S₀作为T-NALE的输入
node_scores = {code: s0_enhanced}

# 然后继续原来的NALE网络传导...
nale_payload = sector_engine.get_nale_network_payload(code, category, final_forecast)
r["nale_network"] = nale_payload
r["pc5_vector"] = pc5_vector  # 保存五维向量
r["s0_enhanced"] = s0_enhanced
"""


# ========== 方法3: 单独使用PC5Fusion ==========
"""
# 在任何需要的地方使用

from src.graph.pc5_fusion import PC5Fusion, PC5Extractor

# 1. 创建融合器
fusion = PC5Fusion(
    weights={
        "P1": 0.25,  # 基本面
        "P3": 0.35,  # 动量 (权重加大)
        "P4": 0.30,  # 板块共振
        "P5": 0.10   # 宏观
    },
    half_lives={
        "P1": 90,    # 3个月
        "P3": 10,    # 10天
        "P4": 7,     # 7天
        "P5": 60     # 2个月
    },
    enable_p2=False  # 暂时关闭P2
)

# 2. 融合得分
pc5_vector = {"P1": 0.5, "P3": 0.6, "P4": 0.7, "P5": 0.2}
s0 = fusion.fuse(pc5_vector, horizon_days=5.0)
print(f"增强版S₀: {s0}")

# 3. 查看维度明细
breakdown = fusion.fuse_with_dimension_breakdown(pc5_vector, horizon_days=5.0)
print(f"维度明细: {breakdown}")

# 4. 动态调整权重
fusion.update_weights({"P3": 0.4, "P4": 0.25})  # 加大动量权重
"""

print("集成代码示例已生成，请参考注释修改现有代码")
