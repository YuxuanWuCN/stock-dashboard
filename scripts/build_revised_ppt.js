/*
 * Generates the standalone revised pitch deck from the curated PPT material.
 * Run with the bundled Node runtime and NODE_PATH configured to its modules.
 */

const path = require('path');
const fs = require('fs');
const PptxGenJS = require('pptxgenjs');
const sharp = require('sharp');

const ROOT = path.resolve(__dirname, '..');
const MATERIAL = path.join(ROOT, 'PPT素材包');
const OUTPUT = path.join(ROOT, 'Rainbow-FinGPT+项目PPT_新素材版_交易成本修订.pptx');

const pptx = new PptxGenJS();
pptx.layout = 'LAYOUT_WIDE';
pptx.author = 'Rainbow-FinGPT 项目组';
pptx.company = '华南师范大学阿伯丁数据科学与人工智能学院';
pptx.subject = '2026 中国国际大学生创新大赛 - Rainbow-FinGPT 项目路演';
pptx.title = 'Rainbow-FinGPT 项目路演（新素材版，交易成本口径修订）';
pptx.lang = 'zh-CN';
pptx.theme = {
  headFontFace: 'Microsoft YaHei',
  bodyFontFace: 'Microsoft YaHei',
  lang: 'zh-CN',
};
pptx.defineLayout({ name: 'CUSTOM_WIDE', width: 13.333, height: 7.5 });
pptx.layout = 'CUSTOM_WIDE';
pptx.margin = 0;

const W = 13.333;
const H = 7.5;
const FONT = 'Microsoft YaHei';
const COLORS = {
  ink: '16302B',
  deep: '123A35',
  forest: '1E5B52',
  teal: '138A82',
  mint: 'B8E2D4',
  sea: 'DDF3EB',
  moss: '74A66B',
  lime: 'B6D869',
  coral: 'E55E57',
  gold: 'E2A53A',
  sand: 'F2EAD7',
  paper: 'F8FBF8',
  white: 'FFFFFF',
  gray: '66756F',
  pale: 'E8EFEB',
  redPale: 'F9E2E0',
  greenPale: 'DDF0E6',
  bluePale: 'DDEFEF',
};

const ASSETS = {
  system: path.join(MATERIAL, '03_架构图', '系统总架构图.png'),
  ontology: path.join(MATERIAL, '03_架构图', '知识本体流水线图.png'),
  decoupled: path.join(MATERIAL, '03_架构图', '解耦三引擎架构图.jpg'),
  storageTrend: path.join(MATERIAL, '01_三大板块核心图表', '存储-02-TrendGate拦截C浪杀跌(佰维).png'),
  failure: path.join(MATERIAL, '02_全池与校准', '失败案例-立新能源封箱预测比对.png'),
  calibration: path.join(MATERIAL, '02_全池与校准', '概率校准-BrierScore可靠性曲线.png'),
};

function addRect(slide, x, y, w, h, fill, opts = {}) {
  slide.addShape(pptx.ShapeType.rect, {
    x, y, w, h,
    fill: { color: fill, transparency: opts.transparency || 0 },
    line: { color: opts.line || fill, transparency: opts.lineTransparency ?? 100, width: opts.lineWidth || 0.5 },
  });
}

function addRoundRect(slide, x, y, w, h, fill, opts = {}) {
  slide.addShape(pptx.ShapeType.roundRect, {
    x, y, w, h,
    rectRadius: 0.06,
    fill: { color: fill, transparency: opts.transparency || 0 },
    line: { color: opts.line || fill, transparency: opts.lineTransparency ?? 100, width: opts.lineWidth || 0.5 },
  });
}

function addText(slide, text, x, y, w, h, opts = {}) {
  slide.addText(text, {
    x, y, w, h,
    fontFace: FONT,
    fontSize: opts.fontSize || 15,
    color: opts.color || COLORS.ink,
    bold: opts.bold || false,
    italic: opts.italic || false,
    breakLine: false,
    margin: opts.margin ?? 0,
    fit: opts.fit || 'shrink',
    valign: opts.valign || 'top',
    align: opts.align || 'left',
    paraSpaceAfterPt: opts.paraSpaceAfterPt || 0,
    bullet: opts.bullet,
    transparency: opts.transparency,
    charSpacing: 0,
  });
}

function addHeader(slide, page, title, subtitle = '') {
  slide.background = { color: COLORS.paper };
  addText(slide, 'RAINBOW-FINGPT  |  可解释量化投研', 0.62, 0.26, 4.4, 0.19, {
    fontSize: 8.5, color: COLORS.teal, bold: true,
  });
  addText(slide, `${String(page).padStart(2, '0')} / 18`, 11.86, 0.27, 0.82, 0.18, {
    fontSize: 8.5, color: COLORS.gray, align: 'right', bold: true,
  });
  addText(slide, title, 0.62, 0.54, 11.7, 0.48, {
    fontSize: 29, color: COLORS.ink, bold: true, fit: 'shrink',
  });
  if (subtitle) {
    addText(slide, subtitle, 0.64, 1.09, 11.7, 0.25, {
      fontSize: 11.5, color: COLORS.gray,
    });
  }
}

function addFooter(slide, text = '历史回测与模拟盘不代表未来收益，不构成投资建议。') {
  addText(slide, text, 0.62, 7.12, 12.05, 0.14, {
    fontSize: 7.4, color: COLORS.gray,
  });
}

function addSource(slide, text) {
  addText(slide, `资料口径：${text}`, 0.62, 6.87, 12.0, 0.14, {
    fontSize: 7.2, color: COLORS.gray, italic: true,
  });
}

function addChip(slide, text, x, y, w, fill, color = COLORS.ink) {
  addRoundRect(slide, x, y, w, 0.28, fill, { lineTransparency: 100 });
  addText(slide, text, x + 0.09, y + 0.065, w - 0.18, 0.13, {
    fontSize: 8.6, color, bold: true, align: 'center', valign: 'mid',
  });
}

function addBulletList(slide, items, x, y, w, h, opts = {}) {
  const runs = [];
  items.forEach((item, index) => {
    runs.push({
      text: item,
      options: {
        bullet: { indent: opts.indent || 14 },
        hanging: opts.hanging || 3,
        breakLine: index < items.length - 1,
      },
    });
  });
  slide.addText(runs, {
    x, y, w, h,
    fontFace: FONT,
    fontSize: opts.fontSize || 13.5,
    color: opts.color || COLORS.ink,
    margin: 0,
    fit: 'shrink',
    paraSpaceAfterPt: opts.paraSpaceAfterPt || 7,
    breakLine: false,
  });
}

function addArrow(slide, x, y, w, h, color = COLORS.teal) {
  slide.addShape(pptx.ShapeType.rightArrow, {
    x, y, w, h,
    fill: { color },
    line: { color, transparency: 100 },
  });
}

function addCircle(slide, x, y, d, fill, text, textColor = COLORS.white, fontSize = 14) {
  slide.addShape(pptx.ShapeType.ellipse, {
    x, y, w: d, h: d,
    fill: { color: fill },
    line: { color: fill, transparency: 100 },
  });
  addText(slide, text, x, y + d * 0.25, d, d * 0.33, {
    fontSize, color: textColor, bold: true, align: 'center', valign: 'mid',
  });
}

