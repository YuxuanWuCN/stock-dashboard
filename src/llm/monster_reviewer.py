# src/llm/monster_reviewer.py —— 妖股审查员智能体
#
# 借鉴 ElliottAgents（arXiv:2507.03435）的多智能体对话协同思想，
# 对高涨幅/高波动候选标的进行"审查员质疑 → 主报告回应 → 收敛结论"的两轮对话审查。
#
# 关键原则（与项目背书一致）：
#   - LLM 只做文本理解与表达，不生成财务数字
#   - 规则引擎负责可重复计算（触发筛选、降级质疑），模型不能覆盖程序计算结果
#   - 审查结论为研究信号，非操作指令，不构成投资建议（项目红线）
#
# 降级路径：LLM 不可用时用规则生成质疑（"10日涨幅超阈值"等），流程不中断。

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from .config import DEEPSEEK_V4_FLASH_MODEL, LLM_ENABLED
from .llm_client import LLMClient, LLMCompletionClient, LLMUnavailableError

logger = logging.getLogger("stock-dashboard.llm.monster-reviewer")
_BEIJING_TZ = ZoneInfo("Asia/Shanghai")

# ------------------------------------------------------------
# 配置（触发阈值，可在 config 中调整）
# ------------------------------------------------------------

# 触发规则：10 日涨幅 >= 30% 或 5 日波动率 >= 全市场 95 分位 或 5 日内涨停 >= 2 次
TRIGGER_10D_GAIN_PCT = 30.0
TRIGGER_VOLATILITY_PCTILE = 95.0
TRIGGER_LIMIT_UP_5D = 2

# 严重度阈值
SEVERITY_HIGH_GAIN_PCT = 50.0
SEVERITY_HIGH_VOLATILITY_PCTILE = 99.0

# 每日新增 LLM 调用上限（成本控制）
MAX_DAILY_LLM_CALLS = 5


# ------------------------------------------------------------
# 数据结构
# ------------------------------------------------------------

@dataclass
class MonsterCandidate:
    """妖股候选标的。"""
    code: str
    name: str
    gain_10d_pct: float
    volatility_5d_pct: float
    volatility_pctile: float = 0.0  # 全市场百分位 0-100
    limit_up_5d: int = 0
    reasons: list[str] = field(default_factory=list)


@dataclass
class Challenge:
    """审查员质疑。"""
    point: str
    evidence: str
    severity: str  # high / medium / low


@dataclass
class Response:
    """主报告对质疑的回应。"""
    challenge_point: str
    stance: str  # support / rebut / insufficient
    reason: str


@dataclass
class Verdict:
    """收敛结论。"""
    attention: str  # normal / downgrade / warning
    summary: str


@dataclass
class ReviewReport:
    """单标的审查报告。"""
    code: str
    name: str
    candidate: MonsterCandidate
    challenges: list[Challenge]
    responses: list[Response]
    verdict: Verdict
    mode: str = "llm"  # llm / rule_fallback
    fallback_reason: str = ""


# ------------------------------------------------------------
# 1. 触发筛选（纯规则，可复现）
# ------------------------------------------------------------

def select_monster_candidates(
    ranking: list[dict],
    volatility_pctiles: dict[str, float],
) -> list[MonsterCandidate]:
    """从排行数据中筛选妖股候选。

    Args:
        ranking: 排行列表，每项含 code/name/gain_10d/volatility_5d/limit_up_5d
        volatility_pctiles: {code: 波动率全市场百分位(0-100)}
    """
    candidates = []
    for item in ranking:
        code = item.get("code", "")
        gain = float(item.get("gain_10d", 0.0) or 0.0)
        vol = float(item.get("volatility_5d", 0.0) or 0.0)
        limit_up = int(item.get("limit_up_5d", 0) or 0)
        pctile = float(volatility_pctiles.get(code, 0.0))

        reasons = []
        if gain >= TRIGGER_10D_GAIN_PCT:
            reasons.append(f"10日涨幅 {gain:.1f}% 超阈值 {TRIGGER_10D_GAIN_PCT}%")
        if pctile >= TRIGGER_VOLATILITY_PCTILE:
            reasons.append(f"5日波动率位于全市场 {pctile:.0f} 分位（阈值 {TRIGGER_VOLATILITY_PCTILE:.0f}）")
        if limit_up >= TRIGGER_LIMIT_UP_5D:
            reasons.append(f"5日内涨停 {limit_up} 次（阈值 {TRIGGER_LIMIT_UP_5D}）")

        if reasons:
            candidates.append(MonsterCandidate(
                code=code, name=item.get("name", code),
                gain_10d_pct=gain, volatility_5d_pct=vol,
                volatility_pctile=pctile, limit_up_5d=limit_up, reasons=reasons,
            ))
    return candidates


