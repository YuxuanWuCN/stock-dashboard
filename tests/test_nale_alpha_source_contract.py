"""Small engineering source fixtures; not observed market input."""

import pandas as pd

from src.data.nale_alpha_source_contract import (
    CandidateSources, EMBEDDING_COLUMNS, SourceClaim, audit_candidate_sources,
)


def _sources():
    dates = ["2026-01-05", "2026-01-06", "2026-01-07"]
    pairs = [(day, code) for day in dates for code in ("000001", "000002")]
    cutoff = lambda day: f"{day}T20:00:00+08:00"
    common = [{"date": day, "code": code, "available_at": f"{day}T16:00:00+08:00",
               "decision_cutoff": cutoff(day), "source_id": "fixture-source"} for day, code in pairs]
    prices = pd.DataFrame([{**row, "close": 10.0, "volume": 1000, "trade_status": "open",
                            "limit_status": "normal", "adjustment_basis": "adjusted"} for row in common])
    benchmark = pd.DataFrame([{"date": day, "close": 100.0, "available_at": f"{day}T16:00:00+08:00",
                               "decision_cutoff": cutoff(day), "source_id": "fixture-source"} for day in dates])
    features = pd.DataFrame([{**row, "source_doc_id": "fixture-doc", "source_revision_id": "v1",
                              "source_published_at": "2026-01-01T10:00:00+08:00", "embedding_version": "fixture-v1",
                              **{name: 0.1 for name in EMBEDDING_COLUMNS}} for row in common])
    scores = pd.DataFrame([{**row, "S0": 0.2, "score_version": "fixture-v1"} for row in common])
    edges = pd.DataFrame([{"target_code": "000001", "neighbor_code": "000002", "weight": 1.0,
                           "valid_from": "2026-01-05", "valid_to": None,
                           "available_at": "2026-01-04T16:00:00+08:00",
                           "source_id": "fixture-source", "source_revision_id": "v1"}])
    claims = {name: SourceClaim("observed", "fixture-provider", "fixture://source", "a" * 64)
              for name in ("prices", "benchmark", "features", "scores", "edges")}
    return CandidateSources(prices, benchmark, features, scores, edges, claims)


def test_structural_pass_never_certifies_source_authenticity():
    result = audit_candidate_sources(_sources(), minimum_stocks=2, minimum_days=3)
    assert result.status == "STRUCTURAL_PASS_PROVENANCE_UNVERIFIED"
    assert result.stock_count == 2 and result.signal_day_count == 3
    assert not result.source_claims_verified


def test_synthetic_claim_and_future_feature_fail_closed():
    sources = _sources()
    sources.claims["prices"] = SourceClaim("synthetic", "fixture", "fixture://source", "a" * 64)
    sources.features.loc[0, "available_at"] = "2026-01-06T09:00:00+08:00"
    result = audit_candidate_sources(sources, minimum_stocks=2, minimum_days=3)
    assert result.status == "BLOCKED"
    assert any("synthetic" in issue for issue in result.issues)
    assert any("future-available" in issue for issue in result.issues)


def test_duplicate_price_key_fails_closed():
    sources = _sources()
    sources.prices.loc[1, "code"] = "000001"
    result = audit_candidate_sources(sources, minimum_stocks=2, minimum_days=3)
    assert result.status == "BLOCKED"
    assert any("duplicate" in issue for issue in result.issues)


def test_missing_embedding_fails_closed():
    sources = _sources()
    sources.features.drop(columns=["embedding_767"], inplace=True)
    result = audit_candidate_sources(sources, minimum_stocks=2, minimum_days=3)
    assert result.status == "BLOCKED"
    assert any("embedding_767" in issue for issue in result.issues)