async function addImageContain(slide, file, x, y, w, h, opts = {}) {
  if (!fs.existsSync(file)) {
    throw new Error(`Missing PPT asset: ${file}`);
  }
  const meta = await sharp(file).metadata();
  const ratio = Math.min(w / meta.width, h / meta.height);
  const renderedW = meta.width * ratio;
  const renderedH = meta.height * ratio;
  slide.addImage({
    path: file,
    x: x + (w - renderedW) / 2,
    y: y + (h - renderedH) / 2,
    w: renderedW,
    h: renderedH,
    transparency: opts.transparency || 0,
  });
}

function addNotes(slide, notes) {
  slide.addNotes(notes);
}

async function addCover() {
  const slide = pptx.addSlide();
  slide.background = { color: COLORS.deep };
  addText(slide, '2026 中国国际大学生创新大赛  |  达观数据产业命题', 0.72, 0.54, 7.2, 0.22, {
    fontSize: 10.5, color: COLORS.mint, bold: true,
  });
  addText(slide, 'Rainbow-FinGPT', 0.7, 1.18, 6.7, 0.72, {
    fontSize: 39, color: COLORS.white, bold: true,
  });
  addText(slide, '面向金融量化投研全流程的\n可解释智能体系统', 0.72, 2.0, 6.2, 0.95, {
    fontSize: 25, color: COLORS.white, bold: true,
  });
  addText(slide, '用“证据链、资产定价、战术风控”把每一笔研究结论拆解为可审计的决策路径。', 0.74, 3.16, 5.78, 0.53, {
    fontSize: 14, color: COLORS.mint,
  });

  const pillars = [
    ['证据可追溯', COLORS.teal],
    ['定价可解释', COLORS.gold],
    ['风控可执行', COLORS.coral],
  ];
  pillars.forEach((item, index) => {
    const x = 0.74 + index * 1.92;
    addCircle(slide, x, 4.25, 0.5, item[1], String(index + 1), COLORS.white, 13);
    addText(slide, item[0], x - 0.02, 4.89, 1.5, 0.2, {
      fontSize: 10.5, color: COLORS.white, bold: true,
    });
  });

  addRoundRect(slide, 7.18, 0.68, 5.45, 5.66, COLORS.white, { transparency: 5, lineTransparency: 100 });
  await addImageContain(slide, ASSETS.decoupled, 7.44, 0.98, 4.92, 4.8);
  addText(slide, '定性语义  →  资产定价  →  战术风控', 7.65, 5.88, 4.55, 0.22, {
    fontSize: 10.5, color: COLORS.deep, bold: true, align: 'center',
  });
  addText(slide, '华南师范大学阿伯丁数据科学与人工智能学院', 0.74, 6.46, 5.75, 0.2, {
    fontSize: 10, color: COLORS.mint,
  });
  addText(slide, '新素材版 | 2026.09', 10.28, 6.48, 2.0, 0.18, {
    fontSize: 9.5, color: COLORS.mint, align: 'right',
  });
  addNotes(slide, '封面。资料来源：PPT素材包/03_架构图/解耦三引擎架构图.jpg。');
}

async function addWhyNow() {
  const slide = pptx.addSlide();
  addHeader(slide, 2, '从“报收益”转向“解释每一笔决策”', '本版聚焦老师提出的两个问题：什么时候买卖？测试如何避免前视偏差？');
  const columns = [
    {
      title: '研究效率', tag: '4–20h → 约15min', color: COLORS.teal,
      body: '把研报阅读、数据清洗、定价、风险检查与报告编译串成可复现流水线。',
    },
    {
      title: '决策解释', tag: '不是黑盒预测', color: COLORS.gold,
      body: '大模型只做事实抽取；入池、仓位与风险门控由明确的统计与规则计算。',
    },
    {
      title: '风险边界', tag: '历史回测 / 模拟盘', color: COLORS.coral,
      body: '不以单一收益率替代有效性证明，主动披露回撤、失败案例与未验证情形。',
    },
  ];
  columns.forEach((column, i) => {
    const x = 0.72 + i * 4.16;
    addRoundRect(slide, x, 1.65, 3.62, 3.9, COLORS.white, { line: COLORS.pale, lineTransparency: 0, lineWidth: 1 });
    addCircle(slide, x + 0.28, 1.96, 0.56, column.color, String(i + 1), COLORS.white, 14);
    addText(slide, column.title, x + 0.28, 2.78, 2.95, 0.31, { fontSize: 18, color: COLORS.ink, bold: true });
    addChip(slide, column.tag, x + 0.28, 3.27, 2.42, i === 2 ? COLORS.redPale : COLORS.sea, i === 2 ? COLORS.coral : COLORS.forest);
    addText(slide, column.body, x + 0.28, 3.85, 2.94, 1.1, { fontSize: 13.2, color: COLORS.gray, fit: 'shrink' });
  });
  addText(slide, '我们的主张不是“保证收益”，而是让每一个研究结论都能被追问、复核与复现。', 1.0, 6.05, 11.15, 0.42, {
    fontSize: 20, color: COLORS.deep, bold: true, align: 'center',
  });
  addSource(slide, 'PPT素材包/README_先读我.md；PPT素材/PPT补充材料_交易决策与测试方法论.md');
  addFooter(slide);
  addNotes(slide, '叙事定位页。该页将素材包的“诚实口径”和新增老师反馈内容置于整个路演主线。');
}

async function addArchitecture() {
  const slide = pptx.addSlide();
  addHeader(slide, 3, '三层解耦：大模型不直接下交易指令', '把语言理解、资产定价、战术执行分离，避免把生成模型当成“炒股黑箱”。');
  addRoundRect(slide, 0.64, 1.52, 7.46, 4.85, COLORS.white, { line: COLORS.pale, lineTransparency: 0, lineWidth: 1 });
  await addImageContain(slide, ASSETS.system, 0.87, 1.73, 7.0, 4.42);
  const rows = [
    ['Layer 1', 'SCN-RAG Qualitative Filter', '研报事实、观点、推论标签化；结论绑定原文锚点。', COLORS.teal],
    ['Layer 2', 'Fama-MacBeth + NALE', '剥离风格暴露，筛选统计上可检验的特质 Alpha。', COLORS.gold],
    ['Layer 3', 'Trend Gate', '在趋势破位或 C 浪风险时降低仓位或转为现金。', COLORS.coral],
  ];
  rows.forEach((row, i) => {
    const y = 1.65 + i * 1.47;
    addRoundRect(slide, 8.52, y, 4.16, 1.18, COLORS.white, { line: COLORS.pale, lineTransparency: 0, lineWidth: 1 });
    addChip(slide, row[0], 8.77, y + 0.2, 0.82, row[3], COLORS.white);
    addText(slide, row[1], 9.75, y + 0.18, 2.6, 0.22, { fontSize: 14.2, color: COLORS.ink, bold: true, fit: 'shrink' });
    addText(slide, row[2], 8.77, y + 0.56, 3.52, 0.32, { fontSize: 10.5, color: COLORS.gray, fit: 'shrink' });
  });
  addSource(slide, 'PPT素材包/03_架构图/系统总架构图.png；项目口径：LLM 仅用于非结构化事实抽取');
  addFooter(slide);
  addNotes(slide, '架构图来自素材包。呈现的是系统职责边界，不把大模型输出视为投资指令。');
}