# ------------------------------------------------------------
# 2. 规则降级质疑（LLM 不可用时）
# ------------------------------------------------------------

def _rule_challenges(c: MonsterCandidate) -> list[Challenge]:
    """由规则生成质疑（降级路径）。"""
    ch = []
    if c.gain_10d_pct >= SEVERITY_HIGH_GAIN_PCT:
        ch.append(Challenge(
            point="短期涨幅过大，存在回调风险",
            evidence=f"10日涨幅 {c.gain_10d_pct:.1f}% 已超高关注阈值 {SEVERITY_HIGH_GAIN_PCT}%",
            severity="high",
        ))
    elif c.gain_10d_pct >= TRIGGER_10D_GAIN_PCT:
        ch.append(Challenge(
            point="短期涨幅偏高",
            evidence=f"10日涨幅 {c.gain_10d_pct:.1f}% 超触发阈值 {TRIGGER_10D_GAIN_PCT}%",
            severity="medium",
        ))
    if c.volatility_pctile >= SEVERITY_HIGH_VOLATILITY_PCTILE:
        ch.append(Challenge(
            point="波动率极端，筹码不稳定",
            evidence=f"5日波动率位于全市场 {c.volatility_pctile:.0f} 分位（高关注 {SEVERITY_HIGH_VOLATILITY_PCTILE:.0f}）",
            severity="high",
        ))
    elif c.volatility_pctile >= TRIGGER_VOLATILITY_PCTILE:
        ch.append(Challenge(
            point="波动率偏高",
            evidence=f"5日波动率位于全市场 {c.volatility_pctile:.0f} 分位",
            severity="medium",
        ))
    if c.limit_up_5d >= TRIGGER_LIMIT_UP_5D:
        ch.append(Challenge(
            point="连续涨停，情绪过热",
            evidence=f"5日内涨停 {c.limit_up_5d} 次",
            severity="medium",
        ))
    if not ch:
        ch.append(Challenge(
            point="进入妖股候选但无突出规则风险",
            evidence="触发规则命中（详见 reasons），但各项指标未达高关注阈值",
            severity="low",
        ))
    return ch


def _rule_verdict(c: MonsterCandidate, challenges: list[Challenge]) -> Verdict:
    """由规则生成收敛结论（降级路径）。"""
    if any(x.severity == "high" for x in challenges):
        return Verdict("warning", f"{c.name}：存在高严重度规则风险（涨幅/波动率超阈值），建议警示关注")
    if any(x.severity == "medium" for x in challenges):
        return Verdict("downgrade", f"{c.name}：存在中严重度规则风险，建议降级关注")
    return Verdict("normal", f"{c.name}：规则风险可控")


# ------------------------------------------------------------
# 3. Prompt 组装
# ------------------------------------------------------------

_SYSTEM_CHALLENGER = (
    "你是金融风险审查员。你的职责：\n"
    "1. 对给定的高涨幅/高波动股票（妖股候选）提出风险质疑\n"
    "2. 质疑必须有数据依据，不得编造数字\n"
    "3. 不确定的地方必须说'数据不足'\n"
    "4. 你绝对不能：给出买卖建议、预测未来涨跌、评估投资价值\n"
    "5. 只用 JSON 输出，格式：[{\"point\": \"质疑点\", \"evidence\": \"依据\", \"severity\": \"high|medium|low\"}]\n"
)

_SYSTEM_RESPONDER = (
    "你是金融研究报告主笔。你的职责：\n"
    "1. 对风险审查员的质疑逐条回应\n"
    "2. 结合已提供的规则数据（涨幅/波动率/量能/市场温度）判断：支持质疑 / 反驳质疑 / 数据不足\n"
    "3. 你绝对不能：编造数字、给出买卖建议、预测未来涨跌\n"
    "4. 只用 JSON 输出，格式：[{\"challenge\": \"对应质疑点\", \"stance\": \"support|rebut|insufficient\", \"reason\": \"理由\"}]\n"
)

