# tools/backfill_market_feedback.py —— 历史样本真实收益回填（spec-kit 004 / US2）
#
# 行为：
#   1. 首次运行先快照原文件（market_feedback.backup_YYYYMMDD.json）
#   2. 逐样本按 code+event_date 从 K 线计算真实 3/5 日收益
#      - ret_3d_pct / ret_5d_pct / realized_* 更新为真实收益
#      - 旧 ret_5d_pct（原 KNN 预测值）保留到 forecast_ret_5d_pct
#      - 不可算样本：realized_available=False，收益字段为 null（不伪造）
#   3. 原子写回 + 输出回填前后对比统计
#   4. 幂等：快照只在首次创建；重跑结果逐字节一致
#
# 用法: python tools/backfill_market_feedback.py [--feedback PATH] [--kline-dir PATH]

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from diagnose_sentiment_alignment import load_kline, realized_for_sample  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FEEDBACK = REPO_ROOT / "docs" / "data" / "llm" / "market_feedback.json"
DEFAULT_KLINE_DIR = REPO_ROOT / "docs" / "data" / "kline"


def snapshot_path(feedback_path: Path) -> Path:
    return feedback_path.with_name(f"market_feedback.backup_{date.today().strftime('%Y%m%d')}.json")


def backfill(feedback_path, kline_dir) -> dict:
    """回填历史样本的真实收益。返回对比统计。

    幂等：快照只在首次创建；重复调用输出一致。
    """
    feedback_path = Path(feedback_path)
    kline_dir = Path(kline_dir)

    if not feedback_path.exists():
        raise FileNotFoundError(f"市场反馈文件不存在: {feedback_path}")

    with open(feedback_path, encoding="utf-8") as fh:
        data = json.load(fh)
    samples = data.get("samples", []) if isinstance(data, dict) else []
    if not samples:
        return {"total": 0, "computable": 0, "not_computable": 0, "changed": 0}

    # 快照（只建一次）
    snap = snapshot_path(feedback_path)
    if not snap.exists():
        with open(feedback_path, encoding="utf-8") as fh:
            original = fh.read()
        snap.write_text(original, encoding="utf-8")

    computable = 0
    not_computable = 0
    changed = 0

    for s in samples:
        old_ret_5d = s.get("ret_5d_pct")
        close_df = load_kline(str(s.get("code")), kline_dir)
        r3, r5 = realized_for_sample(s, close_df)

        # 旧预测值保留（仅当样本还没有 forecast 字段时）
        if "forecast_ret_5d_pct" not in s and old_ret_5d is not None:
            s["forecast_ret_5d_pct"] = old_ret_5d

        s["ret_3d_pct"] = r3
        s["ret_5d_pct"] = r5
        s["realized_ret_3d_pct"] = r3
        s["realized_ret_5d_pct"] = r5
        s["realized_available"] = (r3 is not None or r5 is not None)

        if s["realized_available"]:
            computable += 1
        else:
            not_computable += 1
        if r5 != old_ret_5d:
            changed += 1

    # 原子写回
    tmp = feedback_path.with_suffix(feedback_path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    tmp.replace(feedback_path)

    return {
        "total": len(samples),
        "computable": computable,
        "not_computable": not_computable,
        "changed": changed,
        "snapshot": str(snap),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="历史市场反馈样本真实收益回填（spec-kit 004）")
    parser.add_argument("--feedback", default=str(DEFAULT_FEEDBACK))
    parser.add_argument("--kline-dir", default=str(DEFAULT_KLINE_DIR))
    args = parser.parse_args()

    stats = backfill(args.feedback, args.kline_dir)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - 仅直接脚本执行路径
    raise SystemExit(main())