async function addEvidenceFlow() {
  const slide = pptx.addSlide();
  addHeader(slide, 4, '从研报到结论：先建立可审计的证据链', '将“原文事实”与“主观观点、模型推论”分开，给后续定价与风控保留可复核输入。');
  addRoundRect(slide, 0.7, 1.63, 6.0, 4.82, COLORS.white, { line: COLORS.pale, lineTransparency: 0, lineWidth: 1 });
  await addImageContain(slide, ASSETS.ontology, 0.92, 2.1, 5.56, 2.65);
  addText(slide, '输入材料不等于结论。每一条结论必须能回到原始文本或数据来源。', 1.05, 5.35, 5.28, 0.45, {
    fontSize: 14.2, color: COLORS.deep, bold: true, align: 'center',
  });
  const blocks = [
    ['01', '事实 FACT', '可验证的财务、公告、现货或行情数据。', COLORS.teal],
    ['02', '观点 OPINION', '卖方或管理层的判断，不能直接当作数值证据。', COLORS.gold],
    ['03', '推论 INFERENCE', '需要注明依据、时间戳与适用边界。', COLORS.coral],
  ];
  blocks.forEach((block, i) => {
    const y = 1.72 + i * 1.42;
    addCircle(slide, 7.42, y + 0.18, 0.58, block[3], block[0], COLORS.white, 10.5);
    addText(slide, block[1], 8.28, y + 0.09, 3.65, 0.25, { fontSize: 17, color: COLORS.ink, bold: true });
    addText(slide, block[2], 8.28, y + 0.52, 3.9, 0.28, { fontSize: 12.2, color: COLORS.gray, fit: 'shrink' });
  });
  addRoundRect(slide, 7.28, 5.93, 5.18, 0.52, COLORS.sea, { lineTransparency: 100 });
  addText(slide, '证据可追溯率：资料包记录为 100% Citation-Grounded 锚点', 7.56, 6.1, 4.62, 0.14, {
    fontSize: 10.5, color: COLORS.forest, bold: true, align: 'center',
  });
  addSource(slide, 'PPT素材包/03_架构图/知识本体流水线图.png；PPT素材包/README_先读我.md');
  addFooter(slide);
  addNotes(slide, '技术证据链。资料包将 Citation-Grounded 锚点作为可追溯性证据。');
}

async function addPricingGate() {
  const slide = pptx.addSlide();
  addHeader(slide, 5, '资产定价：两阶段检验，先剥离风格 Beta', 'Stage 1 估计因子暴露；Stage 2 对每期横截面进行定价检验，并用稳健标准误汇总。');
  addRoundRect(slide, 0.7, 1.64, 7.7, 4.88, COLORS.white, { line: COLORS.pale, lineTransparency: 0, lineWidth: 1 });
  addChip(slide, 'STAGE 1  时间序列回归', 1.03, 1.97, 2.05, COLORS.sea, COLORS.forest);
  addText(slide, 'Rᵢ,ₜ − Rf,ₜ = αᵢ + βMKT·MKTₜ + βSMB·SMBₜ + βHML·HMLₜ + βMOM·MOMₜ + εᵢ,ₜ', 1.0, 2.43, 6.88, 0.36, {
    fontSize: 11.7, color: COLORS.deep, bold: true, align: 'center', valign: 'mid',
  });
  const factors = [
    ['MKT', '市场'], ['SMB', '规模'], ['HML', '价值'], ['MOM', '动量'],
  ];
  factors.forEach((factor, i) => {
    const x = 1.02 + i * 1.36;
    addRoundRect(slide, x, 3.03, 1.06, 0.61, i % 2 ? COLORS.sea : COLORS.pale, { lineTransparency: 100 });
    addText(slide, factor[0], x, 3.17, 1.06, 0.17, { fontSize: 11, color: COLORS.forest, bold: true, align: 'center' });
    addText(slide, factor[1], x, 3.43, 1.06, 0.11, { fontSize: 7.8, color: COLORS.gray, align: 'center' });
  });
  addArrow(slide, 3.87, 3.92, 0.48, 0.23, COLORS.gold);
  addChip(slide, 'STAGE 2  横截面定价检验', 1.03, 4.16, 2.24, COLORS.sand, COLORS.gold);
  addText(slide, 'Rᵢ,ₜ₊₁ − Rf,ₜ₊₁ = γ₀,ₜ + Σ γₖ,ₜ · β̂ᵢ,ₖ + uᵢ,ₜ₊₁', 1.05, 4.62, 6.82, 0.3, {
    fontSize: 14.1, color: COLORS.deep, bold: true, align: 'center', valign: 'mid',
  });
  addText(slide, '逐期横截面回归，再用 Newey-West HAC 汇总稳健 t 统计量与特质 Alpha 稳定性。', 1.0, 5.31, 6.92, 0.22, { fontSize: 10.4, color: COLORS.gray, align: 'center', fit: 'shrink' });
  addRoundRect(slide, 8.82, 1.64, 3.82, 4.88, COLORS.deep, { lineTransparency: 100 });
  addText(slide, '入池硬门槛', 9.14, 2.02, 3.14, 0.3, { fontSize: 19, color: COLORS.white, bold: true, align: 'center' });
  addText(slide, 'p-value < 0.05', 9.15, 2.76, 3.15, 0.34, { fontSize: 25, color: COLORS.lime, bold: true, align: 'center' });
  addText(slide, '且', 9.14, 3.26, 3.15, 0.19, { fontSize: 12, color: COLORS.mint, bold: true, align: 'center' });
  addText(slide, 'IR ≥ 0.30', 9.15, 3.64, 3.15, 0.34, { fontSize: 25, color: COLORS.lime, bold: true, align: 'center' });
  addText(slide, '未达到统计显著性或稳定性要求：不进入候选池。', 9.24, 4.55, 2.98, 0.64, { fontSize: 12.2, color: COLORS.white, align: 'center', fit: 'shrink' });
  addSource(slide, 'PPT素材/PPT补充材料_交易决策与测试方法论.md；PPT素材包/05_参考文档/诚实口径数据源(以此为准).md');
  addFooter(slide);
  addNotes(slide, '参数阈值来自新增素材。这里描述的是门槛规则，不把未独立复核的敏感性结果作为实测业绩。');
}

async function addTrendGate() {
  const slide = pptx.addSlide();
  addHeader(slide, 6, 'Trend Gate：风险信号出现时，规则优先于主观判断', '先检查宏观与个股趋势；当关键条件不满足时，减少风险暴露或持有现金。');
  addRoundRect(slide, 0.66, 1.57, 7.25, 4.99, COLORS.white, { line: COLORS.pale, lineTransparency: 0, lineWidth: 1 });
  await addImageContain(slide, ASSETS.storageTrend, 0.92, 1.87, 6.75, 4.35);
  const checks = [
    ['价格 > MA20', '趋势仍在均线上方', COLORS.teal],
    ['EMA5 > EMA20', '短期趋势不弱于中期趋势', COLORS.gold],
    ['非 C 浪下跌', '避免处于主跌结构', COLORS.coral],
  ];
  checks.forEach((check, i) => {
    const y = 1.77 + i * 1.21;
    addCircle(slide, 8.43, y, 0.5, check[2], String(i + 1), COLORS.white, 12);
    addText(slide, check[0], 9.17, y - 0.01, 2.82, 0.2, { fontSize: 15, color: COLORS.ink, bold: true });
    addText(slide, check[1], 9.17, y + 0.32, 3.0, 0.2, { fontSize: 11.2, color: COLORS.gray });
  });
  addRoundRect(slide, 8.18, 5.63, 4.25, 0.75, COLORS.redPale, { line: COLORS.coral, lineTransparency: 45, lineWidth: 1 });
  addText(slide, '任一红灯：剔除、降风险，或转为现金。', 8.44, 5.88, 3.72, 0.19, { fontSize: 12.2, color: COLORS.coral, bold: true, align: 'center' });
  addSource(slide, 'PPT素材包/01_三大板块核心图表/存储-02-TrendGate拦截C浪杀跌(佰维).png；图仅作机制示意');
  addFooter(slide);
  addNotes(slide, '图内的历史指标与 README 口径有冲突，因此本页仅将图作为 Trend Gate 机制示意，不引用图内收益或回撤数据。');
}

