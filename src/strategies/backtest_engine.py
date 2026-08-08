"""v2.5 策略回测引擎 —— 移植自 KHunter trading/backtest_engine.py，去除数据库依赖。

设计：
- 纯 pandas/JSON，无 SQLite/tushare 依赖
- 数据来自现有 fetch_5y_data（自选股 + 扩展池）
- T+1 交易、手续费（佣金/印花税/过户费）、止盈止损、移动止损、亏损冷却
- 输出绩效指标：总收益/最大回撤/夏普/索提诺/胜率/盈亏比/平均持有天数
"""

import logging
from datetime import date, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ------------------------------------------------------------
# 交易成本（A 股规则）
# ------------------------------------------------------------

def calculate_backtest_cost(stock_code: str, price: float, quantity: int, is_buy: bool) -> dict:
    """计算交易成本：佣金 0.015%（最低 5 元）、印花税 0.1%（仅卖出）、过户费 0.001%（沪市）。"""
    commission_rate = 0.00015
    min_commission = 5.0
    stamp_tax_rate = 0.001
    transfer_fee_rate = 0.00001

    is_shanghai = stock_code.startswith("6")
    amount = price * quantity

    commission = max(amount * commission_rate, min_commission)
    transfer_fee = amount * transfer_fee_rate if is_shanghai else 0.0
    stamp_tax = amount * stamp_tax_rate if not is_buy else 0.0

    return {
        "commission": round(commission, 2),
        "transfer_fee": round(transfer_fee, 2),
        "stamp_tax": round(stamp_tax, 2),
        "is_shanghai": is_shanghai,
    }


