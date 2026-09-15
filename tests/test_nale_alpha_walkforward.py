"""Walk-forward scheduling fixtures; no market-performance inference."""

import numpy as np
import pandas as pd
import pytest

from src.analysis.nale_alpha_walkforward import WalkForwardConfig, plan_dates, run_walkforward
from src.graph.nale_alpha_network import make_network_snapshot


def _fixture():
    calendar = tuple(pd.bdate_range("2024-06-20", periods=26).strftime("%Y-%m-%d"))
    codes = ("000001", "000002", "000003")
    ledger = []
    for source, target in (("000001", "000002"), ("000002", "000003"), ("000003", "000001")):
        ledger.append({
            "source_code": source, "target_code": target, "weight": 1.0,
            "source_published_at": calendar[0] + "T10:00:00+08:00",
            "available_at": calendar[0] + "T14:00:00+08:00",
            "valid_from": calendar[0], "valid_to": None,
            "evidence_id": "fixture-edge-" + source + "-" + target,
            "relationship_version": "v1", "is_observed": False,
        })
    edges = pd.DataFrame(ledger)
    networks = {
        day: make_network_snapshot(
            edges, codes, day + "T15:10:00+08:00",
            graph_history_id="fixture-ledger-v1", allow_fixture=True,
        ) for day in calendar
    }
    rows = []
    for day_index, day in enumerate(calendar):
        next_day = calendar[min(day_index + 1, len(calendar) - 1)]
        for code_index, code in enumerate(codes):
            s0 = 0.1 * (code_index - 1) + day_index * 0.003
            neighbor = 0.1 * (((code_index + 2) % 3) - 1) + day_index * 0.003
            difference = neighbor - s0
            row = {
                "date": day, "code": code,
                "signal_at": day + "T15:10:00+08:00",
                "label_available_at": next_day + "T18:00:00+08:00",
                "s0": s0,
                "y_excess": 0.01 + 0.4 * (s0 + 0.45 * difference),
                "pca_version": "fixture-pca10",
                "feature_source_id": "fixture-embedding",
                "network_evidence_id": "fixture-ledger-v1",
                "price_source_id": "fixture-prices",
                "evidence_class": "engineering_fixture",
            }
            for component in range(1, 11):
                row[f"PC{component:02d}"] = (code_index - 1) * 0.2 + day_index * 0.01 + component * 0.001
            rows.append(row)
    config = WalkForwardConfig(
        train_days=4, validation_days=15, test_days=5, purge_days=1,
        ridge_v1=0.01, ridge_v2=0.01, ridge_v3=0.01, half_life_days=20,
    )
    return pd.DataFrame(rows), networks, calendar, config


def test_calendar_split_is_predeclared_and_purged():
    _, _, calendar, config = _fixture()
    plan = plan_dates(calendar, config)
    assert plan.train_dates == calendar[:4]
    assert plan.purged_after_train == calendar[4:5]
    assert plan.validation_dates == calendar[5:20]
    assert plan.purged_after_validation == calendar[20:21]
    assert plan.test_dates == calendar[21:26]
    assert plan.to_dict()["test_dates"] == list(plan.test_dates)
    with pytest.raises(ValueError, match="insufficient"):
        plan_dates(calendar[:10], config)


def test_validation_predictions_and_monthly_v1_freeze():
    panel, networks, calendar, config = _fixture()
    result = run_walkforward(panel, networks, calendar, config, phase="validation", allow_fixture=True)
    assert len(result.predictions) == 15 * 3 * 4
    assert set(result.predictions["version"]) == {"B0", "V1", "V2", "V3"}
    assert set(result.predictions["date"]) == set(result.date_plan.validation_dates)
    assert result.evidence_class == "engineering_fixture"
    assert (result.predictions["training_cutoff"] < result.predictions["label_available_at"]).all()
    assert ((result.predictions["alpha_nale"] >= 0.05) & (result.predictions["alpha_nale"] <= 0.75)).all()
    assert (result.predictions.loc[result.predictions["version"] == "B0", "alpha_nale"] == 0.4).all()
    assert result.predictions["edge_evidence_ids"].str.contains("fixture-edge").all()
    assert len(result.monthly_weights.loc[result.monthly_weights["version"] == "V1"]) >= 2
    v1 = result.monthly_weights.loc[result.monthly_weights["version"] == "V1"]
    assert v1["gate_fit_cutoff"].nunique() == 1
    for component in range(1, 11):
        assert v1[f"w{component:02d}"].nunique() == 1
    for _, month in result.monthly_weights.groupby("fit_cutoff"):
        assert month["calibration_a"].nunique() == 1
        assert month["calibration_c"].nunique() == 1


def test_future_test_labels_do_not_change_validation_predictions():
    panel, networks, calendar, config = _fixture()
    first = run_walkforward(panel, networks, calendar, config, phase="validation", allow_fixture=True)
    changed = panel.copy()
    changed.loc[changed["date"].isin(first.date_plan.test_dates), "y_excess"] += 100.0
    second = run_walkforward(changed, networks, calendar, config, phase="validation", allow_fixture=True)
    pd.testing.assert_frame_equal(first.predictions, second.predictions)
    test = run_walkforward(panel, networks, calendar, config, phase="test", allow_fixture=True)
    assert set(test.predictions["date"]) == set(test.date_plan.test_dates)
    assert len(test.predictions) == 5 * 3 * 4


def test_unmatured_training_label_and_mismatched_evidence_fail_closed():
    panel, networks, calendar, config = _fixture()
    plan = plan_dates(calendar, config)
    late = panel.copy()
    late.loc[late["date"] == plan.train_dates[-1], "label_available_at"] = plan.validation_dates[0] + "T09:30:00+08:00"
    with pytest.raises(ValueError, match="mature training"):
        run_walkforward(late, networks, calendar, config, phase="validation", allow_fixture=True)
    changed_version = panel.copy()
    changed_version.loc[0, "pca_version"] = "pca-after-test"
    with pytest.raises(ValueError, match="PCA version"):
        run_walkforward(changed_version, networks, calendar, config, phase="validation", allow_fixture=True)
    wrong_graph = panel.copy()
    wrong_graph.loc[0, "network_evidence_id"] = "some-other-graph"
    with pytest.raises(ValueError, match="network_evidence_id"):
        run_walkforward(wrong_graph, networks, calendar, config, phase="validation", allow_fixture=True)
    with pytest.raises(ValueError, match="verified evidence"):
        run_walkforward(panel, networks, calendar, config, phase="validation")


def test_validation_runs_with_future_rows_and_networks_withheld():
    panel, networks, calendar, config = _fixture()
    plan = plan_dates(calendar, config)
    full = run_walkforward(panel, networks, calendar, config, phase="validation", allow_fixture=True)
    cutoff_day = plan.validation_dates[-1]
    visible_panel = panel.loc[panel["date"] <= cutoff_day]
    visible_networks = {day: snapshot for day, snapshot in networks.items() if day <= cutoff_day}
    blinded = run_walkforward(
        visible_panel, visible_networks, calendar, config,
        phase="validation", allow_fixture=True,
    )
    pd.testing.assert_frame_equal(full.predictions, blinded.predictions)
    pd.testing.assert_frame_equal(full.monthly_weights, blinded.monthly_weights)
    with pytest.raises(ValueError, match="prediction date"):
        run_walkforward(
            visible_panel, visible_networks, calendar, config,
            phase="test", allow_fixture=True,
        )