async function addDecisionFlow() {
  const slide = pptx.addSlide();
  addHeader(slide, 7, '日频交易决策五步流程', '新增页：T 日收盘后计算；回测/模拟盘按 T+1 交易时点与既定成本假设进行撮合。');
  const steps = [
    ['01', '宏观趋势门控', '牛市/震荡继续\n熊市 30%仓位；C浪清仓', COLORS.teal],
    ['02', '个股 Alpha 评分', '252 日回归\np < 0.05 且 IR ≥ 0.30', COLORS.gold],
    ['03', '个股趋势确认', '价格 > MA20\nEMA5 > EMA20；非 C 浪', COLORS.coral],
    ['04', '权重与死区', 'Top 2–3；等权/Alpha 加权\n变化 < 8% 不调仓', COLORS.moss],
    ['05', 'T+1 模拟撮合', '买 0.125%（佣金+滑点）\n卖 0.175%（税仅卖方0.05%）', COLORS.gray],
  ];
  steps.forEach((step, i) => {
    const x = 0.52 + i * 2.56;
    addRoundRect(slide, x, 2.08, 2.15, 2.66, COLORS.white, { line: COLORS.pale, lineTransparency: 0, lineWidth: 1 });
    addCircle(slide, x + 0.18, 2.3, 0.5, step[3], step[0], COLORS.white, 10.5);
    addText(slide, step[1], x + 0.19, 3.06, 1.72, 0.42, { fontSize: 15.5, color: COLORS.ink, bold: true, align: 'center', fit: 'shrink' });
    addText(slide, step[2], x + 0.24, 3.66, 1.65, 0.58, { fontSize: 9.35, color: COLORS.gray, align: 'center', fit: 'shrink' });
    if (i < steps.length - 1) {
      addArrow(slide, x + 2.2, 3.1, 0.24, 0.22, COLORS.pale);
    }
  });
  addText(slide, '摩擦拆分：佣金万 2.5 双边 + 单边滑点万 10.0；印花税仅卖方 0.05%，故买/卖总摩擦为 0.125% / 0.175%。', 0.96, 4.95, 11.4, 0.18, {
    fontSize: 9.3, color: COLORS.gray, align: 'center', fit: 'shrink',
  });
  addRoundRect(slide, 0.75, 5.35, 11.82, 0.92, COLORS.deep, { lineTransparency: 100 });
  addText(slide, '三处关键拦截：C 浪主跌 → 清仓 / Alpha 不显著 → 不入池 / 个股破趋势 → 退出或降风险', 1.05, 5.68, 11.22, 0.26, {
    fontSize: 15, color: COLORS.white, bold: true, align: 'center',
  });
  addSource(slide, '财政部、税务总局公告2023年第39号（2023-08-28起：印花税仅卖方0.05%）；佣金万2.5双边、滑点万10.0为回测假设');
  addFooter(slide);
  addNotes(slide, '新增页。交易摩擦拆分：买入 0.125%=佣金0.025%+滑点0.10%；卖出0.175%=佣金0.025%+滑点0.10%+卖方印花税0.05%。印花税往返仅0.05%，但含佣金和滑点的回测总摩擦为0.30%。');
}

async function addBuySell() {
  const slide = pptx.addSlide();
  addHeader(slide, 8, '什么时候买、什么时候卖：把规则说清楚', '只有五步流程同时满足买入条件，才形成目标持仓；风险门控触发时优先退出或降低风险。');
  const sides = [
    {
      x: 0.82, title: '形成买入 / 持有', color: COLORS.forest, pale: COLORS.greenPale,
      rows: [
        ['宏观允许', '牛市或震荡；没有 C 浪主跌警报'],
        ['Alpha 通过', 'p < 0.05 且 IR ≥ 0.30'],
        ['趋势通过', '价格 > MA20、EMA5 > EMA20'],
        ['形成目标仓位', 'Top 2–3；等权或按 Alpha 加权；差 ≥ 8% 才调仓'],
      ],
    },
    {
      x: 6.9, title: '卖出 / 降风险 / 现金', color: COLORS.coral, pale: COLORS.redPale,
      rows: [
        ['宏观风险', '熊市降至 30% 仓位；C 浪主跌转为现金'],
        ['Alpha 失效', '不满足显著性或稳定性门槛'],
        ['趋势破位', '价格跌破 MA20、EMA5 下穿 EMA20'],
        ['T+1 模拟执行', '买0.125%；卖0.175%\n税仅卖方 0.05%'],
      ],
    },
  ];
  sides.forEach((side) => {
    addRoundRect(slide, side.x, 1.63, 5.6, 4.99, COLORS.white, { line: side.pale, lineTransparency: 0, lineWidth: 1 });
    addRoundRect(slide, side.x + 0.25, 1.92, 5.1, 0.62, side.pale, { lineTransparency: 100 });
    addText(slide, side.title, side.x + 0.42, 2.1, 4.76, 0.22, { fontSize: 17, color: side.color, bold: true, align: 'center' });
    side.rows.forEach((row, i) => {
      const y = 2.94 + i * 0.76;
      addCircle(slide, side.x + 0.42, y + 0.02, 0.33, side.color, String(i + 1), COLORS.white, 8.5);
      addText(slide, row[0], side.x + 0.92, y, 1.2, 0.2, { fontSize: 12, color: COLORS.ink, bold: true });
      addText(slide, row[1], side.x + 2.18, y, 2.75, 0.38, { fontSize: 10.3, color: COLORS.gray, fit: 'shrink' });
    });
  });
  addText(slide, '纪律的价值：宁可错过短期高涨幅，也不放松显著性与趋势门槛。', 1.2, 6.22, 10.92, 0.25, { fontSize: 15, color: COLORS.deep, bold: true, align: 'center' });
  addSource(slide, '第7页成本模型：佣金万2.5双边、卖方印花税0.05%、单边滑点万10.0；财政部、税务总局公告2023年第39号');
  addFooter(slide);
  addNotes(slide, '新增页。买卖总费率沿用已披露回测假设，但明确税负仅在卖方收取0.05%，避免把佣金和滑点误说为印花税。');
}

