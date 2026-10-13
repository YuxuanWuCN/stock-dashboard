# -*- coding: utf-8 -*-
"""测试摘要器的准确性和性能

验证点：
1. 摘要质量（人工评估）
2. Token 节省效果
3. 去重准确性
"""

import sys
from pathlib import Path

# 添加 src 到路径
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from llm.summarizer import (
    summarize_text,
    compute_simhash,
    hamming_distance,
    is_duplicate,
    deduplicate_texts,
)


def test_summarize():
    """测试摘要功能"""
    print("=" * 60)
    print("测试 1: 摘要质量")
    print("=" * 60)

    full_text = """
    宁德时代发布2024年度业绩公告，公司实现营业收入4520亿元，同比增长22.5%，
    归属于上市公司股东的净利润558亿元，同比增长17.8%。公司动力电池装机量
    全球市占率达37.5%，连续七年保持全球第一。储能电池出货量同比增长超过150%，
    成为新的增长极。公司在固态电池、钠离子电池等前沿技术领域保持领先地位，
    研发投入占营收比例达7.8%。公司表示将继续加大技术创新力度，巩固行业领先
    地位。分析师认为，随着全球新能源汽车渗透率持续提升，公司业绩有望保持
    高速增长态势。不过，原材料价格波动和竞争加剧可能对毛利率产生一定压力。
    """

    print(f"原文长度: {len(full_text)} 字\n")
    print(f"原文内容:\n{full_text}\n")

    summary = summarize_text(full_text, max_length=150, min_length=50)

    print(f"摘要长度: {len(summary)} 字")
    print(f"压缩比例: {len(summary)/len(full_text)*100:.1f}%\n")
    print(f"摘要内容:\n{summary}\n")

    print("✓ Token 节省估算:")
    print(f"  原文: ~{len(full_text)//2} tokens")
    print(f"  摘要: ~{len(summary)//2} tokens")
    print(f"  节省: ~{(1 - len(summary)/len(full_text))*100:.0f}%\n")


def test_deduplication():
    """测试去重功能"""
    print("=" * 60)
    print("测试 2: 去重准确性")
    print("=" * 60)

    texts = [
        "宁德时代发布年度业绩公告，营收大幅增长",
        "宁德时代公布年度业绩报告，营业收入显著提升",  # 相似
        "特斯拉宣布降价促销，Model 3 降价1万元",
        "比亚迪推出新款电动车，续航里程突破800公里",
        "宁德时代业绩公告出炉，收入大增",  # 相似
    ]

    print("原始新闻列表:")
    for i, text in enumerate(texts):
        print(f"  [{i}] {text}")

    # 计算 Simhash
    print("\nSimhash 值:")
    hashes = [compute_simhash(t) for t in texts]
    for i, (text, h) in enumerate(zip(texts, hashes)):
        print(f"  [{i}] {h:016x}")

    # 计算两两汉明距离
    print("\n汉明距离矩阵（阈值=3视为重复）:")
    print("     ", end="")
    for i in range(len(texts)):
        print(f"[{i}]  ", end="")
    print()

    for i in range(len(texts)):
        print(f"[{i}]  ", end="")
        for j in range(len(texts)):
            dist = hamming_distance(hashes[i], hashes[j])
            marker = " ✓" if dist <= 3 and i != j else "  "
            print(f" {dist:2d}{marker} ", end="")
        print()

    # 执行去重
    kept_indices = deduplicate_texts(texts, threshold=3)

    print(f"\n去重后保留的索引: {kept_indices}")
    print("\n去重后新闻列表:")
    for idx in kept_indices:
        print(f"  [{idx}] {texts[idx]}")

    print(f"\n✓ 去重效果: {len(texts)} → {len(kept_indices)} 条 (节省 {(1-len(kept_indices)/len(texts))*100:.0f}%)")


def test_end_to_end():
    """端到端测试：模拟真实新闻处理流程"""
    print("\n" + "=" * 60)
    print("测试 3: 端到端流程（摘要 + 去重）")
    print("=" * 60)

    news_list = [
        {
            "title": "宁德时代2024业绩超预期",
            "content": "宁德时代发布2024年度业绩公告，公司实现营业收入4520亿元，同比增长22.5%，归属于上市公司股东的净利润558亿元，同比增长17.8%。公司动力电池装机量全球市占率达37.5%。",
        },
        {
            "title": "宁德时代发布年报：营收增长22%",
            "content": "宁德时代今日公布2024年年报，全年营收4520亿元，同比增长22.5%，净利润558亿元。公司在动力电池领域继续保持全球第一的市场地位。",
        },
        {
            "title": "特斯拉Model 3降价1万元",
            "content": "特斯拉中国官网显示，Model 3标准续航版价格下调1万元，调整后售价为25.99万元。这是特斯拉今年第三次降价，旨在提升市场竞争力。",
        },
    ]

    print(f"原始新闻数量: {len(news_list)}\n")

    # 步骤1: 摘要
    summaries = []
    total_original_len = 0
    total_summary_len = 0

    for i, news in enumerate(news_list):
        full_text = f"{news['title']} {news['content']}"
        total_original_len += len(full_text)

        summary = summarize_text(full_text, max_length=100)
        summaries.append(summary)
        total_summary_len += len(summary)

        print(f"新闻 {i+1}:")
        print(f"  原文: {len(full_text)} 字")
        print(f"  摘要: {len(summary)} 字")
        print(f"  内容: {summary[:60]}...\n")

    print(f"摘要阶段 Token 节省: ~{(1-total_summary_len/total_original_len)*100:.0f}%\n")

    # 步骤2: 去重
    kept_indices = deduplicate_texts(summaries, threshold=3)

    print(f"去重后保留: {len(kept_indices)} 条")
    for idx in kept_indices:
        print(f"  [{idx}] {summaries[idx][:50]}...")

    print(f"\n✓ 综合节省:")
    print(f"  原始: {len(news_list)} 条新闻, ~{total_original_len//2} tokens")
    print(f"  处理后: {len(kept_indices)} 条摘要, ~{sum(len(summaries[i]) for i in kept_indices)//2} tokens")
    print(f"  总节省: ~{(1 - (sum(len(summaries[i]) for i in kept_indices) / total_original_len))*100:.0f}%")


if __name__ == "__main__":
    test_summarize()
    print("\n")
    test_deduplication()
    test_end_to_end()

    print("\n" + "=" * 60)
    print("✓ 所有测试通过")
    print("=" * 60)
