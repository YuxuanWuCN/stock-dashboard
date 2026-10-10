# src/multi_asset_api.py
"""
Rainbow-FinGPT v4.0 全域多资产 API 蓝图
Unified API Blueprint matching contracts/multi-asset-api.json.
"""

from flask import Blueprint, jsonify, request
import os
import json
from pathlib import Path
from datetime import date

bp_v4 = Blueprint("multi_asset_api_v4", __name__, url_prefix="/api/v4")

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DATA = REPO_ROOT / "docs" / "data"


@bp_v4.route("/overview", methods=["GET"])
def get_overview():
    """获取多资产宏观总览 (权益、大宗、财富三轨)"""
    as_of = str(date.today())
    temp = 68.5
    
    # 尝试从离线快照加载实际市场温度
    temp_file = DOCS_DATA / "strategy" / "market_temperature.json"
    if temp_file.exists():
        try:
            with open(temp_file, "r", encoding="utf-8") as f:
                d = json.load(f)
                temp = float(d.get("temperature", temp))
                as_of = str(d.get("date", as_of))
        except Exception:
            pass
            
    return jsonify({
        "as_of_date": as_of,
        "market_temperature": temp,
        "active_domains": ["EQUITY", "COMMODITY", "WEALTH"],
        "equity_summary": {
            "universe_size": 202,
            "top_pick": "688041"
        },
        "commodity_summary": {
            "dominant_contract": "SA701",
            "hedging_mode": "COLLAR_DYNAMIC"
        }
    })


@bp_v4.route("/equity/ranking", methods=["GET"])
def get_equity_ranking():
    """获取 202 只 A 股核心池打分与 Fama-MacBeth 回归估值"""
    ranking_file = DOCS_DATA / "strategy" / "selection.json"
    stocks = []
    if ranking_file.exists():
        try:
            with open(ranking_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                items = data if isinstance(data, list) else data.get("stocks", [])
                for item in items[:25]:
                    stocks.append({
                        "code": str(item.get("code", "")),
                        "name": str(item.get("name", "")),
                        "score": float(item.get("score", 0.0)),
                        "beta_mkt": float(item.get("beta_mkt", 1.05)),
                        "p_value": float(item.get("p_value", 0.015)),
                        "sector": str(item.get("sector", "存储芯片"))
                    })
        except Exception:
            pass
            
    if not stocks:
        stocks = [
            {"code": "688041", "name": "海光信息", "score": 88.5, "beta_mkt": 1.15, "p_value": 0.012, "sector": "算力芯片"},
            {"code": "688008", "name": "澜起科技", "score": 86.2, "beta_mkt": 0.98, "p_value": 0.008, "sector": "内存接口芯片"},
            {"code": "001309", "name": "德明利", "score": 84.0, "beta_mkt": 1.25, "p_value": 0.021, "sector": "存储模组/主控"}
        ]
        
    return jsonify({
        "count": len(stocks),
        "stocks": stocks
    })


@bp_v4.route("/commodity/tes", methods=["GET"])
def get_commodity_tes():
    """获取郑商所纯碱/玻璃跨资产期望盈余 (TES) 排序与极星领子动作"""
    ranking_file = REPO_ROOT / "competitions" / "czce_futures" / "02_极星量化与实盘" / "logs" / "ranking_cross_asset.json"
    items = []
    as_of = str(date.today())
    
    if ranking_file.exists():
        try:
            with open(ranking_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                as_of = str(data.get("updated_at") or data.get("as_of_date", as_of))
                raw_items = data.get("items") or data.get("ranking", [])
                for it in raw_items:
                    items.append({
                        "symbol": str(it.get("symbol", "")),
                        "name": str(it.get("name", "")),
                        "node_id": str(it.get("node_id", "")),
                        "expected_surplus": float(it.get("tomorrow_expected_surplus_pct", 0.0)),
                        "veto_passed": bool(it.get("statistical_gate_pass", True)),
                        "action": str(it.get("collar_hedge_action", "BUY_PUT_COLLAR"))
                    })
        except Exception:
            pass
            
    if not items:
        items = [
            {"symbol": "SA701", "name": "纯碱2701", "node_id": "NODE_02_SODA_SYN", "expected_surplus": -4.2, "veto_passed": True, "action": "SHORT_HEDGE_COLLAR"},
            {"symbol": "000683", "name": "远兴能源", "node_id": "NODE_01_TRONA", "expected_surplus": 6.8, "veto_passed": True, "action": "LONG_EQUITY_EXPOSURE"},
            {"symbol": "FG701", "name": "玻璃2701", "node_id": "NODE_04_FLOAT_GLASS", "expected_surplus": -2.1, "veto_passed": True, "action": "DYNAMIC_HEDGE"}
        ]
        
    return jsonify({
        "as_of_date": as_of,
        "items": items
    })


@bp_v4.route("/intelligence/chokepoint", methods=["GET"])
def get_chokepoint_graph():
    """获取供应链卡脖子瓶颈拓扑图谱与节点质量得分"""
    nodes = [
        {"id": "NODE_01_TRONA", "label": "天然碱矿采选 (远兴能源)", "chokepoint_score": 88.5},
        {"id": "NODE_02_SODA_SYN", "label": "中游纯碱合成 (中盐/海化)", "chokepoint_score": 62.0},
        {"id": "NODE_04_FLOAT_GLASS", "label": "浮法与光伏玻璃 (旗滨/金晶)", "chokepoint_score": 75.0},
        {"id": "NODE_07_END_MODULE", "label": "终端光伏组件与需求 (隆基绿能)", "chokepoint_score": 58.0}
    ]
    edges = [
        {"source": "NODE_01_TRONA", "target": "NODE_02_SODA_SYN", "k_ratio": 1.0},
        {"source": "NODE_02_SODA_SYN", "target": "NODE_04_FLOAT_GLASS", "k_ratio": 0.20},
        {"source": "NODE_04_FLOAT_GLASS", "target": "NODE_07_END_MODULE", "k_ratio": 0.45}
    ]
    return jsonify({
        "nodes": nodes,
        "edges": edges
    })
