# -*- coding: utf-8 -*-
"""src/sector_rotation/llm_decision_advisor.py —— 大模型辅助决策顾问与审计追溯模块

核心职责：
1. 结构化 Prompt 构建：基于 SECTOR_ROTATION_SPEC §3，组装包含当前持仓、量化建议、候选板块状态的风控咨询 Prompt，
   要求大模型在 150 字以内给出专业解释与确定性 JSON 输出。
2. 确定性低随机度调用：固定 temperature=0.2，控制生成发散度。
3. 非阻塞优雅降级 (Non-Blocking Fallback)：
   - 当未配置 LLM 客户端、客户端不可用、网络超时 (30s)、抛出 LLMUnavailableError 或其它异常、
     或者大模型返回格式破坏/损坏时，100% 优雅回退到量化决策结果，绝不阻断系统流水线。
4. 全流程审计落盘 (Audit Trail)：每一笔调用均记录时间戳、输入提示词、原始输出、解析结构与最终决策到结构化 AuditRecord。
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from .config import LLM_TIMEOUT, SECTORS
from .sector_rotation_engine import RotationDecision
from .utils.sector_utils import SectorState, validate_confidence

logger = logging.getLogger("stock-dashboard.sector_rotation.advisor")


# ============================================================================
# 1. 审计轨迹数据契约
# ============================================================================

@dataclass
class AuditRecord:
    """大模型辅助决策调用审计轨迹契约"""
    timestamp: str
    current_sector: str
    target_sector: Optional[str]
    prompt: str
    raw_response: str
    parsed_decision: Optional[Dict[str, Any]]
    final_decision: RotationDecision
    success: bool
    fallback_reason: Optional[str] = None
    execution_time_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """转换为可落盘的审计记录字典"""
        return {
            "timestamp": self.timestamp,
            "current_sector": self.current_sector,
            "target_sector": self.target_sector,
            "prompt": self.prompt,
            "raw_response": self.raw_response,
            "parsed_decision": self.parsed_decision,
            "final_decision": self.final_decision.to_dict() if hasattr(self.final_decision, "to_dict") else str(self.final_decision),
            "success": self.success,
            "fallback_reason": self.fallback_reason,
            "execution_time_ms": round(self.execution_time_ms, 3),
        }


# ============================================================================
# 2. 大模型决策顾问
# ============================================================================

class LLMDecisionAdvisor:
    """大模型辅助决策与可解释性风控顾问"""

    def __init__(
        self,
        llm_client: Any = None,
        temperature: float = 0.2,
        timeout: int = LLM_TIMEOUT,
        max_tokens: int = 500,
    ) -> None:
        """初始化大模型决策顾问。

        Args:
            llm_client: LLM 补全客户端实例（可选；若未传入则运行时自动降级）
            temperature: 确定性采样温度，默认 0.2
            timeout: 单次调用超时阈值（秒），默认 30
            max_tokens: 最大生成 Token 限制，默认 500
        """
        self.llm_client = llm_client
        self.temperature = float(temperature)
        self.timeout = int(timeout)
        self.max_tokens = int(max_tokens)
        self.audit_log: List[AuditRecord] = []

    def build_prompt(
        self,
        current_sector: str,
        target_sector: Optional[str] = None,
        current_sentiment: float = 0.0,
        target_sentiment: float = 0.0,
        sector_states: Optional[Dict[str, SectorState]] = None,
        quant_decision: Optional[RotationDecision] = None,
    ) -> str:
        """构建标准化的大模型风控决策咨询 Prompt。

        对齐 SECTOR_ROTATION_SPEC §3，包含结构化持仓、候选板块与格式约束。
        """
        curr_sec_name = SECTORS.get(current_sector).name if current_sector in SECTORS else current_sector
        target_sec_name = (
            SECTORS.get(target_sector).name
            if (target_sector and target_sector in SECTORS)
            else (target_sector or "无")
        )

        curr_state = sector_states.get(current_sector) if sector_states else None
        curr_trend = curr_state.sentiment_trend if curr_state else "未知"
        curr_score = curr_state.sentiment_score if curr_state else current_sentiment
        curr_conf = curr_state.confidence if curr_state else 0.80

        quant_rotate = "是" if (quant_decision and quant_decision.should_rotate) else "否"
        quant_target = (quant_decision.target_sector if quant_decision else target_sector) or "无"
        quant_reason = quant_decision.reason if quant_decision else "未提供量化理由"

        # 候选板块概览
        candidates_lines: List[str] = []
        if sector_states:
            for sec_id, state in sector_states.items():
                sec_label = SECTORS.get(sec_id).name if sec_id in SECTORS else sec_id
                candidates_lines.append(
                    f"- {sec_id} ({sec_label}): 情绪得分={state.sentiment_score:.2f}, "
                    f"趋势={state.sentiment_trend}, 置信度={state.confidence:.2f}, 波动率={state.volatility:.2f}"
                )
        else:
            candidates_lines.append(f"- {target_sector or '无'}: 预期情绪得分={target_sentiment:.2f}")

        candidate_sectors_str = "\n".join(candidates_lines)

        prompt = f"""你是 Rainbow-FinGPT 板块轮动系统的专业风控顾问。

