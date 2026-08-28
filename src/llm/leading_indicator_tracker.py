# -*- coding: utf-8 -*-
"""src/llm/leading_indicator_tracker.py —— FinGPT 风格产业链源头追踪与事实三元抽取器

核心能力（落实老师信件与师叔 Serenity 框架）：
1. 事实-观点-推断三元结构化解析（Fact-Opinion-Inference Triangulation）；
2. 提取高频产业领先信号（现货盘口、原厂调价通知、海关出口数据、大客户招标）；
3. 摆脱季度财报滞后性，输出前瞻性供需拐点与阶段跃迁判定。
"""

import json
import logging
from typing import Any, Dict, List, Optional

from .fingpt_deepseek_adapter import FinGPTDeepSeekAdapter
from .llm_client import LLMCompletionClient
from ..analysis.leading_indicators import LeadingIndicatorEngine

logger = logging.getLogger("stock-dashboard.llm.leading_tracker")

_TRACKER_SYSTEM_PROMPT = (
    "你是精通硬科技与半导体产业链的 FinGPT 级产业投研分析师。\n"
    "你的任务是帮助投资者'穿透滞后的季度财报'，从一手材料中提取高频产业领先信号。\n\n"
    "必须遵守的输出规则：\n"
    "1. 事实标注规范（严格区分事实与观点）：\n"
    "   - [FACT:来源] 客观可核验的一手事实（海关数据、原厂调价函、中标公告、财报数字等）\n"
    "   - [OPINION:主体] 主观判断或预测（管理层展望、研报观点、大V言论）\n"
    "   - [INFERENCE:推导] 基于事实推导出的供需拐点结论\n"
    "2. 严禁编造数据。如果新闻材料中缺乏高频线索，请诚实注明'高频线索不足，维持滞后报表观察'。\n"
    "3. 识别标的所在的真实工艺节点（严禁将下游组装当成上游核心卡点）。\n"
    "4. 最终仅输出标准的 JSON 格式。"
)

_TRACKER_USER_TEMPLATE = """请对标的【{stock_name}（{stock_code}）】进行产业链源头追踪与先行信号分析：

【所属行业与节点】：{industry}
【高频先行指标监测】：{leading_metric_desc} (近30天动量: {slope_pct}%, 状态: {momentum})
【最新新闻/公告/互动易线索】：
{news_context}

请输出严格符合以下格式的 JSON：
{{
  "stock_code": "{stock_code}",
  "stock_name": "{stock_name}",
  "process_node": "标的所处的具体工艺节点（如：单晶衬底 / 外延片 / 芯片设计制造 / 模块封装 / 系统集成）",
  "bottleneck_nature": "true_chokepoint | downstream_assembly | commodity",
  "leading_signals": [
    {{
      "type": "FACT",
      "source": "海关/原厂/公告/现货报价等信源",
      "content": "提取的具体高频先行线索"
    }}
  ],
  "opinion_and_guidance": [
    {{
      "type": "OPINION",
      "holder": "管理层/分析师/客户",
      "content": "前瞻性指引或情绪观点"
    }}
  ],
  "inference_conclusion": {{
    "stage": "Concept | Sample | Pilot | Mass_Production | Primary_Supplier",
    "inflection_verdict": "accelerating | steady | decelerating | uncertain",
    "summary": "基于一手高频线索推导出的核心结论（100字以内）"
  }}
}}
"""


class LeadingIndicatorTracker:
    """FinGPT 产业链源头追踪器。"""

    def __init__(self, client: Optional[LLMCompletionClient] = None):
        self.client = client
        self.adapter = None
        # 安全兼容：若传入了非 deepseek 的 client，安全降级为规则模式而不抛出异常
        try:
            self.adapter = FinGPTDeepSeekAdapter(client=client)
        except Exception as e:
            logger.info("LeadingIndicatorTracker 降级为规则模式: %s", e)
        self.indicator_engine = LeadingIndicatorEngine()

    def analyze_source_signals(
        self,
        stock_code: str,
        stock_name: str,
        industry: str,
        news_list: Optional[List[Dict[str, Any]]] = None,
        custom_series: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        """对单只标的进行源头先行信号追踪与事实三元标注。"""
        category = self.indicator_engine.match_industry_category(industry)
        signal_snapshot = self.indicator_engine.generate_synthetic_leading_signal(
            category, historical_trend=custom_series
        )
        metrics = signal_snapshot["momentum_metrics"]

        formatted_news = []
        if news_list:
            for item in news_list[:8]:
                title = item.get("title", "")
                src = item.get("source", "资讯")
                date_str = item.get("date", item.get("publish_time", ""))
                summary = item.get("summary", item.get("content", ""))[:120]
                formatted_news.append(f"- [{date_str} {src}] {title}：{summary}")

        news_context = "\n".join(formatted_news) if formatted_news else "暂无一手高频资讯线索。"

        user_prompt = _TRACKER_USER_TEMPLATE.format(
            stock_code=stock_code,
            stock_name=stock_name,
            industry=industry,
            leading_metric_desc=signal_snapshot["description"],
            slope_pct=metrics.get("slope_pct", 0.0),
            momentum=metrics.get("momentum", "flat"),
            news_context=news_context,
        )

        if not self.adapter or not self.adapter.is_available:
            return self._fallback_rule_result(
                stock_code, stock_name, industry, signal_snapshot, formatted_news
            )

        try:
            resp_text = self.adapter._client.complete(
                system_prompt=_TRACKER_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.2,
                max_tokens=1000,
            )
            parsed = self._extract_json(resp_text)
            parsed["leading_macro_metrics"] = signal_snapshot
            return parsed
        except Exception as e:
            logger.warning("LLM 源头追踪失败，降级为规则处理: %s", e)
            return self._fallback_rule_result(
                stock_code, stock_name, industry, signal_snapshot, formatted_news, str(e)
            )

    def _extract_json(self, text: str) -> Dict[str, Any]:
        """从大模型响应中稳健提取 JSON。"""
        text = text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines[0].startswith("```json"):
                lines = lines[1:]
            elif lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        return json.loads(text)

    def _fallback_rule_result(
        self,
        stock_code: str,
        stock_name: str,
        industry: str,
        signal_snapshot: Dict[str, Any],
        news_items: List[str],
        error_msg: Optional[str] = None,
    ) -> Dict[str, Any]:
        """规则降级产物。"""
        metrics = signal_snapshot["momentum_metrics"]
        return {
            "stock_code": stock_code,
            "stock_name": stock_name,
            "process_node": "待人工或LLM校验",
            "bottleneck_nature": "downstream_assembly",
            "leading_signals": [
                {
                    "type": "FACT",
                    "source": "先行高频指标监控",
                    "content": f"{signal_snapshot['description']}，近30天斜率 {metrics.get('slope_pct', 0)}%",
                }
            ],
            "opinion_and_guidance": [],
            "inference_conclusion": {
                "stage": "Pilot",
                "inflection_verdict": metrics.get("momentum", "steady"),
                "summary": "【降级模式】基于宏观高频指标监控生成，建议结合一手招标与原厂涨价通知复核。",
            },
            "leading_macro_metrics": signal_snapshot,
            "fallback": True,
            "fallback_reason": error_msg or self.adapter.unavailable_reason,
        }