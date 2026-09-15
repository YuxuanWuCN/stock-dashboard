# -*- coding: utf-8 -*-
"""src/graph/pca_nale_networks.py —— PIT 可辩护的网络工厂（M3）。

背景与硬约束（逐条来自交接书 F6/F15 与用户裁决 D1–D4）
------------------------------------------------------
1. **F6：网络边证据在本项目里完全不存在。** 旧代码在"缺相关系数"时回落到默认 `0.5`
   （`sector_graph_engine.py`，M1 已修），使"无证据"被当成"强协同"通过阈值。本模块把该原则
   工程化：**任何边都必须有显式证据；重叠样本不足、零方差、NaN 一律拒边并计数**，绝不回落。
2. **W-text（嵌入相似度）不可 as-of。** 768 维静态向量的 `retrieved_at_utc` 全部晚于 2026-09-07，
   且本机无嵌入模型缓存（fastembed 缓存为空、huggingface 缓存无模型），无法离线重建历史向量。
   故本模块把它登记为 :data:`W_TEXT_EMBEDDING_STATUS`（NOT_ASOF）并**拒绝产出**。
   替代物是**真正 PIT 的注意力联动网络**：用逐条 `publish_time` 聚合出的日频对数计数序列做滚动相关。
3. **W-supply 不存在。** 没有任何带 `source_published_at/available_at` 的供应链边账本
   （`SupplyChainGraph()` 实例化为零边），故标 :data:`W_SUPPLY_STATUS`（NOT_EVALUABLE），只作消融。
4. **行归一化必须复用 M1 权威实现**（``src.graph.nale_alpha_adapter.normalize_network``），
   传播必须复用权威核，避免再次出现两套实现漂移。
5. **时间可回放性**：所有网络只用 ``[signal_index - window + 1, signal_index]`` 区间内的信息；
   改动之后的数据不得改变此前任何网络（`tests/test_pca_nale_networks.py` 有往返测试）。

三类可评网络
------------
======  ==========================  ==================  ===================================
代号    构造                         PIT 依据            经济学解释 / 局限
======  ==========================  ==================  ===================================
W-ind   同 ``sub_industry`` 共现     静态结构假设        同行信息外溢；与中性化行业哑变量同源，
                                                           传播项可能被正交化吸收 ⇒ 必须做去共线消融
W-corr  ``basis_return`` 滚动相关   只用已实现收益      收益联动/共同暴露；**不是**供应链证据，
                                                           报告口径必须写"相关网络传播"
W-attn  日频文本对数计数滚动相关    逐条 ``publish_time``  关注度/信息扩散联动；语料覆盖 A∪C 200 支，
                                                           窗口稀疏月份须报覆盖率
======  ==========================  ==================  ===================================

设计约束：纯函数、不写盘、不改入参；权重非负对称、对角为空（孤立点由归一化阶段置自环）；
所有拒绝原因进入 ``diagnostics`` 计数，不做静默丢弃。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.graph.nale_alpha_adapter import normalize_network, propagate_nale_vectorized

__all__ = [
    "ATTENTION_RELATION",
    "CORRELATION_RELATION",
    "DEFAULT_ALPHA",
    "EDGE_EVIDENCE_COLUMNS",
    "INDUSTRY_RELATION",
    "NETWORK_VERSION",
    "NOT_EVALUABLE_NETWORKS",
    "RELATION_SPECS",
    "W_TEXT_EMBEDDING_STATUS",
    "W_SUPPLY_STATUS",
    "NetworkBuild",
    "NetworkConfig",
    "NetworkError",
    "build_network",
    "build_network_suite",
    "edge_evidence_frame",
    "edge_removal_sensitivity",
    "network_diagnostics",
]

#: 网络工厂产物版本。
NETWORK_VERSION = "pca_nale_network_v1"

#: 三类可评关系代号。
INDUSTRY_RELATION = "industry_cooccurrence"
CORRELATION_RELATION = "return_correlation"
ATTENTION_RELATION = "attention_correlation"

#: 缺证据时**禁止**使用的默认相关系数（F6 陷阱的登记值，仅用于文档与测试断言）。
FORBIDDEN_DEFAULT_CORR = 0.5

#: 传播系数默认值（u=0 ⇒ α=0.4）。
DEFAULT_ALPHA = 0.4

#: W-supply 状态。
W_SUPPLY_STATUS = "NOT_EVALUABLE"

#: W-text（嵌入族）状态。
W_TEXT_EMBEDDING_STATUS = "NOT_ASOF"

#: 两条**不得进入真实实验组**的网络及其理由（必须与主结论并列报告）。
NOT_EVALUABLE_NETWORKS: dict[str, str] = {
    "text_embedding_similarity": (
        f"{W_TEXT_EMBEDDING_STATUS}：768 维嵌入的 retrieved_at_utc 全部晚于 2026-09-07，"
        "且本机无嵌入模型缓存，无法离线重建历史向量 ⇒ 对任何早于该日的信号使用它都构成前视。"
        "替代物为 attention_correlation（逐条 publish_time，真 as-of）。"
    ),
    "supply_chain_edges": (
        f"{W_SUPPLY_STATUS}：仓库内不存在带 source_published_at/available_at 的供应链边账本，"
        "SupplyChainGraph() 实例化为零边 ⇒ 只能做消融，不得作为主结论。"
    ),
}

#: 各关系类型的构造说明（经济学解释 + 局限 + PIT 依据），必须随产物一起报告。
RELATION_SPECS: dict[str, dict[str, str]] = {
    INDUSTRY_RELATION: {
        "construction": "同 sub_industry 共现（静态分类）",
        "pit_basis": "静态结构假设（无版本演化证据）",
        "interpretation": "同行信息外溢",
        "limitation": "与截面中性化所用行业哑变量同源，传播项可能被正交化吸收；须做去共线消融",
        "weight_rule": "同行业 = 1，否则 = 0（无权重刻度，故不做阈值筛选）",
    },
    CORRELATION_RELATION: {
        "construction": "截至 t 的过去 window 个交易日 basis_return 的 Pearson 相关",
        "pit_basis": "只用 t 及以前已实现收益",
        "interpretation": "收益联动 / 共同暴露",
        "limitation": "与供应链经济叙事不符，报告口径必须写「相关网络传播」，不得包装成供应链证据",
        "weight_rule": "ρ >= 阈值 时权重 = ρ（截断负相关为 0），否则无边",
    },
    ATTENTION_RELATION: {
        "construction": "截至 t 的过去 window 个交易日文本对数计数的 Pearson 相关",
        "pit_basis": "逐条 publish_time + 可用性滞后（默认次日）",
        "interpretation": "关注度 / 信息扩散联动",
        "limitation": "语料只覆盖 A∪C 200 支（B 组零语料）；稀疏月份须报覆盖率",
        "weight_rule": "ρ >= 阈值 时权重 = ρ（截断负相关为 0），否则无边",
    },
}

#: §3 契约要求的边账本列。
EDGE_EVIDENCE_COLUMNS: tuple[str, ...] = (
    "edge_id",
    "src_code",
    "dst_code",
    "relation_type",
    "source_published_at",
    "available_at",
    "valid_from",
    "valid_to",
    "is_observed",
    "evidence_id",
    "edge_version",
)


class NetworkError(ValueError):
    """网络构造违反 PIT 契约或参数非法（fail-closed）。"""


@dataclass(frozen=True)
class NetworkConfig:
    """网络构造参数（冻结；改动即换版本并重跑全量对比）。

    Attributes
    ----------
    relation_type : str
        :data:`RELATION_SPECS` 中的键。
    window : int
        滚动窗口长度（交易日）；区间为 ``[t-window+1, t]``（含 t）。
    corr_threshold : float
        相关系数阈值（沿用 M1/M3 冻结值 0.40）；低于阈值即无边。
    min_overlap : int
        成对重叠样本下限；不足**拒边**并计数，绝不回落默认值。
    min_abs_weight : float
        权重下限（数值噪声过滤）；低于该值的正权重被剔除。
    weight_power : float
        权重幂变换指数（1.0 表示不变换）。
    """

    relation_type: str = CORRELATION_RELATION
    window: int = 60
    corr_threshold: float = 0.40
    min_overlap: int = 40
    min_abs_weight: float = 1e-12
    weight_power: float = 1.0

    def __post_init__(self) -> None:
        if self.relation_type not in RELATION_SPECS:
            raise NetworkError(
                f"未声明的关系类型 {self.relation_type!r}（含 NOT_EVALUABLE 代号一律拒绝）；"
                f"合法取值：{sorted(RELATION_SPECS)}"
            )
        if int(self.window) < 2:
            raise NetworkError("window 至少为 2")
        if not (-1.0 <= float(self.corr_threshold) <= 1.0):
            raise NetworkError("corr_threshold 必须落在 [-1, 1]")
        if int(self.min_overlap) < 3:
            raise NetworkError("min_overlap 至少为 3（少于 3 个重叠样本不足以谈相关）")
        if int(self.min_overlap) > int(self.window):
            raise NetworkError("min_overlap 不能大于 window")
        if not np.isfinite(float(self.min_abs_weight)) or float(self.min_abs_weight) < 0:
            raise NetworkError("min_abs_weight 必须为非负有限数")
        if not np.isfinite(float(self.weight_power)) or float(self.weight_power) <= 0:
            raise NetworkError("weight_power 必须为正的有限数")

    @property
    def requires_series(self) -> bool:
        """是否依赖时间序列（相关类网络）。"""
        return self.relation_type in (CORRELATION_RELATION, ATTENTION_RELATION)


@dataclass
class NetworkBuild:
    """单次网络构造产物。"""

    relation_type: str
    codes: tuple[str, ...]
    signal_index: int
    signal_date: str
    weights: np.ndarray
    normalized: np.ndarray
    diagnostics: dict[str, Any] = field(default_factory=dict)
    config: NetworkConfig | None = None
    spec: dict[str, str] = field(default_factory=dict)

    def edge_evidence(self, *, calendar: Sequence[str], available_at: str | None = None) -> pd.DataFrame:
        """产出满足 §3 契约的边账本（逐边一行）。"""
        return edge_evidence_frame(self, calendar=calendar, available_at=available_at)


# ---------------------------------------------------------------------------
# 权重构造
# ---------------------------------------------------------------------------

def _validate_codes(codes: Sequence[str]) -> tuple[str, ...]:
    ordered = tuple(str(code).zfill(6) for code in codes)
    if len(ordered) < 2:
        raise NetworkError("研究域至少需要 2 支股票")
    if len(set(ordered)) != len(ordered):
        raise NetworkError("研究域存在重复股票代码")
    for code in ordered:
        if len(code) != 6 or not code.isdigit():
            raise NetworkError(f"非法证券代码：{code!r}")
    return ordered


def _industry_weights(
    codes: tuple[str, ...], industries: Mapping[str, str]
) -> tuple[np.ndarray, int]:
    """同 sub_industry 共现矩阵（对角为空）。缺行业标签即拒边并计数，返回 (权重, 缺标签节点数)。"""
    labels = np.array([industries.get(code) for code in codes], dtype=object)
    missing = np.array([label is None or (isinstance(label, float) and np.isnan(label)) for label in labels])
    size = len(codes)
    weights = np.zeros((size, size), dtype=float)
    for i in range(size):
        if missing[i]:
            continue
        for j in range(i + 1, size):
            if missing[j] or labels[i] != labels[j]:
                continue
            weights[i, j] = weights[j, i] = 1.0
    return weights, int(missing.sum())


def _correlation_weights(
    matrix: np.ndarray,
    config: NetworkConfig,
    counters: dict[str, int],
) -> np.ndarray:
    """成对 Pearson 相关（只用窗口内、且两侧都有效的样本）。

    ``matrix`` 形状为 ``(n_codes, window)``。拒边规则（**绝不回落默认值**）：

    * 成对**联合有效**样本数 < ``min_overlap`` ⇒ 拒边（``pairs_insufficient_overlap``）；
      注意 NaN 表示"该日未观测"，因此 NaN 生效于**重叠计数**：窗口内出现 NaN 会被
      ``pairs_with_nan_in_window`` 记录，只有当有效重叠不足时才导致拒边 ——
      单个 NaN 日不应连带废掉整对样本，否则 A 组预热期的缺失会污染全年网络；
    * 任一侧在重叠区间内方差为 0 ⇒ 拒边（``pairs_zero_variance``）；
    * 相关系数非有限 ⇒ 拒边（``pairs_nonfinite_rho``）；
    * ρ < 阈值 ⇒ 无边（``pairs_below_threshold``）。
    """
    size = matrix.shape[0]
    weights = np.zeros((size, size), dtype=float)
    for i in range(size):
        for j in range(i + 1, size):
            left, right = matrix[i], matrix[j]
            both = np.isfinite(left) & np.isfinite(right)
            overlap = int(both.sum())
            if not (np.isfinite(left).all() and np.isfinite(right).all()):
                counters["pairs_with_nan_in_window"] += 1
            if overlap < int(config.min_overlap):
                counters["pairs_insufficient_overlap"] += 1
                continue
            x, y = left[both], right[both]
            if np.std(x) <= 0 or np.std(y) <= 0:
                counters["pairs_zero_variance"] += 1
                continue
            rho = float(np.corrcoef(x, y)[0, 1])
            if not np.isfinite(rho):
                counters["pairs_nonfinite_rho"] += 1
                continue
            if rho < float(config.corr_threshold):
                counters["pairs_below_threshold"] += 1
                continue
            weights[i, j] = weights[j, i] = rho ** float(config.weight_power)
    return weights


def _window_slice(matrix: np.ndarray, signal_index: int, window: int) -> np.ndarray:
    """取 ``[t-window+1, t]`` 区间（含 t），左端不足时就是全部历史（缺口沿用既有 NaN）。"""
    start = max(0, int(signal_index) - int(window) + 1)
    if signal_index >= matrix.shape[1]:
        raise NetworkError(f"signal_index={signal_index} 超出序列长度 {matrix.shape[1]}")
    return matrix[:, start : int(signal_index) + 1]


def _series_matrix_from_panel(
    series: pd.DataFrame,
    codes: tuple[str, ...],
    calendar: Sequence[str],
    value_column: str,
) -> np.ndarray:
    """把长表（code, trade_date, value）转成 ``(n_codes, n_calendar)`` 矩阵；缺行保持 NaN。"""
    required = {value_column, "stock_code", "trade_date"}
    missing = required - set(series.columns)
    if missing:
        raise NetworkError(f"序列表缺少列：{sorted(missing)}")
    index_of = {date: position for position, date in enumerate(calendar)}
    matrix = np.full((len(codes), len(calendar)), np.nan)
    code_position = {code: position for position, code in enumerate(codes)}
    work = series.loc[:, ["stock_code", "trade_date", value_column]].copy()
    work["stock_code"] = work["stock_code"].astype(str).str.zfill(6)
    work["trade_date"] = work["trade_date"].astype(str)
    unknown = ~work["trade_date"].isin(index_of)
    if bool(unknown.any()):
        bad = work.loc[unknown, "trade_date"].iloc[0]
        raise NetworkError(f"序列表含不在交易日历中的日期：{bad!r}")
    for code, date, value in zip(work["stock_code"], work["trade_date"], work[value_column]):
        position = code_position.get(code)
        if position is None:
            continue
        matrix[position, index_of[date]] = float(value)
    return matrix


def build_network(
    codes: Sequence[str],
    signal_index: int,
    calendar: Sequence[str],
    config: NetworkConfig,
    *,
    industries: Mapping[str, str] | None = None,
    returns: pd.DataFrame | None = None,
    flow: pd.DataFrame | None = None,
    return_column: str = "basis_return",
    flow_column: str = "flow_total_w1",
) -> NetworkBuild:
    """构造 ``signal_index`` 当日的网络（纯函数）。

    Parameters
    ----------
    codes : Sequence[str]
        研究域（顺序即权重矩阵顺序）。
    signal_index : int
        信号日在 ``calendar`` 中的下标（窗口右端**含**该日）。
    calendar : Sequence[str]
        完整交易日历。
    config : NetworkConfig
        参数。
    industries : Mapping[str, str] | None
        行业标签（``industry_cooccurrence`` 必需）。
    returns : pd.DataFrame | None
        统一口径收益长表（``stock_code, trade_date, basis_return``），``return_correlation`` 必需。
    flow : pd.DataFrame | None
        文本流量长表（``stock_code, trade_date, flow_total_w1``），``attention_correlation`` 必需。
    return_column, flow_column : str
        取值列名。

    Returns
    -------
    NetworkBuild
        原始权重、行归一化权重（孤立行自环）、诊断计数（含各类拒边原因）。

    Raises
    ------
    NetworkError
        缺少必需输入、参数非法、研究域非法。
    """
    ordered = _validate_codes(codes)
    calendar = [str(date) for date in calendar]
    if not calendar:
        raise NetworkError("交易日历为空")
    if not (0 <= int(signal_index) < len(calendar)):
        raise NetworkError("signal_index 超出交易日历范围")
    signal_date = calendar[int(signal_index)]
    counters: dict[str, int] = {
        "pairs_total": 0,
        "pairs_below_threshold": 0,
        "pairs_insufficient_overlap": 0,
        "pairs_zero_variance": 0,
        "pairs_nonfinite_rho": 0,
        "pairs_with_nan_in_window": 0,
        "nodes_missing_industry": 0,
        "window_start": None,
        "window_end": signal_date,
        "window_length": 0,
    }
    size = len(ordered)
    counters["pairs_total"] = size * (size - 1) // 2

    if config.relation_type == INDUSTRY_RELATION:
        if industries is None:
            raise NetworkError("industry_cooccurrence 需要 industries 映射（缺行业即拒边）")
        weights, missing_industry = _industry_weights(ordered, industries)
        counters["nodes_missing_industry"] = missing_industry
        counters["pairs_below_threshold"] = 0
        counters["window_length"] = 0
    else:
        if config.requires_series and config.relation_type == CORRELATION_RELATION:
            if returns is None:
                raise NetworkError("return_correlation 需要 returns 长表")
            matrix = _series_matrix_from_panel(returns, ordered, calendar, return_column)
        else:
            if flow is None:
                raise NetworkError("attention_correlation 需要 flow 长表（逐条 publish_time 聚合）")
            matrix = _series_matrix_from_panel(flow, ordered, calendar, flow_column)
        window = _window_slice(matrix, int(signal_index), int(config.window))
        counters["window_length"] = int(window.shape[1])
        counters["window_start"] = calendar[max(0, int(signal_index) - int(config.window) + 1)]
        weights = _correlation_weights(window, config, counters)
        if float(config.min_abs_weight) > 0:
            weights = np.where(weights < float(config.min_abs_weight), 0.0, weights)

    if not np.isfinite(weights).all() or (weights < 0).any():
        raise NetworkError("权重矩阵出现非有限值或负权重")
    if not np.allclose(weights, weights.T):
        raise NetworkError("权重矩阵必须对称")
    if np.any(np.diag(weights) != 0):
        raise NetworkError("权重矩阵对角线必须为空（自环由归一化阶段处理）")

    normalized = normalize_network(weights, size)
    diagnostics = dict(counters)
    diagnostics["n_nodes"] = size
    diagnostics["n_edges"] = int(np.count_nonzero(np.triu(weights, 1)))
    diagnostics["isolated_nodes"] = int((weights.sum(axis=1) == 0).sum())
    diagnostics["relations_per_node"] = float(np.count_nonzero(np.triu(weights, 1)) * 2 / size)
    return NetworkBuild(
        relation_type=config.relation_type,
        codes=ordered,
        signal_index=int(signal_index),
        signal_date=signal_date,
        weights=weights,
        normalized=normalized,
        diagnostics=diagnostics,
        config=config,
        spec=dict(RELATION_SPECS[config.relation_type]),
    )


# ---------------------------------------------------------------------------
# 诊断、账本、敏感性
# ---------------------------------------------------------------------------

def network_diagnostics(build: NetworkBuild) -> dict[str, Any]:
    """覆盖率 / 密度 / 度分布 / 孤立点 / 权重分布（并列报告用）。"""
    weights = build.weights
    size = weights.shape[0]
    degrees = (weights > 0).sum(axis=1)
    upper = weights[np.triu_indices(size, 1)]
    nonzero = upper[upper > 0]
    return {
        "relation_type": build.relation_type,
        "signal_date": build.signal_date,
        "n_nodes": size,
        "n_edges": int(nonzero.size),
        "density": float(nonzero.size / (size * (size - 1) / 2)),
        "nodes_with_edge": int((degrees > 0).sum()),
        "node_coverage": float((degrees > 0).sum() / size),
        "isolated_nodes": int((degrees == 0).sum()),
        "degree_min": int(degrees.min()),
        "degree_median": float(np.median(degrees)),
        "degree_max": int(degrees.max()),
        "weight_min": float(nonzero.min()) if nonzero.size else 0.0,
        "weight_median": float(np.median(nonzero)) if nonzero.size else 0.0,
        "weight_max": float(nonzero.max()) if nonzero.size else 0.0,
        "corr_threshold": float(build.config.corr_threshold) if build.config else None,
        "window": int(build.config.window) if build.config else None,
        "window_length": build.diagnostics.get("window_length"),
        "pairs_insufficient_overlap": build.diagnostics.get("pairs_insufficient_overlap"),
        "pairs_below_threshold": build.diagnostics.get("pairs_below_threshold"),
        "pairs_zero_variance": build.diagnostics.get("pairs_zero_variance"),
        "pairs_nonfinite_rho": build.diagnostics.get("pairs_nonfinite_rho"),
        "pairs_with_nan_in_window": build.diagnostics.get("pairs_with_nan_in_window"),
        "limitation": build.spec.get("limitation", ""),
    }


def edge_evidence_frame(
    build: NetworkBuild,
    *,
    calendar: Sequence[str],
    available_at: str | None = None,
) -> pd.DataFrame:
    """把权重矩阵展开为 §3 契约的边账本。

    * ``is_observed``：相关类网络为 ``True``（由已实现收益/已发布文本算出）；
      行业共现为 ``False``（**静态结构假设**，不是观测到的关系演化）。
    * ``source_published_at``：静态假设写 ``static_assumption``，否则写窗口起点日期
      （证据只能来自该区间）。
    * ``available_at``：缺省取信号日（窗口右端含该日 ⇒ 信号日收盘后即可用）；
      显式传入时校验其不早于 ``valid_from``。
    """
    calendar = [str(date) for date in calendar]
    relation = build.relation_type
    static = relation == INDUSTRY_RELATION
    valid_from = build.diagnostics.get("window_start") or calendar[0]
    if static:
        valid_from = calendar[0]
    valid_to = build.signal_date
    resolved_available = available_at or build.signal_date
    if str(resolved_available) < str(valid_from):
        raise NetworkError("available_at 早于 valid_from：该边在信号日尚且不可用")
    rows: list[dict[str, Any]] = []
    size = build.weights.shape[0]
    for i in range(size):
        for j in range(size):
            if i == j or build.weights[i, j] <= 0:
                continue
            rows.append(
                {
                    "edge_id": f"{relation}:{build.signal_date}:{build.codes[i]}-{build.codes[j]}",
                    "src_code": build.codes[i],
                    "dst_code": build.codes[j],
                    "relation_type": relation,
                    "source_published_at": "static_assumption" if static else str(valid_from),
                    "available_at": str(resolved_available),
                    "valid_from": str(valid_from),
                    "valid_to": str(valid_to),
                    "is_observed": not static,
                    "evidence_id": f"{relation}:{build.codes[i]}-{build.codes[j]}:{valid_from}->{valid_to}",
                    "edge_version": NETWORK_VERSION,
                    "weight": float(build.weights[i, j]),
                    "normalized_weight": float(build.normalized[i, j]),
                }
            )
    frame = pd.DataFrame(rows, columns=[*EDGE_EVIDENCE_COLUMNS, "weight", "normalized_weight"])
    if frame.empty:
        raise NetworkError("该信号日没有任何边：拒绝对空边账本下结论（请报告覆盖率而非产出空结论）")
    return frame


def edge_removal_sensitivity(
    build: NetworkBuild,
    s0: np.ndarray,
    *,
    alpha: float = DEFAULT_ALPHA,
    fractions: Sequence[float] = (0.01, 0.05),
) -> pd.DataFrame:
    """去边敏感性：按权重从大到小移除前 ``fraction`` 比例的边，报告传播输出的变化。

    用**权威传播核**计算基线 ``S = S0 + α·(W_norm·S0 − S0)``；对每个比例，移除全局权重最大的
    若干条边后重新归一化并传播，报告：

    * ``max_abs_delta`` / ``mean_abs_delta``：逐节点 |ΔS| 的最大值与均值；
    * ``nodes_changed``：|ΔS| > 1e-12 的节点数；
    * ``edges_removed``：实际移除的边数。

    Parameters
    ----------
    build : NetworkBuild
        网络构造产物。
    s0 : np.ndarray
        自有得分向量（长度等于研究域）。
    alpha : float
        传播系数，须在 [0, 1]。
    fractions : Sequence[float]
        移除比例序列（(0,1) 开区间）。

    Returns
    -------
    pd.DataFrame
        每个比例一行。
    """
    scores = np.asarray(s0, dtype=float)
    if scores.shape != (build.weights.shape[0],):
        raise NetworkError("s0 长度必须等于研究域节点数")
    if not np.isfinite(scores).all():
        raise NetworkError("s0 必须为有限值")
    fractions = [float(f) for f in fractions]
    if any(not (0.0 < f < 1.0) for f in fractions):
        raise NetworkError("fractions 必须落在 (0, 1) 开区间")

    baseline, _, _ = propagate_nale_vectorized(scores, build.normalized, float(alpha))
    upper_i, upper_j = np.triu_indices(build.weights.shape[0], 1)
    pair_weights = build.weights[upper_i, upper_j]
    positive = pair_weights > 0
    order = np.argsort(-pair_weights[positive])
    positive_index = np.flatnonzero(positive)[order]
    n_edges = int(positive_index.size)
    if n_edges == 0:
        raise NetworkError("该网络没有任何边，无法评估去边敏感性")

    rows: list[dict[str, Any]] = []
    for fraction in fractions:
        remove_count = int(np.floor(fraction * n_edges))
        if remove_count <= 0:
            rows.append(
                {
                    "fraction": fraction,
                    "edges_removed": 0,
                    "max_abs_delta": 0.0,
                    "mean_abs_delta": 0.0,
                    "nodes_changed": 0,
                    "note": "比例过小，未移除任何边（下取整为 0）",
                }
            )
            continue
        pruned = build.weights.copy()
        chosen = positive_index[:remove_count]
        pruned[upper_i[chosen], upper_j[chosen]] = 0.0
        pruned[upper_j[chosen], upper_i[chosen]] = 0.0
        normalized = normalize_network(pruned, pruned.shape[0])
        pruned_scores, _, _ = propagate_nale_vectorized(scores, normalized, float(alpha))
        delta = np.abs(pruned_scores - baseline)
        rows.append(
            {
                "fraction": fraction,
                "edges_removed": remove_count,
                "max_abs_delta": float(delta.max()),
                "mean_abs_delta": float(delta.mean()),
                "nodes_changed": int((delta > 1e-12).sum()),
                "note": "",
            }
        )
    return pd.DataFrame(rows)


def build_network_suite(
    codes: Sequence[str],
    signal_index: int,
    calendar: Sequence[str],
    configs: Mapping[str, NetworkConfig],
    *,
    industries: Mapping[str, str] | None = None,
    returns: pd.DataFrame | None = None,
    flow: pd.DataFrame | None = None,
    s0: np.ndarray | None = None,
    sensitivity_fractions: Sequence[float] = (0.01, 0.05),
) -> dict[str, Any]:
    """并列构造多种网络（主实验必须同时报告 W-text 替代物与 W-ind，不得只报赢家）。

    Returns
    -------
    dict
        ``{"networks": {name: NetworkBuild}, "diagnostics": DataFrame,
        "sensitivity": {name: DataFrame}, "not_evaluable": NOT_EVALUABLE_NETWORKS,
        "relation_specs": RELATION_SPECS}``。
    """
    networks: dict[str, NetworkBuild] = {}
    diagnostics: list[dict[str, Any]] = []
    sensitivity: dict[str, pd.DataFrame] = {}
    for name, config in configs.items():
        build = build_network(
            codes,
            signal_index,
            calendar,
            config,
            industries=industries,
            returns=returns,
            flow=flow,
        )
        networks[name] = build
        diagnostics.append(network_diagnostics(build))
        if s0 is not None:
            sensitivity[name] = edge_removal_sensitivity(
                build, s0, alpha=DEFAULT_ALPHA, fractions=sensitivity_fractions
            )
    return {
        "networks": networks,
        "diagnostics": pd.DataFrame(diagnostics),
        "sensitivity": sensitivity,
        "not_evaluable": dict(NOT_EVALUABLE_NETWORKS),
        "relation_specs": {name: dict(spec) for name, spec in RELATION_SPECS.items()},
    }