async function addTestProtocol() {
  const slide = pptx.addSlide();
  addHeader(slide, 9, '时序封箱：把“无未来信息”写成可检查协议', '训练、参数冻结、测试与执行时点分开处理；逐板块训练起止日须由可复现配置补充，本页不编造。');
  const lanes = [
    ['半导体存储', '2025Q2–2026Q3', COLORS.teal, '累计收益 +159.01%；最大回撤 -6.51%'],
    ['黄金避险', '2025Q3–2026Q3', COLORS.gold, '累计收益 +94.84%；最大回撤 29.70%'],
    ['绿电公用事业', '2025Q3–2026Q3', COLORS.moss, '最大回撤：基准 -33.05% → 策略 -21.54%'],
  ];
  addText(slide, '训练期（早于测试窗）+ 参数冻结', 0.6, 1.7, 3.1, 0.19, { fontSize: 10.5, color: COLORS.gray, bold: true, align: 'center' });
  addText(slide, '独立测试窗口（只按当时可见数据计算）', 3.74, 1.7, 5.62, 0.19, { fontSize: 11, color: COLORS.gray, bold: true, align: 'center' });
  addText(slide, 'T 日 15:00 → T+1 09:30 模拟撮合', 9.96, 1.7, 2.48, 0.19, { fontSize: 9.5, color: COLORS.gray, bold: true, align: 'center' });
  lanes.forEach((lane, i) => {
    const y = 2.2 + i * 1.18;
    addText(slide, lane[0], 0.74, y + 0.23, 1.65, 0.18, { fontSize: 13, color: COLORS.ink, bold: true, fit: 'shrink' });
    addRoundRect(slide, 2.46, y, 1.2, 0.63, COLORS.pale, { lineTransparency: 100 });
    addText(slide, '训练\n冻结参数', 2.46, y + 0.12, 1.2, 0.24, { fontSize: 9.3, color: COLORS.gray, bold: true, align: 'center' });
    addArrow(slide, 3.79, y + 0.2, 0.36, 0.2, COLORS.pale);
    addRoundRect(slide, 4.22, y, 5.7, 0.63, COLORS.white, { line: lane[2], lineTransparency: 30, lineWidth: 1.4 });
    addText(slide, lane[1], 4.45, y + 0.12, 2.28, 0.18, { fontSize: 12.1, color: COLORS.ink, bold: true });
    addText(slide, lane[3], 6.82, y + 0.12, 2.84, 0.18, { fontSize: 9.8, color: COLORS.gray, align: 'right', fit: 'shrink' });
    addArrow(slide, 10.05, y + 0.2, 0.36, 0.2, COLORS.pale);
    addRoundRect(slide, 10.48, y, 1.8, 0.63, COLORS.sea, { lineTransparency: 100 });
    addText(slide, 'T日 15:00 决策\nT+1 09:30 撮合', 10.48, y + 0.11, 1.8, 0.25, { fontSize: 8.55, color: COLORS.forest, bold: true, align: 'center' });
  });
  const safeguards = [
    ['物理隔离', '测试数据与训练数据分开管理'],
    ['时序封箱', 'T日 15:00 计算；T+1日 09:30 模拟撮合'],
    ['参数冻结', '测试期间不根据结果临时改阈值'],
  ];
  safeguards.forEach((item, i) => {
    const x = 1.5 + i * 3.67;
    addCircle(slide, x, 5.96, 0.42, [COLORS.teal, COLORS.gold, COLORS.coral][i], '✓', COLORS.white, 14);
    addText(slide, item[0], x + 0.62, 5.91, 1.05, 0.16, { fontSize: 10.5, color: COLORS.ink, bold: true });
    addText(slide, item[1], x + 0.62, 6.16, 2.45, 0.14, { fontSize: 8.6, color: COLORS.gray, fit: 'shrink' });
  });
  addText(slide, '注：可信口径文件未逐板块列出训练期起止日；提交前应从回测配置导出并附入证据集。', 0.83, 6.54, 11.75, 0.14, { fontSize: 8.4, color: COLORS.coral, align: 'center', fit: 'shrink' });
  addSource(slide, 'PPT素材包/README_先读我.md（样本期与可用指标）；PPT素材/PPT补充材料_交易决策与测试方法论.md（协议结构）');
  addFooter(slide);
  addNotes(slide, '新增页。样本期按 README 的“诚实口径”修正：存储为 2025Q2–2026Q3，黄金为 2025Q3–2026Q3，不使用资料中不可能的“2026Q7”。');
}

async function addParameterBoundary() {
  const slide = pptx.addSlide();
  addHeader(slide, 10, '参数冻结：公开基准配置，也公开验证边界', '新增资料含敏感性矩阵；因当前包中缺少可复现的完整计算证据，本版只展示已声明的基准配置，不把矩阵数字作为已完成实证。');
  const params = [
    ['Alpha 显著性', 'p < 0.05', '统计显著性门槛'],
    ['Alpha 稳定性', 'IR ≥ 0.30', '入池质量门槛'],
    ['NALE 系数', 'α = 0.4', '资料包说明为论文默认值'],
    ['趋势周期', 'MA20', 'Trend Gate 基准周期'],
    ['调仓死区', '8%', '减少小幅权重变化带来的摩擦'],
  ];
  params.forEach((param, i) => {
    const x = 0.66 + i * 2.53;
    const fill = [COLORS.sea, COLORS.sand, COLORS.greenPale, COLORS.bluePale, COLORS.redPale][i];
    const key = [COLORS.teal, COLORS.gold, COLORS.moss, COLORS.forest, COLORS.coral][i];
    addRoundRect(slide, x, 1.82, 2.14, 2.45, fill, { lineTransparency: 100 });
    addText(slide, param[0], x + 0.16, 2.13, 1.82, 0.2, { fontSize: 12, color: COLORS.ink, bold: true, align: 'center' });
    addText(slide, param[1], x + 0.16, 2.74, 1.82, 0.38, { fontSize: 21, color: key, bold: true, align: 'center' });
    addText(slide, param[2], x + 0.19, 3.48, 1.75, 0.32, { fontSize: 9.7, color: COLORS.gray, align: 'center', fit: 'shrink' });
  });
  addRoundRect(slide, 1.12, 4.92, 11.08, 1.04, COLORS.white, { line: COLORS.pale, lineTransparency: 0, lineWidth: 1 });
  addText(slide, '为什么不把“某一参数最优”直接写成结论？', 1.45, 5.2, 4.3, 0.2, { fontSize: 15, color: COLORS.ink, bold: true });
  addText(slide, '参数若是在测试结果出来后反复调到最优，可能造成过拟合。后续需要按时间切分、完整成本（佣金、卖方税、滑点）与跨市场状态的可复现实验，才能报告敏感性结论。', 1.45, 5.58, 9.92, 0.18, { fontSize: 11, color: COLORS.gray, fit: 'shrink' });
  addSource(slide, 'PPT素材/PPT补充材料_交易决策与测试方法论.md；本页为“已声明配置”而非新增敏感性业绩声明');
  addFooter(slide);
  addNotes(slide, '新增页。为避免将未经独立复核的敏感性数值当作事实，本页保留基准参数和验证要求。');
}

function addMetricBar(slide, label, leftLabel, leftValue, rightLabel, rightValue, x, y, w, max, leftColor, rightColor, opts = {}) {
  addText(slide, label, x, y, w, 0.17, { fontSize: 11.5, color: COLORS.ink, bold: true });
  const barY = y + 0.4;
  const barW = w - 2.5;
  addRoundRect(slide, x, barY, barW, 0.18, COLORS.pale, { lineTransparency: 100 });
  const leftW = Math.max(0.1, Math.abs(leftValue) / max * barW);
  const rightW = Math.max(0.1, Math.abs(rightValue) / max * barW);
  addRoundRect(slide, x, barY, leftW, 0.18, leftColor, { lineTransparency: 100 });
  addRoundRect(slide, x, barY + 0.31, rightW, 0.18, rightColor, { lineTransparency: 100 });
  addText(slide, `${leftLabel}  ${opts.leftText || leftValue}`, x + barW + 0.18, barY - 0.03, 2.2, 0.16, { fontSize: 9.5, color: leftColor, bold: true });
  addText(slide, `${rightLabel}  ${opts.rightText || rightValue}`, x + barW + 0.18, barY + 0.28, 2.2, 0.16, { fontSize: 9.5, color: rightColor, bold: true });
}

