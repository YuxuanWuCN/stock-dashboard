# -*- coding: utf-8 -*-
"""
tests/test_adversarial_m4_data_provenance.py

Adversarial Data & Provenance Stress-Test Suite
Authored by: teamwork_preview_challenger (M4 Data Challenger)

Empirical Challenge Objectives:
1. Verify raw crawled corpus in data/raw/student_ac_crawled/:
   Every stock's recorded input_sha256 must exactly match the re-computed SHA256
   hash of its raw JSONL content.
2. Verify uniqueness across all 300 stocks:
   Zero duplicate input_sha256 hashes, zero duplicate llm_summary strings (no template collapse).
3. Verify string code preservation:
   All stock codes across CSV and JSON files retain 6-digit zero-padded string format.
4. Verify vector properties across all 300 stocks:
   No constant / zero-variance dimensions, full rank, no identical vectors,
   and all adjacent and pairwise cosine similarities strictly < 0.9999.
5. Verify cohort harmonization & schema compliance:
   300x780 matrix, partition integrity (A, B, C), positive announcement counts,
   and zero fake 'local_semantic' features.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Set

import numpy as np
import pandas as pd
import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
CRAWLED_DIR = DATA_DIR / "raw" / "student_ac_crawled"
TASK_SPLIT_DIR = DATA_DIR / "task_split"
REGRESSION_DIR = ROOT_DIR / "reports" / "tables" / "regression_768d"

RE_CODE = re.compile(r"^\d{6}$")
RE_SHA256 = re.compile(r"^[a-f0-9]{64}$")
DIM_COLS = [f"dim_{i:03d}" for i in range(768)]
EXPECTED_780_COLS = [
    "code", "name", "sub_industry", "sector", "cohort_key",
    "feature_source", "embedding_source", "news_count",
    "announcement_count", "input_sha256", "retrieved_at_utc", "llm_summary"
] + DIM_COLS


class TestAdversarialRawCrawlProvenance:
    """Stress-test 1: Re-compute SHA256 hashes from raw JSONL and verify 100% match."""

    def test_recomputed_sha256_matches_meta_and_manifest(self):
        meta_files = sorted(CRAWLED_DIR.glob("*.meta.json"))
        assert len(meta_files) == 200, f"Expected 200 meta files, found {len(meta_files)}"

        manifest_path = CRAWLED_DIR / "manifest.json"
        assert manifest_path.exists(), "manifest.json missing"
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_hashes = {item["code"]: item["input_sha256"] for item in manifest_data["stocks"]}

        mismatches = []
        for mf in meta_files:
            code = mf.stem.split(".")[0]
            assert RE_CODE.match(code), f"Meta file stem '{code}' not 6 digits"
            meta = json.loads(mf.read_text(encoding="utf-8"))
            expected_sha = meta.get("input_sha256", "").strip().lower()
            assert RE_SHA256.match(expected_sha), f"[{code}] Invalid recorded sha: '{expected_sha}'"

            # Check JSONL file exists
            jsonl_path = CRAWLED_DIR / f"{code}.jsonl"
            assert jsonl_path.exists(), f"Missing jsonl for {code}"

            # Parse lines and canonically dump
            lines = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            assert len(lines) == meta.get("total_items"), (
                f"[{code}] Item count mismatch: jsonl={len(lines)} vs meta={meta.get('total_items')}"
            )

            canonical = json.dumps(lines, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            calc_sha = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

            if calc_sha != expected_sha:
                mismatches.append((code, "meta_hash", expected_sha, calc_sha))

            man_sha = manifest_hashes.get(code)
            if man_sha != expected_sha:
                mismatches.append((code, "manifest_hash", expected_sha, man_sha))

        assert len(mismatches) == 0, f"SHA256 mismatches found: {mismatches}"

    def test_recomputed_sha256_matches_provenance_json_and_csv(self):
        prov_a_path = TASK_SPLIT_DIR / "factors_768d_student_A_provenance.json"
        prov_c_path = TASK_SPLIT_DIR / "factors_768d_student_C_provenance.json"
        assert prov_a_path.exists() and prov_c_path.exists()

        prov_a = json.loads(prov_a_path.read_text(encoding="utf-8"))
        prov_c = json.loads(prov_c_path.read_text(encoding="utf-8"))
        prov_hashes = {item["code"]: item["input_sha256"] for item in prov_a["provenance"] + prov_c["provenance"]}

        df_a = pd.read_csv(TASK_SPLIT_DIR / "factors_768d_student_A.csv", dtype={"code": str})
        df_c = pd.read_csv(TASK_SPLIT_DIR / "factors_768d_student_C.csv", dtype={"code": str})
        df_all = pd.read_csv(TASK_SPLIT_DIR / "factors_768d_all.csv", dtype={"code": str})

        csv_ac_hashes = dict(zip(df_a["code"], df_a["input_sha256"]))
        csv_ac_hashes.update(dict(zip(df_c["code"], df_c["input_sha256"])))
        all_hashes = dict(zip(df_all["code"], df_all["input_sha256"]))

        for mf in sorted(CRAWLED_DIR.glob("*.meta.json")):
            code = mf.stem.split(".")[0]
            meta = json.loads(mf.read_text(encoding="utf-8"))
            expected_sha = meta["input_sha256"]

            assert prov_hashes.get(code) == expected_sha, f"[{code}] Provenance JSON hash mismatch"
            assert csv_ac_hashes.get(code) == expected_sha, f"[{code}] Student CSV hash mismatch"
            assert all_hashes.get(code) == expected_sha, f"[{code}] factors_768d_all.csv hash mismatch"


class TestAdversarialUniqueness:
    """Stress-test 2: Uniqueness of input_sha256 and llm_summary across 300 stocks."""

    def test_uniqueness_across_300_stocks(self):
        df = pd.read_csv(TASK_SPLIT_DIR / "factors_768d_all.csv", dtype={"code": str})
        assert len(df) == 300

        # Codes
        assert df["code"].nunique() == 300, "Found duplicate stock codes"

        # Input SHA256 hashes
        dup_shas = df[df.duplicated("input_sha256", keep=False)]
        assert len(dup_shas) == 0, f"Found duplicate SHA256 hashes: {dup_shas['input_sha256'].tolist()}"

        # LLM Summaries
        dup_summaries = df[df.duplicated("llm_summary", keep=False)]
        assert len(dup_summaries) == 0, (
            f"Found {len(dup_summaries)} duplicate llm_summary rows (template collapse): "
            f"{dup_summaries[['code', 'name', 'cohort_key']].to_dict('records')}"
        )

    def test_summary_text_diversity(self):
        """Verify that summaries are not trivially parameterized templates."""
        df = pd.read_csv(TASK_SPLIT_DIR / "factors_768d_all.csv", dtype={"code": str})
        summaries = df["llm_summary"].tolist()

        # Check lengths
        lengths = [len(s) for s in summaries]
        assert all(l >= 100 for l in lengths), "Some summaries are too short (<100 chars)"

        # Check vocabulary richness
        unique_start_chars = set(s[:20] for s in summaries)
        assert len(unique_start_chars) > 50, "Low summary beginning diversity"


class TestAdversarialStringCodePreservation:
    """Stress-test 3: Verify all codes with leading zeros are preserved across CSV/JSON."""

    def test_all_leading_zero_codes_preserved(self):
        re_code = re.compile(r"^\d{6}$")
        leading_zero_count = 0
        total_codes = 0
        violations = []

        def inspect_code(val: Any, loc: str):
            nonlocal leading_zero_count, total_codes
            s = str(val).strip()
            total_codes += 1
            if not re_code.match(s):
                violations.append((loc, s))
            elif s.startswith("0"):
                leading_zero_count += 1

        # Check CSVs in task_split
        for csv_path in TASK_SPLIT_DIR.glob("*.csv"):
            with open(csv_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                col = "code" if "code" in reader.fieldnames else ("stock_code" if "stock_code" in reader.fieldnames else None)
                if col:
                    for idx, row in enumerate(reader):
                        inspect_code(row[col], f"{csv_path.name}:row_{idx}")

        # Check JSON files in task_split
        for json_path in TASK_SPLIT_DIR.glob("*.json"):
            data = json.loads(json_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for p_item in data.get("provenance", []):
                    if "code" in p_item:
                        inspect_code(p_item["code"], f"{json_path.name}:prov")

        # Check meta.json files
        for meta_path in CRAWLED_DIR.glob("*.meta.json"):
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            inspect_code(data.get("code"), f"{meta_path.name}")

        # Check manifest.json
        manifest_path = CRAWLED_DIR / "manifest.json"
        if manifest_path.exists():
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            for s in data.get("stocks", []):
                inspect_code(s.get("code"), "manifest.json:stocks")

        # Check regression CSVs
        for csv_path in REGRESSION_DIR.glob("*.csv"):
            with open(csv_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                col = "code" if "code" in reader.fieldnames else ("stock_code" if "stock_code" in reader.fieldnames else None)
                if col:
                    for idx, row in enumerate(reader):
                        inspect_code(row[col], f"{csv_path.name}:row_{idx}")

        assert len(violations) == 0, f"Truncated / invalid codes found: {violations[:10]}"
        assert leading_zero_count > 500, f"Expected >500 leading zero codes verified, found {leading_zero_count}"


class TestAdversarialVectorProperties:
    """Stress-test 4: Vector variance, rank, uniqueness, and cosine similarities."""

    @pytest.fixture(scope="class")
    @classmethod
    def factor_matrix(cls):
        df = pd.read_csv(TASK_SPLIT_DIR / "factors_768d_all.csv", dtype={"code": str})
        vecs = df[DIM_COLS].values.astype(np.float64)
        return df, vecs

    def test_vector_normalization_and_finiteness(self, factor_matrix):
        df, vecs = factor_matrix
        assert not np.isnan(vecs).any(), "NaN values found in factor matrix"
        assert not np.isinf(vecs).any(), "Inf values found in factor matrix"

        norms = np.linalg.norm(vecs, axis=1)
        max_dev = np.max(np.abs(norms - 1.0))
        assert max_dev < 1e-6, f"L2 norm deviation too high: {max_dev}"

    def test_dimension_variance_and_non_constancy(self, factor_matrix):
        df, vecs = factor_matrix
        variances = np.var(vecs, axis=0)

        # No dimension has exactly zero variance
        zero_var = np.where(variances == 0.0)[0]
        assert len(zero_var) == 0, f"Zero variance dimensions found: {zero_var}"

        # No dimension is constant (max == min)
        mins = np.min(vecs, axis=0)
        maxs = np.max(vecs, axis=0)
        constant_dims = np.where(mins == maxs)[0]
        assert len(constant_dims) == 0, f"Constant dimensions found: {constant_dims}"

        # Every dimension must take distinct values across stocks
        for i in range(768):
            u = len(np.unique(vecs[:, i]))
            assert u >= 200, f"Dimension {DIM_COLS[i]} has only {u} unique values"

    def test_matrix_rank_full_row_rank(self, factor_matrix):
        df, vecs = factor_matrix
        rank = np.linalg.matrix_rank(vecs)
        assert rank == 300, f"Matrix rank {rank} is not full rank (expected 300)"

    def test_pairwise_and_adjacent_cosine_similarities(self, factor_matrix):
        df, vecs = factor_matrix
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        normed = vecs / norms

        # Pairwise cosine similarity matrix
        cos_matrix = np.dot(normed, normed.T)
        np.fill_diagonal(cos_matrix, -1.0)
        max_pairwise_sim = float(np.max(cos_matrix))

        assert max_pairwise_sim < 0.9999, (
            f"Max pairwise cosine similarity {max_pairwise_sim:.6f} >= 0.9999 (near-identical vectors exist!)"
        )
        assert max_pairwise_sim < 0.98, (
            f"Max pairwise cosine similarity {max_pairwise_sim:.6f} surprisingly high (expected < 0.98)"
        )

        # Adjacent cosine similarities
        adj_sims = np.array([float(np.dot(normed[i], normed[i+1])) for i in range(len(normed)-1)])
        max_adj_sim = float(np.max(adj_sims))
        assert max_adj_sim < 0.9999, f"Adjacent cosine similarity {max_adj_sim:.6f} >= 0.9999"
        assert max_adj_sim < 0.95, f"Adjacent cosine similarity {max_adj_sim:.6f} >= 0.95"


class TestAdversarialCohortHarmonization:
    """Stress-test 5: Schema 780 columns, cohort partitions, announcement count > 0."""

    def test_cohort_disjoint_and_complete(self):
        df_a = pd.read_csv(TASK_SPLIT_DIR / "factors_768d_student_A.csv", dtype={"code": str})
        df_b = pd.read_csv(TASK_SPLIT_DIR / "factors_768d_student_B.csv", dtype={"code": str})
        df_c = pd.read_csv(TASK_SPLIT_DIR / "factors_768d_student_C.csv", dtype={"code": str})
        df_all = pd.read_csv(TASK_SPLIT_DIR / "factors_768d_all.csv", dtype={"code": str})

        for name, d in [("A", df_a), ("B", df_b), ("C", df_c), ("All", df_all)]:
            assert d.shape[1] == 780, f"{name} columns expected 780, got {d.shape[1]}"
            assert list(d.columns) == EXPECTED_780_COLS, f"{name} column mismatch"

        assert len(df_a) == 100
        assert len(df_b) == 100
        assert len(df_c) == 100
        assert len(df_all) == 300

        ca, cb, cc, call = set(df_a["code"]), set(df_b["code"]), set(df_c["code"]), set(df_all["code"])
        assert len(ca & cb) == 0, "A and B overlap"
        assert len(cb & cc) == 0, "B and C overlap"
        assert len(ca & cc) == 0, "A and C overlap"
        assert (ca | cb | cc) == call, "Union does not match All"

    def test_zero_fake_data_and_positive_announcements(self):
        df = pd.read_csv(TASK_SPLIT_DIR / "factors_768d_all.csv", dtype={"code": str})
        # Zero fake local_semantic
        bad_sources = df[df["feature_source"].str.contains("local_semantic", case=False, na=False)]
        assert len(bad_sources) == 0, f"Fake local_semantic source found: {len(bad_sources)}"

        # Positive announcement count
        zero_ann = df[df["announcement_count"] <= 0]
        assert len(zero_ann) == 0, f"Announcement count <= 0 found for {len(zero_ann)} stocks"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

