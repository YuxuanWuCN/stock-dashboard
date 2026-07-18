# 🏠 家庭股票自动看板

> **一句话说明**：每个交易日晚上自动抓取自选股票/基金数据，生成含 K 线、成交量、均线和涨跌摘要的可视化网页，自动发布到公网固定网址，父母手机随时可看。

---

## 目录

- [快速开始（从零配置，图文级教程）](#快速开始从零配置图文级教程)
- [本地运行测试](#本地运行测试)
- [如何修改自选股列表](#如何修改自选股列表)
- [故障排查](#故障排查)
- [常见问题 FAQ](#常见问题-faq)

---

## 快速开始（从零配置，图文级教程）

本教程面向不熟悉编程的维护者（子女），每一步都有说明。全过程只需做一次，此后全自动运行。

### 第 1 步：注册 GitHub 账号

访问 [github.com](https://github.com) → 点击右上角 **Sign up** → 按提示注册一个免费账号。

> 💡 建议用常用邮箱注册，后续失败提醒会发到这个邮箱。

### 第 2 步：创建仓库

1. 登录 GitHub，点击右上角头像旁的 **+** → **New repository**。
2. Repository name 填 `stock-dashboard`（建议这个名字，与脚本配套）。
3. 选择 **Public**（公开仓库可免费使用 GitHub Pages；若选 Private，需要在 Settings → Pages 里确认权限）。
4. **不要**勾选 "Add a README file"（我们会上传自己的）。
5. 点击 **Create repository**。

### 第 3 步：上传项目文件

**方法 A（推荐，不需要装 git）——网页上传：**

1. 在新建的仓库页面，点击 **uploading an existing file** 链接。
2. 将本项目所有文件/文件夹拖拽到上传区域。
3. 在下方 Commit message 里写 `初始化项目`，点 **Commit changes**。

**方法 B——用 git 命令：**

```bash
git clone https://github.com/<你的用户名>/stock-dashboard.git
cd stock-dashboard

# 把本项目所有文件复制到这个目录，然后：
git add .
git commit -m "初始化项目"
git push
```

### 第 4 步：开启 GitHub Pages（获得公网网址）

1. 在仓库页面，点击顶部 **Settings**。
2. 左侧菜单点击 **Pages**。
3. Source 选择 **Deploy from a branch**。
4. Branch 选择 `main`，目录选择 `/docs`，点击 **Save**。
5. 等待 1~2 分钟，页面顶部会出现绿色的提示框，里面写着 **"Your site is live at https://..."**。
6. **把这个网址记下来**，这就是父母看的网址。

> 💡 如果显示不出来，回到 Pages 设置页，确认分支选的是 `main`（不是 `master`）。

### 第 5 步：确认 Actions 权限

1. 在仓库 **Settings → Actions → General**。
2. 往下滚动到 **Workflow permissions**。
3. 选择 **Read and write permissions**。
4. 点击 **Save**。

> 这个权限让自动任务能够把数据提交到仓库，从而更新网站内容。

### 第 6 步：确认邮件通知已开启

1. 点击 GitHub 右上角头像 → **Settings**。
2. 左侧菜单点击 **Notifications**。
3. 往下滚动到 **System** 区域，找到 **Actions**。
4. 确认 **"Failed workflows"** 的邮件通知开关是打开的。

> 这样如果某天数据抓取完全失败，GitHub 会自动发邮件提醒你来看一眼。

### 第 7 步：手动测试一次

1. 在仓库页面，点击顶部 **Actions** 标签。
2. 左侧点击 **Daily Stock Data Update**。
3. 右侧点击 **Run workflow** 下拉按钮 → 再点绿色的 **Run workflow**。
4. 等待约 2~5 分钟，任务完成后会显示绿色 ✓。
5. 打开第 4 步记下的网址，应该能看到看板页面了。

🎉 **配置完成！** 之后每个交易日下午 6:30 左右，系统会自动更新数据，你什么都不用管。

### 第 8 步：把网址发给父母

把第 4 步得到的网址发给父母，教他们：

- **iPhone（Safari）**：打开网址 → 底部中间分享按钮 → **添加到主屏幕** → 以后像 App 一样点开。
- **Android（Chrome）**：打开网址 → 右上角三个点 → **添加到主屏幕** → 以后像 App 一样点开。
- 也可以直接存成浏览器书签。

---

## 本地运行测试

如果想在本地电脑上测试数据抓取脚本是否正常：

### 环境要求

- Python 3.11 或更高版本
- 能访问互联网（akshare 需要联网抓数据）

### 安装步骤

```bash
# 1. 进入项目目录
cd stock-dashboard

# 2. 安装依赖（推荐先创建虚拟环境）
python -m venv venv
# Windows: venv\Scripts\activate
# Mac/Linux: source venv/bin/activate

pip install -r requirements.txt

# 3. 运行脚本
python src/fetch_data.py
```

### 运行成功标志

- 控制台输出日志，显示每只标的的抓取结果（✓/✗）。
- `docs/data/kline/` 下出现各只标的的 `.json` 文件。
- `docs/data/summary.json` 和 `docs/data/meta.json` 已生成。

---

## 如何修改自选股列表

自选股列表存储在 `watchlist.csv` 文件中，用 Excel 或记事本都能编辑。

### 用网页修改（最简单）

1. 在 GitHub 仓库页面，点击 `watchlist.csv` 文件。
2. 点击右上角的 **✏️ 编辑**（铅笔图标）。
3. 按格式增删行，改完后点 **Commit changes**。
4. 修改会在下一个交易日自动生效（手动运行一次 Actions 可立即生效）。

### 文件格式

```
code,name,type
600519,贵州茅台,stock
000001,平安银行,stock
510300,沪深300ETF,etf
```

> **规则**：
> - 第一行表头不能改。
> - `code` = 6 位数字代码（上交所 6 开头，深交所 0/3 开头，ETF 5/1 开头）。
> - `name` = 显示名称，自己起，中文即可。
> - `type` = `stock`（股票）或 `etf`（场内基金/ETF）。
> - 以 `#` 开头的行会被忽略（可用于写注释）。
> - 空行自动跳过。

---

## 故障排查

| 现象 | 可能原因 | 解决办法 |
|---|---|---|
| Actions 任务一直转圈不结束 | GitHub 排队中 | 等 10~15 分钟再刷新 |
| Actions 显示红色 ✗ | 所有标的抓取都失败了 | 检查是否收到邮件，尝试手动重新运行；若持续失败检查网络/接口 |
| 网页显示"暂无数据" | 数据文件未生成或路径错误 | 确认 Actions 最近一次是绿的，确认 `docs/data/` 下有 JSON 文件 |
| 手机打开网页字太小 | 浏览器缩放 | 双指放大，或竖屏查看自适应布局 |
| 某只股票显示灰色/stale | 该只上次抓取失败用了旧数据 | 一般下次会自动恢复；持续失败的检查代码是否变更 |
| 节假日/周末 Actions 运行了 | 正常，脚本会自动识别 | 节假日无新数据不会报错，保留上次数据 |
| 邮件设置在哪 | GitHub 通知设置 | 右上角头像 → Settings → Notifications → Actions 区域 |

---

## 常见问题 FAQ

**Q：需要花钱吗？**
A：完全免费。GitHub Actions 每月有 2000 分钟免费额度，本项目每天只跑几分钟。GitHub Pages 免费托管公开仓库。

**Q：能不能加港股/美股？**
A：当前版本只支持 A 股和场内基金。港股/美股是计划中的扩展项。

**Q：如果某天数据抓取失败了怎么办？**
A：网页会继续显示上一次成功的数据，不会空白。同时你会收到 GitHub 的邮件通知，提醒你去排查。

**Q：GitHub 被墙了怎么办？**
A：GitHub 在国内有间歇性访问问题。如果父母打不开，可以考虑用 Cloudflare Pages 等国内访问更快的替代方案（需要额外配置，本期不做）。

**Q：能加 MACD/KDJ 等指标吗？**
A：按需求方要求，本期只做 K 线 + 均线 + 成交量，复杂指标放在未来迭代。

---

## 项目结构

```
stock-dashboard/
├── .github/workflows/daily.yml    GitHub Actions 定时任务
├── src/
│   ├── fetch_data.py              主脚本：抓取+计算+产出
│   ├── config.py                  配置区
│   └── utils.py                   工具函数
├── watchlist.csv                  自选股列表（可自行编辑）
├── docs/                          GitHub Pages 发布目录
│   ├── index.html                 看板主页面
│   ├── assets/
│   │   ├── app.js
│   │   └── style.css
│   └── data/                      程序自动生成，勿手动修改
│       ├── summary.json
│       ├── meta.json
│       └── kline/*.json
└── requirements.txt
```

---

## 致维护者

这个项目的设计理念是 **"配置一次，长期自动运行"**。你不需要每天登录检查，只有在收到失败邮件时才需要看一下。父母需要做的就是打开手机浏览器点一下链接 —— 和打开任何一个 App 一样简单。

如果遇到问题，首先看 [故障排查](#故障排查)；如果解决不了，可以打开 GitHub Actions 页面查看最后一次运行的日志（点击红色 ✗ → 点击 `fetch-and-publish` → 展开 `运行数据抓取脚本` 看日志输出）。