async function addStorageResults() {
  const slide = pptx.addSlide();
  addHeader(slide, 11, '实证一：存储周期，策略的优势是回撤控制', '2025Q2–2026Q3 历史回测。策略绝对收益低于等权基准；因此本页只主张其风控结果。');
  addRoundRect(slide, 0.73, 1.68, 3.26, 4.55, COLORS.deep, { lineTransparency: 100 });
  addText(slide, '+159.01%', 1.0, 2.08, 2.72, 0.5, { fontSize: 30, color: COLORS.white, bold: true, align: 'center' });
  addText(slide, '策略累计收益', 1.0, 2.72, 2.72, 0.18, { fontSize: 11.5, color: COLORS.mint, bold: true, align: 'center' });
  addText(slide, '等权基准：+222.30%', 1.0, 3.5, 2.72, 0.22, { fontSize: 15, color: COLORS.lime, bold: true, align: 'center' });
  addText(slide, '结论：策略在绝对收益上落后于等权基准，不可描述为取得全面超额。', 1.06, 4.19, 2.62, 0.68, { fontSize: 11.8, color: COLORS.white, align: 'center', fit: 'shrink' });
  addText(slide, '回撤对比', 4.58, 1.93, 2.0, 0.23, { fontSize: 17.5, color: COLORS.ink, bold: true });
  addText(slide, '最大动态回撤（幅度越小越好）', 4.58, 2.31, 4.1, 0.18, { fontSize: 10.2, color: COLORS.gray });
  addMetricBar(slide, '存储板块', '等权基准', -32.04, '策略', -6.51, 4.58, 2.86, 6.9, 35, COLORS.gray, COLORS.teal, { leftText: '-32.04%', rightText: '-6.51%' });
  addRoundRect(slide, 4.58, 4.1, 7.35, 1.0, COLORS.sea, { lineTransparency: 100 });
  addText(slide, '核心证据：在该样本期，Trend Gate 的价值体现在把最大回撤从 -32.04% 压制至 -6.51%。', 4.91, 4.44, 6.7, 0.29, { fontSize: 15, color: COLORS.forest, bold: true, align: 'center', fit: 'shrink' });
  addText(slide, '样本期限制：该段为半导体存储牛市，不能替代熊市或全市场表现。', 4.65, 5.67, 7.1, 0.2, { fontSize: 11, color: COLORS.coral, bold: true, align: 'center' });
  addSource(slide, 'PPT素材包/README_先读我.md；PPT素材包/05_参考文档/诚实口径数据源(以此为准).md');
  addFooter(slide);
  addNotes(slide, '资料来源优先级为 README 与诚实口径文档。未使用存储-01 图内与该口径冲突的指标。');
}

async function addCrossSectorResults() {
  const slide = pptx.addSlide();
  addHeader(slide, 12, '实证二：跨板块检验，优势与边界并存', '均为历史回测。不同板块市场环境不同，不能把某一窗口的最优表现外推为普适能力。');
  const cards = [
    {
      x: 0.78, color: COLORS.gold, pale: COLORS.sand, title: '黄金避险', period: '2025Q3–2026Q3', main: '+94.84%', label: '累计收益', note: '最大动态回撤：29.70%\n接近 30% 风险边界。',
    },
    {
      x: 4.63, color: COLORS.moss, pale: COLORS.greenPale, title: '绿电公用事业', period: '2025Q3–2026Q3', main: '-33.05% → -21.54%', label: '基准 → 策略最大回撤', note: '回撤得到压制；\n仍需更多市场状态验证。',
    },
    {
      x: 8.48, color: COLORS.teal, pale: COLORS.sea, title: '共同解释', period: '历史回测 / 模拟盘', main: '风险控制', label: '不是收益承诺', note: '三组结果支持继续验证\n“门控降低回撤”的假设。',
    },
  ];
  cards.forEach((card, i) => {
    addRoundRect(slide, card.x, 1.77, 3.22, 4.42, COLORS.white, { line: card.pale, lineTransparency: 0, lineWidth: 1 });
    addCircle(slide, card.x + 0.34, 2.15, 0.56, card.color, String(i + 1), COLORS.white, 13);
    addText(slide, card.title, card.x + 0.35, 2.99, 2.55, 0.26, { fontSize: 17, color: COLORS.ink, bold: true, align: 'center' });
    addChip(slide, card.period, card.x + 0.54, 3.45, 2.14, card.pale, card.color);
    addText(slide, card.main, card.x + 0.27, 4.11, 2.7, 0.52, { fontSize: i === 1 ? 20 : 27, color: card.color, bold: true, align: 'center', fit: 'shrink' });
    addText(slide, card.label, card.x + 0.34, 4.83, 2.54, 0.18, { fontSize: 10.5, color: COLORS.gray, align: 'center' });
    addText(slide, card.note, card.x + 0.43, 5.38, 2.36, 0.42, { fontSize: 10.8, color: COLORS.gray, align: 'center', fit: 'shrink' });
  });
  addSource(slide, 'PPT素材包/README_先读我.md；PPT素材包/05_参考文档/诚实口径数据源(以此为准).md');
  addFooter(slide);
  addNotes(slide, '黄金与绿电数值按诚实口径资料展示。未引用旧版逐页讲稿的收益、夏普或“全面跑赢”等说法。');
}

async function addFailureCase() {
  const slide = pptx.addSlide();
  addHeader(slide, 13, '失败案例：涨了 82%，系统为何仍然拒绝？', '主动展示不通过 Alpha 门控的立新能源（001258），避免只挑选对系统有利的案例。');
  addRoundRect(slide, 0.68, 1.62, 6.18, 4.84, COLORS.white, { line: COLORS.pale, lineTransparency: 0, lineWidth: 1 });
  addText(slide, '价格结果 ≠ 可验证的特质 Alpha', 1.1, 2.02, 5.3, 0.31, { fontSize: 19, color: COLORS.ink, bold: true, align: 'center' });
  addRoundRect(slide, 1.22, 2.65, 5.05, 0.95, COLORS.sand, { lineTransparency: 100 });
  addText(slide, '+82.36%', 1.55, 2.88, 2.3, 0.34, { fontSize: 25, color: COLORS.gold, bold: true, align: 'center' });
  addText(slide, '测试区间累计涨幅\n（市场表现）', 4.09, 2.91, 1.78, 0.28, { fontSize: 10.2, color: COLORS.gray, bold: true, align: 'center' });
  addArrow(slide, 3.42, 3.95, 0.7, 0.3, COLORS.pale);
  addText(slide, '是否为统计上可靠的超额收益？', 1.16, 4.32, 5.22, 0.22, { fontSize: 13.3, color: COLORS.deep, bold: true, align: 'center' });
  addRoundRect(slide, 1.22, 4.83, 5.05, 0.7, COLORS.redPale, { lineTransparency: 100 });
  addText(slide, '用 p-value 与 IR 门槛检验，而不是追逐涨幅。', 1.58, 5.08, 4.34, 0.18, { fontSize: 11.4, color: COLORS.coral, bold: true, align: 'center' });
  addRoundRect(slide, 7.26, 1.62, 5.38, 4.84, COLORS.deep, { lineTransparency: 100 });
  addText(slide, '+82.36%', 7.75, 2.03, 4.35, 0.45, { fontSize: 31, color: COLORS.lime, bold: true, align: 'center' });
  addText(slide, '测试区间累计涨幅', 7.75, 2.62, 4.35, 0.18, { fontSize: 11.5, color: COLORS.mint, bold: true, align: 'center' });
  const stats = [
    ['p-value', '0.3543', '高于 0.05，统计不显著'],
    ['IR', '0.063', '低于 0.30，稳定性不足'],
  ];
  stats.forEach((stat, i) => {
    const y = 3.26 + i * 0.83;
    addText(slide, stat[0], 7.7, y, 1.15, 0.17, { fontSize: 11, color: COLORS.mint, bold: true });
    addText(slide, stat[1], 8.95, y - 0.06, 1.26, 0.24, { fontSize: 18, color: COLORS.white, bold: true, align: 'center' });
    addText(slide, stat[2], 10.35, y, 1.66, 0.17, { fontSize: 9.6, color: COLORS.mint, fit: 'shrink' });
  });
  addRoundRect(slide, 7.78, 5.28, 4.34, 0.6, COLORS.redPale, { lineTransparency: 100 });
  addText(slide, '系统判定：REJECT（不进入候选池）', 8.02, 5.49, 3.86, 0.18, { fontSize: 12.5, color: COLORS.coral, bold: true, align: 'center' });
  addSource(slide, 'PPT素材包/05_参考文档/诚实口径数据源(以此为准).md；未使用含冲突内嵌指标的失败案例图');
  addFooter(slide);
  addNotes(slide, '失败案例。资料指定测试期为 2025-07-14 至 2026-08-14，累计涨幅 +82.36%，p=0.3543，IR=0.063。为避免展示未核验的图内指标，本页用原生形状呈现。');
}

