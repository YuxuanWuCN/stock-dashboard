# analysis/similarity.py —— 历史相似走势匹配（KNN）
#
# 核心约束：
# 1. 每个历史时点只能用该时点之前的数据（滚动标准化窗口）
# 2. 当前时点只与过去时点比较
# 3. 样本去重（最小间隔 5 个交易日）
# 4. 样本不足时返回 null 而非伪造成绩
# 5. 仅依赖 numpy，无 sklearn

import logging
from typing import Optional

import numpy as np
import pandas as pd

from .config import (
    FEATURE_NAMES,
    STANDARDIZATION_WINDOW,
    KNN_K,
    KNN_MIN_SAMPLES,
    KNN_MIN_INTERVAL,
    FORECAST_HORIZONS,
    CONFIDENCE_HIGH_SAMPLES,
    CONFIDENCE_LOW_SAMPLES,
)

logger = logging.getLogger("stock-dashboard.similarity")


# ============================================================
# 1. 构建特征矩阵
# ============================================================

def build_raw_features(df: pd.DataFrame) -> tuple[np.ndarray, pd.DatetimeIndex]:
    """
    从指标 DataFrame 中提取原始特征矩阵。
    返回 (features_array, index) —— index 与 df 相同。

    对于不在 FEATURE_NAMES 中的特征（如偏离值），在函数内从已有列派生。
    """
    df = df.copy()

    # 派生特征
    # 偏离 MA
    for ma_col, window in [("ma5", 5), ("ma20", 20), ("ma60", 60)]:
        dev_col = f"deviation_{ma_col}"
        if dev_col in FEATURE_NAMES:
            if ma_col in df.columns:
                df[dev_col] = (df["close"] - df[ma_col]) / df[ma_col].replace(0, np.nan) * 100.0
            else:
                df[dev_col] = np.nan

    # MACD hist 标准化 —— 使用 ATR 作为分母（若可用），否则用收盘价
    if "macd_hist_norm" in FEATURE_NAMES and "macd_hist" in df.columns:
        # 用 ATR 标准化（若 AT 可用），否则用收盘价绝对偏差
        if "atr14" in df.columns:
            # MACD hist 除以 ATR，更稳定
            df["macd_hist_norm"] = df["macd_hist"] / df["atr14"].replace(0, np.nan)
        else:
            close_std = df["close"].rolling(window=20, min_periods=20).std()
            df["macd_hist_norm"] = df["macd_hist"] / close_std.replace(0, np.nan)

    # 确保所有特征列存在，缺失填 NaN
    for feat in FEATURE_NAMES:
        if feat not in df.columns:
            df[feat] = np.nan

    features = df[FEATURE_NAMES].values.astype(np.float64)
    return features, df.index


# ============================================================
# 2. 滚动标准化（核心：不泄露未来数据）
# ============================================================

def rolling_standardize(
    features: np.ndarray,
    window: int = STANDARDIZATION_WINDOW,
) -> np.ndarray:
    """
    对特征矩阵做滚动 z-score 标准化。

    对每个时间 t，使用 [t-window+1, t] 的均值和标准差来标准化第 t 行的特征。
    这也意味着前 window-1 行将无法标准化（全为 NaN）。

    参数:
        features: (n_samples, n_features) 原始特征矩阵
        window: 滚动窗口大小（交易日数）

    返回:
        standardized: 同形状数组，不可标准化的行全为 NaN
    """
    n_samples, n_features = features.shape
    standardized = np.full_like(features, np.nan)

    if n_samples < window:
        return standardized

    # 使用累积和方法高效计算滚动均值和标准差
    # 对每个特征列分别处理
    for j in range(n_features):
        col = features[:, j]
        # 移除 NaN 的影响：将 NaN 视为 0 参与累积和（但后面会用有效计数修正）
        col_filled = np.nan_to_num(col, nan=0.0)
        valid_mask = ~np.isnan(col)

        cumsum = np.cumsum(col_filled)
        cum_count = np.cumsum(valid_mask.astype(float))

        # 滚动窗口内的和与计数
        cumsum_shifted = np.zeros(n_samples)
        cumsum_shifted[window:] = cumsum[:-window]
        cum_count_shifted = np.zeros(n_samples)
        cum_count_shifted[window:] = cum_count[:-window]

        roll_sum = cumsum - cumsum_shifted
        roll_count = cum_count - cum_count_shifted

        # 均值
        roll_mean = np.full(n_samples, np.nan)
        valid = roll_count >= window * 0.8  # 至少 80% 有效数据
        roll_mean[valid & (roll_count > 0)] = (
            roll_sum[valid & (roll_count > 0)] / roll_count[valid & (roll_count > 0)]
        )

        # 标准差
        # 计算平方和
        col_sq = col_filled ** 2
        cumsum_sq = np.cumsum(col_sq)
        cumsum_sq_shifted = np.zeros(n_samples)
        cumsum_sq_shifted[window:] = cumsum_sq[:-window]
        roll_sum_sq = cumsum_sq - cumsum_sq_shifted

        roll_var = np.full(n_samples, np.nan)
        valid_mean = ~np.isnan(roll_mean)
        # var = E[X^2] - E[X]^2
        roll_var[valid_mean] = np.maximum(
            roll_sum_sq[valid_mean] / roll_count[valid_mean] - roll_mean[valid_mean] ** 2,
            0.0
        )
        roll_std = np.sqrt(roll_var)

        # z-score
        zscore_valid = valid_mean & (roll_std > 1e-10) & ~np.isnan(col)
        standardized[zscore_valid, j] = (
            col[zscore_valid] - roll_mean[zscore_valid]
        ) / roll_std[zscore_valid]

    return standardized


