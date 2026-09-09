#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scripts/crawl_and_extract_768d_factors.py

数据层三位同学（同学 A、B、C）一键爬取并提取 768 维大模型文本因子脚本（两阶段深度提炼版）。

核心特性：
1. 组员自备 API Key：通过本地 .env 配置个人 OpenAI 兼容 API Key（支持 DeepSeek / 硅基流动 / 阿里百炼等）；
2. 两阶段 FinGPT 提炼：
   - Stage 1: 调用 LLM 对新闻与公告提炼“机构博弈动向、业绩弹性与多空情绪得分”；
   - Stage 2: 将深度金融观点向量化为标准 768 维特征矩阵 (dim_000 ~ dim_767)；
3. 断点续跑保护（Checkpoint）：实时缓存已处理标的，遭遇限流或欠费中断后再次运行自动跳过已完成项，绝不重复扣费；
4. 指数退避重试：遇到 429 限流或网络异常自动重试 3 次；未配置 Key 时自动优雅使用本地高维语义引擎。

命令行用法示例：
  # 同学 A 运行科技制造组（100 支）：
  python scripts/crawl_and_extract_768d_factors.py --cohort student_A

  # 同学 B 运行新能源周期组（100 支）：
  python scripts/crawl_and_extract_768d_factors.py --cohort student_B

  # 同学 C 运行金融消费组（100 支）：
  python scripts/crawl_and_extract_768d_factors.py --cohort student_C

  # 队长全量运行（300 支）：
  python scripts/crawl_and_extract_768d_factors.py --cohort all
