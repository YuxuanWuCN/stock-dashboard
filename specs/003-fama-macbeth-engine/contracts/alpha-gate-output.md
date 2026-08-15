# 契约: Alpha 门控输出字段（ranking.json / {code}.json 扩展）

**Feature**: 003-fama-macbeth-engine | **Date**: 2026-08-15

## alpha_gate 字段组（每个标的）

```json
{
  "alpha_gate": {
    "verdict": "pass" | "reject",
    "alpha": 0.00042,
    "alpha_p_value": 0.021,
    "information_ratio": 0.48,
    "betas": {"mkt": 1.05, "smb": 0.31, "hml": -0.12, "mom": 0.07},
    "window_end": "2026-08-14",
    "reject_reason": "statistical" | "economical" | "insufficient_data" | null
  }
}
```

## 校验规则（FR-007）

- verdict=reject 时 reject_reason 必填；verdict=pass 时 reject_reason=null
- insufficient_data 时 alpha/alpha_p_value/information_ratio/betas 均为 null（FR-009）
- src/analysis/schema.py 校验器同步扩展；旧字段不变

## 消费方

- build_ranking.py 激进组合候选：只取 verdict=pass
- docs/index.html 前端展示（可选，非本 feature 必需）
- 审计：pass 但未进候选 = 校验失败（SC-003）