当前持仓状态：
- 持仓板块: {current_sector} ({curr_sec_name})
- 板块情绪得分: {curr_score:.2f}
- 情绪趋势: {curr_trend}
- 置信度: {curr_conf:.2f}

量化引擎建议：
- 是否建议轮动: {quant_rotate}
- 目标推荐板块: {quant_target} ({target_sec_name})
- 量化触发理由: {quant_reason}

市场全板块综合状态：
{candidate_sectors_str}

请作为独立风控顾问进行全面复核：
1. 当前板块是否需要轮动？（是/否）
2. 如果需要轮动，确认推荐切换到哪个目标板块？
3. 决策理由（严格控制在150字以内，逻辑客观严谨）

输出格式必须严格为合法 JSON（不得包含其他杂乱文字）：
{{
    "should_rotate": true,
    "target_sector": "{quant_target}",
    "reason": "当前板块处于下沉通道，目标板块处于强景气周期...",
    "confidence": 0.85
}}"""
        return prompt

    def _parse_llm_response(self, raw_text: str) -> Dict[str, Any]:
        """鲁棒解析 LLM 返回的 JSON 决策内容。

        支持：
        - Markdown ```json ... ``` 代码块包裹提取
        - 自由文本中寻找最外层花括号 {...}
        - 字段存在性校验与类型规范化
        """
        if not raw_text or not raw_text.strip():
            raise ValueError("LLM 返回内容为空")

        cleaned = raw_text.strip()

        # 1. 尝试提取 ```json ... ``` 或 ``` ... ``` 中的内容
        fence_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", cleaned, re.IGNORECASE)
        if fence_match:
            json_str = fence_match.group(1).strip()
        else:
            # 2. 寻找最外层花括号
            brace_start = cleaned.find("{")
            brace_end = cleaned.rfind("}")
            if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
                json_str = cleaned[brace_start : brace_end + 1].strip()
            else:
                json_str = cleaned

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as err:
            raise ValueError(f"无法将文本解析为有效 JSON: {err}，原始内容: {raw_text[:200]}") from err

        if not isinstance(data, dict):
            raise ValueError(f"JSON 根对象必须为字典，收到: {type(data)}")

        # 字段校验与清洗
        if "should_rotate" not in data:
            raise ValueError("缺失关键字段: 'should_rotate'")

        raw_rotate = data["should_rotate"]
        if isinstance(raw_rotate, str):
            should_rotate = raw_rotate.strip().lower() in ("true", "1", "yes", "是")
        else:
            should_rotate = bool(raw_rotate)

        target_sector = data.get("target_sector")
        if target_sector is not None:
            target_sector = str(target_sector).strip().lower()
            if target_sector in ("", "null", "none"):
                target_sector = None

        reason = str(data.get("reason", "")).strip()
        # 裁剪至 150 字以内
        if len(reason) > 150:
            reason = reason[:147] + "..."

        confidence = validate_confidence(data.get("confidence", 0.80))

        return {
            "should_rotate": should_rotate,
            "target_sector": target_sector,
            "reason": reason,
            "confidence": confidence,
        }

    def advise(
        self,
        current_sector: str,
        sector_states: Dict[str, SectorState],
        quantitative_decision: RotationDecision,
        llm_client: Any = None,
    ) -> RotationDecision:
        """调用大模型复核量化决策，保证非阻塞降级并记录审计日志。

        Args:
            current_sector: 当前持仓板块
            sector_states: 全板块状态字典
            quantitative_decision: 量化引擎产出的原始决策
            llm_client: 可选指定的 LLM 客户端实例（若为 None 则使用实例自带客户端）

        Returns:
            RotationDecision 经大模型复核（或降级）后的最终决策
        """
        t0 = time.perf_counter()
        now_ts = datetime.now().isoformat()
        client = llm_client if llm_client is not None else self.llm_client

        # 构造标准提示词
        curr_score = (
            sector_states[current_sector].sentiment_score
            if (sector_states and current_sector in sector_states)
            else 0.0
        )
        target_score = 0.0
        if quantitative_decision.target_sector and sector_states and quantitative_decision.target_sector in sector_states:
            target_score = sector_states[quantitative_decision.target_sector].sentiment_score

        prompt = self.build_prompt(
            current_sector=current_sector,
            target_sector=quantitative_decision.target_sector,
            current_sentiment=curr_score,
            target_sentiment=target_score,
            sector_states=sector_states,
            quant_decision=quantitative_decision,
        )

        # --------------------------------------------------------------------
        # 场景 A: 无可用 LLM 客户端 -> 立即优雅降级（非阻塞，执行时间 < 1ms）
        # --------------------------------------------------------------------
        is_client_available = client is not None
        if is_client_available:
            if hasattr(client, "is_available") and not client.is_available:
                is_client_available = False
            elif hasattr(client, "enabled") and not client.enabled:
                is_client_available = False

        if not is_client_available:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            fallback_reason = "LLM client not provided or disabled; falling back to quantitative decision"
            final_decision = RotationDecision(
                should_rotate=quantitative_decision.should_rotate,
                current_sector=current_sector,
                target_sector=quantitative_decision.target_sector,
                reason=quantitative_decision.reason,
                confidence=quantitative_decision.confidence,
                is_fallback=True,
                llm_rationale=fallback_reason,
                execution_time_ms=elapsed_ms,
                timestamp=now_ts,
                metrics=quantitative_decision.metrics,
                llm_validation={"fallback": True, "reason": fallback_reason},
            )
            record = AuditRecord(
                timestamp=now_ts,
                current_sector=current_sector,
                target_sector=quantitative_decision.target_sector,
                prompt=prompt,
                raw_response="",
                parsed_decision=None,
                final_decision=final_decision,
                success=False,
                fallback_reason=fallback_reason,
                execution_time_ms=elapsed_ms,
            )
            self.audit_log.append(record)
            return final_decision

        # --------------------------------------------------------------------
        # 场景 B: 调用 LLM 客户端并解析响应
        # --------------------------------------------------------------------
        raw_response = ""
        try:
            if hasattr(client, "complete"):
                raw_response = client.complete(
                    system_prompt="你是 Rainbow-FinGPT 严谨的板块轮动量化风控顾问，严格按 JSON 输出。",
                    user_prompt=prompt,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                )
            elif hasattr(client, "generate"):
                raw_response = client.generate(prompt)
            elif callable(client):
                raw_response = client(prompt)
            else:
                raise ValueError(f"未知的 LLM 客户端调用契约: {type(client)}")

            parsed = self._parse_llm_response(raw_response)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            # 成功解析：构建合规决策对象
            final_decision = RotationDecision(
                should_rotate=parsed["should_rotate"],
                current_sector=current_sector,
                target_sector=parsed["target_sector"] if parsed["should_rotate"] else None,
                reason=parsed["reason"] or quantitative_decision.reason,
                confidence=parsed["confidence"],
                is_fallback=False,
                llm_rationale=parsed["reason"],
                execution_time_ms=elapsed_ms,
                timestamp=now_ts,
                metrics=quantitative_decision.metrics,
                llm_validation=parsed,
            )
            record = AuditRecord(
                timestamp=now_ts,
                current_sector=current_sector,
                target_sector=final_decision.target_sector,
                prompt=prompt,
                raw_response=raw_response,
                parsed_decision=parsed,
                final_decision=final_decision,
                success=True,
                fallback_reason=None,
                execution_time_ms=elapsed_ms,
            )
            self.audit_log.append(record)
            return final_decision

        except Exception as exc:
            # ----------------------------------------------------------------
            # 场景 C: 网络故障、超时 (30s) 或输出格式异常 -> 降级保护
            # ----------------------------------------------------------------
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            error_reason = f"LLM error: {type(exc).__name__} ({str(exc)})"
            logger.warning(
                "LLMDecisionAdvisor 遇到异常，自动降级至量化决策: %s",
                error_reason,
            )

            fallback_decision = RotationDecision(
                should_rotate=quantitative_decision.should_rotate,
                current_sector=current_sector,
                target_sector=quantitative_decision.target_sector,
                reason=quantitative_decision.reason,
                confidence=quantitative_decision.confidence,
                is_fallback=True,
                llm_rationale=f"LLM degraded ({error_reason}); quantitative decision preserved",
                execution_time_ms=elapsed_ms,
                timestamp=now_ts,
                metrics=quantitative_decision.metrics,
                llm_validation={"fallback": True, "error": error_reason},
            )
            record = AuditRecord(
                timestamp=now_ts,
                current_sector=current_sector,
                target_sector=quantitative_decision.target_sector,
                prompt=prompt,
                raw_response=raw_response,
                parsed_decision=None,
                final_decision=fallback_decision,
                success=False,
                fallback_reason=error_reason,
                execution_time_ms=elapsed_ms,
            )
            self.audit_log.append(record)
            return fallback_decision

    def validate_decision(
        self,
        quantitative_decision: RotationDecision,
        sector_data: Dict[str, SectorState],
        current_sector: str = "",
        llm_client: Any = None,
    ) -> RotationDecision:
        """兼容 AGENT_TASK_ASSIGNMENT §2.1 命名的验证接口。"""
        eff_current = current_sector or quantitative_decision.current_sector
        return self.advise(
            current_sector=eff_current,
            sector_states=sector_data,
            quantitative_decision=quantitative_decision,
            llm_client=llm_client,
        )

    def generate_reasoning(self, quantitative_scores: Dict[str, float]) -> str:
        """生成基于量化分数的自然语言归因解释。"""
        if not quantitative_scores:
            return "暂无有效板块量化评分数据。"
        sorted_scores = sorted(quantitative_scores.items(), key=lambda x: x[1], reverse=True)
        top_sector, top_score = sorted_scores[0]
        top_name = SECTORS.get(top_sector).name if top_sector in SECTORS else top_sector
        return (
            f"根据最新多因子量化评估，{top_name} ({top_sector}) 综合评分达到 {top_score:.2f}，"
            f"在全市场中呈现显著景气优势。"
        )

    def clear_audit_log(self) -> None:
        """清空历史审计记录。"""
        self.audit_log.clear()

    def get_audit_history(self) -> List[Dict[str, Any]]:
        """获取序列化格式的历史审计轨迹列表。"""
        return [record.to_dict() for record in self.audit_log]

    @property
    def last_audit_record(self) -> Optional[AuditRecord]:
        """获取最近一条审计记录。"""
        return self.audit_log[-1] if self.audit_log else None
