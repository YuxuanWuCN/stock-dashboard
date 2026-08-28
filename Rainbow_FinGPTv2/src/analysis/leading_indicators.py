"""src/analysis/leading_indicators.py —— 产业链高频领先指标抓取与拐点计算器

职责：
1. 从公开高频源（海关出口、现货价格、行业高频指数）获取先行数据，打破季度财报滞后 1~3 个月的时滞；
2. 计算领先指标的 30 天/月度斜率 (momentum) 与 拐点信号 (inflection_flag)；
3. 输出结构化领先指标数据，供 FinGPT 研报管线与 Alpha 门控使用。

设计理念（对应老师信件第一条）：
- 财报是“滞后确认”，领先数据是“先行信号”；
- 原厂报价/海关出口先行反映供需拐点。
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("stock-dashboard.analysis.leading_indicators")

# 预定义的行业领先指标映射（工艺卡点与先行观测点）
INDUSTRY_LEADING_MAP = {
    "semiconductor": {
        "name": "半导体/存储芯片",
        "description": "存储芯片现货价格、进出口均价、原厂报价通知",
        "keywords": ["存储芯片", "DRAM", "NAND", "InP衬底", "晶圆代工", "先进制程"],
        "proxy_type": "customs_and_spot_price",
    },
    "optical_communication": {
        "name": "光模块/光芯片",
        "description": "光模块出口额、云厂商资本开支指引、InP/EML激光芯片订单",
        "keywords": ["800G", "1.6T", "EML", "光芯片", "InP衬底", "CPO", "硅光"],
        "proxy_type": "capex_and_order_flow",
    },
    "new_energy": {
        "name": "新能源/光伏/锂电",
        "description": "上游多晶硅/碳酸锂现货价格、装机开工率、组件出口",
        "keywords": ["碳酸锂", "多晶硅", "装机量", "并网", "电价补贴"],
        "proxy_type": "commodity_spot_price",
    },
    "gold_resources": {
        "name": "贵金属/有色资源",
        "description": "COMEX黄金现货价、全球央行购金量、实际利率预期",
        "keywords": ["现货黄金", "央行购金", "金银比", "实际利率"],
        "proxy_type": "macro_commodity",
    },
}

# 真实数据源映射（akshare 免费接口；原厂报价/海关出口无稳定免费源，
# 用行业板块指数 / 商品期货现货作"领先代理"，语义见 fetch_real_leading_signal）
REAL_SOURCE_MAP = {
    "semiconductor": {
        "source": "akshare_board_industry",
        "ak_symbol": "半导体",
        "name": "半导体行业指数（领先代理）",
        "description": "东财行业板块指数日线，替代原厂报价/海关出口的免费可行代理",
    },
    "optical_communication": {
        "source": "akshare_board_industry",
        "ak_symbol": "通信设备",
        "name": "通信设备行业指数（领先代理）",
        "description": "东财行业板块指数日线，替代云厂商资本开支指引的免费可行代理",
    },
    "new_energy": {
        "source": "akshare_futures_main",
        "ak_symbol": "LC0",
        "name": "碳酸锂期货主力（领先代理）",
        "description": "碳酸锂期货主力价格，替代多晶硅/组件出口的免费可行代理",
    },
    "gold_resources": {
        "source": "akshare_spot_sge",
        "ak_symbol": "Au99.99",
        "name": "上金所黄金现货（领先代理）",
        "description": "上海黄金交易所 Au99.99 现货价",
    },
}

# 类别级内存缓存：同一类别只抓一次 akshare，避免 202 只标的重发请求
_category_series_cache: Dict[str, Optional[List[float]]] = {}


def _first_available(series_like, candidates: List[str]):
    """从 DataFrame/dict 中按候选列名取第一列可用的数值序列（>=5 个非空值）。"""
    for c in candidates:
        if isinstance(series_like, pd.DataFrame) and c in series_like.columns:
            s = pd.to_numeric(series_like[c], errors="coerce").dropna()
            if len(s) >= 5:
                return s
        elif isinstance(series_like, dict) and c in series_like:
            s = pd.to_numeric(pd.Series(series_like[c]), errors="coerce").dropna()
            if len(s) >= 5:
                return s
    return None


def _fetch_akshare_series(category: str) -> Optional[List[float]]:
    """从 akshare 拉取真实领先序列（惰性导入、异常隔离、候选列名解析）。

    返回按时间排序的数值列表；任何失败（未安装/无网络/接口变更）返回 None。
    """
    cfg = REAL_SOURCE_MAP.get(category)
    if not cfg:
        return None
    try:
        import akshare as ak
    except Exception as exc:  # akshare 未安装或导入失败
        logger.warning("akshare 不可用（%s），领先指标降级合成", exc)
        return None

    symbol = cfg["ak_symbol"]
    try:
        source = cfg["source"]
        if source == "akshare_board_industry":
            raw = ak.stock_board_industry_hist_em(
                symbol=symbol, start_date="20200101", end_date="20991231",
                period="日k", adjust="",
            )
            s = _first_available(raw, ["收盘", "close", "最新价"])
        elif source == "akshare_futures_main":
            raw = ak.futures_main_sina(symbol=symbol)
            s = _first_available(raw, ["收盘价", "close", "最新价", "结算价"])
        elif source == "akshare_spot_sge":
            raw = ak.spot_hist_sge(symbol=symbol)
            s = _first_available(raw, ["price", "收盘价", "close", "最新价"])
        else:
            return None
        if s is None:
            return None
        return s.astype(float).tolist()
    except Exception as exc:
        logger.warning("akshare 抓取 %s(%s) 失败（%s），降级合成", category, symbol, exc)
        return None


def _fetch_akshare_series_cached(category: str) -> Optional[List[float]]:
    """带内存缓存的真实序列抓取（同一类别只抓一次）。"""
    if category not in _category_series_cache:
        _category_series_cache[category] = _fetch_akshare_series(category)
    return _category_series_cache[category]


def calculate_momentum_and_inflection(
    series: pd.Series, window: int = 20
) -> Dict[str, Any]:
    """计算时间序列的动量斜率与拐点信号。

    Args:
        series: 按时间排序的数值序列（无缺失）
        window: 考察窗口期

    Returns:
        dict 包含:
          - slope_pct: 窗口内变化率 (%)
          - momentum: "accelerating" | "decelerating" | "flat"
          - inflection_flag: "positive_reversal" | "negative_reversal" | "none"
    """
    if len(series) < 5:
        return {
            "slope_pct": 0.0,
            "momentum": "flat",
            "inflection_flag": "none",
            "confidence": "low",
        }

    s = series.dropna()
    if len(s) < 5:
        return {
            "slope_pct": 0.0,
            "momentum": "flat",
            "inflection_flag": "none",
            "confidence": "low",
        }

    recent = s.iloc[-min(window, len(s)) :]
    start_val = recent.iloc[0]
    end_val = recent.iloc[-1]

    if start_val == 0:
        slope_pct = 0.0
    else:
        slope_pct = round(float((end_val - start_val) / abs(start_val) * 100), 2)

    # 计算短期 vs 中期动量差（二阶导数识别拐点）
    half = len(recent) // 2
    if half >= 2:
        m1 = (recent.iloc[half] - recent.iloc[0]) / max(abs(recent.iloc[0]), 1e-6)
        m2 = (recent.iloc[-1] - recent.iloc[half]) / max(abs(recent.iloc[half]), 1e-6)

        # 拐点判定
        if m1 < -0.03 and m2 > 0.03:
            inflection = "positive_reversal"  # 触底反转
        elif m1 > 0.03 and m2 < -0.03:
            inflection = "negative_reversal"  # 见顶回落
        else:
            inflection = "none"

        if m2 > 0.05:
            momentum = "accelerating"
        elif m2 < -0.05:
            momentum = "decelerating"
        else:
            momentum = "flat"
    else:
        inflection = "none"
        momentum = "flat"

    return {
        "slope_pct": slope_pct,
        "momentum": momentum,
        "inflection_flag": inflection,
        "latest_value": float(end_val),
        "confidence": "high" if len(s) >= window else "medium",
    }


class LeadingIndicatorEngine:
    """产业链先行领先指标引擎。"""

    def __init__(self, data_dir: Optional[Path] = None):
        if data_dir is None:
            root = Path(__file__).resolve().parent.parent.parent
            self.data_dir = root / "docs" / "data" / "leading_signals"
        else:
            self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def match_industry_category(self, industry_name: str) -> str:
        """将股票的中文行业标签模糊匹配到领先指标分类。"""
        if not industry_name:
            return "general"
        name = industry_name.lower()
        if any(k in name for k in ["半导体", "集成电路", "存储", "芯片", "电子"]):
            return "semiconductor"
        if any(k in name for k in ["通信", "光模块", "光器件", "激光", "cpo", "光通信"]):
            return "optical_communication"
        if any(k in name for k in ["光伏", "风电", "新能源", "锂电", "电池", "绿电"]):
            return "new_energy"
        if any(k in name for k in ["黄金", "贵金属", "有色", "铜", "铝", "资源"]):
            return "gold_resources"
        return "general"

    def generate_synthetic_leading_signal(
        self, category: str, historical_trend: Optional[List[float]] = None
    ) -> Dict[str, Any]:
        """构建高频领先信号快照（支持真实序列输入与规则降级）。"""
        meta = INDUSTRY_LEADING_MAP.get(category, {
            "name": "通用行业",
            "description": "宏观景气度与综合工业品价格",
            "keywords": ["PMI", "工业增加值", "大宗商品"],
            "proxy_type": "macro_general",
        })

        if historical_trend and len(historical_trend) >= 5:
            series = pd.Series(historical_trend)
            calc = calculate_momentum_and_inflection(series)
        else:
            # 默认平稳状态
            calc = {
                "slope_pct": 0.0,
                "momentum": "flat",
                "inflection_flag": "none",
                "latest_value": 100.0,
                "confidence": "low",
            }

        return {
            "category": category,
            "industry_name": meta["name"],
            "description": meta["description"],
            "proxy_type": meta["proxy_type"],
            "keywords": meta["keywords"],
            "data_source": "synthetic_fallback",
            "source_name": "合成降级",
            "momentum_metrics": calc,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def fetch_real_leading_signal(
        self, category: str, historical_trend: Optional[List[float]] = None
    ) -> Dict[str, Any]:
        """抓取真实领先信号：优先 akshare，失败降级合成。

        返回含 data_source（"akshare" | "synthetic_fallback"）的信号快照。
        合成降级的数据绝不参与评分（由 scoring 层判为中性），避免用假数据打分。
        """
        real_series = _fetch_akshare_series_cached(category)
        if real_series:
            calc = calculate_momentum_and_inflection(pd.Series(real_series))
            meta = INDUSTRY_LEADING_MAP.get(category, {
                "name": "通用行业",
                "description": "宏观景气度与综合工业品价格",
                "keywords": ["PMI", "工业增加值", "大宗商品"],
                "proxy_type": "macro_general",
            })
            real_meta = REAL_SOURCE_MAP.get(category, {})
            return {
                "category": category,
                "industry_name": meta["name"],
                "description": real_meta.get("description", meta.get("description", "")),
                "proxy_type": meta["proxy_type"],
                "keywords": meta["keywords"],
                "data_source": "akshare",
                "source_name": real_meta.get("name", ""),
                "series": real_series,
                "momentum_metrics": calc,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

        fallback = self.generate_synthetic_leading_signal(category, historical_trend)
        fallback["data_source"] = "synthetic_fallback"
        return fallback
