# src/strategies —— v2.5 选股策略引擎（移植自 KHunter，重构为纯 pandas 实现）
#
# 设计要点：
# - 仅依赖 pandas/numpy，复用 src/analysis/indicators.py 的指标计算
# - 策略只作用于 watchlist.csv 与扩展股票池（strategy_pool.csv）
# - 不引入 SQLite，结果落盘为 JSON（与现有看板数据体系一致）