_SYSTEM_SUMMARIZER = (
    "你是风险审查总结人。你的职责：\n"
    "1. 综合质疑与回应，输出收敛结论\n"
    "2. 关注度建议三选一：normal（正常关注）/ downgrade（降级关注）/ warning（警示关注）\n"
    "3. 结论是研究信号，不是操作指令\n"
    "4. 只用 JSON 输出，格式：{\"attention\": \"normal|downgrade|warning\", \"summary\": \"理由摘要\"}\n"
)


def _candidate_data_text(c: MonsterCandidate) -> str:
    return (
        f"标的：{c.name}（{c.code}）\n"
        f"10日涨幅：{c.gain_10d_pct:.1f}%\n"
        f"5日波动率：{c.volatility_5d_pct:.1f}%（全市场 {c.volatility_pctile:.0f} 分位）\n"
        f"5日涨停次数：{c.limit_up_5d}\n"
        f"触发原因：{'；'.join(c.reasons)}"
    )


# ------------------------------------------------------------
# 4. 响应解析（容错）
# ------------------------------------------------------------

def _parse_json_response(text: str) -> Any:
    """容错解析 LLM 输出：去围栏、截取 JSON 段、失败返回 None。"""
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1]
        if t.endswith("```"):
            t = t[:-3]
    # 优先匹配最外层的 [...]（列表），再试 {...}（对象）：
    # 若先提取 {...}，会把 [{"a": ...}] 截成 {"a": ...}，丢失列表结构
    for s, e in [(t.find("["), t.rfind("]")), (t.find("{"), t.rfind("}"))]:
        if s >= 0 and e > s:
            try:
                return json.loads(t[s:e + 1])
            except json.JSONDecodeError:
                continue
    return None


def parse_challenges(text: str) -> list[Challenge]:
    data = _parse_json_response(text)
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if isinstance(item, dict) and item.get("point"):
            out.append(Challenge(
                point=str(item["point"]),
                evidence=str(item.get("evidence", "")),
                severity=str(item.get("severity", "medium")) if item.get("severity") in ("high", "medium", "low") else "medium",
            ))
    return out


def parse_responses(text: str) -> list[Response]:
    data = _parse_json_response(text)
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if isinstance(item, dict) and item.get("challenge"):
            stance = item.get("stance", "insufficient")
            if stance not in ("support", "rebut", "insufficient"):
                stance = "insufficient"
            out.append(Response(
                challenge_point=str(item["challenge"]),
                stance=stance,
                reason=str(item.get("reason", "")),
            ))
    return out


def parse_verdict(text: str) -> Optional[Verdict]:
    data = _parse_json_response(text)
    if not isinstance(data, dict):
        return None
    attention = data.get("attention", "normal")
    if attention not in ("normal", "downgrade", "warning"):
        attention = "normal"
    return Verdict(attention=attention, summary=str(data.get("summary", "")))


# ------------------------------------------------------------
# 5. 审查主流程
# ------------------------------------------------------------

