const fs = require("fs");
const path = require("path");
const { Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell, WidthType, AlignmentType } = require("docx");

const F = (text, opts = {}) => new TextRun({ text, size: 21, font: "Microsoft YaHei", ...opts });
const H = (text, level) => new Paragraph({ heading: level, spacing: { before: 200, after: 100 }, children: [new TextRun({ text, font: "Microsoft YaHei" })] });
const P = (text, opts = {}) => new Paragraph({ spacing: { after: 80 }, alignment: AlignmentType.JUSTIFIED, children: [F(text, opts)] });
const bullet = (text) => new Paragraph({ bullet: { level: 0 }, spacing: { after: 40 }, children: [F(text)] });
const cell = (text, opts = {}) => new TableCell({ width: { size: opts.w || 20, type: WidthType.PERCENTAGE }, children: [new Paragraph({ children: [F(text, { bold: opts.bold, size: 19 })] })] });
const table = (headers, rows, widths) => new Table({
  width: { size: 100, type: WidthType.PERCENTAGE },
  columnWidths: widths,
  rows: [
    new TableRow({ children: headers.map((h) => cell(h, { bold: true })) }),
    ...rows.map((r) => new TableRow({ children: r.map((c, i) => cell(c, { w: widths[i] })) })),
  ],
});

const sections = [];

// ============ 封面 ============
sections.push(new Paragraph({ spacing: { before: 1200, after: 200 }, alignment: AlignmentType.CENTER, children: [new TextRun({ text: "基于多源数据与策略引擎的个人量化研究平台", size: 36, font: "Microsoft YaHei", bold: true })] }));
sections.push(new Paragraph({ spacing: { after: 600 }, alignment: AlignmentType.CENTER, children: [new TextRun({ text: "StockDashboard 项目研究报告", size: 30, font: "Microsoft YaHei", bold: true })] }));
sections.push(new Paragraph({ spacing: { after: 100 }, alignment: AlignmentType.CENTER, children: [F("吴宇轩", { size: 24 })] }));
sections.push(new Paragraph({ spacing: { after: 100 }, alignment: AlignmentType.CENTER, children: [F("华南师范大学 数据科学与人工智能学院", { size: 20 })] }));
sections.push(new Paragraph({ spacing: { after: 400 }, alignment: AlignmentType.CENTER, children: [F("2026 年 8 月", { size: 20 })] }));

// ============ 摘要 ============
sections.push(H("摘要", HeadingLevel.HEADING_1));
sections.push(P("本项目构建了一个覆盖 A 股、港股、美股、韩股及 ETF 的 202 只全球金融标的的个人量化研究平台。系统每日定时完成多市场数据采集（含陈旧数据标记）、规则打分、K 近邻概率预测、基于 FinGPT 方法论的 LLM 研究报告生成，以及三组策略引擎（多金叉共振、涨停回马枪、启明星）的事件驱动回测。所有环节以\"确定性规则算数、LLM 负责叙事、模拟盘检验校准\"为架构原则，且不连接任何证券账户，严守研究红线。"));
sections.push(P("截至 2026-08-13，平台已完成 5 个交易日的模拟盘对决与随机对照检验。其中激进组合在 100 次随机等权抽样中两次进入前 1%（分位数 100%、99%），稳健组合累计跑赢随机基准。报告最后一节记录了近期对立新能源（001258）的一次案例验证，并附上目前尚未想清楚的问题。"));

// ============ 1. 研究背景与动机 ============
sections.push(H("1. 项目缘起与研究动机", HeadingLevel.HEADING_1));
sections.push(P("这个项目的起点，是在您的会计学课上做的那次报告。为了准备那份报告，我第一次系统地去看一家公司的财务数据是怎么和市场表现对应起来的。做完之后有一个感觉一直没散去：课堂上分析一家公司可以查报表、看科目，但如果想同时跟踪几十只、上百只标的，靠人工整理是不现实的。于是我想，能不能把这套分析流程自动化，做成一个每天自己跑的工具。"));
sections.push(P("于是有了这个项目。金融市场信息密集且时效性强，对个人而言，每晚跨市场（中国大陆、香港、美国、韩国及基金）整理研究素材既耗时又易出错。大语言模型（如 BloombergGPT、FinGPT）展示了对新闻情绪提取与研究报告生成的能力，但其输出存在幻觉风险，市场预测本质上也是概率性的——直接让模型回答\"买什么\"既不科学也不可信。"));
sections.push(P("所以系统采用了混合架构：确定性的、可复现的规则负责计算数字，语言模型只负责围绕已有证据做解释与综合。项目想做到的是可复现的数据管道、诚实的评估协议和校准优先的设计，而不是承诺任何短期收益。"));

