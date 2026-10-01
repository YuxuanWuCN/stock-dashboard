import pandas as pd

from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path


MODULE = Path(__file__).parents[1] / "03_算法模型与回测" / "backtest" / "top3_surplus_rotation.py"
spec = spec_from_file_location("top3_surplus_rotation", MODULE)
rotation = module_from_spec(spec)
spec.loader.exec_module(rotation)


def test_top3_uses_only_current_day_rank_and_next_day_return():
    panel = pd.DataFrame([
        {"date": "2025-06-02", "symbol": "S1", "asset_type": "stock", "expected_surplus_pct": 9, "next_return_pct": -10},
        {"date": "2025-06-02", "symbol": "S2", "asset_type": "stock", "expected_surplus_pct": 8, "next_return_pct": 4},
        {"date": "2025-06-02", "symbol": "F1", "asset_type": "futures", "expected_surplus_pct": 7, "next_return_pct": 6},
        {"date": "2025-06-03", "symbol": "S1", "asset_type": "stock", "expected_surplus_pct": 1, "next_return_pct": 2},
        {"date": "2025-06-03", "symbol": "F1", "asset_type": "futures", "expected_surplus_pct": 3, "next_return_pct": 5},
    ])
    result = rotation.compare_top3(panel, top_n=1)
    mixed = result["metrics"]["mixed_top3"]
    assert round(mixed["total_return_pct"], 6) == -5.5
    assert result["metrics"]["switching"]["weak_stock_days"] == 1
    assert result["metrics"]["switching"]["weak_stock_days_with_futures"] == 0


def test_mixed_top3_switches_to_futures_when_they_rank_higher():
    panel = pd.DataFrame([
        {"date": "2025-06-02", "symbol": "S1", "asset_type": "stock", "expected_surplus_pct": 1, "next_return_pct": -4},
        {"date": "2025-06-02", "symbol": "F1", "asset_type": "futures", "expected_surplus_pct": 5, "next_return_pct": 3},
        {"date": "2025-06-03", "symbol": "S1", "asset_type": "stock", "expected_surplus_pct": 1, "next_return_pct": 0},
        {"date": "2025-06-03", "symbol": "F1", "asset_type": "futures", "expected_surplus_pct": 5, "next_return_pct": 0},
    ])
    result = rotation.compare_top3(panel, top_n=1, weak_stock_threshold_pct=-0.1)
    switching = result["metrics"]["switching"]
    assert switching["weak_stock_days"] == 1
    assert switching["weak_stock_days_with_futures"] == 1
    assert switching["average_futures_weight_on_weak_stock_days_pct"] == 100.0
    assert switching["weak_stock_months"] == 1
    assert switching["weak_stock_months_with_futures"] == 1