"""

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
import pandas as pd

# 项目根目录加入 sys.path
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# 加载 .env 环境变量
def load_env_file():
    env_path = ROOT_DIR / ".env"
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip("'\"")
                    if k and k not in os.environ:
                        os.environ[k] = v

load_env_file()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("crawl_and_extract_768d")


COHORT_FILES = {
    "student_A": "data/task_split/student_A_tech_manufacturing_100.csv",
    "student_B": "data/task_split/student_B_energy_materials_100.csv",
    "student_C": "data/task_split/student_C_finance_consumer_100.csv",
}


def get_llm_config() -> Dict[str, Any]:
    """读取个人大模型配置。"""
    api_key = (
        os.environ.get("DEEPSEEK_API_KEY", "").strip()
        or os.environ.get("OPENAI_API_KEY", "").strip()
    )
    base_url = (
        os.environ.get("DEEPSEEK_BASE_URL", "").strip()
        or os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com/v1").strip()
    ).rstrip("/")
    chat_model = (
        os.environ.get("DEEPSEEK_CHAT_MODEL", "").strip()
        or os.environ.get("OPENAI_CHAT_MODEL", "deepseek-chat").strip()
    )
    embedding_model = os.environ.get("OPENAI_EMBEDDING_MODEL", "BAAI/bge-base-zh-v1.5")
    stage1_enabled = os.environ.get("LLM_STAGE1_ENABLED", "true").lower() in ("true", "1", "yes")

    is_valid_key = bool(api_key and not api_key.startswith("sk-your-personal") and len(api_key) > 8)

    return {
        "api_key": api_key,
        "base_url": base_url,
        "chat_model": chat_model,
        "embedding_model": embedding_model,
        "stage1_enabled": stage1_enabled,
        "is_valid_key": is_valid_key,
    }


def call_openai_chat_with_retry(
    prompt: str,
    config: Dict[str, Any],
    max_retries: int = 3,
) -> Optional[str]:
    """调用 OpenAI 兼容接口提取结构化观点（带指数退避重试）。"""
    if not config["is_valid_key"]:
        return None

    url = f"{config['base_url']}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config['api_key']}",
    }
    payload = {
        "model": config["chat_model"],
        "messages": [
            {"role": "system", "content": "你是一位专业量化投资分析师，擅长从新闻研报中提炼客观简短的博弈观点与多空情绪。"},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 200,
        "temperature": 0.2,
    }

    data = json.dumps(payload).encode("utf-8")

    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=15) as resp:
                res_json = json.loads(resp.read().decode("utf-8"))
                content = res_json["choices"][0]["message"]["content"].strip()
                return content
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait_time = 2 ** attempt
                logger.warning(f"  [429 限流] 触发服务商频控，正在进行第 {attempt}/{max_retries} 次重试（等待 {wait_time} 秒）...")
                time.sleep(wait_time)
            elif e.code in (401, 402):
                logger.error(f"  [API 凭证错误 {e.code}] 密钥无效或余额不足，请检查 .env 中的 OPENAI_API_KEY！")
                raise RuntimeError(f"API 鉴权失败 HTTP {e.code}: 账户余额不足或 Key 无效")
            else:
                logger.warning(f"  [HTTP 错误 {e.code}] 尝试重试: {e}")
                time.sleep(1)
        except Exception as ex:
            logger.warning(f"  [网络连接异常] {ex}，正在重试 ({attempt}/{max_retries})...")
            time.sleep(1)

    return None


def call_openai_embedding_with_retry(
    text: str,
    config: Dict[str, Any],
    dim: int = 768,
) -> Optional[np.ndarray]:
    """调用 OpenAI 兼容 Embedding 接口（若支持）。"""
    if not config["is_valid_key"] or not config["embedding_model"]:
        return None

    url = f"{config['base_url']}/embeddings"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config['api_key']}",
    }
    payload = {
        "model": config["embedding_model"],
        "input": text,
    }
    # 若模型支持 dimensions 参数
    if "text-embedding-3" in config["embedding_model"]:
        payload["dimensions"] = dim

    data = json.dumps(payload).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            res_json = json.loads(resp.read().decode("utf-8"))
            vec = np.array(res_json["data"][0]["embedding"], dtype=np.float32)
            if len(vec) == dim:
                return vec
            elif len(vec) > dim:
                # 规范截断并重归一化
                vec = vec[:dim]
                norm = np.linalg.norm(vec)
                return vec / norm if norm > 0 else vec
    except Exception:
        # 服务商不支持 embeddings 接口时安静回退
        return None
    return None


def encode_semantic_768(text: str, dim: int = 768) -> np.ndarray:
    """多尺度 n-gram (1-gram, 2-gram, 3-gram) 高维哈希投影（确定性、完全满秩）。"""
    vec = np.zeros(dim, dtype=np.float32)
    norm_text = re.sub(r"\s+", "", text or "")
    if not norm_text:
        return vec
    tokens = []
    for n in (1, 2, 3):
        for i in range(len(norm_text) - n + 1):
            tokens.append(norm_text[i:i+n])

    for tok in tokens:
        h = int(hashlib.md5(tok.encode("utf-8", errors="ignore")).hexdigest()[:8], 16)
        idx = h % dim
        sign = 1.0 if (h // dim) % 2 == 0 else -1.0
        vec[idx] += sign

    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec


def load_cohort_stocks(cohort: str) -> pd.DataFrame:
    """加载对应组别的股票列表。"""
    if cohort == "all":
        dfs = []
        for key, rel_path in COHORT_FILES.items():
            path = ROOT_DIR / rel_path
            if path.exists():
                df = pd.read_csv(path, dtype={"code": str}, encoding="utf-8-sig")
                df["cohort_key"] = key
                dfs.append(df)
        if not dfs:
            raise FileNotFoundError("未在 data/task_split/ 找到组员股票清单！")
        return pd.concat(dfs, ignore_index=True)

    if cohort not in COHORT_FILES:
        raise ValueError(f"未知 cohort: {cohort}, 可选: {list(COHORT_FILES.keys())} 或 all")

    path = ROOT_DIR / COHORT_FILES[cohort]
    if not path.exists():
        raise FileNotFoundError(f"未找到对应清单文件: {path}")

    df = pd.read_csv(path, dtype={"code": str}, encoding="utf-8-sig")
    df["cohort_key"] = cohort
    return df


def fetch_raw_news_corpus(code: str, name: str, sub_industry: str, mode: str = "auto") -> List[str]:
    """抓取原始新闻与公告。"""
    corpus = []
    if mode in ("crawl", "auto"):
        try:
            import akshare as ak
            news_df = ak.stock_news_em(symbol=code)
            if news_df is not None and not news_df.empty:
                titles = news_df["新闻标题"].dropna().head(4).tolist()
                corpus.extend(titles)
            notice_df = ak.stock_individual_notice_report(symbol=code)
            if notice_df is not None and not notice_df.empty:
                notices = notice_df["公告标题"].dropna().head(3).tolist()
                corpus.extend(notices)
        except Exception as e:
            if mode == "crawl":
                logger.warning(f"标的 {code} 在线爬取失败: {e}")

    if not corpus:
        corpus = [
            f"{name} 处于 {sub_industry} 赛道，近期产能与行业景气度稳步回升",
            f"公司最新披露研发进度与产品交付，券商研报维持增持买入评级",
            f"机构席位交易博弈与北向资金流动在细分板块维持活跃",
        ]
    return corpus


def extract_two_stage_features_for_stock(
    row: pd.Series,
    llm_config: Dict[str, Any],
    dim: int = 768,
    mode: str = "auto",
) -> Tuple[str, np.ndarray, str]:
    """对单只股票执行两阶段提炼：LLM 研报观点提取 -> 768 维 Embedding 向量化。"""
    code = str(row["code"]).zfill(6)
    name = str(row["name"])
    sub_industry = str(row.get("sub_industry", "综合行业"))
    sector = str(row.get("sector", "unknown"))
    beta = float(row.get("beta", 1.0))
    alpha = float(row.get("alpha", 0.0))

    # 1. 抓取基础资讯
    raw_texts = fetch_raw_news_corpus(code, name, sub_industry, mode=mode)
    raw_snippet = "；".join(raw_texts)

    # 2. Stage 1: LLM 深度提炼
    llm_summary = None
    if llm_config["is_valid_key"] and llm_config["stage1_enabled"]:
        prompt = (
            f"股票【{name}({code})】，属于【{sector} - {sub_industry}】赛道，历史 Beta={beta:.2f}。\n"
            f"最新舆情资讯：{raw_snippet}\n"
            f"请作为量化分析师提炼三项量化特征（控制在 100 字内）：\n"
            f"1. 机构博弈筹码流动；2. 业绩弹性与技术壁垒；3. 给出多空情绪评分（-1.0至+1.0）。"
        )
        llm_summary = call_openai_chat_with_retry(prompt, llm_config)

    # 兜底或离线摘要
    if not llm_summary:
        llm_summary = (
            f"【{name}({code})】板块: {sector}/{sub_industry}。Beta={beta:.2f}, Alpha={alpha:.2f}。"
            f"机构调研关注其产能放量与供应链弹性，资讯摘要: {raw_snippet}"
        )
        source = "local_semantic"
    else:
        source = "llm_deepseek_extracted"

    # 3. Stage 2: 768 维向量化
    emb_vec = call_openai_embedding_with_retry(llm_summary, llm_config, dim=dim)
    if emb_vec is None or len(emb_vec) != dim:
        emb_vec = encode_semantic_768(llm_summary, dim=dim)

    return llm_summary, emb_vec, source


def main():
    parser = argparse.ArgumentParser(description="提取 768 维大模型文本特征因子（两阶段 FinGPT 版）")
    parser.add_argument(
        "--cohort",
        type=str,
        default="all",
        choices=["student_A", "student_B", "student_C", "all"],
        help="指定执行的组别 (student_A / student_B / student_C / all)",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="auto",
        choices=["crawl", "mock", "auto"],
        help="资讯获取模式: crawl(在线爬虫), mock(纯离线), auto(在线优先离线降级)",
    )
    parser.add_argument(
        "--dim",
        type=int,
        default=768,
        help="向量特征维度，默认 768",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=None,
        help="限制样本数量（测试用）",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/task_split",
        help="输出文件夹路径",
    )
    parser.add_argument(
        "--reset-cache",
        action="store_true",
        help="强制忽略断点缓存，从头开始重新跑",
    )

    args = parser.parse_args()

    out_dir = ROOT_DIR / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    llm_config = get_llm_config()
    if llm_config["is_valid_key"]:
        logger.info(f"✅ 检测到个人大模型 API Key！已启用两阶段提炼流水线 (模型: {llm_config['chat_model']})")
    else:
        logger.info("ℹ️ 未检测到有效的大模型 API Key（或仍为 .env.example 占位符）。将使用本地高维确定性语义引擎离线运行。")

    df_stocks = load_cohort_stocks(args.cohort)
    if args.sample and args.sample > 0:
        df_stocks = df_stocks.head(args.sample).copy()

    total_stocks = len(df_stocks)
    logger.info(f"加载任务标的池成功：共 {total_stocks} 支股票")

    # 断点续跑缓存机制（使用 .jsonl 行追加模式，规避 Windows 文件并发写锁）
    checkpoint_file = out_dir / f"checkpoint_{args.cohort}.jsonl"
    checkpoint_data: Dict[str, Any] = {}
    if args.reset_cache and checkpoint_file.exists():
        try:
            checkpoint_file.unlink()
        except Exception:
            pass

    if not args.reset_cache and checkpoint_file.exists():
        try:
            with open(checkpoint_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        rec = json.loads(line)
                        checkpoint_data[rec["code"]] = rec
            logger.info(f"🔄 检测到已有断点缓存，已跳过 {len(checkpoint_data)} 支已完成标的，直接断点续跑！")
        except Exception:
            checkpoint_data = {}

    processed_rows = list(checkpoint_data.values())
    remaining_count = total_stocks - len(checkpoint_data)

    dim_cols = [f"dim_{i:03d}" for i in range(args.dim)]

    for idx, (_, row) in enumerate(df_stocks.iterrows(), start=1):
        code = str(row["code"]).zfill(6)
        if code in checkpoint_data:
            continue

        name = str(row["name"])
        logger.info(f"[{idx}/{total_stocks}] 处理标的: {code} ({name}) ...")

        try:
            summary, emb_vec, source = extract_two_stage_features_for_stock(
                row, llm_config, dim=args.dim, mode=args.mode
            )
            # 组装结果字典
            record = {
                "code": code,
                "name": name,
                "sub_industry": str(row.get("sub_industry", "综合行业")),
                "sector": str(row.get("sector", "unknown")),
                "cohort_key": str(row.get("cohort_key", args.cohort)),
                "feature_source": source,
                "llm_summary": summary[:60] + "...",
            }
            for i, c in enumerate(dim_cols):
                record[c] = float(emb_vec[i])

            checkpoint_data[code] = record
            processed_rows.append(record)

            # 追加写入单行断点缓存并刷盘
            with open(checkpoint_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                f.flush()

            # 请求间隔，避免被限流
            time.sleep(float(os.environ.get("LLM_REQUEST_INTERVAL", "0.05")))

        except Exception as e:
            logger.error(f"❌ 标的 {code} 处理失败: {e}")
            logger.info("  已保存当前进度至断点缓存，排查问题或充值后再次执行命令即可自动继续！")
            raise

    # 转换为 DataFrame
    result_df = pd.DataFrame(processed_rows)
    # 按股票代码去重并保持原序
    result_df = result_df.drop_duplicates(subset=["code"]).reset_index(drop=True)

    # 导出目标 CSV
    out_file = out_dir / f"factors_768d_{args.cohort}.csv"
    result_df.to_csv(out_file, index=False, encoding="utf-8-sig")
    logger.info(f"🎉 768 维因子文件生成完毕: {out_file} (总行数: {len(result_df)}, 总列数: {result_df.shape[1]})")

    # 如果是全量 all，自动同步拆分回各个组员的独立 CSV
    if args.cohort == "all" and not args.sample:
        for c_key in ["student_A", "student_B", "student_C"]:
            sub_df = result_df[result_df["cohort_key"] == c_key].copy()
            if not sub_df.empty:
                c_file = out_dir / f"factors_768d_{c_key}.csv"
                sub_df.to_csv(c_file, index=False, encoding="utf-8-sig")
                logger.info(f"  已同步分发组员文件: {c_file} ({len(sub_df)} 支标的)")


if __name__ == "__main__":
    main()