// ============ 2. 系统架构 ============
sections.push(H("2. 系统架构", HeadingLevel.HEADING_1));
sections.push(P("系统以 Windows 任务计划程序驱动本地 Python 流水线，每日 18:00（CST）运行，美股收盘后 08:00 补跑，全部产物通过版本化 JSON 数据契约输出到 GitHub Pages 静态前端。"));
sections.push(table(
  ["组件", "职责", "关键设计"],
  [
    ["数据采集", "202 标的 x 5 市场直连采集", "多源回退 + 陈旧标记（STALE_DAYS=10）"],
    ["规则打分", "风险/机会/行业评分", "20 日波动率、60 日回撤、ATR 等"],
    ["KNN 预测", "3 日/5 日上涨概率", "5 年日线历史相似匹配"],
    ["LLM 流水线", "研究报告生成（DeepSeek API）", "批式情绪分析 + RAG 引用绑定"],
    ["策略引擎", "3 策略信号 + 事件驱动回测", "T+1 结算、真实费用、止盈止损"],
    ["市场温度", "四因子情绪仪表", "涨跌比/跌停/涨停跟进/换手"],
    ["模拟盘对决", "稳健 vs 激进组合", "预测概率 vs 实现收益对齐"],
  ],
  [15, 40, 45]
));
sections.push(new Paragraph({ spacing: { before: 100 } }));
sections.push(P("策略引擎移植自开源项目 KHunter，并适配为无数据库、无自动交易的纯 pandas 实现；LLM 层复用 FinGPT 的\"数据为中心 NLP + RAG + 市场反馈\"方法论，而非其模型权重。"));

// ============ 3. 实验与结果 ============
sections.push(H("3. 实验与结果", HeadingLevel.HEADING_1));
sections.push(H("3.1 数据覆盖与质量", HeadingLevel.HEADING_2));
sections.push(P("202 只标的全部完成采集与排名。一只港股（恒生银行）因第三方数据源滞后被正确标记为 stale 并降级——\"标记而非伪造\"的机制经受了真实检验。"));
sections.push(H("3.2 模拟盘对决（5 个交易日）", HeadingLevel.HEADING_2));
sections.push(P("稳健组合（约 80% 仓位，黄金 ETF + 大盘防御）与激进组合（全仓 8 只全宇宙扫描高概率标的）自 2026-08-07 起每日对决，并以\"全池等权买入持有\"为基准。"));
sections.push(table(
  ["组合", "5 日累计收益", "随机对照表现（100 次抽样）"],
  [
    ["激进组合", "+2.91%", "2 次进入前 1%（分位 100%、99%）"],
    ["稳健组合", "-0.33%", "跑赢随机基准 3/5 日"],
    ["全池等权基准", "+0.35%（08-13 时点）", "—"],
  ],
  [25, 30, 45]
));
sections.push(new Paragraph({ spacing: { before: 100 } }));
sections.push(P("注：样本仅 5 日，尚不足以支撑统计结论；随机对照的目的在于逐步积累\"预测概率 vs 实现频率\"的校准数据，而非短期收益最大化。"));

// ============ 4. 深度案例：立新能源 ============
sections.push(H("4. 深度案例：立新能源（001258）", HeadingLevel.HEADING_1));
sections.push(P("立新能源在 2026 年 7 月走出 7 连板行情（6.49→15.73），随后两日连续跌停。这是自选池里近期波动最剧烈的一只，因此拿它作为案例，检验系统各模块在极端行情下的表现。"));
sections.push(H("4.1 翻倍事实核验", HeadingLevel.HEADING_2));
sections.push(table(
  ["口径", "起点", "高点", "涨幅"],
  [
    ["连板行情", "07-16 收 7.42", "07-28 盘中 15.73", "+109.2%"],
    ["滚动 60 日低点", "07-13 低 6.49", "07-24 收 13.03", "+100.8%"],
  ],
  [25, 25, 30, 20]
));
sections.push(new Paragraph({ spacing: { before: 100 } }));
sections.push(H("4.2 涨停回调统计（全历史 6 波涨停簇）", HeadingLevel.HEADING_2));
sections.push(P("将连续涨停聚簇后，6 波行情中 5 波在 20 个交易日内发生自高点回落 ≥10% 的回调（发生率 83.3%），回调等待天数中位数为 4 天，回调幅度中位数为 12.05%。"));
sections.push(H("4.3 四因子风险评分预警", HeadingLevel.HEADING_2));
sections.push(P("以规模（市值）、资金（量能）、行业（板块强度）、情绪（波动率+乖离）四因子构建日度风险评分（0-100）。07-28/07-29 连续跌停前 5 日均分 69.7，显著高于全样本均值 24.8（差 44.9 分），显示资金与情绪因子对暴跌具备早期预警能力；规模与行业因子受数据源限制标注为未验证。"));

