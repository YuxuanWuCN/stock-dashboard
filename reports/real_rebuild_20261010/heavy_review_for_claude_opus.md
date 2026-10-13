# Heavy Review Package for Claude Code / Opus 5.5

## Scope

Please independently review the latest full Heavy gate result and the current worktree. Do not trust the orchestrator summary alone. Do not commit.

## Latest Heavy Result

Report: `.quality-state/reports/20261012222035-heavy-c9b4bf.md`

- Source hash: `2b7acd427f911ebab1da0ca339e60d38e206f486428043b5dacfbc319fb88fce`
- Result: FAIL
- Total: 15 failed, 1943 passed, 2011 warnings, 15 subtests
- Heavy report says `秘密扫描` failed because `tests/test_server_config_and_scheduler.py` matches `\\bsk-[A-Za-z0-9_-]{20,}\\b`.
- Full regression failures:
  1. `tests/test_adversarial_m4_data_provenance.py::TestAdversarialRawCrawlProvenance::test_recomputed_sha256_matches_provenance_json_and_csv`
  2. `tests/test_data_adapter.py::test_unified_data_adapter_factors`
  3. `tests/test_data_adapter.py::test_market_data_packet_assembly`
  4. `tests/test_factor_providers.py::test_kenneth_french_provider_fallback`
  5. `tests/test_factor_providers.py::test_eastmoney_miaoxiang_provider`
  6. `tests/test_sector_graph_missing_corr.py::test_missing_corr_matrix_rejects_all_peers_and_never_follows`
  7. `tests/test_sector_graph_missing_corr.py::test_nan_corr_rows_are_treated_as_missing_evidence`
  8. `tests/test_sector_graph_missing_corr.py::test_unknown_code_absent_from_matrix_is_missing_not_half`
  9. `tests/test_sector_graph_missing_corr.py::test_negative_corr_is_not_promoted_to_peers`
  10. `tests/test_sector_graph_missing_corr.py::test_real_high_corr_still_produces_follower_catchup`
  11. `tests/test_sector_graph_missing_corr.py::test_missing_evidence_count_uses_group_members_not_matrix`
  12. `tests/test_storage_supercycle_pipeline.py::test_full_storage_supercycle_backtest_pipeline` (Sharpe exactly 1.0, assertion requires >1.0)
  13. `tests/test_truncation_invariance.py::test_zigzag_confirmation_lag_strictly_causal`
  14. `tests/test_truncation_invariance.py::test_biwin_688525_confirmation_lag`
  15. `tests/test_validate_teacher_framework.py::test_load_kline_shape` (fixture now 261 rows, assertion requires >=267)

## Important Context

- P4-specific test suite currently passes 40/40.
- Quality small and medium passed before Heavy.
- M4/P4 source and quantitative JSON were not intentionally changed during this direct Heavy run.
- Do not weaken assertions or fabricate data to force Heavy green.
- Missing optional dependencies and data caches are likely environment issues, but the three failures in storage backtest/ZigZag/kline fixture require independent review because they may indicate real regressions or stale assumptions.
- The secret scan hit may be a test fixture false positive; inspect the exact line and determine whether it is a literal example or an actual secret. Do not simply suppress the scanner.

## Requested Opus Review

1. Classify each of the 15 failures and the secret-scan finding as: real code regression, stale test/fixture contract, missing dependency/data, or scanner false positive.
2. Check whether any failure is caused by this M4/P4 worktree diff.
3. Recommend minimal fixes only where justified; no synthetic data, no weakened production safeguards, no commit.
4. Verify `tests/test_p4_real_quant.py` remains green.
5. Report whether Heavy can honestly be called passed, or remains blocked, with evidence.
