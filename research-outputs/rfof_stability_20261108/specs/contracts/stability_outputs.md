# 契约:模块接口与输出表

本特性无 HTTP 接口,契约为 Python 函数签名和输出文件列。

## 模块接口

```python
# stability_universe.py
def load_close(path: Path) -> pd.Series: ...
def detect_jumps(close: pd.Series, limit: float) -> pd.Series: ...   # 返回异常日收益
def load_universe(codes: list[str]) -> pd.DataFrame: ...             # 含异常日则 ValueError

# stability_methods.py  (均只使用 returns.iloc[:t] 即 t-1 日及以前信息)
def weights_a0(returns: pd.DataFrame) -> pd.Series: ...
def weights_lw_minvar(returns: pd.DataFrame, cap: float = 0.40) -> pd.Series: ...
def weights_hrp(returns: pd.DataFrame) -> pd.Series: ...
def vol_target_scale(port_ret: pd.Series, target: float = 0.08, window: int = 60) -> float: ...

# stability_walkforward.py
def run_walkforward(returns, method, train_days=756, cost_bps=15) -> pd.DataFrame: ...
def window_metrics(daily_ret: pd.Series, windows: dict) -> pd.DataFrame: ...

# stability_futures.py
def futures_variant(prices, roll_cost_bps, rolls_per_year, margin_pct, ma_window, holiday_mode) -> pd.Series: ...

# stability_verdict.py
def judge(results: pd.DataFrame, baseline: str = "A0") -> pd.DataFrame: ...
```

## 输出文件(写入 `reports/stability_YYYYMMDD/`)

| 文件 | 列 |
|---|---|
| `tables/etf_data_audit.csv` | 见 data-model.md AuditRecord |
| `tables/defense_method_results.csv` | `method,param_id,window,max_dd_pct,ann_vol_pct,ann_ret_pct,turnover,cost_drag_pct` |
| `tables/futures_sensitivity.csv` | `variant,roll_cost_bps,rolls_per_year,margin_pct,ma_window,holiday_mode,ann_ret_pct,ann_vol_pct,max_dd_pct` |
| `tables/verdict.csv` | 见 data-model.md Verdict |
| `figures/*.png` | 至少 200 dpi,坐标轴带标签与单位,中文字体正常显示 |
| `结果报告.md` | 结论、证据、局限、可操作建议;标注"回测/价格收益,不含分红" |

## 契约不变量
- 输出目录已存在时必须报错,不得覆盖。
- 所有表的日期列为 ISO 格式,百分比列以 `_pct` 结尾。
- 判定表中 `label=improved` 的行必须能由同目录的结果表复算得到。