// ============ 5. 一次案例验证：立新能源 ============
sections.push(H("5. 一次案例验证：顺着您的思路做的回测", HeadingLevel.HEADING_1));
sections.push(P("前几天向您请教立新能源的时候，您提到几点：这只票短期涨了一倍，处在业务成绩兑现期，已经获利的话建议减仓、不宜追高，回调是早晚的事；另外市值才一百多亿，盘子小，资金拉起来容易，下去也容易，规模、资金、行业和情绪都很重要。"));
sections.push(P("这几句话我回去以后试着在项目里做了验证——正好这个系统有回测引擎，可以把判断写成规则跑一遍历史数据。结果如下："));
sections.push(table(
  ["您提到的", "我写成的规则", "回测结果"],
  [
    ["短期涨了一倍", "滚动 60 日低点收盘翻倍触发", "07-24 触发，涨幅 +100.8%"],
    ["获利建议减仓、不宜追高", "触发次日开盘分三组：清仓 / 减至 1/3 / 不动", "清仓组躲过随后 -19% 的连续跌停"],
    ["回调是早晚的事", "涨停后 20 个交易日内自高点回落 ≥10%", "6 波行情中 5 波回调，中位数 4 天"],
    ["市值才一百多亿", "流通市值核验", "项目暂时没有接市值数据源"],
    ["规模、资金、行业、情绪", "四因子日度风险评分", "资金和情绪两项对暴跌有预警，规模和行业缺数据"],
  ],
  [22, 33, 45]
));
sections.push(new Paragraph({ spacing: { before: 100 } }));
sections.push(P("三组对照的具体数字（触发日 07-24，按次日 07-27 开盘价 13.02 处理）："));
sections.push(table(
  ["窗口", "清仓", "减至 1/3", "不动", "不动的最大回撤"],
  [
    ["5 日", "0.0%", "-0.74%", "-2.23%", "-18.98%"],
    ["10 日", "0.0%", "+3.74%", "+11.21%", "-18.98%"],
    ["20 日", "0.0%", "+5.76%", "+17.28%", "-18.98%"],
  ],
  [15, 20, 20, 20, 25]
));
sections.push(new Paragraph({ spacing: { before: 100 } }));
sections.push(P("跑完之后有个问题我没想明白：同样是涨停之后回调，今年 3 月那一波涨了 62% 就开始跌，7 月这一波却先涨了 100% 才回调。同一个形态、两次结果差这么多，是不是和当时的市场环境有关？还是资金性质（游资和机构）或者行业消息的差别？如果以后有机会，想听听您怎么看这个问题。"));

// ============ 6. 局限与展望 ============
sections.push(H("6. 局限与展望", HeadingLevel.HEADING_1));
sections.push(bullet("样本量：全部\"结果\"建立在 5 个交易日上，尚无统计意义上的结论；随机对照的 100 次抽样只是起始。"));
sections.push(bullet("数据依赖：第三方免费接口可能暂停或滞后（如恒生银行案例），stale 标记只能缓解不能根除。"));
sections.push(bullet("覆盖缺口：资金流与事件数据需付费源，未接入；自选股池存在固有的选择偏差。"));
sections.push(bullet("LLM 边界：DeepSeek API 推理并非本地微调 FinGPT，RAG 引用绑定缓解但未消除幻觉。"));
sections.push(bullet("市值与行业因子：数据源缺失，四因子框架中两项尚未实证，是明确的后续工作。"));
sections.push(P("展望：继续积累校准数据并应用强化学习式后训练循环；部署真实 FinGPT 权重本地 GPU 推理；扩展多因子与跨市场风险实验。最终目标是把\"工程演示\"推进为可发表的\"实证研究\"。"));

// ============ 结语 ============
sections.push(H("结语", HeadingLevel.HEADING_1));
sections.push(P("这个项目目前还谈不上什么研究成果，样本量太小，很多因子也还没接上数据。它更多是一个练习：把课堂上学到的分析方法，试着变成一套每天能自己跑的流程，看看哪些经验判断在数据上站得住脚。"));
sections.push(P("做下来最大的体会是，很多市场上流传的说法，写成规则跑一遍就能知道成不成立——这一点是我在您课上做完那份报告之后才慢慢意识到的。项目还有不少地方没想清楚，如果以后有机会，希望还能向您请教。"));

// ============ 构建文档 ============
const doc = new Document({ sections: [{ children: sections }] });
Packer.toBuffer(doc).then((buf) => {
  const out = path.join("D:\\股票分析项目\\2.0版\\reports", "StockDashboard_项目研究报告.docx");
  fs.writeFileSync(out, buf);
  console.log("OK:", out, buf.length, "bytes");
});