async function addScorecard() {
  const slide = pptx.addSlide();
  addHeader(slide, 14, '透明成绩单：不把未达标项藏起来', '用“已验证、部分达成、未达标、待验证”四类状态呈现证据，而不是只展示最好看的指标。');
  const rows = [
    ['研报结构化解析', '92.4%', '部分达成', COLORS.gold, '方向预测不等于解析正确率'],
    ['证据可追溯覆盖', '100%', '已验证', COLORS.teal, 'Citation-Grounded 坐标级锚点'],
    ['方向预测命中率', '55.9%–62.7%', '未达标', COLORS.coral, '高于随机，但远低于 80% 目标'],
    ['胜率 / 盈亏比', '46.30% / 0.83', '未达标', COLORS.coral, '含佣金、卖方税和滑点的回测统计'],
    ['存储回撤控制', '-32.04% → -6.51%', '已验证', COLORS.teal, '特定样本期的历史回测结果'],
    ['熊市 / 震荡市覆盖', '尚未完成', '待验证', COLORS.gold, '无法外推至全市场环境'],
  ];
  const cols = [0.75, 3.35, 5.9, 8.0, 9.92];
  ['指标', '资料包记录', '状态', '状态说明', '影响/边界'].forEach((label, i) => {
    addText(slide, label, cols[i], 1.77, [2.38, 2.32, 1.6, 1.7, 2.42][i], 0.2, { fontSize: 10.5, color: COLORS.gray, bold: true, align: i === 2 ? 'center' : 'left' });
  });
  rows.forEach((row, i) => {
    const y = 2.18 + i * 0.67;
    if (i % 2 === 0) addRect(slide, 0.67, y - 0.07, 12.0, 0.56, COLORS.white);
    addText(slide, row[0], cols[0], y + 0.07, 2.37, 0.16, { fontSize: 10.6, color: COLORS.ink, bold: true, fit: 'shrink' });
    addText(slide, row[1], cols[1], y + 0.07, 2.3, 0.16, { fontSize: 10.4, color: COLORS.ink, fit: 'shrink' });
    addChip(slide, row[2], cols[2], y + 0.04, 1.55, row[3] === COLORS.coral ? COLORS.redPale : row[3] === COLORS.teal ? COLORS.sea : COLORS.sand, row[3]);
    addText(slide, row[4], cols[3], y + 0.07, 1.7, 0.16, { fontSize: 9.4, color: COLORS.gray, fit: 'shrink' });
    addText(slide, row[5], cols[4], y + 0.07, 2.35, 0.16, { fontSize: 9.4, color: COLORS.gray, fit: 'shrink' });
  });
  addRoundRect(slide, 1.3, 6.27, 10.74, 0.43, COLORS.deep, { lineTransparency: 100 });
  addText(slide, '好看的单项数字不是结论；完整的失败样本与未验证窗口，才是下一轮验证的起点。', 1.61, 6.42, 10.1, 0.14, { fontSize: 11.2, color: COLORS.white, bold: true, align: 'center' });
  addSource(slide, 'PPT素材包/05_参考文档/诚实口径数据源(以此为准).md；成本为佣金万2.5双边、卖方税0.05%、单边滑点万10.0假设');
  addFooter(slide);
  addNotes(slide, '诚信成绩单。胜率/盈亏比沿用既有扣费后全池统计；其成本模型为佣金0.025%双边、卖方印花税0.05%、滑点0.10%单边。未重新计算该统计。');
}

async function addLimitations() {
  const slide = pptx.addSlide();
  addHeader(slide, 15, '三条必须说清的边界', '这些边界不是“减分项”，而是让后续验证与真实部署有可追踪起点。');
  const limits = [
    ['非真实资金交易', '当前证据为历史回测与模拟盘；没有以真实资金成交结果代替模型假设。', COLORS.coral, '佣金、卖方税、滑点均为假设；冲击成本等仍待验证。'],
    ['不是全市场', '当前突出结果主要来自 2025–2026 特定产业窗口。', COLORS.gold, '熊市、震荡市与跨行业稳定性仍需时间切分回测。'],
    ['不是保证收益', '方向预测与全池胜率存在未达标项；Alpha 门槛也会错过上涨。', COLORS.teal, '系统价值更偏向可解释研究与风险控制，而非收益承诺。'],
  ];
  limits.forEach((limit, i) => {
    const x = 0.72 + i * 4.15;
    addRoundRect(slide, x, 1.75, 3.58, 4.45, COLORS.white, { line: COLORS.pale, lineTransparency: 0, lineWidth: 1 });
    addCircle(slide, x + 1.39, 2.12, 0.78, limit[2], ['!', '!', '≠'][i], COLORS.white, 25);
    addText(slide, limit[0], x + 0.32, 3.25, 2.93, 0.28, { fontSize: 18, color: COLORS.ink, bold: true, align: 'center' });
    addText(slide, limit[1], x + 0.38, 3.86, 2.8, 0.85, { fontSize: 12.1, color: COLORS.gray, align: 'center', fit: 'shrink' });
    addRoundRect(slide, x + 0.34, 5.22, 2.9, 0.59, i === 0 ? COLORS.redPale : i === 1 ? COLORS.sand : COLORS.sea, { lineTransparency: 100 });
    addText(slide, limit[3], x + 0.53, 5.39, 2.52, 0.24, { fontSize: 9.5, color: COLORS.ink, align: 'center', fit: 'shrink' });
  });
  addSource(slide, 'PPT素材包/05_参考文档/诚实口径数据源(以此为准).md：系统局限性与风险提示');
  addFooter(slide);
  addNotes(slide, '局限性页。按资料包的学术诚信声明，明确指出历史回测、牛市窗口和方向预测能力边界。');
}

