# -*- coding: utf-8 -*-
"""tests/test_sector_graph_missing_corr.py —— M1 修复回归：缺失相关性证据不得被伪造。

被修复缺陷（``src/graph/sector_graph_engine.get_nale_network_payload``）：
    ``corr = 0.5`` 与 ``stock_corr_with_leader = 0.5`` 作为缺省值，使得
    「无相关性矩阵 / 股票不在矩阵中 / 相关系数为 NaN」时——
      * 任意 peer 都因 ``0.5 >= corr_threshold(0.40)`` 被塞进 co_movement_peers；
      * 龙头相关性永远 ≥ 阈值 ⇒ 只要板块有涨停就必然给出 ``follower_catchup``
        与 0.5%~3.0% 的溢出收益，属于凭空编造的量化结论。
    修复后：缺证据 ⇒ 拒绝该 peer、显式计数，且龙头相关性为 ``None`` 时不得推断追随。

本文件同时守住正向能力：真实相关系数 ≥ 阈值时仍必须正常产出 follower_catchup。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.graph.sector_graph_engine import SectorGraphEngine

STORAGE_STOCKS = [
    {"code": "001309", "name": "德明利", "category": "存储"},
    {"code": "603986", "name": "兆易创新", "category": "存储"},
    {"code": "688525", "name": "佰维存储", "category": "存储"},
]


def _build_engine(corr_threshold: float = 0.40) -> SectorGraphEngine:
    """构造一个真实存在涨停龙头（001309, +9.98%）的存储板块引擎。"""
    rng = np.random.default_rng(42)
    t_len = 60
    base = rng.normal(0.001, 0.02, t_len)

    def to_closes(rets: np.ndarray, final_change_pct: float) -> list[float]:
        closes = [10.0]
        for r in rets[:-1]:
            closes.append(closes[-1] * (1.0 + r))
        closes.append(closes[-1] * (1.0 + final_change_pct / 100.0))
        return closes

    kline_map = {
        "001309": {"kline": [[f"2026-08-{i}", c] for i, c in enumerate(to_closes(base + rng.normal(0, 0.005, t_len), 9.98))]},
        "603986": {"kline": [[f"2026-08-{i}", c] for i, c in enumerate(to_closes(base * 0.9 + rng.normal(0, 0.005, t_len), 3.20))]},
        "688525": {"kline": [[f"2026-08-{i}", c] for i, c in enumerate(to_closes(base * 0.8 + rng.normal(0, 0.008, t_len), 1.50))]},
    }

    engine = SectorGraphEngine(corr_threshold=corr_threshold)
    engine.build_graph(STORAGE_STOCKS, kline_map, lookback_days=60)
    return engine


def test_limit_up_leader_exists_in_fixture() -> None:
    """夹具自证：板块确实处于涨停扩散场景，否则下面的断言无意义。"""
    engine = _build_engine()
    state = engine.sector_states.get("存储")

    assert state is not None
    assert state.has_limit_up is True
    assert state.leader is not None
    assert state.leader["code"] == "001309"


def test_missing_corr_matrix_rejects_all_peers_and_never_follows() -> None:
    """相关性矩阵整体缺失：不得产出任何 peer，也不得判定 follower_catchup。"""
    engine = _build_engine()
    engine.corr_matrix = None

    payload = engine.get_nale_network_payload("603986", "存储")

    assert payload["co_movement_peers"] == []
    assert payload["corr_missing_evidence_count"] == 2
    assert payload["leader_corr_with_stock"] is None
    assert payload["leader_corr_missing"] is True
    assert payload["tier_role"] != "follower_catchup"
    assert payload["spillover_return_5d_pct"] == 0.0
    assert payload["spillover_prob_5d_pct"] == 0.0


def test_nan_corr_rows_are_treated_as_missing_evidence() -> None:
    """矩阵存在但目标股票整行为 NaN：等同缺证据，不得回落 0.5。"""
    engine = _build_engine()
    columns = list(engine.corr_matrix.columns)
    nan_matrix = engine.corr_matrix.copy()
    nan_matrix.loc["603986", :] = np.nan
    nan_matrix.loc[:, "603986"] = np.nan
    engine.corr_matrix = nan_matrix

    payload = engine.get_nale_network_payload("603986", "存储")

    assert payload["co_movement_peers"] == []
    assert payload["corr_missing_evidence_count"] == len(columns) - 1
    assert payload["leader_corr_with_stock"] is None
    assert payload["tier_role"] != "follower_catchup"


def test_unknown_code_absent_from_matrix_is_missing_not_half() -> None:
    """股票不在矩阵索引中：同样按缺证据处理（旧实现会给出 0.5）。"""
    engine = _build_engine()
    engine.corr_matrix = pd.DataFrame(
        np.eye(2),
        index=["001309", "688525"],
        columns=["001309", "688525"],
    )

    payload = engine.get_nale_network_payload("603986", "存储")

    assert payload["co_movement_peers"] == []
    assert payload["corr_missing_evidence_count"] == 2
    assert payload["tier_role"] != "follower_catchup"


def test_negative_corr_is_not_promoted_to_peers() -> None:
    """显式负相关（有证据但不达标）：不计入缺证据计数，也不得成为 peer。"""
    engine = _build_engine()
    engine.corr_matrix = pd.DataFrame(
        [[1.0, -0.62, -0.10], [-0.62, 1.0, 0.05], [-0.10, 0.05, 1.0]],
        index=["001309", "603986", "688525"],
        columns=["001309", "603986", "688525"],
    )

    payload = engine.get_nale_network_payload("603986", "存储")

    assert payload["co_movement_peers"] == []
    assert payload["corr_missing_evidence_count"] == 0
    assert payload["leader_corr_with_stock"] == -0.62
    assert payload["tier_role"] == "divergent"


def test_real_high_corr_still_produces_follower_catchup() -> None:
    """正向能力守卫：真实高相关 + 涨停龙头仍必须产出补涨判定（修复未误伤）。"""
    engine = _build_engine()
    engine.corr_matrix = pd.DataFrame(
        [[1.0, 0.85, 0.11], [0.85, 1.0, 0.11], [0.11, 0.11, 1.0]],
        index=["001309", "603986", "688525"],
        columns=["001309", "603986", "688525"],
    )

    payload = engine.get_nale_network_payload("603986", "存储")

    assert payload["tier_role"] == "follower_catchup"
    assert payload["leader_corr_with_stock"] == 0.85
    assert payload["leader_corr_missing"] is False
    assert payload["corr_missing_evidence_count"] == 0
    assert len(payload["co_movement_peers"]) == 1
    assert payload["co_movement_peers"][0]["code"] == "001309"
    assert payload["co_movement_peers"][0]["corr"] == 0.85
    # 手算：ΔR = clip(9.98 * 0.85 * 0.25, 0.5, 3.0) = clip(2.12075, ...) = 2.12
    assert payload["spillover_return_5d_pct"] == pytest.approx(2.12, abs=1e-9)
    # 手算：ΔProb = clip(10 * 0.85, 5, 12) = 8.5
    assert payload["spillover_prob_5d_pct"] == pytest.approx(8.5, abs=1e-9)


def test_leader_itself_never_receives_spillover() -> None:
    """龙头自身是溢出源：即便相关性矩阵缺失也不得给自己加溢出收益。"""
    engine = _build_engine()
    engine.corr_matrix = None

    payload = engine.get_nale_network_payload("001309", "存储")

    assert payload["tier_role"] == "leader"
    assert payload["spillover_return_5d_pct"] == 0.0
    assert payload["spillover_prob_5d_pct"] == 0.0


def test_unknown_sector_payload_keeps_schema_and_safe_defaults() -> None:
    """未知板块的兜底分支也必须透出同一套字段，且不得暗示存在相关性证据。"""
    engine = _build_engine()

    payload = engine.get_nale_network_payload("603986", "不存在板块")

    assert payload["co_movement_peers"] == []
    assert payload["corr_missing_evidence_count"] == 0
    assert payload["leader_corr_with_stock"] is None
    assert payload["leader_corr_missing"] is True
    assert payload["tier_role"] == "neutral"
    assert payload["spillover_return_5d_pct"] == 0.0


def test_missing_evidence_count_uses_group_members_not_matrix() -> None:
    """计数口径=板块内可比较 peer 数，与矩阵列数无关（防止用矩阵大小伪装证据量）。"""
    engine = _build_engine()
    engine.corr_matrix = pd.DataFrame(
        np.eye(6),
        index=[f"00000{i}" for i in range(1, 7)],
        columns=[f"00000{i}" for i in range(1, 7)],
    )

    payload = engine.get_nale_network_payload("603986", "存储")

    assert payload["corr_missing_evidence_count"] == len(STORAGE_STOCKS) - 1