class BacktestEngine:
    """事件驱动回测引擎。"""

    def __init__(self, stock_data: Dict[str, pd.DataFrame],
                 stock_names: Optional[Dict[str, str]] = None,
                 initial_capital: float = 300000.0):
        """
        Args:
            stock_data: {code: 升序 DataFrame(date/open/high/low/close/volume)}
            stock_names: {code: name}
            initial_capital: 初始资金
        """
        self.stock_data = stock_data
        self.stock_names = stock_names or {}
        self.initial_capital = initial_capital

        # 交易日历：所有股票日期的并集（升序）
        all_dates = set()
        for df in stock_data.values():
            all_dates.update(str(d)[:10] for d in df["date"])
        self.trading_dates = sorted(all_dates)

    # ------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------

    def run(self, strategy_name: str, config: dict) -> dict:
        """运行回测。

        config 支持：
            start_date / end_date: YYYY-MM-DD
            take_profit_pct: 止盈（默认 21%）
            stop_loss_pct: 止损（默认 -7%）
            trailing_stop_pct: 移动止损（默认 8%，即最高价回落 8% 卖出）
            max_hold_days: 最大持有天数（默认 20）
            min_score: 买入最低分（默认 60，本引擎用策略命中代替）
            max_positions: 最大同时持仓数（默认 10）
        """
        start_date = config.get("start_date", self.trading_dates[0] if self.trading_dates else None)
        end_date = config.get("end_date", self.trading_dates[-1] if self.trading_dates else None)
        if not start_date or not end_date:
            return {"error": "回测日期范围为空"}

        dates = [d for d in self.trading_dates if start_date <= d <= end_date]
        if not dates:
            return {"error": f"回测期间 {start_date}~{end_date} 没有交易日"}

        take_profit_pct = config.get("take_profit_pct", 21.0)
        stop_loss_pct = config.get("stop_loss_pct", -7.0)
        trailing_stop_pct = config.get("trailing_stop_pct", 8.0)
        max_hold_days = config.get("max_hold_days", 20)
        max_positions = config.get("max_positions", 10)

        cash = self.initial_capital
        positions: List[dict] = []      # 持仓
        trades: List[dict] = []         # 已平仓交易
        capital_history: List[float] = [self.initial_capital]
        equity_history: List[float] = [self.initial_capital]
        stock_buy_count: Dict[str, int] = {}
        cool_down_pool: Dict[str, str] = {}   # {code: 冷却结束日期}
        consecutive_loss: Dict[str, int] = {}

        from src.strategies.strategy_registry import get_registry
        registry = get_registry()
        registry.auto_register_from_directory()
        strategy = registry.get_strategy(strategy_name)
        if strategy is None:
            return {"error": f"策略 {strategy_name} 未注册"}

        # 预计算：每只股票按日索引（date -> 行号）
        stock_rows = {}
        for code, df in self.stock_data.items():
            # date 列转字符串后作为索引；reset_index 时删除原 date 列避免重复
            df_copy = df.copy()
            df_copy["date"] = pd.to_datetime(df_copy["date"]).dt.strftime("%Y-%m-%d")
            df_copy = df_copy.drop_duplicates(subset=["date"]).set_index("date", drop=True)
            stock_rows[code] = df_copy

        # 历史窗口（信号需要 lookback 数据，从 start_date 前推 60 个交易日）
        warmup_days = 60

        for i, current_date in enumerate(dates):
            # ---------- 1. 卖出（先卖后买，T+1 当日买入不可卖） ----------
            positions, closed = self._process_sell(
                positions, current_date, stock_rows,
                take_profit_pct, stop_loss_pct, trailing_stop_pct,
                max_hold_days,
            )
            trades.extend(closed)
            for t in closed:
                code = t["code"]
                if t["pnl"] < 0:
                    consecutive_loss[code] = consecutive_loss.get(code, 0) + 1
                    if consecutive_loss[code] >= 2:
                        cool_down_pool[code] = self._add_days(current_date, 30)
                    elif abs(t["pnl"]) / t["cost"] >= 0.08:
                        cool_down_pool[code] = self._add_days(current_date, 20)
                    cash += t["net_proceeds"]
                else:
                    consecutive_loss[code] = 0
                    cash += t["net_proceeds"]

            # ---------- 2. 买入 ----------
            if len(positions) < max_positions:
                candidates = self._select_candidates(strategy, stock_rows, current_date)
                for cand in candidates:
                    if len(positions) >= max_positions:
                        break
                    code = cand["code"]
                    if code in cool_down_pool and cool_down_pool[code] >= current_date:
                        continue
                    if stock_buy_count.get(code, 0) >= config.get("max_buy_count_per_stock", 6):
                        continue
                    if any(p["code"] == code for p in positions):
                        continue
                    row = stock_rows[code].loc[current_date]
                    price = float(row["close"])
                    quantity = int(cash * 0.2 // (price * 100)) * 100  # 每笔 20% 资金，整手
                    if quantity <= 0:
                        continue
                    cost_info = calculate_backtest_cost(code, price, quantity, is_buy=True)
                    total_cost = price * quantity + cost_info["commission"] + cost_info["transfer_fee"]
                    if total_cost > cash:
                        continue
                    cash -= total_cost
                    positions.append({
                        "code": code,
                        "name": cand.get("name", ""),
                        "buy_date": current_date,
                        "buy_price": price,
                        "quantity": quantity,
                        "cost": total_cost,
                        "strategy": strategy_name,
                        "highest_price": price,
                        "signals": cand.get("signals", []),
                    })
                    stock_buy_count[code] = stock_buy_count.get(code, 0) + 1

            # ---------- 3. 市值结算 ----------
            positions_value = 0.0
            for p in positions:
                row = stock_rows.get(p["code"])
                if row is not None and current_date in row.index:
                    px = float(row.loc[current_date, "close"])
                    p["current_price"] = px
                    p["highest_price"] = max(p["highest_price"], px)
                    positions_value += px * p["quantity"]
            equity = cash + positions_value
            capital_history.append(equity)
            equity_history.append(equity)

        # 期末：未平仓持仓按最后价格平仓（只计市值，不计入 trades 绩效的已实现部分）
        final_equity = equity_history[-1]
        performance = self._calculate_performance(trades, capital_history, final_equity, dates)

        return {
            "strategy": strategy_name,
            "config": config,
            "period": {"start": start_date, "end": end_date, "trading_days": len(dates)},
            "performance": performance,
            "trades": trades,
            "positions_open": positions,
            "capital_history": capital_history,
        }

    # ------------------------------------------------------------
    # 选股
    # ------------------------------------------------------------

    def _select_candidates(self, strategy, stock_rows: dict, current_date: str) -> List[dict]:
        """在当前日期用策略选股（只用 current_date 之前的数据，防未来函数）。"""
        candidates = []
        for code, df_idx in stock_rows.items():
            if current_date not in df_idx.index:
                continue
            loc = df_idx.index.get_loc(current_date)
            if loc < 20:
                continue
            history = df_idx.iloc[: loc + 1].reset_index()
            if "date" not in history.columns:
                history = history.rename(columns={history.columns[0]: "date"})
            name = self.stock_names.get(code, "")
            signals = strategy.execute_selection(history, code, name)
            if signals:
                candidates.append({"code": code, "name": name, "signals": signals})
        return candidates

    # ------------------------------------------------------------
    # 卖出
    # ------------------------------------------------------------

    def _process_sell(self, positions: List[dict], current_date: str, stock_rows: dict,
                      take_profit_pct: float, stop_loss_pct: float,
                      trailing_stop_pct: float, max_hold_days: int):
        """处理卖出：止盈/止损/移动止损/持有到期。返回 (剩余持仓, 已平仓交易)。"""
        remaining = []
        closed = []
        for p in positions:
            code = p["code"]
            row = stock_rows.get(code)
            if row is None or current_date not in row.index:
                remaining.append(p)
                continue
            px = float(row.loc[current_date, "close"])
            buy_date = p["buy_date"]
            hold_days = self._days_between(buy_date, current_date)
            pnl_pct = (px - p["buy_price"]) / p["buy_price"] * 100.0

            sell_reason = None
            if pnl_pct >= take_profit_pct:
                sell_reason = "take_profit"
            elif pnl_pct <= stop_loss_pct:
                sell_reason = "stop_loss"
            elif hold_days >= 1 and p["highest_price"] > p["buy_price"] * 1.01:
                drawdown = (p["highest_price"] - px) / p["highest_price"] * 100.0
                if drawdown >= trailing_stop_pct:
                    sell_reason = "trailing_stop"
            elif hold_days >= max_hold_days:
                sell_reason = "position_expire"

            if sell_reason is None:
                remaining.append(p)
                continue

            quantity = p["quantity"]
            cost_info = calculate_backtest_cost(code, px, quantity, is_buy=False)
            proceeds = px * quantity
            net_proceeds = proceeds - cost_info["commission"] - cost_info["transfer_fee"] - cost_info["stamp_tax"]
            pnl = net_proceeds - p["cost"]
            closed.append({
                "code": code,
                "name": p.get("name", ""),
                "buy_date": buy_date,
                "sell_date": current_date,
                "buy_price": p["buy_price"],
                "sell_price": px,
                "quantity": quantity,
                "cost": p["cost"],
                "net_proceeds": net_proceeds,
                "pnl": pnl,
                "pnl_pct": (pnl / p["cost"]) * 100.0,
                "hold_days": hold_days,
                "reason": sell_reason,
            })
        return remaining, closed

    # ------------------------------------------------------------
    # 绩效
    # ------------------------------------------------------------

    def _calculate_performance(self, trades: List[dict], capital_history: List[float],
                               final_equity: float, dates: List[str]) -> dict:
        """计算绩效指标。"""
        total_return = (final_equity / self.initial_capital - 1) * 100.0

        # 最大回撤
        peak = self.initial_capital
        max_drawdown = 0.0
        for eq in capital_history:
            peak = max(peak, eq)
            dd = (eq - peak) / peak * 100.0
            max_drawdown = min(max_drawdown, dd)

        # 日收益序列 → 夏普/索提诺
        eq_series = pd.Series(capital_history)
        daily_ret = eq_series.pct_change().dropna()
        if len(daily_ret) > 1:
            std = daily_ret.std()
            sharpe = (daily_ret.mean() - 0.02 / 252) / std * np.sqrt(252) if std > 0 else 0.0
            downside = daily_ret[daily_ret < 0].std()
            sortino = (daily_ret.mean() - 0.02 / 252) / downside * np.sqrt(252) if downside and downside > 0 else 0.0
        else:
            sharpe = sortino = 0.0

        # 交易统计
        n_trades = len(trades)
        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]
        win_rate = len(wins) / n_trades * 100.0 if n_trades else 0.0
        gross_profit = sum(t["pnl"] for t in wins)
        gross_loss = abs(sum(t["pnl"] for t in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
        avg_win = gross_profit / len(wins) if wins else 0.0
        avg_loss = gross_loss / len(losses) if losses else 0.0
        payoff_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0
        avg_hold = np.mean([t["hold_days"] for t in trades]) if trades else 0.0

        return {
            "initial_capital": self.initial_capital,
            "final_equity": round(final_equity, 2),
            "total_return_pct": round(total_return, 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "sharpe": round(sharpe, 2),
            "sortino": round(sortino, 2),
            "trades": n_trades,
            "win_rate_pct": round(win_rate, 1),
            "profit_factor": round(profit_factor, 2),
            "payoff_ratio": round(payoff_ratio, 2),
            "avg_hold_days": round(avg_hold, 1),
        }

    # ------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------

    @staticmethod
    def _days_between(d1: str, d2: str) -> int:
        return (date.fromisoformat(d2) - date.fromisoformat(d1)).days

    @staticmethod
    def _add_days(d: str, days: int) -> str:
        return (date.fromisoformat(d) + timedelta(days=days)).isoformat()