async function addCommercialPath() {
  const slide = pptx.addSlide();
  addHeader(slide, 16, '产业落地：从投研辅助工具开始', '当前更适合作为“可解释、可追溯”的投研辅助能力，而不是独立自动交易产品。');
  const stages = [
    ['现在', '研究原型', '研报事实抽取、Alpha 门控、风险解释与可复现材料。', COLORS.teal],
    ['下一步', '跨状态验证', '补充熊市、震荡市和更长时间样本；如实披露结果。', COLORS.gold],
    ['随后', '受控试点', '在合规与风险预算下，开展小规模、可追踪的验证。', COLORS.coral],
  ];
  stages.forEach((stage, i) => {
    const x = 0.83 + i * 4.13;
    addCircle(slide, x + 1.22, 1.96, 0.98, stage[3], String(i + 1), COLORS.white, 23);
    addText(slide, stage[0], x + 0.55, 3.15, 2.34, 0.2, { fontSize: 10.6, color: stage[3], bold: true, align: 'center' });
    addText(slide, stage[1], x + 0.36, 3.55, 2.72, 0.28, { fontSize: 18.5, color: COLORS.ink, bold: true, align: 'center' });
    addText(slide, stage[2], x + 0.44, 4.22, 2.56, 0.58, { fontSize: 12, color: COLORS.gray, align: 'center', fit: 'shrink' });
    if (i < stages.length - 1) addArrow(slide, x + 3.26, 2.34, 0.52, 0.28, COLORS.pale);
  });
  addRoundRect(slide, 1.2, 5.7, 10.94, 0.63, COLORS.sea, { lineTransparency: 100 });
  addText(slide, '优先服务 B 端投研与研究决策：提供证据链、统计筛选与风险解释，不承诺投资结果。', 1.5, 5.94, 10.32, 0.18, { fontSize: 13, color: COLORS.forest, bold: true, align: 'center' });
  addSource(slide, 'PPT素材包/05_参考文档/诚实口径数据源(以此为准).md：商业化路径（诚实版）');
  addFooter(slide);
  addNotes(slide, '商业化路径按资料包“诚实版”调整：定位为 B 端投研辅助，真实交易验证与合规仍是后续阶段。');
}

async function addEvidencePack() {
  const slide = pptx.addSlide();
  addHeader(slide, 17, '可复现交付：建立可回溯证据链', '提交的不只是 PPT，而是一组可从素材、研报、口径到代码依次追溯的材料。');
  const artifacts = [
    ['实证图表', '三大板块核心图表\n与全池/校准素材', COLORS.teal],
    ['研报原件', '存储、黄金、绿电\n三份 PDF 佐证', COLORS.gold],
    ['口径说明', 'README 与“诚实口径数据源”\n作为数字来源优先级', COLORS.coral],
    ['工程证据', '源码、测试与质量门禁\n用于后续复现与复核', COLORS.moss],
  ];
  artifacts.forEach((artifact, i) => {
    const x = 0.72 + i * 3.12;
    addRoundRect(slide, x, 1.96, 2.66, 3.72, COLORS.white, { line: COLORS.pale, lineTransparency: 0, lineWidth: 1 });
    addCircle(slide, x + 0.95, 2.32, 0.76, artifact[2], String(i + 1), COLORS.white, 19);
    addText(slide, artifact[0], x + 0.24, 3.47, 2.18, 0.22, { fontSize: 15, color: COLORS.ink, bold: true, align: 'center' });
    addText(slide, artifact[1], x + 0.34, 4.14, 1.98, 0.46, { fontSize: 11, color: COLORS.gray, align: 'center', fit: 'shrink' });
  });
  addText(slide, '验证顺序：原始材料 → 口径来源 → 计算/图表 → 路演结论。结论无法绕过来源。', 1.1, 6.16, 11.15, 0.27, { fontSize: 16, color: COLORS.deep, bold: true, align: 'center' });
  addSource(slide, 'PPT素材包目录结构；PPT素材/新版PPT_口径说明.md');
  addFooter(slide);
  addNotes(slide, '交付物页。强调资料包是可审计材料集合，而不是只提交收益截图。');
}

async function addClosing() {
  const slide = pptx.addSlide();
  slide.background = { color: COLORS.deep };
  addText(slide, 'Rainbow-FinGPT', 0.76, 0.75, 6.0, 0.5, { fontSize: 30, color: COLORS.white, bold: true });
  addText(slide, '让量化投研结论可解释、可追溯、可复现', 0.78, 1.48, 8.5, 0.38, { fontSize: 20, color: COLORS.mint, bold: true });
  const messages = [
    ['不是把大模型直接用于交易', '先把非结构化信息转成可核查证据。'],
    ['不是只展示最好的回测窗口', '同时披露基准、失败案例与未验证边界。'],
    ['不是承诺收益', '用明确的买卖规则、时间协议与风控逻辑支持研究决策。'],
  ];
  messages.forEach((message, i) => {
    const y = 2.43 + i * 1.0;
    addCircle(slide, 0.92, y, 0.48, [COLORS.teal, COLORS.gold, COLORS.coral][i], String(i + 1), COLORS.white, 11);
    addText(slide, message[0], 1.68, y - 0.02, 4.8, 0.22, { fontSize: 15, color: COLORS.white, bold: true });
    addText(slide, message[1], 1.68, y + 0.34, 5.85, 0.19, { fontSize: 10.8, color: COLORS.mint });
  });
  addRoundRect(slide, 8.04, 1.35, 4.45, 4.67, COLORS.white, { transparency: 7, lineTransparency: 100 });
  addText(slide, '欢迎追问三个问题', 8.43, 1.86, 3.68, 0.23, { fontSize: 16, color: COLORS.white, bold: true, align: 'center' });
  const prompts = [
    ['证据从哪来？', '可否回到原文与数据来源？', COLORS.teal],
    ['参数何时锁定？', '测试前是否已固定？', COLORS.gold],
    ['风险何时退出？', '门控条件是否可复核？', COLORS.coral],
  ];
  prompts.forEach((prompt, i) => {
    const y = 2.42 + i * 0.92;
    addCircle(slide, 8.52, y, 0.52, prompt[2], String(i + 1), COLORS.white, 12);
    addText(slide, prompt[0], 9.34, y - 0.01, 2.45, 0.18, { fontSize: 12.2, color: COLORS.white, bold: true });
    addText(slide, prompt[1], 9.34, y + 0.31, 2.44, 0.15, { fontSize: 9.1, color: COLORS.mint });
  });
  addText(slide, '谢谢各位评委老师', 8.45, 5.28, 3.7, 0.28, { fontSize: 19, color: COLORS.white, bold: true, align: 'center' });
  addText(slide, '欢迎围绕证据来源、测试协议和风险边界提问。', 8.45, 5.68, 3.7, 0.2, { fontSize: 10.5, color: COLORS.mint, align: 'center' });
  addText(slide, '华南师范大学阿伯丁数据科学与人工智能学院', 0.78, 6.64, 6.8, 0.17, { fontSize: 9.3, color: COLORS.mint });
  addText(slide, '历史回测与模拟盘不代表未来收益，不构成投资建议。', 8.22, 6.64, 4.0, 0.17, { fontSize: 8.5, color: COLORS.mint, align: 'right' });
  addNotes(slide, '结束页。以可追问的问题替代含有未统一 Brier 数字的校准图，避免在结束页引入未核验指标。');
}

async function main() {
  await addCover();
  await addWhyNow();
  await addArchitecture();
  await addEvidenceFlow();
  await addPricingGate();
  await addTrendGate();
  await addDecisionFlow();
  await addBuySell();
  await addTestProtocol();
  await addParameterBoundary();
  await addStorageResults();
  await addCrossSectorResults();
  await addFailureCase();
  await addScorecard();
  await addLimitations();
  await addCommercialPath();
  await addEvidencePack();
  await addClosing();
  await pptx.writeFile({ fileName: OUTPUT });
  console.log(`Wrote ${OUTPUT}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
