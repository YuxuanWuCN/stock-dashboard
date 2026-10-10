# 今晚就能做的验证（Stage-1 / G1-G2）

> 状态：**代码已就绪并部署，尚未上机**。本文档是上机操作清单。
> 更新时间：2026-09-28 23:15

---

## 一、已经完成的改动

| 项目 | 状态 |
| :--- | :--- |
| 旧策略 `CZCE_TemporalTrendGate_LiveStrategy.py` | **已退役**，移出客户端策略树（见下方"为什么"） |
| `CZCE_AccountBridge.py` | **已重写**为只读桥接，部署到 `Quant\Strategy\用户策略\` |
| `CZCE_OrderGateway.py` | **新建**订单网关，部署到同一目录 |
| 协议与限额 | `ipc/policy.json`（唯一来源）+ `ipc/PROTOCOL.md`（规范） |
| Agent CLI | `python -m src.trading.agent_gateway` |
| 测试 | 新增 40 项，全量 **142 项通过** |

**旧策略为什么必须退役**：它把 10,000 吨现货敞口换算成 500 手目标空头
（振荡期 125 手、破位期 475 手）。按纯碱 1500 元/吨、20 吨/手、保证金 12% 估算，
125 手就占用约 45 万保证金、475 手约 171 万——比赛模拟账户极可能直接触发追保。
而且它调用 `SellShort(lots_diff, current_price)`，而官方签名是
`SellShort(orderQty, orderPrice, contractNo, userNo, coverFlag, hedge)`，参数不足。
**实盘规模必须按账户权益确定，不能按假设库存确定。**

---

## 二、今晚的上机步骤（约 10 分钟）

### 步骤 1 · 启动并登录
1. 双击桌面 **【郑商杯v9.5】**；
2. 用比赛模拟账号登录（**登录这一步只能你本人做**，我不接触账号密码）。

### 步骤 2 · 加载只读桥接

> ⚠️ **更正**：本文档早先写的"【量化】→【量化策略】→【策略管理】"路径在 v19.5 中不存在。
> 请以 `LOAD_STRATEGY_GUIDE.md` 为准：**右键 → 插入模块 → 量化策略 → 添加策略**。

1. 在客户端任意窗口空白处 **右键** → **【插入模块】** → **【量化策略】**；
2. 在量化模块中点击 **【添加策略】**，展开 **【用户策略】**，应能看到：
   - `CZCE_AccountBridge`
   - `CZCE_OrderGateway`
3. **今晚只加载 `CZCE_AccountBridge`**，先不要加载网关（权限分离：先证明只读链路，再开写权限）；
4. 加载时务必：
   - 勾选 **【实盘运行】**（不勾选，`A_` 系列函数全部不可用，这是唯一硬性开关）；
   - 在关联账户设置中 **选中比赛模拟账户**；
5. 点击 **【运行策略】**。

> 已验证的事实：极星支持 `SetTriggerType(3, 1000)` **定时触发**，收盘后行情不推送
> 也照样每秒触发一次，所以**今晚就能验证，不用等明天开盘**。

### 步骤 3 · 跑 G1 验收

```powershell
cd D:\第九届郑商所杯_2026
python -m src.trading.agent_gateway g1
```

期望输出：`[G1] PASS —— 策略已被客户端加载，定时触发与账户关联均正常。`

### 步骤 4 · 跑 G2 验收

```powershell
python -m src.trading.agent_gateway g2
```

程序会自动检查：快照新鲜度、API 探针成功率、权益/可用/保证金是否可解析。

**然后必须由你人工完成最后一步**：打开极星的【资金】页面，逐项核对
`动态权益 / 可用资金 / 占用保证金` 三个数字是否与输出完全一致。
一致才算 G2 通过，才能进入明天的 G3 发单测试。

---

## 三、把结果发给我

跑完上面两条命令后，把输出贴给我（或者直接说"跑完了"），我会读取：

- `ipc/bridge_diagnostics.json` —— `initialize` 诊断矩阵
- `ipc/heartbeat.json` —— 心跳与全部 API 探针（含每个函数的成功/失败原因）
- `ipc/account_snapshot.json` —— 账户快照

这些都是纯文本，我可以直接读，**不需要截图**。

---

## 四、常见故障对照表

| 现象 | 原因 | 处理 |
| :--- | :--- | :--- |
| `bridge_diagnostics.json` 不存在 | 策略未加载，或加载后未点运行 | 重新加载并点【运行策略】 |
| 权益/可用/保证金全是 0 | **没勾【实盘运行】**，或账户未关联 | 停止策略 → 设置里勾选并关联账户 → 重新运行 |
| `heartbeat.json` 不存在但诊断文件存在 | `handle_data` 从未被触发（定时触发没设成功） | 看诊断文件里 `triggers` 的 `3(timer)` 是否 `ok=false` |
| 部分探针失败 | 收盘后无行情，`Q_Last/Close/BarCount` 可能为空 | 允许，探针成功率 ≥80% 即通过 |
| `A_GetAllPositionSymbol` 失败 | 无持仓或未订阅 | 允许，G2 不因此失败 |

---

## 五、明天的 G3/G4（开盘后，需你逐笔确认）

```powershell
# 1. 加载 CZCE_OrderGateway（同样勾选实盘运行 + 关联账户）
# 2. 打开交易开关（默认关闭，这是唯一一次主动放权）
python -m src.trading.agent_gateway policy-set true

# 3. 生成订单意向 —— 我生成，你确认
python -m src.trading.agent_gateway propose --direction SELL --offset ENTRY --lots 1 --reason "G3 通路验证：单笔1手测试单"

# 4. 你确认后，才签发批准凭证
python -m src.trading.agent_gateway approve --by 你的名字

# 5. 核对发单结果与委托状态
python -m src.trading.agent_gateway status

# 6. 测试完立刻撤单（或平仓）并关闸
python -m src.trading.agent_gateway cancel --order-id <上一步看到的 localOrderId>
python -m src.trading.agent_gateway policy-set false
```

**任何时刻想停，执行 `python -m src.trading.agent_gateway kill`** —— 网关会在
1 秒内 `StopTrade()` 并拒绝一切发单。

---

## 六、尚未解决的两个问题（不阻塞今晚验证）

1. **合规性未确认**：`04_大赛规则与资料\` 目前是**空目录**。程序化下单是否被本届
   规则允许，尚无书面依据。极星官方自带量化下单 API 与示例，通常意味着允许，
   但"通常"不等于"确认"——建议把章程放进该目录，我逐条核对。
2. **旧的夸大表述待清理**：`EPOLESTAR_LIVE_MANUAL.md` 声称部署在
   `%APPDATA%\Epolestar000450v9.5\...`（该路径**不存在**），并使用"毫秒级落盘"
   "全量同步部署"等与实际不符的措辞。这份文档需要在验证完成后统一订正。
