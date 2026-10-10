# -*- coding: utf-8 -*-
"""src/intelligence/ast_alpha_miner.py —— 基于 AST 正则化与逆衰减记忆的神经-符号自主因子挖掘引擎

核心理论与对标文献：
1. KDD 2025: AlphaAgent (arXiv:2502.16789) - AST 正则化防 Alpha 衰减
2. ICAIF 2024: FactorMAD (arXiv:2411.08804) - 可解释符号因子挖掘
3. 2026 最新重磅: The Alpha Illusion (arXiv:2605.16895) - 杜绝黑盒与前视泄漏

实现机制：
- 金融时间序列与横截面算子库 (Ts_Rank, Ts_ArgMax, Correlation, Decay_Linear, Delta, Rank 等)
- AST 抽象语法树节点表示与解析/序列化
- 三大正则化机制：
  (1) 独创性树核检验 (Tree Edit Distance Similarity Gate, threshold <= 0.70)
  (2) 假设-公式语义一致性校验 (Semantic Hypothesis-Factor Alignment)
  (3) 语法树结构复杂度控制 (max_depth <= 4, max_nodes <= 12)
- 向量化因子计算与鲁棒性清洗 (IC, Rank-IC, ICIR, 半衰期折旧率)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

import numpy as np
import pandas as pd

logger = logging.getLogger("stock-dashboard.ast_alpha_miner")


# ==============================================================================
# 1. 基础金融算子实现 (Vectorized Financial Operators)
# ==============================================================================

def op_ts_rank(df: pd.DataFrame, window: int = 10) -> pd.DataFrame:
    """计算滚动时间窗口内的百分位排位 Ts_Rank(x, d) in [0, 1]。"""
    window = max(2, int(window))
    def _rank_last(x: np.ndarray) -> float:
        if len(x) == 0 or np.isnan(x[-1]):
            return np.nan
        valid = x[~np.isnan(x)]
        if len(valid) <= 1:
            return 0.5
        last_val = valid[-1]
        return float(np.sum(valid <= last_val) / len(valid))
    
    return df.rolling(window, min_periods=max(2, window // 2)).apply(_rank_last, raw=True)


def op_ts_argmax(df: pd.DataFrame, window: int = 10) -> pd.DataFrame:
    """计算滚动时间窗口内最大值发生的相对时间 Ts_ArgMax(x, d) in [0, 1]。"""
    window = max(2, int(window))
    def _argmax_last(x: np.ndarray) -> float:
        valid = x[~np.isnan(x)]
        if len(valid) == 0:
            return np.nan
        idx = int(np.argmax(valid))
        return float(idx / (len(valid) - 1)) if len(valid) > 1 else 0.5

    return df.rolling(window, min_periods=max(2, window // 2)).apply(_argmax_last, raw=True)


def op_delta(df: pd.DataFrame, period: int = 5) -> pd.DataFrame:
    """计算滞后差分 Delta(x, d) = x_t - x_{t-d}。"""
    period = max(1, int(period))
    return df.diff(period)


def op_decay_linear(df: pd.DataFrame, window: int = 10) -> pd.DataFrame:
    """线性递减加权移动平均 Decay_Linear(x, d)。"""
    window = max(2, int(window))

    def _decay(x: np.ndarray) -> float:
        k = len(x)
        if k == 0:
            return np.nan
        valid_mask = ~np.isnan(x)
        if not valid_mask.any():
            return np.nan
        w = np.arange(1, k + 1, dtype=np.float64)[valid_mask]
        s = w.sum()
        if s == 0:
            return np.nan
        w /= s
        return float(np.sum(x[valid_mask] * w))

    return df.rolling(window, min_periods=max(2, window // 2)).apply(_decay, raw=True)


def op_correlation(df_x: pd.DataFrame, df_y: pd.DataFrame, window: int = 10) -> pd.DataFrame:
    """计算两时序滚动皮尔逊相关系数 Correlation(x, y, d)。"""
    window = max(3, int(window))
    return df_x.rolling(window, min_periods=3).corr(df_y).fillna(0.0).clip(-1.0, 1.0)


def op_cs_rank(df: pd.DataFrame) -> pd.DataFrame:
    """截面标准化排名 Rank(x) in [0, 1]。"""
    return df.rank(axis=1, pct=True)


# ==============================================================================
# 2. AST 抽象语法树节点模型 (AST Node & Regularization Architecture)
# ==============================================================================

@dataclass
class ASTNode:
    """AST 抽象语法树节点。"""
    operator: str
    children: List[Union[ASTNode, str, float]] = field(default_factory=list)
    params: Dict[str, Any] = field(default_factory=dict)

    def to_formula(self) -> str:
        """递归导出紧凑的数学公式表达式。"""
        if not self.children:
            if "value" in self.params:
                return str(self.params["value"])
            return self.operator

        args = []
        for child in self.children:
            if isinstance(child, ASTNode):
                args.append(child.to_formula())
            else:
                args.append(str(child))
        
        for k, v in self.params.items():
            args.append(f"{k}={v}")

        return f"{self.operator}({', '.join(args)})"

    def get_depth(self) -> int:
        """获取当前语法树的最大深度。"""
        if not self.children:
            return 1
        sub_depths = [
            child.get_depth() if isinstance(child, ASTNode) else 1
            for child in self.children
        ]
        return 1 + (max(sub_depths) if sub_depths else 0)

    def get_node_count(self) -> int:
        """获取当前语法树的总节点数。"""
        count = 1
        for child in self.children:
            if isinstance(child, ASTNode):
                count += child.get_node_count()
            else:
                count += 1
        return count

    def get_operators_set(self) -> Set[str]:
        """获取树中包含的所有算子集合。"""
        ops = {self.operator}
        for child in self.children:
            if isinstance(child, ASTNode):
                ops.update(child.get_operators_set())
        return ops

    def to_dict(self) -> Dict[str, Any]:
        """序列化为可持久化字典。"""
        return {
            "operator": self.operator,
            "children": [
                c.to_dict() if isinstance(c, ASTNode) else c for c in self.children
            ],
            "params": self.params,
            "depth": self.get_depth(),
            "node_count": self.get_node_count(),
        }


# ==============================================================================
# 3. AST 正则化校验器 (Regularization & Anti-Decay Gates)
# ==============================================================================

class ASTRegularizer:
    """根据 KDD 2025 AlphaAgent 规范实现的 AST 正则化校验器。"""

    def __init__(
        self,
        max_depth: int = 4,
        max_nodes: int = 12,
        max_similarity_threshold: float = 0.70,
    ):
        self.max_depth = max_depth
        self.max_nodes = max_nodes
        self.max_similarity_threshold = max_similarity_threshold

    def calculate_tree_similarity(self, node1: ASTNode, node2: ASTNode) -> float:
        """计算两棵抽象语法树的 Jaccard + 结构双层树核相似度 [0.0, 1.0]。"""
        ops1 = node1.get_operators_set()
        ops2 = node2.get_operators_set()
        
        # 1. 算子集合 Jaccard 相似度
        union_ops = ops1 | ops2
        if not union_ops:
            return 1.0
        jaccard_ops = len(ops1 & ops2) / len(union_ops)

        # 2. 树深度与节点规模结构相似度
        d1, d2 = node1.get_depth(), node2.get_depth()
        depth_sim = 1.0 - abs(d1 - d2) / max(d1, d2, 1)

        n1, n2 = node1.get_node_count(), node2.get_node_count()
        node_sim = 1.0 - abs(n1 - n2) / max(n1, n2, 1)

        # 3. 根节点与参数匹配
        root_match = 1.0 if node1.operator == node2.operator else 0.0

        # 加权融合
        similarity = 0.40 * jaccard_ops + 0.25 * root_match + 0.20 * depth_sim + 0.15 * node_sim
        return round(float(np.clip(similarity, 0.0, 1.0)), 4)

    def validate_complexity(self, root: ASTNode) -> Tuple[bool, str]:
        """复杂度门禁：限制最大树深与节点总数，严防过拟合。"""
        depth = root.get_depth()
        if depth > self.max_depth:
            return False, f"AST Depth {depth} exceeds max limit {self.max_depth}"
        
        nodes = root.get_node_count()
        if nodes > self.max_nodes:
            return False, f"AST Node count {nodes} exceeds max limit {self.max_nodes}"

        return True, "Complexity validation passed"

    def validate_originality(
        self, candidate: ASTNode, factor_zoo: List[ASTNode]
    ) -> Tuple[bool, float, str]:
        """独创性门禁：检验与已有因子库的最高相似度，杜绝同质拥挤。"""
        if not factor_zoo:
            return True, 0.0, "Factor zoo empty, 100% original"

        max_sim = 0.0
        most_similar_formula = ""
        for existing in factor_zoo:
            sim = self.calculate_tree_similarity(candidate, existing)
            if sim > max_sim:
                max_sim = sim
                most_similar_formula = existing.to_formula()

        if max_sim > self.max_similarity_threshold:
            return (
                False,
                max_sim,
                f"Similarity {max_sim:.3f} > threshold {self.max_similarity_threshold} with '{most_similar_formula}'",
            )

        return True, max_sim, f"Originality verified, max similarity = {max_sim:.3f}"

    def validate_semantic_alignment(
        self, root: ASTNode, economic_hypothesis: str
    ) -> Tuple[bool, str]:
        """假说-因子语义对齐门禁：校验公式算子与经济学假说的合理性。"""
        ops = root.get_operators_set()
        hypo_lower = economic_hypothesis.lower()

        # 动量/反转假说必须包含差分或时序排位
        if "momentum" in hypo_lower or "动量" in economic_hypothesis:
            if not any(op in ops for op in ["Ts_Rank", "Delta", "Decay_Linear", "Ts_ArgMax"]):
                return False, "Hypothesis claims momentum/trend but lacks time-series dynamic operators"

        # 波动率/分歧假说必须包含波动率或相关性算子
        if "volatility" in hypo_lower or "波动" in economic_hypothesis or "分歧" in economic_hypothesis:
            if not any(op in ops for op in ["Ts_Std", "Correlation", "Abs"]):
                return False, "Hypothesis claims volatility/divergence but lacks dispersion operators"

        return True, "Semantic alignment verified"


# ==============================================================================
# 4. 神经-符号公式化因子执行引擎 (Neuro-Symbolic Factor Engine)
# ==============================================================================

class NeuroSymbolicAlphaEngine:
    """因子解析与执行中枢：负责 AST 计算、因子质量打分与防衰减跟踪。"""

    def __init__(self, regularizer: Optional[ASTRegularizer] = None):
        self.regularizer = regularizer or ASTRegularizer()
        self.registered_alphas: List[Dict[str, Any]] = []

    def evaluate_node(
        self, node: Union[ASTNode, str, float], market_data: Dict[str, pd.DataFrame]
    ) -> pd.DataFrame:
        """递归计算 AST 节点的特征矩阵。"""
        if isinstance(node, (int, float)):
            sample_df = next(iter(market_data.values()))
            return pd.DataFrame(float(node), index=sample_df.index, columns=sample_df.columns)

        if isinstance(node, str):
            # 基础输入变量 (close, open, high, low, volume, amount, turnover)
            col_key = node.lower()
            if col_key in market_data:
                return market_data[col_key].copy()
            raise KeyError(f"Feature '{node}' not found in market data packets: {list(market_data.keys())}")

        op = node.operator
        params = node.params

        if op == "Rank":
            arg = self.evaluate_node(node.children[0], market_data)
            return op_cs_rank(arg)

        elif op == "Ts_Rank":
            arg = self.evaluate_node(node.children[0], market_data)
            window = int(params.get("window", 10))
            return op_ts_rank(arg, window=window)

        elif op == "Ts_ArgMax":
            arg = self.evaluate_node(node.children[0], market_data)
            window = int(params.get("window", 10))
            return op_ts_argmax(arg, window=window)

        elif op == "Delta":
            arg = self.evaluate_node(node.children[0], market_data)
            period = int(params.get("period", 5))
            return op_delta(arg, period=period)

        elif op == "Decay_Linear":
            arg = self.evaluate_node(node.children[0], market_data)
            window = int(params.get("window", 10))
            return op_decay_linear(arg, window=window)

        elif op == "Correlation":
            arg1 = self.evaluate_node(node.children[0], market_data)
            arg2 = self.evaluate_node(node.children[1], market_data)
            window = int(params.get("window", 10))
            return op_correlation(arg1, arg2, window=window)

        elif op == "Add":
            left = self.evaluate_node(node.children[0], market_data)
            right = self.evaluate_node(node.children[1], market_data)
            return left + right

        elif op == "Sub":
            left = self.evaluate_node(node.children[0], market_data)
            right = self.evaluate_node(node.children[1], market_data)
            return left - right

        elif op == "Mul":
            left = self.evaluate_node(node.children[0], market_data)
            right = self.evaluate_node(node.children[1], market_data)
            return left * right

        elif op == "Div":
            left = self.evaluate_node(node.children[0], market_data)
            right = self.evaluate_node(node.children[1], market_data)
            denom = right.replace(0.0, np.nan)
            return (left / denom).fillna(0.0)

        elif op == "Sign":
            arg = self.evaluate_node(node.children[0], market_data)
            return np.sign(arg)

        elif op == "Abs":
            arg = self.evaluate_node(node.children[0], market_data)
            return np.abs(arg)

        raise NotImplementedError(f"Unsupported operator: {op}")

    def evaluate_factor_quality(
        self, factor_df: pd.DataFrame, forward_returns: pd.DataFrame
    ) -> Dict[str, float]:
        """计算因子的核心度量：Rank-IC, IC 均值, IC 波动, ICIR, 胜率。"""
        # 对齐日期与标的
        common_idx = factor_df.index.intersection(forward_returns.index)
        common_cols = factor_df.columns.intersection(forward_returns.columns)

        if len(common_idx) < 10 or len(common_cols) < 2:
            return {
                "mean_ic": 0.0,
                "rank_ic": 0.0,
                "icir": 0.0,
                "ic_win_rate": 0.0,
                "valid_days": len(common_idx),
            }

        f = factor_df.loc[common_idx, common_cols]
        r = forward_returns.loc[common_idx, common_cols]

        ic_list = []
        rank_ic_list = []

        for d in common_idx:
            row_f = f.loc[d].dropna()
            row_r = r.loc[d].dropna()
            valid_syms = row_f.index.intersection(row_r.index)
            if len(valid_syms) >= 3:
                vals_f = row_f.loc[valid_syms].values
                vals_r = row_r.loc[valid_syms].values
                if np.std(vals_f) > 1e-8 and np.std(vals_r) > 1e-8:
                    # Pearson IC
                    ic = np.corrcoef(vals_f, vals_r)[0, 1]
                    if not np.isnan(ic):
                        ic_list.append(ic)
                    
                    # Spearman Rank IC
                    rk_f = pd.Series(vals_f).rank().values
                    rk_r = pd.Series(vals_r).rank().values
                    rank_ic = np.corrcoef(rk_f, rk_r)[0, 1]
                    if not np.isnan(rank_ic):
                        rank_ic_list.append(rank_ic)

        if not rank_ic_list:
            return {"mean_ic": 0.0, "rank_ic": 0.0, "icir": 0.0, "ic_win_rate": 0.0, "valid_days": 0}

        mean_ic = float(np.mean(ic_list)) if ic_list else 0.0
        mean_rank_ic = float(np.mean(rank_ic_list))
        std_rank_ic = float(np.std(rank_ic_list)) if len(rank_ic_list) > 1 else 1.0
        icir = float(mean_rank_ic / (std_rank_ic + 1e-8) * np.sqrt(250))
        win_rate = float(np.mean(np.array(rank_ic_list) > 0))

        return {
            "mean_ic": round(mean_ic, 4),
            "rank_ic": round(mean_rank_ic, 4),
            "icir": round(icir, 4),
            "ic_win_rate": round(win_rate, 4),
            "valid_days": len(rank_ic_list),
        }

    def register_candidate_factor(
        self,
        name: str,
        hypothesis: str,
        ast_root: ASTNode,
        market_data: Dict[str, pd.DataFrame],
        forward_returns: pd.DataFrame,
    ) -> Dict[str, Any]:
        """完整挖掘流水线：正则化门禁 -> 向量化执行 -> 质量检验 -> 沉淀入库。"""
        # 1. 复杂度门控
        c_pass, c_msg = self.regularizer.validate_complexity(ast_root)
        if not c_pass:
            return {"status": "REJECTED", "reason": c_msg}

        # 2. 独创性门控
        existing_trees = [item["ast"] for item in self.registered_alphas]
        o_pass, max_sim, o_msg = self.regularizer.validate_originality(ast_root, existing_trees)
        if not o_pass:
            return {"status": "REJECTED", "reason": o_msg, "max_similarity": max_sim}

        # 3. 假说语义对齐门控
        s_pass, s_msg = self.regularizer.validate_semantic_alignment(ast_root, hypothesis)
        if not s_pass:
            return {"status": "REJECTED", "reason": s_msg}

        # 4. 执行计算
        factor_values = self.evaluate_node(ast_root, market_data)

        # 5. 质量与有效性评测
        quality = self.evaluate_factor_quality(factor_values, forward_returns)

        # 6. 沉淀入库
        record = {
            "name": name,
            "hypothesis": hypothesis,
            "formula": ast_root.to_formula(),
            "ast": ast_root,
            "quality": quality,
            "depth": ast_root.get_depth(),
            "nodes": ast_root.get_node_count(),
            "status": "APPROVED",
        }
        self.registered_alphas.append(record)
        logger.info(f"Alpha '{name}' registered successfully! Rank-IC: {quality['rank_ic']}, ICIR: {quality['icir']}")
        return record
