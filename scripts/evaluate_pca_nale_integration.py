# -*- coding: utf-8 -*-
"""scripts/evaluate_pca_nale_integration.py —— PCA→NALE 走步评测 CLI（M4）。

只读消费 M2（as-of 面板）与 M3（网络工厂），把**同一份数据、同一切分、同一标签**下的
若干传播变体并列评测，并把所有产物隔离到带 ``run_id`` 的目录里（修 M1.4 的
``ashare_pca_backtest/`` 就地覆盖缺陷）。

必须遵守的纪律（逐条对应交接书 §3/§7、F3、F7、F10 与用户裁决 D1–D4）
--------------------------------------------------------------------
1. **run_id 强制**：``--run-id`` 必填且匹配 ``[A-Za-z0-9._-]+``；任一目标目录已存在即**拒绝运行**
   （绝不就地覆盖）。没有 run_id 的目录一个字节都不写。
2. **口径复核点时必须冻结**：``compute_return_basis`` 的 ``verification`` 只用**首个信号日之前**的
   数据算（:func:`frozen_verification`），冻结日写进 manifest。全样本 ``verify_caliber`` 属前视通道，
   禁止进入任何产物（有测试守卫）。
3. **同数据同切分**：所有变体共用同一批信号日、同一批股票、同一标签列。
4. **缺证据不回落**：网络由 M3 构造（缺相关即拒边），传播只用 M1 权威核；W-text（嵌入）与 W-supply
   两条 **NOT_EVALUABLE** 网络必须与主结论并列出现在报告与 manifest 中。
5. **统计**：日截面 Pearson IC / Spearman Rank IC，单日有效股票数 < ``min_stocks_per_day``（默认 20）
   记缺失并计数；ICIR **不年化**；配对区块 bootstrap（seed 42、次数可配，区块长度以**交易日**计并按
   信号步长换算为信号日块，另报区块长度敏感性）；跨变体 Holm 校正。
6. **组合口径显式计费**：0 成本作对照、主结论双边 ``--cost-bps``（默认 15）；换手按腿内名单更替比例
   估计并逐期扣费；重叠持有期收益**禁止**逐年化（只报每期均值/标准差/t 与 bootstrap 区间，
   任何字段名都不得含 "annual"）。
7. **动态门控按网络分别拟合**（V1/V2/V3 复用 `src/pricing/nale_alpha_models.py`），训练段只用
   **标签已成熟**且早于应用期的信号日；``gate_min_train_dates`` 因样本长度远小于 Week1 默认 126，
   属**降级设置**，写入 manifest 与报告。
8. **manifest 钉死输入**：输入文件 SHA256、语料清单哈希、版本字符串、冻结日、参数一起落盘。

用法示例
--------
``python scripts/evaluate_pca_nale_integration.py --run-id m4-smoke-20260914 --domain A --max-signal-dates 6``
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.special import erf

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.audit_return_basis import build_declarations  # noqa: E402
from src.data.pca_nale_asof_panel import (  # noqa: E402
    ASOF_PANEL_VERSION,
    NEUTRALIZATION_VERSION,
    PCA_VERSION,
    S0_PC5_PRIOR_VERSION,
    S0_VERSION,
    AsofPanelConfig,
    build_asof_panel,
    load_corpus_records,
    text_flow_features,
    trading_calendar_from_panel,
)
from src.data.return_basis import (  # noqa: E402
    CALIBER_WATERMARK,
    compute_return_basis,
    verify_caliber,
)
from src.graph.nale_alpha_adapter import normalize_network, propagate_nale_vectorized  # noqa: E402
from src.graph.pca_nale_networks import (  # noqa: E402
    ATTENTION_RELATION,
    CORRELATION_RELATION,
    INDUSTRY_RELATION,
    NETWORK_VERSION,
    NOT_EVALUABLE_NETWORKS,
    RELATION_SPECS,
    NetworkConfig,
    NetworkError,
    build_network,
    edge_evidence_frame,
    network_diagnostics,
)
from src.pricing.nale_alpha_models import TrainingPanel, fit_gate  # noqa: E402

#: 评测产物版本。
EVAL_VERSION = "pca_nale_integration_eval_v1"

# 主实验范围的冻结裁定。C 组静态 768 维向量的输入语料无法与其 provenance
# 对齐，不能作为 PCA/NALE 主结论输入；见 C_PROVENANCE_INVALIDATION.md。
PRIMARY_EXPERIMENT_POLICY: dict[str, Any] = {
    "primary_domain": "A",
    "student_A": "可复现主实验：真实 CSMAR 日频面板与已核验输入。",
    "student_B": "不纳入本 PCA/NALE 主实验；不得与 A 组技术特征拼接为统一截面。",
    "student_C_static_768d": "INVALIDATED：原始语料与 provenance 不完整，禁止用于主结论、IC、回测或夏普。",
    "student_C_retained": [
        "CSMAR 日频行情面板（收益/网络类研究可用）",
        "带 publish_time 的逐条文本（仅可作为新的 text_flow_v1 探索，不能称为静态 768 维向量复现）",
    ],
    "invalidation_notice": "reports/tables/pca_nale_integration/C_PROVENANCE_INVALIDATION.md",
}

#: 三类产物的根目录（都必须在 run_id 之下一层）。
OUTPUT_ROOTS: dict[str, str] = {
    "processed": "data/processed/pca_nale_integration",
    "tables": "reports/tables/pca_nale_integration",
    "figures": "reports/figures/pca_nale_integration",
}

DEFAULT_PANEL = ROOT / "data/task_split/csmar_master/csmar_factor_panel_master.csv"
DEFAULT_FACTORS = ROOT / "data/task_split/factors_768d_all.csv"
DEFAULT_UNIVERSE = ROOT / "data/task_split/universe_300_assigned.csv"
DEFAULT_CALIBER = ROOT / "config/data_caliber/csmar_master_close_basis.json"
DEFAULT_CORPUS = ROOT / "data/raw/student_ac_crawled"

TECHNICAL_FEATURES: tuple[str, ...] = (
    "mom_5d", "mom_20d", "mom_60d", "vol_20d", "vol_60d", "turnover_20d",
    "amihud", "price_pos", "amplitude", "gap", "hit_limit", "abnormal_trd",
)

#: 默认网络配置（主实验：W-attn 与 W-ind 并列，W-corr 对照）。
DEFAULT_NETWORK_CONFIGS: dict[str, NetworkConfig] = {
    "W-ind": NetworkConfig(relation_type=INDUSTRY_RELATION),
    "W-corr": NetworkConfig(relation_type=CORRELATION_RELATION, window=60, corr_threshold=0.40, min_overlap=40),
    "W-attn": NetworkConfig(relation_type=ATTENTION_RELATION, window=60, corr_threshold=0.40, min_overlap=40),
}

DEFAULT_ALPHA_GRID: tuple[float, ...] = (0.05, 0.20, 0.40, 0.60, 0.75)
DEFAULT_B0_ALPHA = 0.4
DEFAULT_COST_BPS = 15.0
MIN_STOCKS_PER_DAY = 20
MIN_LEG = 10
DEFAULT_BOOTSTRAP_REPS = 2000
DEFAULT_BLOCK_TRADING_DAYS: tuple[int, ...] = (10, 40)
BLOCK_SENSITIVITY_TRADING_DAYS: tuple[int, ...] = (5, 20)
DEFAULT_SEED = 42
DEFAULT_SIGNAL_STEP = 5
DEFAULT_START_INDEX = 180
DEFAULT_FIRST_APPLY_INDEX = 300
DEFAULT_GATE_MIN_TRAIN_DATES = 20
DEFAULT_GATE_RIDGE_LAMBDA = 1.0
DEFAULT_HALF_LIFE_DAYS = 20.0

#: 禁止出现在产物字段名里的字眼（重叠持有期不得逐年化，修 F3）。
FORBIDDEN_FIELD_TOKENS: tuple[str, ...] = ("annual", "annualized")

RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]+")


class EvaluationError(ValueError):
    """评测输入或纪律被违反（fail-closed）。"""


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

def sha256_of(path: str | Path) -> str:
    """流式 SHA256（大文件友好）。"""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            block = handle.read(1 << 20)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def directory_inventory_sha256(directory: str | Path) -> str | None:
    """目录清单哈希（文件名+字节数排序后拼接），钉死语料集合而不必读全量内容。"""
    target = Path(directory)
    if not target.is_dir():
        return None
    entries = sorted(f"{path.name}:{path.stat().st_size}" for path in target.rglob("*") if path.is_file())
    return hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest()


def guard_field_names(columns: Sequence[str]) -> None:
    """守卫：产物字段名不得含年化字样（重叠持有期禁止逐年化）。"""
    bad = [name for name in columns if any(token in str(name).lower() for token in FORBIDDEN_FIELD_TOKENS)]
    if bad:
        raise EvaluationError(f"字段名含年化字样，违反 F3 纪律：{bad}")


def validate_run_id(run_id: str) -> str:
    """校验 run_id 并返回（必须是单层安全目录名）。"""
    text = str(run_id or "").strip()
    if not text:
        raise EvaluationError("必须显式提供 --run-id（禁止写无 run_id 的目录）")
    if not RUN_ID_PATTERN.fullmatch(text) or text in (".", ".."):
        raise EvaluationError(f"run_id 只允许字母数字与 . _ -：{text!r}")
    return text


def resolve_output_dirs(run_id: str, root: Path = ROOT) -> dict[str, Path]:
    """返回三个隔离产物目录；任一已存在即拒绝覆盖。"""
    dirs = {name: Path(root) / relative / validate_run_id(run_id) for name, relative in OUTPUT_ROOTS.items()}
    existing = [str(path) for path in dirs.values() if path.exists()]
    if existing:
        raise EvaluationError(f"产物目录已存在，拒绝就地覆盖：{existing}")
    return dirs


def frozen_verification(
    panel: pd.DataFrame,
    declarations: pd.DataFrame,
    freeze_date: str,
) -> pd.DataFrame:
    """只用 ``trade_date <= freeze_date`` 的数据算口径复核结论（点时必须冻结）。"""
    subset = panel[panel["trade_date"].astype(str) <= str(freeze_date)]
    if subset.empty:
        raise EvaluationError(f"冻结日 {freeze_date} 之前没有任何数据，无法冻结口径复核")
    verification = verify_caliber(subset, declarations)
    verification["verification_window_end"] = str(freeze_date)
    return verification


# ---------------------------------------------------------------------------
# 统计原语（纯函数、可手算）
# ---------------------------------------------------------------------------

def cross_sectional_ic(
    scores: pd.Series,
    labels: pd.Series,
    *,
    min_stocks: int = MIN_STOCKS_PER_DAY,
) -> dict[str, Any]:
    """单日截面 IC：Pearson 与 Spearman；有效股票数不足则记缺失。"""
    frame = pd.DataFrame({"score": scores, "label": labels}).dropna()
    frame = frame[np.isfinite(frame["score"]) & np.isfinite(frame["label"])]
    n_stocks = int(len(frame))
    if n_stocks < int(min_stocks):
        return {"pearson": np.nan, "spearman": np.nan, "n_stocks": n_stocks, "excluded": True}
    pearson = float(frame["score"].corr(frame["label"]))
    spearman = float(frame["score"].corr(frame["label"], method="spearman"))
    return {"pearson": pearson, "spearman": spearman, "n_stocks": n_stocks, "excluded": False}


def ic_summary(values: Sequence[float]) -> dict[str, float]:
    """IC 汇总：均值/标准差/ICIR（**不年化**）/t 值/有效天数。"""
    series = pd.Series(list(values), dtype=float).dropna()
    n_days = int(len(series))
    if n_days == 0:
        return {"n_days": 0, "mean_ic": np.nan, "std_ic": np.nan, "icir": np.nan, "t_stat": np.nan}
    mean = float(series.mean())
    std = float(series.std(ddof=1)) if n_days > 1 else 0.0
    icir = mean / std if std > 0 else np.nan
    t_stat = mean / (std / np.sqrt(n_days)) if std > 0 and n_days > 1 else np.nan
    return {"n_days": n_days, "mean_ic": mean, "std_ic": std, "icir": icir, "t_stat": t_stat}


def block_bootstrap_interval(
    values: Sequence[float],
    *,
    block_length: int,
    reps: int = DEFAULT_BOOTSTRAP_REPS,
    seed: int = DEFAULT_SEED,
    confidence: float = 0.95,
) -> dict[str, float]:
    """配对区块 bootstrap：对按时间排序的序列做**连续区块**重采样。

    ``block_length`` 以信号日为单位（调用方用 :func:`trading_days_to_signal_blocks` 换算）。
    """
    series = np.asarray([value for value in values if np.isfinite(value)], dtype=float)
    if series.size == 0:
        raise EvaluationError("bootstrap 输入为空")
    if int(block_length) < 1:
        raise EvaluationError("block_length 至少为 1")
    if int(reps) < 1:
        raise EvaluationError("bootstrap 次数至少为 1")
    if not (0.0 < float(confidence) < 1.0):
        raise EvaluationError("confidence 必须落在 (0, 1)")
    block = min(int(block_length), series.size)
    n_blocks = int(np.ceil(series.size / block))
    rng = np.random.default_rng(int(seed))
    starts = rng.integers(0, series.size, size=(int(reps), n_blocks))
    offsets = np.arange(block)[None, :]
    sample = np.empty((int(reps), n_blocks * block), dtype=float)
    for column in range(n_blocks):
        indices = (starts[:, column][:, None] + offsets) % series.size
        sample[:, column * block : (column + 1) * block] = series[indices]
    means = sample.mean(axis=1)
    tail = (1.0 - float(confidence)) / 2.0
    return {
        "point_mean": float(series.mean()),
        "ci_low": float(np.quantile(means, tail)),
        "ci_high": float(np.quantile(means, 1.0 - tail)),
        "bootstrap_std": float(means.std(ddof=1)),
        "n_observations": int(series.size),
        "block_length_signal_dates": int(block),
        "reps": int(reps),
        "seed": int(seed),
    }


def holm_adjust(pvalues: Sequence[float]) -> list[float]:
    """Holm–Bonferroni 逐步向下校正（保持与输入顺序对应）。"""
    values = np.asarray([np.nan if value is None else float(value) for value in pvalues], dtype=float)
    adjusted = np.full(values.shape, np.nan)
    valid = np.flatnonzero(np.isfinite(values))
    if valid.size == 0:
        return adjusted.tolist()
    order = valid[np.argsort(values[valid], kind="stable")]
    total = order.size
    running = 0.0
    for rank, index in enumerate(order):
        running = max(running, (total - rank) * values[index])
        adjusted[index] = min(1.0, running)
    return adjusted.tolist()


def normal_two_sided_p(t_stat: float) -> float:
    """正态近似的双侧 p 值（日截面 IC 序列、大样本）。"""
    if not np.isfinite(t_stat):
        return float("nan")
    return float(2.0 * (1.0 - 0.5 * (1.0 + erf(abs(float(t_stat)) / np.sqrt(2.0)))))


def trading_days_to_signal_blocks(trading_days: int, step: int) -> int:
    """把以交易日计的区块长度换算为信号日块数（向上取整，至少 1）。"""
    if int(step) < 1:
        raise EvaluationError("signal step 至少为 1")
    return max(1, int(np.ceil(int(trading_days) / int(step))))


def leg_turnover(previous: Sequence[str], current: Sequence[str]) -> float:
    """腿内换手：名单更替比例（0 = 完全不变，1 = 全部换掉）。"""
    previous_set, current_set = set(previous), set(current)
    if not current_set:
        return 0.0
    if not previous_set:
        return 1.0
    return float(len(current_set - previous_set) / len(current_set))


def long_short_period_returns(
    frame: pd.DataFrame,
    *,
    score_column: str,
    label_column: str,
    cost_bps: float,
    min_leg: int = MIN_LEG,
    quantile: float = 0.2,
) -> pd.DataFrame:
    """逐信号日多空组合（含显式计费与换手）。

    * 多头 = 得分最高一档、空头 = 最低一档；档位 ``max(min_leg, ceil(quantile × 有效股票数))``；
    * 换手 = 多头与空头名单更替比例的均值；成本 = 换手 × 双边 ``cost_bps``；
    * **不做**任何年化，只给每期（h 交易日持有期）收益。
    """
    if not (0.0 < float(quantile) < 0.5):
        raise EvaluationError("quantile 必须落在 (0, 0.5)")
    rows: list[dict[str, Any]] = []
    previous_long: list[str] = []
    previous_short: list[str] = []
    for signal_date, group in frame.groupby("signal_date", sort=True):
        usable = group.dropna(subset=[score_column, label_column])
        usable = usable[np.isfinite(usable[score_column]) & np.isfinite(usable[label_column])]
        n_stocks = int(len(usable))
        if n_stocks < 2 * int(min_leg):
            rows.append(
                {
                    "signal_date": signal_date,
                    "n_stocks": n_stocks,
                    "excluded": True,
                    "long_mean": np.nan,
                    "short_mean": np.nan,
                    "gross_return": np.nan,
                    "turnover": np.nan,
                    "net_return": np.nan,
                }
            )
            continue
        size = max(int(min_leg), int(np.ceil(float(quantile) * n_stocks)))
        ordered = usable.sort_values(score_column, ascending=False, kind="stable")
        long_leg, short_leg = ordered.head(size), ordered.tail(size)
        long_names = long_leg["stock_code"].astype(str).tolist()
        short_names = short_leg["stock_code"].astype(str).tolist()
        turnover = 0.5 * (leg_turnover(previous_long, long_names) + leg_turnover(previous_short, short_names))
        gross = float(long_leg[label_column].mean() - short_leg[label_column].mean())
        rows.append(
            {
                "signal_date": signal_date,
                "n_stocks": n_stocks,
                "excluded": False,
                "long_mean": float(long_leg[label_column].mean()),
                "short_mean": float(short_leg[label_column].mean()),
                "gross_return": gross,
                "turnover": float(turnover),
                "net_return": float(gross - turnover * float(cost_bps) / 10000.0 * 2.0),
            }
        )
        previous_long, previous_short = long_names, short_names
    table = pd.DataFrame(rows)
    guard_field_names(list(table.columns))
    return table


def permuted_network(weights: np.ndarray, *, seed: int) -> np.ndarray:
    """安慰剂网络：随机置换节点标签（保留权重多重集与度分布，破坏"谁是谁"）。"""
    matrix = np.asarray(weights, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
        raise EvaluationError("权重矩阵必须是方阵")
    if np.any(np.diag(matrix) != 0):
        raise EvaluationError("安慰剂置换要求对角线为空")
    rng = np.random.default_rng(int(seed))
    order = rng.permutation(matrix.shape[0])
    return matrix[np.ix_(order, order)]


# ---------------------------------------------------------------------------
# 评测配置
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EvaluationConfig:
    """评测参数（全部写入 manifest）。"""

    run_id: str
    domain: str = "A"
    feature_family: str = "price_technical_v1"
    networks: tuple[str, ...] = ("W-ind", "W-corr", "W-attn")
    labels: tuple[int, ...] = (5, 20)
    alpha_grid: tuple[float, ...] = DEFAULT_ALPHA_GRID
    signal_step: int = DEFAULT_SIGNAL_STEP
    train_window_days: int = 120
    min_train_rows: int = 2000
    min_cross_section: int = 30
    n_components: int = 10
    start_index: int = DEFAULT_START_INDEX
    first_apply_index: int = DEFAULT_FIRST_APPLY_INDEX
    max_signal_dates: int | None = None
    cost_bps: float = DEFAULT_COST_BPS
    quantile: float = 0.2
    bootstrap_reps: int = DEFAULT_BOOTSTRAP_REPS
    block_trading_days: tuple[int, ...] = DEFAULT_BLOCK_TRADING_DAYS
    gate_versions: tuple[str, ...] = ("V1", "V2", "V3")
    gate_min_train_dates: int = DEFAULT_GATE_MIN_TRAIN_DATES
    gate_ridge_lambda: float = DEFAULT_GATE_RIDGE_LAMBDA
    gate_half_life_days: float = DEFAULT_HALF_LIFE_DAYS
    seed: int = DEFAULT_SEED
    placebo_networks: tuple[str, ...] = ("W-ind",)

    def __post_init__(self) -> None:
        validate_run_id(self.run_id)
        if self.domain != "A":
            raise EvaluationError("当前主实验仅支持 A；C 组静态 768 维向量已溯源作废")
        if self.feature_family not in ("price_technical_v1", "text_flow_v1"):
            raise EvaluationError("feature_family 只支持 price_technical_v1 / text_flow_v1")
        unknown = [name for name in self.networks if name not in DEFAULT_NETWORK_CONFIGS]
        if unknown or not self.networks:
            raise EvaluationError(
                f"未知或不存在的网络：{unknown or '(空)'}；合法取值：{sorted(DEFAULT_NETWORK_CONFIGS)}"
            )
        if not self.labels or any(int(horizon) < 1 for horizon in self.labels):
            raise EvaluationError("labels 必须为正整数序列")
        for alpha in self.alpha_grid:
            if not (0.0 <= float(alpha) <= 1.0):
                raise EvaluationError(f"alpha 必须落在 [0,1]：{alpha!r}")
        if not (0.0 < float(self.quantile) < 0.5):
            raise EvaluationError("quantile 必须落在 (0, 0.5)")
        if self.max_signal_dates is not None and int(self.max_signal_dates) < 1:
            raise EvaluationError("max_signal_dates 必须为正")
        if int(self.first_apply_index) <= int(self.start_index):
            raise EvaluationError("first_apply_index 必须大于 start_index")
        if int(self.signal_step) < 1:
            raise EvaluationError("signal_step 至少为 1")
        if not np.isfinite(float(self.cost_bps)) or float(self.cost_bps) < 0:
            raise EvaluationError("cost_bps 必须为非负有限数")
        if int(self.bootstrap_reps) < 1:
            raise EvaluationError("bootstrap_reps 至少为 1")
        for version in self.gate_versions:
            if version not in ("V1", "V2", "V3"):
                raise EvaluationError(f"未知门控版本：{version!r}")

    def to_manifest(self) -> dict[str, Any]:
        payload = dict(self.__dict__)
        for name in ("alpha_grid", "networks", "labels", "block_trading_days", "gate_versions", "placebo_networks"):
            payload[name] = list(payload[name])
        return payload


@dataclass
class EvaluationInputs:
    """装载后的输入（含哈希）。"""

    panel: pd.DataFrame
    factors: pd.DataFrame
    universe: pd.DataFrame
    declarations: pd.DataFrame
    calendar: tuple[str, ...]
    codes: tuple[str, ...]
    industries: dict[str, str]
    hashes: dict[str, str] = field(default_factory=dict)
    corpus_inventory_sha256: str | None = None


def load_inputs(paths: Mapping[str, Path], config: EvaluationConfig) -> EvaluationInputs:
    """装载并校验输入；返回含 SHA256 的容器。"""
    panel = pd.read_csv(paths["panel"], dtype={"stock_code": str})
    factors = pd.read_csv(paths["factors"], dtype={"code": str})
    universe = pd.read_csv(paths["universe"], dtype=str)
    declarations = build_declarations(paths["caliber"], paths["factors"])
    cohort_of = dict(zip(factors["code"], factors["cohort_key"]))
    codes = tuple(sorted({code for code, group in cohort_of.items() if group == "student_A"} & set(panel["stock_code"])))
    if len(codes) < 2 * MIN_LEG:
        raise EvaluationError(f"研究域只有 {len(codes)} 支，不足以构造 2×{MIN_LEG} 的组合")
    calendar = trading_calendar_from_panel(panel)
    hashes = {name: sha256_of(path) for name, path in paths.items() if Path(path).is_file()}
    return EvaluationInputs(
        panel=panel,
        factors=factors,
        universe=universe,
        declarations=declarations,
        calendar=calendar,
        codes=codes,
        industries=dict(zip(universe["code"], universe["sub_industry"])),
        hashes=hashes,
        corpus_inventory_sha256=directory_inventory_sha256(paths["corpus"]),
    )


def signal_date_plan(calendar: Sequence[str], config: EvaluationConfig) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """返回 ``(含训练段的全部计划信号日, 用于评测的信号日)``。"""
    planner = tuple(calendar[int(config.start_index) :: int(config.signal_step)])
    apply_from = calendar[int(config.first_apply_index)]
    applications = tuple(date for date in planner if date >= apply_from)
    if not applications:
        raise EvaluationError("first_apply_index 之后没有信号日，无法评测")
    if config.max_signal_dates is not None:
        applications = applications[: int(config.max_signal_dates)]
    return planner, applications


def label_available_at(calendar: Sequence[str], signal_date: str, horizon: int) -> str:
    """标签成熟时点（上海时间收盘后），供动态门控判定"标签是否已成熟"。"""
    position = calendar.index(signal_date)
    mature = min(position + int(horizon), len(calendar) - 1)
    stamp = pd.Timestamp(calendar[mature]).tz_localize("Asia/Shanghai") + pd.Timedelta(hours=15)
    return stamp.isoformat()


def mature_training_dates(
    planner: Sequence[str],
    calendar: Sequence[str],
    first_apply_index: int,
    horizon: int,
) -> tuple[str, ...]:
    """训练用信号日：其标签在首个应用日**之前**已成熟。"""
    return tuple(date for date in planner if calendar.index(date) + int(horizon) < int(first_apply_index))


# ---------------------------------------------------------------------------
# 网络状态与变体装配
# ---------------------------------------------------------------------------

@dataclass
class NetworkState:
    """单网络在计划信号日上的状态（S0、归一化权重、行切片、门控）。"""

    name: str
    relation_type: str
    normalized: dict[str, np.ndarray] = field(default_factory=dict)
    rows: dict[str, pd.DataFrame] = field(default_factory=dict)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[pd.DataFrame] = field(default_factory=list)
    gates: dict[str, Any] = field(default_factory=dict)
    skipped_empty_edges: int = 0

    def codes(self, date: str) -> list[str]:
        """该日在网的股票顺序。"""
        return self.rows[date]["stock_code"].astype(str).tolist()


def collect_network_state(
    network_name: str,
    inputs: EvaluationInputs,
    basis: pd.DataFrame,
    flow: pd.DataFrame | None,
    asof: pd.DataFrame,
    planner: Sequence[str],
    applications: Sequence[str],
) -> NetworkState:
    """逐计划信号日构造网络并缓存状态（含诊断与边账本）。"""
    config = DEFAULT_NETWORK_CONFIGS[network_name]
    state = NetworkState(name=network_name, relation_type=config.relation_type)
    apply_set = set(applications)
    for signal_date in planner:
        build = build_network(
            inputs.codes,
            inputs.calendar.index(signal_date),
            inputs.calendar,
            config,
            industries=inputs.industries,
            returns=basis,
            flow=flow,
        )
        available = asof[(asof["signal_date"] == signal_date) & asof["is_available"]]
        if available.empty:
            continue
        node_position = {code: position for position, code in enumerate(build.codes)}
        ordered = available[available["stock_code"].isin(node_position)].copy()
        ordered["node_position"] = ordered["stock_code"].map(node_position)
        ordered = ordered.sort_values("node_position").reset_index(drop=True)
        keep = ordered["node_position"].to_numpy()
        # 当日可用截面上的**诱导子图**必须重新行归一化：直接切片会破坏行和，
        # 孤立行由 normalize_network 置自环（N = S0）。
        state.normalized[signal_date] = normalize_network(build.normalized[np.ix_(keep, keep)])
        state.rows[signal_date] = ordered
        if signal_date in apply_set:
            state.diagnostics.append({"signal_date": signal_date, "network": network_name, **network_diagnostics(build)})
            try:
                state.evidence.append(edge_evidence_frame(build, calendar=inputs.calendar))
            except NetworkError:
                state.skipped_empty_edges += 1
    if not state.normalized:
        raise EvaluationError(f"网络 {network_name} 在任何计划信号日都没有可用截面")
    return state


def fit_network_gates(
    state: NetworkState,
    inputs: EvaluationInputs,
    config: EvaluationConfig,
) -> dict[str, Any]:
    """按网络在**标签已成熟**的训练段上拟合 V1/V2/V3 门控。"""
    horizon = min(config.labels)
    planner = tuple(inputs.calendar[int(config.start_index) :: int(config.signal_step)])
    training_dates = [date for date in mature_training_dates(
        planner, inputs.calendar, config.first_apply_index, horizon
    ) if date in state.rows]
    rows: list[pd.DataFrame] = []
    for date in training_dates:
        frame = state.rows[date].copy()
        _, _, difference = propagate_nale_vectorized(
            frame["S0"].to_numpy(dtype=float), state.normalized[date], DEFAULT_B0_ALPHA
        )
        frame["_difference"] = difference
        rows.append(frame)
    if not rows:
        return {}
    training = pd.concat(rows, ignore_index=True).dropna(subset=["S0", f"label_{horizon}"])
    if training.empty:
        raise EvaluationError(f"网络 {state.name} 的动态门控训练段没有可用行")
    pc_columns = [f"PC{index:02d}_z" for index in range(1, config.n_components + 1)]
    first_apply_date = inputs.calendar[int(config.first_apply_index)]
    cutoff = (pd.Timestamp(first_apply_date).tz_localize("Asia/Shanghai") - pd.Timedelta(minutes=1)).isoformat()
    # V3 的时间权重需要"交易日年龄"：年龄 = 距首个应用日的交易日数（同一天所有股票共享，
    # 且随训练日递增而严格递减），只用日历位置，不涉及任何未来信息。
    ages = [
        int(config.first_apply_index) - inputs.calendar.index(date)
        for date in training["signal_date"]
    ]
    panel = TrainingPanel(
        signal_dates=training["signal_date"].tolist(),
        label_available_at=[
            label_available_at(inputs.calendar, date, horizon) for date in training["signal_date"]
        ],
        s0=training["S0"].to_numpy(dtype=float),
        difference=training["_difference"].to_numpy(dtype=float),
        z=training.loc[:, pc_columns].to_numpy(dtype=float),
        excess_return=training[f"label_{horizon}"].to_numpy(dtype=float),
        age_trading_days=ages,
    )
    fits: dict[str, Any] = {}
    for version in config.gate_versions:
        kwargs: dict[str, Any] = {}
        if version == "V3":
            kwargs["half_life_days"] = float(config.gate_half_life_days)
        fits[version] = fit_gate(
            panel,
            version=version,
            fit_cutoff=cutoff,
            ridge_lambda=float(config.gate_ridge_lambda),
            min_train_dates=int(config.gate_min_train_dates),
            **kwargs,
        )
    return fits


def _propagate(state: NetworkState, date: str, alpha: np.ndarray | float) -> np.ndarray:
    """用权威核在给定 α 下传播该日得分。"""
    s0 = state.rows[date]["S0"].to_numpy(dtype=float)
    scores, _, _ = propagate_nale_vectorized(s0, state.normalized[date], alpha)
    return scores


def build_variant_scores(
    states: Mapping[str, NetworkState],
    applications: Sequence[str],
    asof: pd.DataFrame,
    config: EvaluationConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """装配全部变体（α=0 / B0 / 网格 / 动态门控 / 安慰剂）的逐日得分。"""
    rows: list[pd.DataFrame] = []
    index_rows: list[dict[str, Any]] = []

    def emit(
        network: str,
        state: NetworkState,
        variant: str,
        family: str,
        scores_by_date: Mapping[str, np.ndarray],
        alpha_by_date: Mapping[str, np.ndarray | float],
        note: str,
    ) -> None:
        pieces: list[pd.DataFrame] = []
        alphas: list[float] = []
        for date in applications:
            if date not in state.rows:
                continue
            frame = state.rows[date].loc[:, ["stock_code", "signal_date"]].copy()
            frame["network"] = network
            frame["variant"] = variant
            frame["score"] = scores_by_date[date]
            pieces.append(frame)
            alphas.append(float(np.mean(alpha_by_date[date])))
        if not pieces:
            return
        rows.append(pd.concat(pieces, ignore_index=True))
        index_rows.append(
            {
                "network": network,
                "variant": variant,
                "family": family,
                "alpha_mean": float(np.mean(alphas)),
                "alpha_min": float(np.min(alphas)),
                "alpha_max": float(np.max(alphas)),
                "relation_type": state.relation_type,
                "note": note,
            }
        )

    for network, state in states.items():
        dates = [date for date in applications if date in state.rows]
        if not dates:
            continue
        emit(
            network, state, "alpha_0.00", "fixed",
            {date: state.rows[date]["S0"].to_numpy(dtype=float) for date in dates},
            {date: 0.0 for date in dates},
            "α=0 即不传播，S ≡ S0（跨网络应逐位相同）",
        )
        emit(
            network, state, f"b0_alpha_{DEFAULT_B0_ALPHA:.2f}", "fixed",
            {date: _propagate(state, date, DEFAULT_B0_ALPHA) for date in dates},
            {date: DEFAULT_B0_ALPHA for date in dates},
            "B0 固定 α=0.40",
        )
        for alpha in config.alpha_grid:
            if abs(float(alpha) - DEFAULT_B0_ALPHA) < 1e-12 or float(alpha) == 0.0:
                continue
            emit(
                network, state, f"alpha_{float(alpha):.2f}", "grid",
                {date: _propagate(state, date, float(alpha)) for date in dates},
                {date: float(alpha) for date in dates},
                "α 网格",
            )
        if network in config.placebo_networks:
            # 安慰剂：逐日把归一化权重的对角线清零后置换节点标签，再重新归一化
            # （权重多重集与度分布不变，但不再对应真实身份）。
            placebo_by_date: dict[str, np.ndarray] = {}
            placebo_scores: dict[str, np.ndarray] = {}
            for date in dates:
                base = state.normalized[date].copy()
                np.fill_diagonal(base, 0.0)
                permuted = normalize_network(permuted_network(base, seed=config.seed))
                placebo_by_date[date] = permuted
                placebo_scores[date] = propagate_nale_vectorized(
                    state.rows[date]["S0"].to_numpy(dtype=float), permuted, DEFAULT_B0_ALPHA
                )[0]
            emit(
                network, state, "placebo_node_permutation", "placebo",
                placebo_scores,
                {date: DEFAULT_B0_ALPHA for date in dates},
                "节点标签置换（权重多重集与度分布不变，破坏网络-身份对应）",
            )
        pc_columns = [f"PC{index:02d}_z" for index in range(1, config.n_components + 1)]
        for version, fit in state.gates.items():
            alpha_by_date = {
                date: fit.alpha(state.rows[date].loc[:, pc_columns].to_numpy(dtype=float))
                for date in dates
            }
            emit(
                network, state, f"gate_{version}", "dynamic",
                {date: _propagate(state, date, alpha_by_date[date]) for date in dates},
                alpha_by_date,
                f"动态门控 {version}（按网络拟合，训练段仅用标签已成熟的信号日）",
            )
    if not rows:
        raise EvaluationError("没有任何变体产出得分")
    scores_long = pd.concat(rows, ignore_index=True)
    variant_index = pd.DataFrame(index_rows)
    guard_field_names(list(scores_long.columns) + list(variant_index.columns))
    return scores_long, variant_index


def build_gate_prediction_audit(
    states: Mapping[str, NetworkState],
    applications: Sequence[str],
    config: EvaluationConfig,
) -> pd.DataFrame:
    """写出动态门控的逐行可复核输入、贡献和回退状态。

    ``variant_scores`` 是所有模型共用的评分长表；本表只服务动态门控审计，
    使回退到 B0 不会被误读为成功的动态拟合。
    """
    pc_columns = [f"PC{index:02d}_z" for index in range(1, config.n_components + 1)]
    rows: list[pd.DataFrame] = []
    for network, state in states.items():
        for version, fit in state.gates.items():
            for signal_date in applications:
                if signal_date not in state.rows:
                    continue
                source = state.rows[signal_date]
                z = source.loc[:, pc_columns].to_numpy(dtype=float)
                _, neighbor, difference = propagate_nale_vectorized(
                    source["S0"].to_numpy(dtype=float), state.normalized[signal_date], 0.0
                )
                # GateFit.alpha() deliberately returns B0 alpha for any explicit fallback.
                alpha = fit.alpha(z)
                linear = np.zeros(len(source), dtype=float) if fit.fallback_reason else fit.intercept + z @ fit.weights
                audit = source.loc[:, ["stock_code", "signal_date", "S0", *pc_columns]].copy()
                audit.insert(2, "network", network)
                audit.insert(3, "version", version)
                audit["neighbor_score"] = neighbor
                audit["difference"] = difference
                for index, column in enumerate(pc_columns):
                    audit[f"PC{index + 1:02d}_contribution"] = z[:, index] * fit.weights[index]
                audit["gate_linear_u"] = linear
                audit["alpha_nale"] = alpha
                audit["propagated_score"] = _propagate(state, signal_date, alpha)
                audit["fit_cutoff"] = fit.fit_cutoff
                audit["fallback_reason"] = fit.fallback_reason or ""
                rows.append(audit)
    if not rows:
        return pd.DataFrame()
    result = pd.concat(rows, ignore_index=True)
    if result.duplicated(["stock_code", "signal_date", "network", "version"]).any():
        raise EvaluationError("动态门控审计表出现重复预测键")
    guard_field_names(list(result.columns))
    return result


# ---------------------------------------------------------------------------
# 统计表
# ---------------------------------------------------------------------------

def compute_ic_tables(
    scores_long: pd.DataFrame,
    asof: pd.DataFrame,
    config: EvaluationConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """逐日 IC → 汇总 + bootstrap（含区块长度敏感性）+ Holm 校正。"""
    label_columns = [f"label_{horizon}" for horizon in config.labels]
    reference = asof.loc[:, ["stock_code", "signal_date", *label_columns]]
    merged_all = scores_long.merge(reference, on=["stock_code", "signal_date"], how="inner", validate="many_to_one")
    ic_rows: list[dict[str, Any]] = []
    for (network, variant, signal_date), group in merged_all.groupby(
        ["network", "variant", "signal_date"], sort=True
    ):
        for horizon in config.labels:
            stats = cross_sectional_ic(group["score"], group[f"label_{horizon}"])
            ic_rows.append(
                {
                    "network": network,
                    "variant": variant,
                    "signal_date": signal_date,
                    "horizon": int(horizon),
                    "n_stocks": stats["n_stocks"],
                    "excluded": stats["excluded"],
                    "pearson_ic": stats["pearson"],
                    "spearman_ic": stats["spearman"],
                }
            )
    ic_series = pd.DataFrame(ic_rows)
    guard_field_names(list(ic_series.columns))

    summary_rows: list[dict[str, Any]] = []
    bootstrap_rows: list[dict[str, Any]] = []
    for (network, variant, horizon), group in ic_series.groupby(["network", "variant", "horizon"], sort=True):
        ordered = group.sort_values("signal_date")
        pearson = ordered["pearson_ic"].tolist()
        spearman = ordered["spearman_ic"].tolist()
        summary = ic_summary(pearson)
        rank_summary = ic_summary(spearman)
        summary_rows.append(
            {
                "network": network,
                "variant": variant,
                "horizon": int(horizon),
                "n_days": summary["n_days"],
                "n_days_excluded": int(ordered["excluded"].sum()),
                "mean_n_stocks": float(ordered["n_stocks"].mean()),
                "mean_pearson_ic": summary["mean_ic"],
                "std_pearson_ic": summary["std_ic"],
                "icir_pearson": summary["icir"],
                "t_stat_pearson": summary["t_stat"],
                "spearman_n_days": rank_summary["n_days"],
                "mean_spearman_ic": rank_summary["mean_ic"],
                "std_spearman_ic": rank_summary["std_ic"],
                "icir_spearman": rank_summary["icir"],
                "t_stat_spearman": rank_summary["t_stat"],
            }
        )
        for trading_days in tuple(dict.fromkeys((*config.block_trading_days, *BLOCK_SENSITIVITY_TRADING_DAYS))):
            blocks = trading_days_to_signal_blocks(trading_days, config.signal_step)
            for metric_name, values in (("pearson_ic", pearson), ("spearman_ic", spearman)):
                valid = [value for value in values if np.isfinite(value)]
                if not valid:
                    continue
                interval = block_bootstrap_interval(
                    valid, block_length=blocks, reps=config.bootstrap_reps, seed=config.seed
                )
                bootstrap_rows.append(
                    {
                        "network": network,
                        "variant": variant,
                        "horizon": int(horizon),
                        "metric": metric_name,
                        "block_trading_days": int(trading_days),
                        "is_sensitivity": trading_days not in config.block_trading_days,
                        **interval,
                    }
                )
    summary_table = pd.DataFrame(summary_rows)
    bootstrap_table = pd.DataFrame(bootstrap_rows)
    guard_field_names(list(summary_table.columns) + list(bootstrap_table.columns))
    summary_table["p_value_pearson"] = summary_table["t_stat_pearson"].apply(normal_two_sided_p)
    summary_table["holm_adjusted_p"] = holm_adjust(summary_table["p_value_pearson"].tolist())
    return ic_series, summary_table, bootstrap_table


def compute_portfolio_tables(
    scores_long: pd.DataFrame,
    asof: pd.DataFrame,
    config: EvaluationConfig,
) -> pd.DataFrame:
    """逐变体多空组合（0 成本对照 + 主结论成本档）。"""
    label_columns = [f"label_{horizon}" for horizon in config.labels]
    reference = asof.loc[:, ["stock_code", "signal_date", *label_columns]]
    merged_all = scores_long.merge(reference, on=["stock_code", "signal_date"], how="inner", validate="many_to_one")
    rows: list[dict[str, Any]] = []
    blocks = trading_days_to_signal_blocks(config.block_trading_days[0], config.signal_step)
    for (network, variant), group in merged_all.groupby(["network", "variant"], sort=True):
        for horizon in config.labels:
            frame = group.rename(columns={f"label_{horizon}": "label"}).loc[
                :, ["signal_date", "stock_code", "score", "label"]
            ]
            for cost in (0.0, float(config.cost_bps)):
                table = long_short_period_returns(
                    frame,
                    score_column="score",
                    label_column="label",
                    cost_bps=cost,
                    min_leg=MIN_LEG,
                    quantile=config.quantile,
                )
                usable = table[~table["excluded"]]
                if usable.empty:
                    continue
                for metric in ("gross_return", "net_return"):
                    values = usable[metric].tolist()
                    interval = block_bootstrap_interval(
                        values, block_length=blocks, reps=config.bootstrap_reps, seed=config.seed
                    )
                    rows.append(
                        {
                            "network": network,
                            "variant": variant,
                            "horizon": int(horizon),
                            "cost_bps": cost,
                            "metric": metric,
                            "n_periods": int(len(usable)),
                            "n_periods_excluded": int(table["excluded"].sum()),
                            "mean_period_return": float(np.mean(values)),
                            "std_period_return": float(np.std(values, ddof=1)) if len(values) > 1 else np.nan,
                            "mean_turnover": float(usable["turnover"].mean()),
                            **interval,
                        }
                    )
    table = pd.DataFrame(rows)
    guard_field_names(list(table.columns))
    return table


# ---------------------------------------------------------------------------
# 产物写出
# ---------------------------------------------------------------------------

def write_manifest(
    path: Path,
    *,
    config: EvaluationConfig,
    inputs: EvaluationInputs,
    frozen_at: str,
    signal_dates: Sequence[str],
    summary: Mapping[str, Any],
    gate_report: Mapping[str, Any],
    diagnostics: pd.DataFrame,
) -> None:
    """把输入哈希、版本、冻结日、参数与网络覆盖度钉进 manifest。"""
    coverage: dict[str, Any] = {}
    if not diagnostics.empty:
        for network, group in diagnostics.groupby("network"):
            coverage[str(network)] = {
                "n_signal_dates": int(len(group)),
                "mean_node_coverage": float(group["node_coverage"].mean()),
                "min_node_coverage": float(group["node_coverage"].min()),
                "max_isolated_nodes": int(group["isolated_nodes"].max()),
                "mean_edges": float(group["n_edges"].mean()),
            }
    payload = {
        "eval_version": EVAL_VERSION,
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_id": config.run_id,
        "config": config.to_manifest(),
        "primary_experiment_policy": PRIMARY_EXPERIMENT_POLICY,
        "caliber_watermark": CALIBER_WATERMARK,
        "verification_frozen_at": frozen_at,
        "verification_window_rule": "only trade_date <= verification_frozen_at（PIT；全样本复核禁止进入产物）",
        "signal_dates": list(signal_dates),
        "n_signal_dates": len(signal_dates),
        "universe_size": len(inputs.codes),
        "input_sha256": dict(inputs.hashes),
        "corpus_inventory_sha256": inputs.corpus_inventory_sha256,
        "versions": {
            "asof_panel": ASOF_PANEL_VERSION,
            "s0": S0_VERSION,
            "s0_pc5_prior": S0_PC5_PRIOR_VERSION,
            "pca": PCA_VERSION,
            "neutralization": NEUTRALIZATION_VERSION,
            "network": NETWORK_VERSION,
            "eval": EVAL_VERSION,
        },
        "not_evaluable_networks": dict(NOT_EVALUABLE_NETWORKS),
        "relation_specs": {name: dict(spec) for name, spec in RELATION_SPECS.items()},
        "network_coverage": coverage,
        "gate_fits": dict(gate_report),
        "summary": dict(summary),
    }
    guard_field_names(list(payload.keys()))
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def write_report(
    path: Path,
    *,
    config: EvaluationConfig,
    manifest: Mapping[str, Any],
    summary_table: pd.DataFrame,
    portfolio_table: pd.DataFrame,
    diagnostics: pd.DataFrame,
) -> None:
    """人读报告：并列结论 + NOT_EVALUABLE + 纪律声明与局限。"""
    lines: list[str] = []
    lines.append("# PCA→NALE 集成走步评测报告（M4）")
    lines.append("")
    lines.append(f"- run_id：`{config.run_id}`｜评测版本：`{EVAL_VERSION}`｜口径水印：`{CALIBER_WATERMARK}`")
    lines.append(f"- 研究域：{config.domain}（{manifest['universe_size']} 支）｜特征族：`{config.feature_family}`")
    lines.append(f"- 信号日：应用期 {manifest['n_signal_dates']} 个（步长 {config.signal_step} 交易日）")
    lines.append(f"- **口径复核冻结日：`{manifest['verification_frozen_at']}`**（只用该日及以前数据；全样本复核禁止入产物）")
    lines.append("- 标签：主 5 交易日、辅 20 交易日；**重叠持有期不做任何年化**（F3）")
    lines.append(
        f"- 计费：0 成本对照 + 主结论双边 {config.cost_bps:.1f} bp；区块 bootstrap seed {config.seed}、"
        f"{config.bootstrap_reps} 次"
    )
    lines.append(
        f"- 动态门控：`gate_min_train_dates={config.gate_min_train_dates}`"
        "（**降级设置**，Week1 默认 126 在本样本上不可达）"
    )
    lines.append("- **主实验范围：仅 A 组。**C 组静态 768 维向量已溯源作废，绝不进入本报告的 IC、回测或主结论。")
    lines.append("")
    lines.append("## 1. IC 汇总（同一数据 / 同一切分 / 同一标签）")
    lines.append("")
    if summary_table.empty:
        lines.append("（无可用结果）")
    else:
        lines.append("| 网络 | 变体 | 视界 | 天数 | 排除日 | 均值 IC | ICIR(不年化) | t | Holm p |")
        lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
        ordered = summary_table.sort_values(["horizon", "mean_pearson_ic"], ascending=[True, False])
        for _, row in ordered.iterrows():
            lines.append(
                "| {network} | {variant} | {horizon} | {days} | {excluded} | {mean} | {icir} | {t} | {holm} |".format(
                    network=row["network"],
                    variant=row["variant"],
                    horizon=int(row["horizon"]),
                    days=int(row["n_days"]),
                    excluded=int(row["n_days_excluded"]),
                    mean=f"{row['mean_pearson_ic']:.4f}" if np.isfinite(row["mean_pearson_ic"]) else "n/a",
                    icir=f"{row['icir_pearson']:.3f}" if np.isfinite(row["icir_pearson"]) else "n/a",
                    t=f"{row['t_stat_pearson']:.3f}" if np.isfinite(row["t_stat_pearson"]) else "n/a",
                    holm=f"{row['holm_adjusted_p']:.4f}" if np.isfinite(row["holm_adjusted_p"]) else "n/a",
                )
            )
    lines.append("")
    lines.append("## 2. 多空组合（显式计费、禁止年化）")
    lines.append("")
    if portfolio_table.empty:
        lines.append("（无可用结果）")
    else:
        main = portfolio_table[
            (portfolio_table["cost_bps"] == float(config.cost_bps))
            & (portfolio_table["metric"] == "net_return")
        ]
        lines.append("| 网络 | 变体 | 视界 | 期数 | 每期均值 | 每期标准差 | 平均换手 | 95% 区间 |")
        lines.append("|---|---|---:|---:|---:|---:|---:|---|")
        for _, row in main.sort_values("mean_period_return", ascending=False).iterrows():
            lines.append(
                "| {network} | {variant} | {horizon} | {periods} | {mean:.5f} | {std} | {turnover:.3f} | [{low:.5f}, {high:.5f}] |".format(
                    network=row["network"],
                    variant=row["variant"],
                    horizon=int(row["horizon"]),
                    periods=int(row["n_periods"]),
                    mean=row["mean_period_return"],
                    std=f"{row['std_period_return']:.5f}" if np.isfinite(row["std_period_return"]) else "n/a",
                    turnover=row["mean_turnover"],
                    low=row["ci_low"],
                    high=row["ci_high"],
                )
            )
    lines.append("")
    lines.append("## 3. 网络诊断（并列报告，不得只报赢家）")
    lines.append("")
    if diagnostics.empty:
        lines.append("（无）")
    else:
        summary_columns = [
            "network", "n_edges", "density", "node_coverage", "isolated_nodes",
            "degree_min", "degree_median", "degree_max", "pairs_insufficient_overlap", "pairs_below_threshold",
        ]
        reduced = diagnostics.loc[:, [column for column in summary_columns if column in diagnostics.columns]]
        lines.append("```")
        lines.append(reduced.describe(include="all").to_string())
        lines.append("```")
        lines.append("")
        lines.append("覆盖度口径：`node_coverage` = 有至少一条边的节点比例；孤立点仅自环（N = S0）。")
    lines.append("")
    lines.append("## 4. 明确不可评的网络（必须与上面的结论并列出现）")
    lines.append("")
    for name, reason in NOT_EVALUABLE_NETWORKS.items():
        lines.append(f"- `{name}`：{reason}")
    lines.append("")
    lines.append("## 5. C 组保留与限制")
    lines.append("")
    lines.append("- **禁止使用**：C 组静态 768 维向量及其任何派生 IC、回测、夏普或主结论。")
    lines.append("- **仍可保留**：C 组 CSMAR 日频行情面板；以及带 `publish_time` 的逐条文本，仅限新的 `text_flow_v1` 探索。")
    lines.append("- 这些保留项不等同于复现旧静态向量，且不纳入当前 A 组主实验。")
    lines.append("")
    lines.append("## 6. 纪律声明与局限")
    lines.append("")
    lines.append("- 本报告不含任何年化字段（写出前有字段名守卫，含 annual 字样即抛错）。")
    lines.append("- W-ind 与截面中性化所用行业哑变量同源，其传播项可能被正交化吸收；解释其增益前必须结合")
    lines.append("  `placebo_node_permutation`（节点标签置换）结果一起看。")
    lines.append("- 动态门控按网络分别拟合，训练段只用标签已成熟的信号日；`gate_min_train_dates` 属降级设置。")
    lines.append("- 单日有效股票数 < 20 的信号日记缺失并计入 `n_days_excluded`。")
    lines.append("- 组合换手用腿内名单更替比例估计，属近似口径；未建模冲击成本与涨跌停不可成交。")
    lines.append("- W-attn 存在孤立点（覆盖率见第 3 节），孤立点在传播中等价于不传播；跨网络比较必须同时看覆盖率。")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_figure(path: Path, summary_table: pd.DataFrame) -> str | None:
    """IC 柱状图（matplotlib 缺失时返回 None，不假造图片）。"""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:  # pragma: no cover - 环境无 matplotlib 时跳过
        return None
    if summary_table.empty:
        return None
    subset = summary_table[summary_table["horizon"] == summary_table["horizon"].min()].copy()
    subset["label"] = subset["network"] + "|" + subset["variant"]
    figure, axis = plt.subplots(figsize=(max(6.0, 0.32 * len(subset)), 4.2))
    axis.bar(subset["label"], subset["mean_pearson_ic"], color="#4c72b0")
    axis.axhline(0.0, color="black", linewidth=0.8)
    axis.set_ylabel("mean Pearson IC per period (not annualised)")
    axis.set_title("PCA to NALE variants (same data / same split / same label)")
    axis.tick_params(axis="x", rotation=90, labelsize=7)
    figure.tight_layout()
    figure.savefig(path, dpi=140)
    plt.close(figure)
    return str(path)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def run_evaluation(
    config: EvaluationConfig,
    *,
    paths: Mapping[str, Path] | None = None,
    root: Path = ROOT,
    verbose: bool = True,
) -> dict[str, Any]:
    """执行一次走步评测，返回摘要（产物已落盘）。"""
    resolved: dict[str, Path] = {
        "panel": DEFAULT_PANEL,
        "factors": DEFAULT_FACTORS,
        "universe": DEFAULT_UNIVERSE,
        "caliber": DEFAULT_CALIBER,
        "corpus": DEFAULT_CORPUS,
    }
    if paths:
        resolved.update({name: Path(path) for name, path in paths.items()})
    directories = resolve_output_dirs(config.run_id, root=root)
    for directory in directories.values():
        directory.mkdir(parents=True, exist_ok=False)

    inputs = load_inputs(resolved, config)
    planner, applications = signal_date_plan(inputs.calendar, config)
    first_apply = applications[0]
    frozen_at = inputs.calendar[inputs.calendar.index(first_apply) - 1]

    verification = frozen_verification(inputs.panel, inputs.declarations, frozen_at)
    basis = compute_return_basis(inputs.panel, inputs.declarations, verification=verification)

    flow = None
    corpus_records = 0
    if "W-attn" in config.networks:
        records = load_corpus_records(resolved["corpus"])
        corpus_records = int(len(records))
        flow = text_flow_features(records, inputs.calendar, inputs.codes, windows=(1,), lag_days=1)
    features = _build_feature_frame(inputs, config, resolved, flow)

    asof_config = AsofPanelConfig(
        feature_family=config.feature_family,
        n_components=config.n_components,
        train_window_days=config.train_window_days,
        min_train_rows=config.min_train_rows,
        min_cross_section=config.min_cross_section,
        horizons=tuple(config.labels),
        signal_dates=planner,
        industry_column="sub_industry",
    )
    panel_result = build_asof_panel(
        features,
        inputs.panel,
        basis,
        inputs.calendar,
        inputs.codes,
        asof_config,
        industries=inputs.industries,
        corpus_version=f"student_ac_crawled:{corpus_records}records" if flow is not None else "unavailable",
        embedding_model_version="NOT_ASOF:fastembed:jinaai/jina-embeddings-v2-base-zh",
        embedding_truncation_date="2026-09-07",
    )
    asof = panel_result.panel

    states: dict[str, NetworkState] = {}
    gate_report: dict[str, Any] = {}
    for network_name in config.networks:
        state = collect_network_state(network_name, inputs, basis, flow, asof, planner, applications)
        state.gates = fit_network_gates(state, inputs, config)
        states[network_name] = state
        gate_report[network_name] = {
            version: {
                "intercept": float(fit.intercept),
                "weights": [float(value) for value in fit.weights],
                "fallback_reason": fit.fallback_reason,
                "converged": bool(fit.converged),
                "n_rows": int(fit.n_rows),
                "n_signal_dates": int(fit.n_signal_dates),
                "fit_cutoff": fit.fit_cutoff,
                "ridge_lambda": float(fit.ridge_lambda),
                "calibration_intercept": float(fit.calibration.intercept),
                "calibration_slope": float(fit.calibration.slope),
                "objective": float(fit.objective),
                "gradient_norm": float(fit.gradient_norm),
                "optimizer_message": fit.optimizer_message,
            }
            for version, fit in state.gates.items()
        }

    scores_long, variant_index = build_variant_scores(states, applications, asof, config)
    gate_prediction_audit = build_gate_prediction_audit(states, applications, config)
    ic_series, summary_table, bootstrap_table = compute_ic_tables(scores_long, asof, config)
    portfolio_table = compute_portfolio_tables(scores_long, asof, config)
    diagnostics_table = pd.DataFrame([row for state in states.values() for row in state.diagnostics])
    evidence_frames = [frame.assign(network=state.name) for state in states.values() for frame in state.evidence]

    asof.to_csv(directories["processed"] / "asof_panel.csv.gz", index=False, compression="gzip")
    scores_long.to_csv(directories["processed"] / "variant_scores.csv.gz", index=False, compression="gzip")
    gate_prediction_audit.to_csv(
        directories["processed"] / "gate_predictions.csv.gz", index=False, compression="gzip"
    )
    if evidence_frames:
        pd.concat(evidence_frames, ignore_index=True).to_csv(
            directories["processed"] / "edge_evidence.csv.gz", index=False, compression="gzip"
        )
    diagnostics_table.to_csv(directories["tables"] / "network_diagnostics.csv", index=False)
    variant_index.to_csv(directories["tables"] / "variant_index.csv", index=False)
    ic_series.to_csv(directories["tables"] / "ic_series.csv", index=False)
    summary_table.to_csv(directories["tables"] / "metrics_by_variant.csv", index=False)
    bootstrap_table.to_csv(directories["tables"] / "bootstrap.csv", index=False)
    portfolio_table.to_csv(directories["tables"] / "portfolio.csv", index=False)

    summary = {
        "n_signal_dates_planned": len(planner),
        "n_signal_dates_applied": len(applications),
        "n_variants": int(variant_index.shape[0]),
        "n_ic_rows": int(ic_series.shape[0]),
        "excluded_days_total": int(summary_table["n_days_excluded"].sum()) if not summary_table.empty else 0,
        "mean_ic_by_network_horizon": {
            f"{network}|{horizon}": float(value)
            for (network, horizon), value in (
                summary_table.groupby(["network", "horizon"])["mean_pearson_ic"].mean().items()
                if not summary_table.empty
                else []
            )
        },
        "skipped_empty_edge_days": {state.name: state.skipped_empty_edges for state in states.values()},
        "corpus_records": corpus_records,
    }
    manifest_path = directories["tables"] / "manifest.json"
    write_manifest(
        manifest_path,
        config=config,
        inputs=inputs,
        frozen_at=frozen_at,
        signal_dates=applications,
        summary=summary,
        gate_report=gate_report,
        diagnostics=diagnostics_table,
    )
    write_report(
        directories["tables"] / "report.md",
        config=config,
        manifest=json.loads(manifest_path.read_text(encoding="utf-8")),
        summary_table=summary_table,
        portfolio_table=portfolio_table,
        diagnostics=diagnostics_table,
    )
    summary["figure"] = write_figure(directories["figures"] / "ic_by_variant.png", summary_table)
    summary["directories"] = {name: str(path) for name, path in directories.items()}
    if verbose:
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return summary


def _build_feature_frame(
    inputs: EvaluationInputs,
    config: EvaluationConfig,
    paths: Mapping[str, Path],
    flow: pd.DataFrame | None,
) -> pd.DataFrame:
    """按特征族取列；文本族复用已聚合的 as-of 流量（避免重复读语料）。"""
    if config.feature_family == "price_technical_v1":
        return inputs.panel.loc[
            inputs.panel["stock_code"].isin(inputs.codes),
            ["stock_code", "trade_date", *TECHNICAL_FEATURES],
        ].copy()
    if flow is not None:
        return flow
    records = load_corpus_records(paths["corpus"])
    return text_flow_features(records, inputs.calendar, inputs.codes, windows=(5, 20, 60), lag_days=1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """命令行接口。"""
    parser = argparse.ArgumentParser(description="PCA→NALE 集成走步评测（M4）")
    parser.add_argument("--run-id", required=True, help="产物目录名（必填；已存在则拒绝运行）")
    parser.add_argument("--domain", default="A", choices=["A"])
    parser.add_argument("--feature-family", default="price_technical_v1",
                        choices=["price_technical_v1", "text_flow_v1"])
    parser.add_argument("--networks", default="W-ind,W-corr,W-attn")
    parser.add_argument("--labels", default="5,20")
    parser.add_argument("--alpha-grid", default=",".join(str(alpha) for alpha in DEFAULT_ALPHA_GRID))
    parser.add_argument("--signal-step", type=int, default=DEFAULT_SIGNAL_STEP)
    parser.add_argument("--start-index", type=int, default=DEFAULT_START_INDEX)
    parser.add_argument("--first-apply-index", type=int, default=DEFAULT_FIRST_APPLY_INDEX)
    parser.add_argument("--max-signal-dates", type=int, default=None)
    parser.add_argument("--cost-bps", type=float, default=DEFAULT_COST_BPS)
    parser.add_argument("--bootstrap-reps", type=int, default=DEFAULT_BOOTSTRAP_REPS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--gate-versions", default="V1,V2,V3")
    parser.add_argument("--gate-min-train-dates", type=int, default=DEFAULT_GATE_MIN_TRAIN_DATES)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--factors", type=Path, default=DEFAULT_FACTORS)
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--caliber-config", type=Path, default=DEFAULT_CALIBER)
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS)
    return parser


def config_from_args(args: argparse.Namespace) -> EvaluationConfig:
    """把命令行参数转成冻结配置。"""
    return EvaluationConfig(
        run_id=args.run_id,
        domain=args.domain,
        feature_family=args.feature_family,
        networks=tuple(part.strip() for part in str(args.networks).split(",") if part.strip()),
        labels=tuple(int(part) for part in str(args.labels).split(",") if part.strip()),
        alpha_grid=tuple(float(part) for part in str(args.alpha_grid).split(",") if part.strip()),
        signal_step=int(args.signal_step),
        start_index=int(args.start_index),
        first_apply_index=int(args.first_apply_index),
        max_signal_dates=args.max_signal_dates,
        cost_bps=float(args.cost_bps),
        bootstrap_reps=int(args.bootstrap_reps),
        gate_versions=tuple(part.strip() for part in str(args.gate_versions).split(",") if part.strip()),
        gate_min_train_dates=int(args.gate_min_train_dates),
        seed=int(args.seed),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 入口：失败返回非零退出码并把原因写 stderr。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = config_from_args(args)
        run_evaluation(
            config,
            paths={
                "panel": args.panel,
                "factors": args.factors,
                "universe": args.universe,
                "caliber": args.caliber_config,
                "corpus": args.corpus_dir,
            },
        )
    except (EvaluationError, NetworkError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