# ============================================================
# 3. 寻找相似样本
# ============================================================

def _euclidean_distance(query: np.ndarray, candidates: np.ndarray) -> np.ndarray:
    """计算 query 与所有 candidates 之间的欧几里得距离。"""
    diff = candidates - query
    # 仅使用两者都不为 NaN 的维度
    distances = np.sqrt(np.nansum(diff ** 2, axis=1))
    return distances


def find_similar_samples(
    df: pd.DataFrame,
    horizons: list = None,
    k: int = KNN_K,
    min_samples: int = KNN_MIN_SAMPLES,
    min_interval: int = KNN_MIN_INTERVAL,
    std_window: int = STANDARDIZATION_WINDOW,
    feature_names: list = None,
) -> dict:
    """
    核心入口：为当前时点寻找历史相似走势。

    参数:
        df: 含全部技术指标的 DataFrame（按日期升序）
        horizons: 预测周期列表，默认 [3, 5]
        k: 最近邻数量
        min_samples: 最低有效样本数
        min_interval: 相邻样本最小间隔（交易日）
        std_window: 标准化窗口
        feature_names: 使用的特征列表

    返回:
        {
            "method": "standardized_knn_v1",
            "sample_size": N,
            "minimum_sample_size": min_samples,
            "confidence": "medium",
            "horizon_3d": {
                "up_probability_pct": float,
                "average_return_pct": float,
                "median_return_pct": float,
                "best_return_pct": float,
                "worst_return_pct": float,
            },
            "horizon_5d": {...},
        }

    若样本不足，返回的 horizon 中各统计值为 null。
    """
    if horizons is None:
        horizons = FORECAST_HORIZONS
    if feature_names is None:
        feature_names = FEATURE_NAMES

    n = len(df)

    # 初始化结果
    result = {
        "method": "standardized_knn_v1",
        "sample_size": 0,
        "minimum_sample_size": min_samples,
        "confidence": "low",
    }
    for h in horizons:
        result[f"horizon_{h}d"] = {
            "up_probability_pct": None,
            "average_return_pct": None,
            "median_return_pct": None,
            "best_return_pct": None,
            "worst_return_pct": None,
        }

    # ---- 构建特征矩阵 ----
    raw_features, idx = build_raw_features(df)

    if n < std_window + min_samples:
        logger.warning("数据行数 %d 不足以做相似分析（需至少 %d）", n, std_window + min_samples)
        return result

    # ---- 滚动标准化 ----
    standardized = rolling_standardize(raw_features, window=std_window)

    # 当前时点（最后一行）的标准化特征
    current_vec = standardized[-1]

    # 检查当前特征是否有效（至少有一半特征非 NaN）
    valid_current = ~np.isnan(current_vec)
    if valid_current.sum() < len(feature_names) * 0.5:
        logger.warning("当前时点有效特征 %d/%d 不足，无法做相似分析",
                       valid_current.sum(), len(feature_names))
        return result

    # ---- 候选样本范围 ----
    # 候选范围：已标准化的历史时点，且距离当前至少 min_interval 天
    # 当前时点在 n-1，所以最多用 n-1-min_interval 之前的样本
    candidate_end = n - 1 - min_interval  # 当前点不可作为历史样本

    # 候选起始：第 std_window-1 行（第一个有标准化值的行）
    candidate_start = std_window - 1

    if candidate_start >= candidate_end:
        logger.warning("候选样本范围为空")
        return result

    # ---- 收集候选向量及其前向收益标签 ----
    candidate_vectors = []
    candidate_indices = []
    labels = {h: [] for h in horizons}

    close = df["close"].values

    for i in range(candidate_start, candidate_end):
        vec = standardized[i]
        # 检查特征有效性
        valid = ~np.isnan(vec)
        if valid.sum() < len(feature_names) * 0.5:
            continue

        candidate_vectors.append(vec)
        candidate_indices.append(i)

        # 计算前向收益标签
        for h in horizons:
            future_idx = i + h
            if future_idx < n and close[future_idx] > 0 and close[i] > 0:
                ret = (close[future_idx] - close[i]) / close[i] * 100.0
                labels[h].append(ret)
            else:
                labels[h].append(np.nan)

    if len(candidate_vectors) < min_samples:
        logger.warning("有效候选样本 %d < 最低 %d，样本不足", len(candidate_vectors), min_samples)
        return result

    candidate_vectors = np.array(candidate_vectors)

    # ---- 计算距离 ----
    # 仅使用当前向量非 NaN 的维度
    valid_dims = ~np.isnan(current_vec)
    query_vec = current_vec[valid_dims]
    cand_mat = candidate_vectors[:, valid_dims]

    # 对于候选样本中有 NaN 的行，使用仅有效维度的距离
    distances = np.zeros(len(candidate_vectors))
    for i in range(len(candidate_vectors)):
        row = cand_mat[i]
        valid_in_row = ~np.isnan(row)
        # 使用 query 和 candidate 都有效的维度
        common_valid = valid_dims.copy()
        # 找出两者都有效的维度
        dims_ok = ~np.isnan(row)
        if dims_ok.sum() < len(feature_names) * 0.5:
            distances[i] = np.inf
            continue
        diff = row[dims_ok] - query_vec[dims_ok]
        distances[i] = np.sqrt(np.nansum(diff ** 2) / dims_ok.sum() * len(feature_names))

    # ---- 按距离排序，选择最近邻（带间隔去重） ----
    sort_idx = np.argsort(distances)

    selected = []  # (original_index, distance)
    for si in sort_idx:
        if distances[si] == np.inf:
            break
        if len(selected) >= k:
            break

        cand_row = candidate_indices[si]
        # 检查最小间隔
        too_close = False
        for sel_row, _ in selected:
            if abs(cand_row - sel_row) < min_interval:
                too_close = True
                break

        if not too_close:
            selected.append((cand_row, distances[si]))

    sample_size = len(selected)
    result["sample_size"] = sample_size

    if sample_size < min_samples:
        logger.warning("去重后有效样本 %d < 最低 %d", sample_size, min_samples)
        return result

    # ---- 统计每个 horizon 的收益 ----
    # 建立 index -> label 的映射
    label_map = {h: {ci: lbl for ci, lbl in zip(candidate_indices, labels[h])} for h in horizons}

    for h in horizons:
        returns = [label_map[h].get(ci, np.nan) for ci, _ in selected]
        returns = [r for r in returns if not np.isnan(r)]

        if len(returns) < min_samples:
            continue

        returns_arr = np.array(returns)
        up_count = np.sum(returns_arr > 0)
        up_prob = up_count / len(returns) * 100.0

        result[f"horizon_{h}d"].update({
            "up_probability_pct": round(float(up_prob), 1),
            "average_return_pct": round(float(np.mean(returns_arr)), 2),
            "median_return_pct": round(float(np.median(returns_arr)), 2),
            "best_return_pct": round(float(np.max(returns_arr)), 2),
            "worst_return_pct": round(float(np.min(returns_arr)), 2),
        })

    # ---- 置信等级 ----
    if sample_size >= CONFIDENCE_HIGH_SAMPLES:
        result["confidence"] = "high"
    elif sample_size >= CONFIDENCE_LOW_SAMPLES:
        result["confidence"] = "medium"
    else:
        result["confidence"] = "low"

    logger.info(
        "KNN 相似分析完成: %d 样本, 3d预测 %.2f%%, 5d预测 %.2f%%, 置信度 %s",
        sample_size,
        result["horizon_3d"]["average_return_pct"] or 0,
        result["horizon_5d"]["average_return_pct"] or 0,
        result["confidence"],
    )

    return result
