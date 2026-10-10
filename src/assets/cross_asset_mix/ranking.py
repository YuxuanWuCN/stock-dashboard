"""Cross-Asset Momentum, Risk, and Trend Strength Ranking Engine.

Implements Milestone 2 of the Cross-Asset Mixed Portfolio:
1. 20-day Compounded Momentum (geometric product of daily returns)
2. Inverse Volatility Metric with anti-overflow floor (sigma_floor = 0.08)
3. Composite Trend Strength Indicator (CTSI: MA divergence, Bollinger channel pos, MA alignment)
4. Empirical Cross-Asset Percentile Ranking (non-parametric mapping to uniform [0, 100])
5. CrossAssetRanker engine with Top-K selection and inverse-vol / equal weight allocation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union
import numpy as np
import pandas as pd

from .contracts import ContractSpec, get_contract_spec


def calculate_compounded_20d_momentum(
    returns_df: Union[pd.DataFrame, pd.Series],
    window: int = 20,
) -> Union[pd.DataFrame, pd.Series]:
    """Calculates compounded 20-day momentum: prod_{tau=t-19}^t (1 + r_tau) - 1.

    Args:
        returns_df: Daily return series or DataFrame.
        window: Rolling observation window (default 20 days).

    Returns:
        Rolling compounded geometric momentum series or DataFrame.
    """
    gross_returns = 1.0 + returns_df.fillna(0.0)
    rolling_prod = gross_returns.rolling(window=window, min_periods=window).apply(
        np.prod, raw=True
    )
    return rolling_prod - 1.0


def calc_compounded_momentum(
    returns: Union[pd.Series, pd.DataFrame, np.ndarray, List[float]],
    window: int = 20,
) -> Union[float, pd.Series, pd.DataFrame]:
    """Calculate compounded geometric momentum over window.

    If a 1D array, list, or Series is passed, returns a single float for the window.
    If a DataFrame is passed, returns a DataFrame of rolling compounded momentum.
    """
    if isinstance(returns, pd.DataFrame):
        return calculate_compounded_20d_momentum(returns, window=window)

    arr = np.asarray(returns, dtype=float)
    if len(arr) == 0:
        return 0.0
    sub = arr[-window:] if len(arr) >= window else arr
    sub = np.nan_to_num(sub, nan=0.0)
    return float(np.prod(1.0 + sub) - 1.0)


def calculate_inverse_volatility(
    returns_df: Union[pd.DataFrame, pd.Series],
    window: int = 20,
    floor: float = 0.08,
    trading_days: int = 252,
) -> Union[pd.DataFrame, pd.Series]:
    """Annualized daily volatility with floor to prevent division overflow.

    Args:
        returns_df: Daily return series or DataFrame.
        window: Rolling observation window (default 20 days).
        floor: Minimum annualized volatility floor (default 0.08 = 8%).
        trading_days: Number of trading days per year (default 252).

    Returns:
        Rolling inverse annualized volatility series or DataFrame.
    """
    daily_vol = returns_df.rolling(window=window, min_periods=window).std()
    ann_vol = daily_vol * np.sqrt(float(trading_days))
    clamped_vol = np.maximum(ann_vol, floor)
    return 1.0 / clamped_vol


def calc_inverse_volatility(
    returns: Union[pd.Series, pd.DataFrame, np.ndarray, List[float]],
    window: int = 20,
    floor: float = 0.08,
    trading_days: int = 252,
) -> Union[float, pd.Series, pd.DataFrame]:
    """Calculate inverse annualized sample volatility with anti-overflow floor.

    Formula: 1.0 / max(sample_std * sqrt(trading_days), floor)
    If 1D array, list, or Series is passed, returns a float.
    If DataFrame is passed, returns a rolling DataFrame.
    """
    if isinstance(returns, pd.DataFrame):
        return calculate_inverse_volatility(
            returns, window=window, floor=floor, trading_days=trading_days
        )

    arr = np.asarray(returns, dtype=float)
    if len(arr) < 2:
        return float(1.0 / floor)

    sub = arr[-window:] if len(arr) >= window else arr
    valid = sub[np.isfinite(sub)]
    if len(valid) < 2:
        return float(1.0 / floor)

    sample_std = float(np.std(valid, ddof=1))
    ann_vol = sample_std * np.sqrt(float(trading_days))
    clamped_vol = max(ann_vol, floor)
    return float(1.0 / clamped_vol)


def calculate_ctsi(
    prices_df: Union[pd.DataFrame, pd.Series],
    window: int = 20,
) -> Union[pd.DataFrame, pd.Series]:
    """Composite Trend Strength Indicator combining MA divergence, channel position, and alignment.

    Formula:
        CTSI = 0.40 * MA_div + 0.40 * Boll_pos + 0.20 * MA_alignment

    Where:
        - MA_div = (Price - MA20) / MA20
        - Boll_pos = (Price - Lower) / (Upper - Lower), clipped to [0, 1], neutral 0.5
        - MA_alignment = 1.0 if MA5 > MA20 else 0.0
    """
    ma20 = prices_df.rolling(window=window, min_periods=5).mean()
    ma5 = prices_df.rolling(window=5, min_periods=2).mean()
    std20 = prices_df.rolling(window=window, min_periods=5).std().replace(0.0, np.nan)

    # MA divergence: (Price - MA20) / MA20
    ma_div = (prices_df - ma20) / ma20.replace(0.0, np.nan)

    # Bollinger channel position: (Price - Lower) / (Upper - Lower)
    upper = ma20 + 2.0 * std20
    lower = ma20 - 2.0 * std20
    channel_range = (upper - lower).replace(0.0, np.nan)
    channel_pos = (prices_df - lower) / channel_range
    channel_pos = channel_pos.clip(0.0, 1.0)

    # MA alignment: MA5 > MA20
    alignment = (ma5 > ma20).astype(float)

    ctsi = 0.4 * ma_div.fillna(0.0) + 0.4 * channel_pos.fillna(0.5) + 0.2 * alignment
    return ctsi


def calc_trend_strength_ctsi(
    prices: Union[pd.Series, pd.DataFrame, np.ndarray, List[float]],
    window: int = 20,
) -> Union[float, pd.Series, pd.DataFrame]:
    """Calculate Composite Trend Strength Indicator score.

    If 1D array, list, or Series is passed, returns latest float score.
    If DataFrame is passed, returns rolling DataFrame of CTSI scores.
    """
    if isinstance(prices, pd.DataFrame):
        return calculate_ctsi(prices, window=window)

    if isinstance(prices, pd.Series):
        res = calculate_ctsi(prices, window=window)
        val = res.iloc[-1]
        return float(val) if np.isfinite(val) else 0.5

    s = pd.Series(prices, dtype=float)
    res = calculate_ctsi(s, window=window)
    val = res.iloc[-1]
    return float(val) if np.isfinite(val) else 0.5


def compute_cross_asset_percentile_rank(series: pd.Series) -> pd.Series:
    """Maps raw factor scores non-parametrically to uniform percentile range [0, 100].

    Formula:
        RankPct(X_i) = (Rank(X_i) - 1.0) / (N - 1.0) * 100.0

    Handles edge cases:
        - Empty or all-NaN series: returns input series.
        - Single-element series: returns 100.0.
        - Tied scores: average rank assignment ensures identical percentiles.
    """
    valid = series.dropna()
    if len(valid) == 0:
        return series.copy()
    if len(valid) == 1:
        res = series.copy()
        res.loc[valid.index] = 100.0
        return res
    ranks = valid.rank(ascending=True, method="average")
    percentiles = (ranks - 1.0) / (len(valid) - 1.0) * 100.0
    res = series.copy()
    res.loc[valid.index] = percentiles
    return res


@dataclass
class RankItem:
    """Single asset ranking entry in cross-asset universe."""

    rank: int
    symbol: str
    name: str
    asset_type: str  # 'STOCK' | 'FUTURES'
    momentum_20d: float
    inv_vol: float
    trend_strength: float
    composite_score: float
    target_weight: float
    side: str = "LONG"


@dataclass
class RankResult:
    """Cross-asset universe ranking result for a rebalance date."""

    as_of_date: str
    ranked_df: pd.DataFrame
    selected_top_k: List[RankItem]


def select_top_k(
    ranked_df: pd.DataFrame,
    k: int = 10,
    weighting: str = "inverse_vol",
) -> List[RankItem]:
    """Select Top-K ranked items and calculate normalized portfolio weights summing to 1.0.

    Args:
        ranked_df: DataFrame containing ranked assets (columns: rank, symbol, name,
                   asset_type, momentum_20d, inv_vol, trend_strength, composite_score).
        k: Number of top assets to select.
        weighting: 'inverse_vol' (proportional to inverse volatility) or 'equal' (1/K).

    Returns:
        List of RankItem instances with target_weight summing to 1.0.
    """
    if ranked_df is None or ranked_df.empty or k <= 0:
        return []

    # Sort primarily by rank or descending composite_score
    if "rank" in ranked_df.columns:
        df_sorted = ranked_df.sort_values(by="rank", ascending=True)
    elif "composite_score" in ranked_df.columns:
        df_sorted = ranked_df.sort_values(by="composite_score", ascending=False)
    else:
        df_sorted = ranked_df

    selected_df = df_sorted.head(k)
    n_selected = len(selected_df)
    if n_selected == 0:
        return []

    if weighting == "equal":
        weights = [1.0 / n_selected] * n_selected
    else:  # 'inverse_vol'
        ivs = [
            float(val) if np.isfinite(val) and val > 0 else 1.0
            for val in selected_df["inv_vol"]
        ]
        sum_iv = sum(ivs)
        if sum_iv > 0:
            weights = [iv / sum_iv for iv in ivs]
        else:
            weights = [1.0 / n_selected] * n_selected

    items: List[RankItem] = []
    for rank_idx, ((_, row), w) in enumerate(zip(selected_df.iterrows(), weights)):
        item = RankItem(
            rank=int(row.get("rank", rank_idx + 1)),
            symbol=str(row.get("symbol", "")),
            name=str(row.get("name", "")),
            asset_type=str(row.get("asset_type", "STOCK")),
            momentum_20d=float(row.get("momentum_20d", 0.0)),
            inv_vol=float(row.get("inv_vol", 0.0)),
            trend_strength=float(row.get("trend_strength", 0.0)),
            composite_score=float(row.get("composite_score", 0.0)),
            target_weight=round(float(w), 6),
        )
        items.append(item)
    return items


class CrossAssetRanker:
    """Cross-asset momentum, risk, and trend strength ranking engine.

    Calibrates heterogeneous assets (equities and commodity futures) uniformly
    via non-parametric percentile ranking and produces Top-K selections with
    risk-balanced target weights.
    """

    def __init__(
        self,
        dataset: Any,
        momentum_weight: float = 0.5,
        inv_vol_weight: float = 0.3,
        trend_weight: float = 0.2,
        vol_floor: float = 0.08,
    ):
        self.dataset = dataset
        self.momentum_weight = momentum_weight
        self.inv_vol_weight = inv_vol_weight
        self.trend_weight = trend_weight
        self.vol_floor = vol_floor

    def select_top_k(
        self,
        ranked_df: pd.DataFrame,
        k: int = 10,
        weighting: str = "inverse_vol",
    ) -> List[RankItem]:
        """Delegate to standalone select_top_k."""
        return select_top_k(ranked_df, k=k, weighting=weighting)

    def rank_universe(
        self,
        as_of_date: str,
        window: int = 20,
        top_k: int = 10,
        weighting: str = "inverse_vol",
        allocation_mode: str = "unified",
        stock_sleeve_weight: float = 0.50,
        futures_sleeve_weight: float = 0.50,
        stock_top_k: int = 5,
        futures_top_k: int = 3,
        enable_futures_short: bool = False,
        futures_short_k: int = 2,
        futures_overlay_ratio: float = 1.0,
    ) -> RankResult:
        """Execute cross-asset ranking across all assets as of a given date.

        Args:
            as_of_date: Rebalance evaluation date string ('YYYY-MM-DD').
            window: Momentum and volatility lookback window (default 20 days).
            top_k: Number of highest ranking assets to extract (in unified mode).
            weighting: Target weighting model ('inverse_vol' or 'equal').
            allocation_mode: 'unified' (classic global Top-K) or 'dual_sleeve' (quota per asset class).
            stock_sleeve_weight: Capital weight allocated to stock sleeve in dual_sleeve mode.
            futures_sleeve_weight: Capital weight allocated to futures sleeve in dual_sleeve mode.
            stock_top_k: Number of stocks selected in dual_sleeve mode.
            futures_top_k: Number of futures selected in dual_sleeve mode.
            enable_futures_short: Whether to select bottom-ranking futures for shorting.
            futures_short_k: Number of futures selected for shorting.
            futures_overlay_ratio: Capital leverage multiplier for futures sleeve.

        Returns:
            RankResult containing full ranking table and selected Top-K items.
        """
        empty_df = pd.DataFrame(
            columns=[
                "rank",
                "symbol",
                "name",
                "asset_type",
                "momentum_20d",
                "inv_vol",
                "trend_strength",
                "composite_score",
                "target_weight",
            ]
        )
        if (
            self.dataset is None
            or not hasattr(self.dataset, "returns")
            or self.dataset.returns is None
            or self.dataset.returns.empty
        ):
            return RankResult(as_of_date=as_of_date, ranked_df=empty_df, selected_top_k=[])

        dt = pd.to_datetime(as_of_date)
        hist_returns = self.dataset.returns.loc[:dt]
        hist_prices = self.dataset.prices.loc[:dt]

        if len(hist_returns) < window:
            return RankResult(as_of_date=as_of_date, ranked_df=empty_df, selected_top_k=[])

        mom_df = calculate_compounded_20d_momentum(hist_returns, window=window)
        iv_df = calculate_inverse_volatility(
            hist_returns, window=window, floor=self.vol_floor
        )
        ctsi_df = calculate_ctsi(hist_prices, window=window)

        mom_latest = mom_df.iloc[-1]
        iv_latest = iv_df.iloc[-1]
        ctsi_latest = ctsi_df.iloc[-1]

        mom_pct = compute_cross_asset_percentile_rank(mom_latest)
        iv_pct = compute_cross_asset_percentile_rank(iv_latest)
        ctsi_pct = compute_cross_asset_percentile_rank(ctsi_latest)

        composite = (
            self.momentum_weight * mom_pct
            + self.inv_vol_weight * iv_pct
            + self.trend_weight * ctsi_pct
        )

        sorted_symbols = composite.sort_values(ascending=False).index.tolist()

        if allocation_mode == "dual_sleeve":
            # Separate stocks and futures
            stock_syms = []
            fut_syms = []
            for s in sorted_symbols:
                st = self.dataset.asset_types.get(s, "") if hasattr(self.dataset, "asset_types") and self.dataset.asset_types else ""
                if "FUTURES" in str(st).upper() or str(get_contract_spec(s).asset_type).upper().endswith("FUTURES"):
                    fut_syms.append(s)
                else:
                    stock_syms.append(s)

            sel_stocks = stock_syms[:stock_top_k]

            if enable_futures_short:
                sel_futs_long = fut_syms[:futures_top_k]
                sel_futs_short = [s for s in fut_syms[-futures_short_k:] if s not in sel_futs_long]
                selected_symbols = sel_stocks + sel_futs_long + sel_futs_short
            else:
                sel_futs_long = fut_syms[:futures_top_k]
                sel_futs_short = []
                selected_symbols = sel_stocks + sel_futs_long

            effective_fut_weight = futures_sleeve_weight * futures_overlay_ratio
            weights_map = {}

            # Stock weights
            if sel_stocks:
                if weighting == "equal":
                    for s in sel_stocks:
                        weights_map[s] = (stock_sleeve_weight / len(sel_stocks)) if sel_stocks else 0.0
                else:  # inverse_vol
                    iv_s = [float(iv_latest.get(s, 1.0)) for s in sel_stocks]
                    sum_iv_s = sum(iv_s) if sum(iv_s) > 0 else float(len(sel_stocks))
                    for s, iv in zip(sel_stocks, iv_s):
                        weights_map[s] = (iv / sum_iv_s) * stock_sleeve_weight

            # Futures weights
            if not enable_futures_short:
                if sel_futs_long:
                    if weighting == "equal":
                        for s in sel_futs_long:
                            weights_map[s] = (effective_fut_weight / len(sel_futs_long)) if sel_futs_long else 0.0
                    else:
                        iv_f = [float(iv_latest.get(s, 1.0)) for s in sel_futs_long]
                        sum_iv_f = sum(iv_f) if sum(iv_f) > 0 else float(len(sel_futs_long))
                        for s, iv in zip(sel_futs_long, iv_f):
                            weights_map[s] = (iv / sum_iv_f) * effective_fut_weight
            else:
                # Long/Short Hedge
                long_quota = effective_fut_weight * 0.5
                short_quota = effective_fut_weight * 0.5
                if sel_futs_long:
                    if weighting == "equal":
                        for s in sel_futs_long:
                            weights_map[s] = (long_quota / len(sel_futs_long))
                    else:
                        iv_fl = [float(iv_latest.get(s, 1.0)) for s in sel_futs_long]
                        sum_iv_fl = sum(iv_fl) if sum(iv_fl) > 0 else float(len(sel_futs_long))
                        for s, iv in zip(sel_futs_long, iv_fl):
                            weights_map[s] = (iv / sum_iv_fl) * long_quota
                if sel_futs_short:
                    if weighting == "equal":
                        for s in sel_futs_short:
                            weights_map[s] = -(short_quota / len(sel_futs_short))
                    else:
                        iv_fs = [float(iv_latest.get(s, 1.0)) for s in sel_futs_short]
                        sum_iv_fs = sum(iv_fs) if sum(iv_fs) > 0 else float(len(sel_futs_short))
                        for s, iv in zip(sel_futs_short, iv_fs):
                            weights_map[s] = -((iv / sum_iv_fs) * short_quota)
        else:
            selected_symbols = sorted_symbols[:top_k]
            # Weights on Top-K
            if weighting == "equal":
                weights_map = {
                    sym: (1.0 / len(selected_symbols) if len(selected_symbols) > 0 else 0.0)
                    for sym in selected_symbols
                }
            else:
                selected_iv = [float(iv_latest.get(sym, 1.0)) for sym in selected_symbols]
                sum_iv = sum(selected_iv) if sum(selected_iv) > 0 else float(len(selected_symbols))
                weights_map = {
                    sym: (float(iv_latest.get(sym, 1.0)) / sum_iv) if sum_iv > 0 else 0.0
                    for sym in selected_symbols
                }

        items: List[RankItem] = []
        ranked_rows = []

        for idx, sym in enumerate(sorted_symbols):
            # Asset type from dataset if provided, else from contract spec
            dataset_type = None
            if hasattr(self.dataset, "asset_types") and isinstance(self.dataset.asset_types, dict):
                dataset_type = self.dataset.asset_types.get(sym)

            spec = get_contract_spec(sym)
            asset_type_val = dataset_type or (
                spec.asset_type.value if hasattr(spec.asset_type, "value") else str(spec.asset_type)
            )

            score = float(composite.get(sym, 0.0))
            is_top_k = sym in selected_symbols
            weight = weights_map.get(sym, 0.0) if is_top_k else 0.0

            item = RankItem(
                rank=idx + 1,
                symbol=sym,
                name=spec.name,
                asset_type=asset_type_val,
                momentum_20d=float(mom_latest.get(sym, 0.0)),
                inv_vol=float(iv_latest.get(sym, 0.0)),
                trend_strength=float(ctsi_latest.get(sym, 0.0)),
                composite_score=score,
                target_weight=round(weight, 6),
                side="SHORT" if weight < 0 else "LONG",
            )
            ranked_rows.append(item.__dict__)
            if is_top_k:
                items.append(item)

        ranked_df = pd.DataFrame(ranked_rows)
        return RankResult(as_of_date=as_of_date, ranked_df=ranked_df, selected_top_k=items)


def rank_cross_asset_universe(
    dataset: Any,
    as_of_date: str,
    window: int = 20,
    top_k: int = 10,
    momentum_weight: float = 0.5,
    inv_vol_weight: float = 0.3,
    trend_weight: float = 0.2,
    vol_floor: float = 0.08,
    weighting: str = "inverse_vol",
) -> RankResult:
    """Convenience functional wrapper to instantiate ranker and rank universe."""
    ranker = CrossAssetRanker(
        dataset=dataset,
        momentum_weight=momentum_weight,
        inv_vol_weight=inv_vol_weight,
        trend_weight=trend_weight,
        vol_floor=vol_floor,
    )
    return ranker.rank_universe(
        as_of_date=as_of_date, window=window, top_k=top_k, weighting=weighting
    )
