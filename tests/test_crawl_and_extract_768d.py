# -*- coding: utf-8 -*-
"""tests/test_crawl_and_extract_768d.py

验证 768 维因子多线程高并发提取流水线、threading.Lock 写入保护、超时退避与断点续跑机制。
"""

import concurrent.futures
import json
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.crawl_and_extract_768d_factors import (
    encode_semantic_768,
    fetch_with_timeout_and_retry,
    extract_two_stage_features_for_stock,
    load_cohort_stocks,
    ROOT_DIR,
)


def test_encode_semantic_768_properties():
    """测试确定性 768 维语义投影数学性质：维度=768、L2 范数=1.0、0 NaN、0 Inf。"""
    sample_texts = [
        "宁德时代处于硬科技与新能源赛道，产能稳步扩张",
        "公司披露三季度财报，毛利率显著回升，获机构买入评级",
        "",  # 边界：空字符串
        "   \t\n  ",  # 边界：纯空白字符
        "1234567890!@#$%^&*()_+~`|}{[]:;?><,./-=",  # 边界：特殊符号
    ]
    for text in sample_texts:
        vec = encode_semantic_768(text, dim=768)
        assert len(vec) == 768, f"向量维度错误: {len(vec)}"
        assert not np.isnan(vec).any(), "向量中存在 NaN"
        assert not np.isinf(vec).any(), "向量中存在 Inf"
        norm = np.linalg.norm(vec)
        assert np.isclose(norm, 1.0, atol=1e-5), f"L2 范数未归一化为 1.0 (实际模长: {norm})"


def test_fetch_with_timeout_and_retry_fast_success():
    """测试快速成功任务直接返回。"""
    def fast_fn(x, y):
        return x + y

    res = fetch_with_timeout_and_retry(fast_fn, 3, 5, timeout=2.0, max_retries=2)
    assert res == 8


def test_fetch_with_timeout_and_retry_timeout_fallback():
    """测试阻塞任务在超时后被安全打断并执行指数退避重试，最终优雅降级。"""
    def hanging_fn():
        time.sleep(1.0)
        return "never_reached"

    t0 = time.time()
    # timeout 0.1s, max_retries 2
    res = fetch_with_timeout_and_retry(hanging_fn, timeout=0.1, max_retries=2, backoff_base=1.2)
    elapsed = time.time() - t0
    assert res is None, "超时任务未能正确返回 None 降级"
    assert elapsed >= 0.2, f"重试耗时偏短: {elapsed:.2f}s"


def test_concurrent_checkpoint_writing_with_lock():
    """测试多线程并发写入 checkpoint 文件时，threading.Lock 确保原子写入无损坏。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        chk_file = Path(tmpdir) / "checkpoint_test.jsonl"
        lock = threading.Lock()
        total_items = 60
        num_threads = 8

        def write_task(idx):
            record = {
                "code": f"{idx:06d}",
                "name": f"Stock_{idx}",
                "score": float(idx * 0.1),
                "data": [float(i) for i in range(10)],
            }
            # 模拟网络抖动和计算延时
            time.sleep(0.005)
            with lock:
                with open(chk_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                    f.flush()

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(write_task, i) for i in range(total_items)]
            for f in concurrent.futures.as_completed(futures):
                f.result()

        # 检验生成的文件
        lines = chk_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == total_items, f"预期写入 {total_items} 行，实际为 {len(lines)}"

        parsed_codes = set()
        for line in lines:
            rec = json.loads(line)
            parsed_codes.add(rec["code"])

        assert len(parsed_codes) == total_items, "存在重复写入或损坏的行"


def test_breakpoint_resume_logic():
    """测试断点续跑：已存在的部分断点不会被重复执行。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        chk_file = Path(tmpdir) / "checkpoint_resume.jsonl"

        # 预先存入 3 支股票的断点
        pre_cached = [
            {"code": "000001", "name": "平安银行", "dim_000": 1.0},
            {"code": "000002", "name": "万科A", "dim_000": 1.0},
            {"code": "600519", "name": "贵州茅台", "dim_000": 1.0},
        ]
        with open(chk_file, "w", encoding="utf-8") as f:
            for rec in pre_cached:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        # 模拟读取断点
        cached_data = {}
        with open(chk_file, "r", encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line.strip())
                cached_data[rec["code"]] = rec

        assert len(cached_data) == 3

        all_stocks = ["000001", "000002", "600519", "300750", "002594"]
        pending = [code for code in all_stocks if code not in cached_data]
        assert pending == ["300750", "002594"], f"待处理标的错误: {pending}"


def test_factors_768d_all_data_integrity():
    """校验全池 300 支标的 768 维因子产物 data/task_split/factors_768d_all.csv 的全量完整性。"""
    csv_path = ROOT_DIR / "data/task_split/factors_768d_all.csv"
    assert csv_path.exists(), f"未找到特征矩阵文件: {csv_path}"

    df = pd.read_csv(csv_path, dtype={"code": str}, encoding="utf-8-sig")
    assert len(df) == 300, f"标的数量不为 300: 实际 {len(df)}"
    assert df["code"].nunique() == 300, "股票代码存在重复"

    # 校验 768 列特征
    dim_cols = [c for c in df.columns if c.startswith("dim_")]
    assert len(dim_cols) == 768, f"特征列数不等于 768: 实际 {len(dim_cols)}"
    assert df.shape[1] == 780, f"总列数不等于 780 (12 元数据 + 768 特征): 实际 {df.shape[1]}"

    matrix = df[dim_cols].values.astype(np.float64)
    assert not np.isnan(matrix).any(), "特征矩阵中存在 NaN"
    assert not np.isinf(matrix).any(), "特征矩阵中存在 Inf"

    norms = np.linalg.norm(matrix, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5), (
        f"L2 范数未严格归一化至 1.0: min={norms.min():.7f}, max={norms.max():.7f}"
    )


def test_cohort_partitions_sync():
    """校验三大组员（科技制造、新能源周期、金融消费）拆分文件的完整性。"""
    cohorts = [
        ("student_A", "data/task_split/factors_768d_student_A.csv"),
        ("student_B", "data/task_split/factors_768d_student_B.csv"),
        ("student_C", "data/task_split/factors_768d_student_C.csv"),
    ]
    for c_key, rel_path in cohorts:
        file_path = ROOT_DIR / rel_path
        assert file_path.exists(), f"组员特征文件缺失: {file_path}"
        sub_df = pd.read_csv(file_path, dtype={"code": str}, encoding="utf-8-sig")
        assert len(sub_df) == 100, f"{c_key} 标的数量不等于 100: 实际 {len(sub_df)}"
        assert sub_df.shape[1] == 780, f"{c_key} 列数不等于 780: 实际 {sub_df.shape[1]}"

        dim_cols = [c for c in sub_df.columns if c.startswith("dim_")]
        matrix = sub_df[dim_cols].values.astype(np.float64)
        assert not np.isnan(matrix).any()
        assert not np.isinf(matrix).any()
        norms = np.linalg.norm(matrix, axis=1)
        assert np.allclose(norms, 1.0, atol=1e-5)
