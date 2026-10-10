# 极星 9.5.19.5（郑商杯 v19.5）加载量化策略的正确路径

> **权威来源**：本文内容直接取自客户端自带的界面资源文件
> `config\LanguageApi\LanguageApi.MainFrame.pub` 与 `LanguageApi.QuantFrame.pub`，
> 不是猜测，也不是抄来的二手文档。
>
> **重要更正**：`EPOLESTAR_LIVE_MANUAL.md` 里写的
> "【量化】→【量化策略】→【策略管理】" **在 v19.5 里并不存在**，
> 该文档的这一步是错的，需要重写。

---

## 一、客户端真实的菜单项（逐条来自资源文件）

### 1.1 顶栏一级菜单（MainFrame.pub）

| ID | 中文 | 英文 |
| :--- | :--- | :--- |
| 160 | 行情 | Quote |
| 161 | 交易 | Trade |
| 162 | 系统选项 | Config |
| 163 | 帮助 | Help |
| 164 | 布局 | Layout |
| **165** | **量化** | **Quant** |
| 180 | 主题 | Theme |

### 1.2 可插入的模块（MainFrame.pub）

| ID | 中文 | 英文 |
| :--- | :--- | :--- |
| 100 | **插入模块** | Insert module |
| 101 | **右键插入模块，双击返回功能页** | Layout、DbClick escape |
| 145 | 行情分析 | Quote |
| 146 | 本地套利 | Spread |
| 147 | 快速下单 | FastOrder |
| **148** | **量化策略** | **Quant** |
| 149 | 期权策略 | Option |
| 150 / 151 | 程序化2 / 程序化3 | Program2 / Program3 |
| 152 | 数据管理 | DataCenter |

### 1.3 量化模块内部按钮（QuantFrame.pub）

| ID | 中文 | 英文 |
| :--- | :--- | :--- |
| 1 / 2 / 3 / 4 | 策略源码 / 运行日志 / 交易信号 / 组合监控 | Strategy Source / Running Log / Trading Signals / Comb Monitor |
| **28** | **添加策略** | **Add Strategy** |
| **31** | **开始策略** | **Start Strategy** |
| 30 | 停止策略 | Stop Strategy |
| 26 | **属性设置** | Property Settings |
| 27 | 示例策略 | Sample Strategy |
| 29 | 添加分区 | Add Partition |
| **66 / 164** | **关联账户：/ 关联账号** | Asso Acc |
| 67 | 登录其他账户 | Login Other Account |
| **108** | **实盘运行** | **Firm Offer** |
| 52 / 53 | 自动 / 自动间隔： | Auto / Auto Interval |
| 145 / 146 | 删除策略 / 编辑策略 | Remove / Edit Strategy |
| 314 | *优先使用策略代码中的合约 | *Give priority to the contracts in the strategy code |

---

## 二、正确操作步骤

### 步骤 1 · 打开量化模块（两条路任选）

**路径 A（推荐）**：在客户端任意窗口的空白处 **右键** → 选择 **【插入模块】** → 子菜单选 **【量化策略】**

**路径 B**：点击顶栏 **【量化】** 菜单 → 选择量化策略相关项

> 依据：资源文件 ID 101 明确写着"右键插入模块，双击返回功能页"。
> 若布局被弄乱，用 【布局】→【还原默认布局】恢复。

### 步骤 2 · 添加我们的策略

在量化模块里：

1. 点击 **【添加策略】**（Add Strategy）
2. 在弹出的策略树中展开 **用户策略**（策略文件目录：`Quant\Strategy\用户策略\`）
3. 选择 **`CZCE_AccountBridge`**（Stage-1 只读桥接，**今晚先只加载这个**）
4. 在新策略实例上：**关联账户** 选 `19098047316`
5. 在 **【属性设置】** 里 **勾选【实盘运行】** —— 不勾选，`A_` 系列账户函数全部失效
6. 点击 **【开始策略】**（Start Strategy）

### 步骤 3 · 告诉我一声

我立刻执行 `python -m src.trading.agent_gateway g1` 和 `g2`，并把
`bridge_diagnostics.json` / `heartbeat.json` / `account_snapshot.json` 全文读出来给你结论。

---

## 三、已确认的环境事实

| 项目 | 值 |
| :--- | :--- |
| 产品版本 | **郑商杯 v19.5**（`update.ini` 中 `cur=9.5.19.5`，exe 名为 `epolestar v9.5.exe`） |
| 真实运行安装目录 | `C:\Users\ASUS\AppData\Roaming\Epolestar000450v9.5\` |
| 另一份副本（非运行） | `D:\Epolestar000450v9.5\`（两处 `base_api.py` SHA256 相同） |
| 登录账号 | **19098047316**（交易登录状态 0，ReadyCount 1 —— 连接正常） |
| 主窗口类名 | `class SSLForm`（**自绘窗口，原生子窗口数 = 0，UIA 控件数 = 0**） |
| 行情时段 | 夜盘 21:00–23:00 已收，下一交易时段 09:00 |

## 四、为什么不能靠 UI Automation 点击

主窗口 `class SSLForm` 的原生子窗口数为 **0**，Windows UI Automation 枚举到 **0 个控件**，
所以无法用控件自动化。可行的办法只有：**窗口置顶 → 截图 → OCR 得到文字与坐标 → 按坐标点击**。

现在既然已经从资源文件里拿到了**确切的按钮文字**（"插入模块"、"量化策略"、"添加策略"、
"开始策略"、"实盘运行"），OCR 就不需要"猜"了，可以直接做**精确字符串匹配 + 每步截图复核**，
可靠性比之前高得多。这也意味着：**明天开盘前我可以自己把策略加载起来。**
