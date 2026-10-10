# Agent ↔ 极星 9.5 订单握手协议 v1.0

> 目标：让外部 agent 能"生成订单"，但**只有人类确认后**才会由极星官方 API 真正发单。
> 全链路可审计、可熔断、可回滚。

---

## 一、为什么不用 GUI 自动化点击

| 方案 | 可靠性 | 可审计 | Agent 可读性 | 结论 |
| :--- | :--- | :--- | :--- | :--- |
| **官方内嵌 API + 文件握手** | 高（客户端原生执行） | 每次动作落 JSONL | 纯文本，可直接解析 | ✅ 采用 |
| UIA 界面控件自动化 | 中（弹窗/焦点/DPI 易碎） | 差 | 依赖控件树 | ⚠️ 仅备选 |
| 屏幕截图 + OCR 点击 | 低 | 差 | 当前模型不支持读图，且本机未装 tesseract | ❌ 不做 |

极星 9.5 自带量化沙箱（`Quant\Editor\api\base_api.py`，6479 行），官方提供
`A_SendOrder` / `A_DeleteOrder` / `A_OrderStatus` / `A_OrderFilledLot` 等函数与完整示例
（`Quant\Strategy\系统示例\`）。**它只能在客户端内嵌 Python 3.7 中运行，不能被外部
Python 进程 import**——这是此前"接不进去"的真正原因，不是权限或接口缺失。

---

## 二、两级权限分离

| Stage | 文件 | 能力 | 用途 |
| :--- | :--- | :--- | :--- |
| **Stage-1** | `bridge/CZCE_AccountBridge.py` | **只读**：账户快照 + 诊断 + 心跳 | 验收 G1/G2，证明链路通、数据真 |
| **Stage-2** | `strategies/CZCE_OrderGateway.py` | **可发单**（受 policy 与人工批准双重约束） | 验收 G3/G4 |

Stage-1 的源码中不存在任何下单函数调用；该不变式由
`tests/test_order_protocol.py::TestPrivilegeSeparation` 用 AST 静态校验，
每次跑测试都会重新确认。

---

## 三、文件清单

目录：`D:\第九届郑商所杯_2026\02_极星量化与实盘\ipc\`

| 文件 | 方向 | 说明 |
| :--- | :--- | :--- |
| `policy.json` | 人工维护 | **唯一限额来源**，两侧都只读此文件，禁止硬编码 |
| `account_snapshot.json` | 策略 → agent | 账户快照（G2 验收对象） |
| `heartbeat.json` | 策略 → agent | Stage-1 心跳 + 全部 API 探针结果 |
| `bridge_diagnostics.json` | 策略 → agent | `initialize` 阶段的诊断矩阵（G1 验收对象） |
| `order_request.json` | agent → 策略 | 待确认的订单意向 |
| `order_approval.json` | agent → 策略 | 人类批准凭证（绑定意向字节哈希） |
| `cancel_request.json` | agent → 策略 | 撤单指令 |
| `reconciliation.json` | 策略 → agent | 发单结果 + 委托状态回查（G3/G4） |
| `gateway_heartbeat.json` | 策略 → agent | Stage-2 心跳 + 开关状态 |
| `execution_log.jsonl` | 策略 → agent | 追加式审计流水 |
| `kill_switch.flag` | 人工 → 策略 | 存在即 `StopTrade()` 并拒绝一切发单 |
| `consumed/` | 策略维护 | 已处理意向归档，**防重放** |

---

## 四、时序

```
  agent                        ipc/                       极星内嵌策略
    │                            │                              │
    ├─ propose ─────────────────►│ order_request.json           │
    │                            │◄───── 校验限额/时效/白名单 ───┤
    │   （人类在对话中确认）        │                              │
    ├─ approve --by 张三 ───────►│ order_approval.json          │
    │                            │◄───── sha256 字节比对 ────────┤
    │                            │◄───── A_SendOrder ────────────┤
    │                            │      execution_log.jsonl      │
    │◄──── status ───────────────│ reconciliation.json           │
    │                            │◄───── A_OrderStatus 轮询 ─────┤
    │◄───────────────────────────│ consumed/(防重放归档)          │
```

---

## 五、安全约束（全部来自 `policy.json`）

| 约束 | 值 | 作用 |
| :--- | :--- | :--- |
| `allow_trading` | `false` | 出厂禁止交易；运行时可翻转，翻 false 立即 `StopTrade()` |
| `max_lots_per_order` | `1` | 单笔手数上限 |
| `max_orders_per_day` | `3` | 当日委托笔数上限 |
| `max_open_orders` | `1` | 同时在途委托上限 |
| `max_request_age_sec` | `120` | 意向与批准的双重时效 |
| `allowed_symbols` | `["ZCE|Z|SA|MAIN"]` | 合约白名单 |
| `allowed_price_types` | `["LIMIT"]` | **禁止市价单** |
| `min_available_for_entry` | `100000.0` | 开仓前最低可用资金 |
| `require_margin_rate_below_pct` | `60.0` | 保证金率上限 |

另有代码级硬保护：
- 价格必须 > 0 且相对最新价偏离 ≤ 10%（防脏 tick 报出离谱价）；
- 账户未绑定（`A_AccountID` 为空）直接拒发；
- 发单成功后 `request` 与 `approval` 立刻移入 `consumed/`，单凭证不可复用。

---

## 六、常用命令

```powershell
cd D:\第九届郑商所杯_2026

python -m src.trading.agent_gateway g1                  # G1 策略是否被加载
python -m src.trading.agent_gateway g2                  # G2 账户快照是否可信
python -m src.trading.agent_gateway policy-set true     # 打开交易开关（需谨慎）
python -m src.trading.agent_gateway propose --direction SELL --offset ENTRY --reason "G3 通路验证"
python -m src.trading.agent_gateway approve --by 你的名字 # 人工确认后才执行
python -m src.trading.agent_gateway status              # G3/G4 核对
python -m src.trading.agent_gateway cancel --order-id 1-1
python -m src.trading.agent_gateway kill                # 熔断
python -m src.trading.agent_gateway unkill
```

---

## 七、四级验收门槛

| 门槛 | 内容 | 通过条件 |
| :--- | :--- | :--- |
| **G1** | 策略被加载 | `bridge_diagnostics.json` 存在；定时触发 OK；账户已关联；心跳 < 30s |
| **G2** | 账户数据可信 | 探针成功率 ≥ 80%；权益/可用/保证金非空；**并人工与客户端界面逐项比对一致** |
| **G3** | 发单通路 | `A_SendOrder` 返回 `retCode=0`；客户端【委托】列表可见该单 |
| **G4** | 核对闭环 | `A_OrderStatus` / `A_OrderFilledLot` 与 `reconciliation.json` 一致；撤单成功 |

**G2 未通过不得进入 G3。** 在不知道账户真实状态的情况下发单，等于盲飞。