class MonsterReviewer:
    """妖股审查员：审查员质疑 → 主报告回应 → 收敛结论。"""

    def __init__(self, client: Optional[LLMCompletionClient] = None,
                 max_daily_calls: int = MAX_DAILY_LLM_CALLS) -> None:
        self._client = client
        self.max_daily_calls = max_daily_calls
        self._calls_used = 0
        self._date = datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d")

    def _llm_available(self) -> bool:
        if not LLM_ENABLED:
            return False
        if self._client is None:
            self._client = LLMClient()
        try:
            return bool(self._client.is_available())
        except Exception:
            return False

    def _complete(self, system: str, user: str) -> str:
        if self._calls_used >= self.max_daily_calls:
            raise RuntimeError("daily_call_limit")
        text = self._client.complete(system, user, temperature=0.3)  # type: ignore[union-attr]
        self._calls_used += 1
        return text

    def review(self, candidate: MonsterCandidate) -> ReviewReport:
        """对单个候选执行两轮对话审查。"""
        c = candidate
        fallback_reason = ""
        data_text = _candidate_data_text(c)

        if not self._llm_available():
            fallback_reason = "llm_unavailable"
        else:
            try:
                # 第一轮：审查员质疑
                raw = self._complete(_SYSTEM_CHALLENGER, data_text)
                challenges = parse_challenges(raw)
                if not challenges:
                    raise ValueError("empty_challenges")
                # 第二轮：主报告回应
                resp_text = "\n".join(f"- {x.point}（{x.severity}）: {x.evidence}" for x in challenges)
                raw2 = self._complete(_SYSTEM_RESPONDER, data_text + "\n\n审查员质疑：\n" + resp_text)
                responses = parse_responses(raw2)
                if not responses:
                    responses = [Response(x.point, "insufficient", "主报告未给出有效回应") for x in challenges]
                # 收敛：总结人
                raw3 = self._complete(_SYSTEM_SUMMARIZER, data_text + "\n\n质疑与回应：\n" + resp_text)
                verdict = parse_verdict(raw3) or _rule_verdict(c, challenges)
                return ReviewReport(c.code, c.name, c, challenges, responses, verdict, mode="llm")
            except (LLMUnavailableError, ValueError, RuntimeError, Exception) as exc:
                logger.warning("MonsterReviewer LLM 路径失败，降级规则质疑: %s", exc)
                fallback_reason = str(exc) if not isinstance(exc, LLMUnavailableError) else exc.category

        # 降级：规则质疑
        challenges = _rule_challenges(c)
        responses = [Response(x.point, "insufficient", "LLM 不可用，未生成主报告回应") for x in challenges]
        verdict = _rule_verdict(c, challenges)
        return ReviewReport(c.code, c.name, c, challenges, responses, verdict,
                            mode="rule_fallback", fallback_reason=fallback_reason)

    def review_all(self, candidates: list[MonsterCandidate]) -> list[ReviewReport]:
        return [self.review(c) for c in candidates]


# ------------------------------------------------------------
# 6. 报告渲染
# ------------------------------------------------------------

def render_review_section(reports: list[ReviewReport]) -> str:
    """渲染"妖股风险审查"报告章节（markdown）。"""
    lines = ["## 妖股风险审查", ""]
    if not reports:
        lines.append("今日无高波动标的（未触发审查规则）。")
        return "\n".join(lines)

    lines.append(f"今日触发审查标的：{len(reports)} 只")
    lines.append("")
    for r in reports:
        lines.append(f"### {r.name}（{r.code}）")
        if r.mode == "rule_fallback":
            lines.append(f"*审查模式：规则降级（{r.fallback_reason}）*")
            lines.append("")
        lines.append("**触发原因**：" + "；".join(r.candidate.reasons))
        lines.append("")
        lines.append("**审查员质疑**：")
        for x in r.challenges:
            lines.append(f"- [{x.severity}] {x.point} — {x.evidence}")
        lines.append("")
        lines.append("**主报告回应**：")
        for x in r.responses:
            stance_map = {"support": "支持质疑", "rebut": "反驳质疑", "insufficient": "数据不足"}
            lines.append(f"- {x.challenge_point} → {stance_map.get(x.stance, x.stance)}：{x.reason}")
        lines.append("")
        lines.append(f"**收敛结论**：{r.verdict.attention} — {r.verdict.summary}")
        lines.append("")
    lines.append("> 审查结论为研究信号，仅供参考，不构成投资建议。")
    return "\n".join(lines)


# ------------------------------------------------------------
# 7. CLI
# ------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="妖股审查员智能体")
    parser.add_argument("--date", default=datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d"),
                        help="交易日 YYYY-MM-DD")
    parser.add_argument("--demo", action="store_true",
                        help="用内置演示数据运行（无需真实排行数据）")
    args = parser.parse_args(argv)

    if args.demo:
        candidates = [
            MonsterCandidate("001258", "立新能源", 112.0, 8.5, 99.5, 7,
                             ["10日涨幅 112.0% 超阈值 30%", "5日波动率位于全市场 100 分位"]),
            MonsterCandidate("002230", "科大讯飞", 8.0, 2.1, 60.0, 0, []),
        ]
        candidates = [c for c in candidates if c.reasons]
    else:
        # 生产路径：从排行数据筛选（由调用方传入，此处演示降级）
        candidates = []

    if not candidates:
        print("今日无妖股候选标的（或未提供排行数据）。")
        return 0

    reviewer = MonsterReviewer()
    reports = reviewer.review_all(candidates)
    section = render_review_section(reports)
    print(section)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
