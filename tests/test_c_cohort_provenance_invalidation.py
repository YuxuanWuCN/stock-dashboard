# -*- coding: utf-8 -*-
"""tests/test_c_cohort_provenance_invalidation.py —— C 组 768 维溯源作废事实的**可执行冻结**。

背景（详见 `reports/tables/pca_nale_integration/C_PROVENANCE_INVALIDATION.md`）：
C 组 100 支 768 维向量的输入语料在仓库与 GitHub 全域均不存在，因子表声明的公告数（172,968）
是盘上实有（36,255）的 4.77 倍。配方本身正确（A 组三方 100/100 自洽），缺的是输入。

本文件的作用是**把"作废"变成断言**，而不是写一段说明就完事：

* 若有人为了"让 heavy 变绿"改写 C 组因子表的哈希去凑 sidecar，本测试会**立刻失败**
  （因为断言 C 组表与盘上不一致的计数必须为 0/100）；
* 将来真正补全输入（三条解除条件）后，也必须由人工显式更新本测试与那份说明——这正是设计目的。

刻意不复用其它测试的夹具：直接读取盘上真实语料与因子表，按 PR5 生成脚本
`scripts/generate_student_c_768d_strict.py::_corpus_hash` 的配方独立重算。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
CRAWLED = ROOT / "data/raw/student_ac_crawled"
TASK_SPLIT = ROOT / "data/task_split"
NOTICE = ROOT / "reports/tables/pca_nale_integration/C_PROVENANCE_INVALIDATION.md"

#: 作废说明中引用的实测数字（改动说明即须同步改这里，形成人工确认点）。
EXPECTED_A_ANNOUNCEMENTS = 40999
EXPECTED_A_NEWS = 980
EXPECTED_A_TOTAL_ITEMS = 41979
EXPECTED_C_SIDECAR_ANNOUNCEMENTS = 36255
EXPECTED_C_TABLE_ANNOUNCEMENTS = 172968
EXPECTED_C_SIDECAR_NEWS = 991
EXPECTED_C_TABLE_NEWS = 0
EXPECTED_C_TOTAL_ITEMS = 37246


def corpus_hash(lines: list[dict]) -> str:
    """PR5 生成脚本使用的规范化哈希（逐字复刻，不改动）。"""
    canonical = json.dumps(lines, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _metadata() -> tuple[dict[str, dict], dict[str, int], dict[str, str]]:
    """读 sidecar、逐支记录数、按盘上语料重算的哈希。"""
    sidecars: dict[str, dict] = {}
    items: dict[str, int] = {}
    recomputed: dict[str, str] = {}
    for path in sorted(CRAWLED.glob("*.meta.json")):
        code = path.name.split(".")[0]
        sidecars[code] = json.loads(path.read_text(encoding="utf-8"))
        jsonl = CRAWLED / f"{code}.jsonl"
        lines = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
        items[code] = len(lines)
        recomputed[code] = corpus_hash(lines)
    return sidecars, items, recomputed


def _table(cohort_letter: str) -> pd.DataFrame:
    return pd.read_csv(TASK_SPLIT / f"factors_768d_student_{cohort_letter}.csv", dtype={"code": str})


def _three_way(cohort: str) -> dict[str, object]:
    """三方一致性计数与条数合计（cohort 形如 student_A / student_C）。"""
    sidecars, items, recomputed = _metadata()
    codes = sorted(code for code, meta in sidecars.items() if str(meta.get("cohort")) == cohort)
    table = _table(cohort[-1])
    table_hash = dict(zip(table["code"], table["input_sha256"].astype(str).str.lower()))
    table_ann = dict(zip(table["code"], table["announcement_count"].astype(float).astype(int)))
    table_news = dict(zip(table["code"], table["news_count"].astype(float).astype(int)))
    return {
        "codes": codes,
        "recomputed_eq_sidecar": sum(1 for code in codes if recomputed[code] == str(sidecars[code]["input_sha256"]).lower()),
        "table_eq_sidecar": sum(1 for code in codes if table_hash.get(code) == str(sidecars[code]["input_sha256"]).lower()),
        "table_eq_recomputed": sum(1 for code in codes if table_hash.get(code) == recomputed[code]),
        "sidecar_ann": sum(int(sidecars[code].get("announcement_count", -1)) for code in codes),
        "table_ann": sum(table_ann.get(code, 0) for code in codes),
        "sidecar_news": sum(int(sidecars[code].get("news_count", -1)) for code in codes),
        "table_news": sum(table_news.get(code, 0) for code in codes),
        "sidecar_total_items": sum(int(sidecars[code].get("total_items", -1)) for code in codes),
        "jsonl_lines": sum(items[code] for code in codes),
    }


def test_pr5_hash_recipe_is_the_right_one_evidence_from_cohort_a() -> None:
    """配方正确性由 A 组反证：重算、sidecar、因子表三方 100/100 自洽。"""
    stats = _three_way("student_A")

    assert len(stats["codes"]) == 100
    assert stats["recomputed_eq_sidecar"] == 100
    assert stats["table_eq_sidecar"] == 100
    assert stats["table_eq_recomputed"] == 100
    assert stats["sidecar_ann"] == EXPECTED_A_ANNOUNCEMENTS
    assert stats["table_ann"] == EXPECTED_A_ANNOUNCEMENTS
    assert stats["sidecar_news"] == EXPECTED_A_NEWS
    assert stats["table_news"] == EXPECTED_A_NEWS
    assert stats["sidecar_total_items"] == EXPECTED_A_TOTAL_ITEMS
    assert stats["jsonl_lines"] == EXPECTED_A_TOTAL_ITEMS


def test_cohort_c_factor_table_disagrees_with_every_on_disk_artifact() -> None:
    """C 组：盘上语料与 sidecar 自洽（100/100），但因子表与两者**全部不符**（0/100）。

    若将来有人改写因子表哈希来"凑上" sidecar，此断言会失败 —— 这是刻意的冻结。
    """
    stats = _three_way("student_C")

    assert len(stats["codes"]) == 100
    assert stats["recomputed_eq_sidecar"] == 100
    assert stats["table_eq_sidecar"] == 0
    assert stats["table_eq_recomputed"] == 0


def test_cohort_c_declared_input_is_about_4_77x_the_available_corpus() -> None:
    """C 表声明的公告数是盘上实有的约 4.77 倍；新闻被整列记为 0，而 sidecar 有 991 条。"""
    stats = _three_way("student_C")

    assert stats["sidecar_ann"] == EXPECTED_C_SIDECAR_ANNOUNCEMENTS
    assert stats["table_ann"] == EXPECTED_C_TABLE_ANNOUNCEMENTS
    assert stats["sidecar_news"] == EXPECTED_C_SIDECAR_NEWS
    assert stats["table_news"] == EXPECTED_C_TABLE_NEWS
    assert stats["sidecar_total_items"] == EXPECTED_C_TOTAL_ITEMS
    assert stats["jsonl_lines"] == EXPECTED_C_TOTAL_ITEMS
    ratio = stats["table_ann"] / stats["sidecar_ann"]
    assert ratio == pytest.approx(4.7709, abs=5e-5)


def test_cohort_c_manifest_points_at_a_missing_source_directory() -> None:
    """C 组自己的 manifest 引用一个不存在的 sources 目录，佐证"原始输入从未入库"。"""
    manifest_path = TASK_SPLIT / "student_c/csmar/student_c_csmar_factor_panel_filtered_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    referenced = str(manifest["filling_calendar"])

    assert referenced.startswith("data/task_split/student_c/sources/")
    assert not (ROOT / referenced).exists()
    assert not (TASK_SPLIT / "student_c/sources").exists()


def test_invalidation_notice_exists_and_states_the_frozen_facts() -> None:
    """说明文件必须存在，并写明结论、证据数字、禁止改写与解除条件。"""
    text = NOTICE.read_text(encoding="utf-8")

    for required in (
        "溯源作废说明",
        "不可核验",
        "0/100",
        "100/100",
        "172,968",
        "36,255",
        "991",
        "4.77",
        "全域",
        "NOT_ASOF",
        "严禁改写因子表哈希",
        "解除条件",
        "student_b/sources/csmar_raw",
        "refs/pull/*",
    ):
        assert required in text, f"作废说明缺少条目：{required}"
    assert "json.dumps(items, ensure_ascii=False, sort_keys=True, separators=" in text


def test_notice_numbers_are_the_live_measurements() -> None:
    """说明里引用的数字必须与当前实测一致（防止说明与数据脱节）。"""
    stats_c = _three_way("student_C")
    stats_a = _three_way("student_A")
    text = NOTICE.read_text(encoding="utf-8")

    for value in (
        f"{stats_c['sidecar_ann']:,}",
        f"{stats_c['table_ann']:,}",
        f"{stats_c['sidecar_news']:,}",
        f"{stats_c['sidecar_total_items']:,}",
        f"{stats_a['sidecar_ann']:,}",
        f"{stats_a['sidecar_total_items']:,}",
    ):
        assert value in text, f"说明未引用实测值 {value}"
    assert f"{stats_c['table_ann'] / stats_c['sidecar_ann']:.4f}" in text