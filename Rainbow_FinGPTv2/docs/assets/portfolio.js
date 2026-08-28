// 📈 量化组合实盘看板 - 数据加载与可视化控制 (v2 · 对齐 records 数据 schema)

document.addEventListener('DOMContentLoaded', () => {
    const state = {
        portfolios: {},      // id -> { records, name, navSeries, holdings }
        benchmark: null,     // { records, navSeries }
        sentiment: null,
        evolution: null,
        returnsChart: null,
        currentPeriod: 'all' // 默认展示全部 60 天长跑
    };

    const portfolioConfig = {
        aggressive: { name: '激进成长', color: '#ef4444', desc: '高弹性 · 动量突破' },
        robust:     { name: '妖股弹性', color: '#8b5cf6', desc: '高波动 · 短线择时' },
        defensive:  { name: '稳健防守', color: '#10b981', desc: '低回撤 · 宏观对冲' },
        tech:       { name: '科技主题', color: '#0284c7', desc: '算力/半导体成长' },
        bluechip:   { name: '蓝筹价值', color: '#f59e0b', desc: '核心资产 · 稳健红利' },
        global:     { name: '全球配置', color: '#6366f1', desc: '宽基指数 · 跨市场' }
    };

    // 进化区把英文 key 映射为友好名
    const friendlyName = {
        aggressive: '激进成长', robust: '妖股弹性', defensive: '稳健防守',
        tech: '科技主题', bluechip: '蓝筹价值', global: '全球配置',
        benchmark: '全池等权基准'
    };

    init();

    async function init() {
        showLoading();
        await Promise.all([
            loadPortfolios(),
            loadBenchmark(),
            loadSentiment(),
            loadEvolution()
        ]);
        render();
    }

    function showLoading() {
        const ut = document.getElementById('update-time');
        if (ut) ut.textContent = '数据加载中...';
    }

    // ------------------------------------------------------------------
    // 工具：从 records 序列构建净值曲线与统计
    // ------------------------------------------------------------------
    function buildSeries(records) {
        // records: [{ trade_date, portfolio_return_pct|daily_return_pct, ... }]
        const out = [];
        let nav = 100;
        (records || []).forEach(r => {
            const daily = (r.portfolio_return_pct != null) ? r.portfolio_return_pct : (r.daily_return_pct || 0);
            nav = nav * (1 + daily / 100);
            out.push({
                date: r.trade_date,
                daily: daily,
                nav: nav,
                total: nav - 100   // 累计收益 %
            });
        });
        return out;
    }

    function computeSharpe(series) {
        const rets = series.map(p => p.daily);
        if (rets.length < 2) return 0;
        const mean = rets.reduce((a, b) => a + b, 0) / rets.length;
        const variance = rets.reduce((a, b) => a + (b - mean) * (b - mean), 0) / (rets.length - 1);
        const std = Math.sqrt(variance);
        if (std === 0) return 0;
        return (mean / std) * Math.sqrt(252);
    }

    function computeMaxDrawdown(series) {
        let peak = -Infinity, mdd = 0;
        series.forEach(p => {
            if (p.nav > peak) peak = p.nav;
            const dd = peak > 0 ? (p.nav - peak) / peak : 0;
            if (dd < mdd) mdd = dd;
        });
        return mdd * 100; // 负数 %
    }

    // ------------------------------------------------------------------
    // 数据加载
    // ------------------------------------------------------------------
    async function loadPortfolios() {
        const ids = Object.keys(portfolioConfig);
        for (const id of ids) {
            try {
                const [perfRes, holdRes] = await Promise.all([
                    fetch(`data/quantitative/performance_${id}.json?v=${Date.now()}`),
                    fetch(`data/paper/portfolio_${id}.json?v=${Date.now()}`).catch(() => null)
                ]);
                if (!perfRes.ok) continue;
                const perf = await perfRes.json();
                const records = perf.records || [];
                const series = buildSeries(records);

                let holdings = [];
                if (holdRes && holdRes.ok) {
                    const holdData = await holdRes.json();
                    holdings = (holdData.items || holdData.holdings || []).map(h => h.name || h.code);
                }

                state.portfolios[id] = {
                    name: perf.portfolio_name || portfolioConfig[id].name,
                    records,
                    series,
                    holdings,
                    cashPct: null
                };
            } catch (error) {
                console.warn(`加载 ${id} 失败:`, error);
            }
        }
    }

    async function loadBenchmark() {
        try {
            const response = await fetch(`data/quantitative/benchmark.json?v=${Date.now()}`);
            if (!response.ok) return;
            const data = await response.json();
            const records = data.records || [];
            // 基准使用 daily_return_pct（等权组合日收益）
            const series = buildSeries(records.map(r => ({
                trade_date: r.trade_date,
                portfolio_return_pct: r.daily_return_pct != null ? r.daily_return_pct : (r.equal_weight_return_pct || 0)
            })));
            state.benchmark = { records, series };
        } catch (e) {
            console.warn('加载基准失败:', e);
        }
    }

    async function loadSentiment() {
        try {
            const response = await fetch(`data/quantitative/latest_sentiment.json?v=${Date.now()}`);
            if (response.ok) state.sentiment = await response.json();
        } catch (error) {
            console.warn('加载市场情绪失败:', error);
        }
    }

    async function loadEvolution() {
        try {
            const response = await fetch(`data/quantitative/latest_evolution.json?v=${Date.now()}`);
            if (response.ok) state.evolution = await response.json();
        } catch (error) {
            console.warn('加载策略进化失败:', error);
        }
    }

    // ------------------------------------------------------------------
    // 渲染
    // ------------------------------------------------------------------
    function render() {
        renderUpdateTime();
        renderSentiment();
        renderPortfolioCards();
        renderReturnsChart();
        renderEvolution();
        setupEventListeners();
    }

    function renderUpdateTime() {
        const dates = Object.values(state.portfolios)
            .map(p => p.series.length ? p.series[p.series.length - 1].date : null)
            .filter(Boolean);
        const el = document.getElementById('update-time');
        if (el) {
            if (dates.length) {
                const latestDate = dates.sort().reverse()[0];
                el.textContent = `数据更新至: ${latestDate}（60 天长跑）`;
            } else {
                el.textContent = '暂无数据，每日收盘后自动记录';
            }
        }
    }

    function renderSentiment() {
        const sec = document.getElementById('sentiment-section');
        if (!state.sentiment) {
            if (sec) sec.style.display = 'none';
            return;
        }
        const s = state.sentiment;
        const sa = s.sentiment_analysis || {};

        if (s.date && document.getElementById('sentiment-date')) {
            document.getElementById('sentiment-date').textContent = s.date;
        }
        if (sa.sentiment && document.getElementById('sentiment-mood')) {
            document.getElementById('sentiment-mood').textContent = sa.sentiment;
        }
        if (typeof sa.sentiment_score === 'number') {
            const score = sa.sentiment_score;
            const fill = document.getElementById('sentiment-score-fill');
            const txt = document.getElementById('sentiment-score-text');
            if (fill) fill.style.width = `${Math.max(0, Math.min(100, score * 10))}%`;
            if (txt) txt.textContent = `${score}/10`;
        }
        if (sa.capital_flow && document.getElementById('capital-flow')) {
            document.getElementById('capital-flow').textContent = sa.capital_flow;
        }
        if (sa.hot_sectors && Array.isArray(sa.hot_sectors) && document.getElementById('hot-sectors')) {
            document.getElementById('hot-sectors').textContent = sa.hot_sectors.join('、');
        }
        if (sa.trading_advice) {
            const ta = sa.trading_advice;
            const recName = friendlyName[ta.recommended_portfolio] || ta.recommended_portfolio;
            if (document.getElementById('recommend-portfolio')) document.getElementById('recommend-portfolio').textContent = recName;
            if (document.getElementById('recommend-reason')) document.getElementById('recommend-reason').textContent = ta.reasoning || '';
            if (document.getElementById('recommend-position') && ta.position_suggestion) {
                document.getElementById('recommend-position').textContent = `建议仓位: ${ta.position_suggestion}`;
            }
        }
    }

    function renderPortfolioCards() {
        const grid = document.getElementById('portfolios-grid');
        if (!grid) return;
        grid.innerHTML = '';

        Object.keys(portfolioConfig).forEach(id => {
            const config = portfolioConfig[id];
            const data = state.portfolios[id];
            if (!data || !data.series.length) return;

            const series = data.series;
            const latest = series[series.length - 1];
            const dailyReturn = latest.daily || 0;
            const totalReturn = latest.total || 0;
            const sharpe = computeSharpe(series);
            const mdd = computeMaxDrawdown(series);
            const holdings = data.holdings && data.holdings.length ? data.holdings : null;

            const card = document.createElement('div');
            card.className = `portfolio-card ${id}`;
            const returnClass = totalReturn >= 0 ? 'up' : 'down';
            const returnColor = totalReturn >= 0 ? '#dc2626' : '#16a34a';

            card.innerHTML = `
                <div class="portfolio-name">
                    <span>${config.name}</span>
                    <span style="font-size:12px;font-weight:600;color:#64748b;">${config.desc || ''}</span>
                </div>
                <div class="portfolio-return" style="color:${returnColor}">
                    ${totalReturn >= 0 ? '+' : ''}${totalReturn.toFixed(2)}%
                    <span style="font-size:13px;font-weight:600;color:#64748b;margin-left:4px;">(60天累计)</span>
                </div>
                <div class="portfolio-stats">
                    <div class="portfolio-stat">
                        <div class="portfolio-stat-label">最新单日涨跌</div>
                        <div class="portfolio-stat-value" style="color:${dailyReturn >= 0 ? '#dc2626' : '#16a34a'}">
                            ${dailyReturn >= 0 ? '+' : ''}${dailyReturn.toFixed(2)}%
                        </div>
                    </div>
                    <div class="portfolio-stat">
                        <div class="portfolio-stat-label">年化夏普比率</div>
                        <div class="portfolio-stat-value">${sharpe.toFixed(2)}</div>
                    </div>
                    <div class="portfolio-stat">
                        <div class="portfolio-stat-label">最大回撤</div>
                        <div class="portfolio-stat-value" style="color:#16a34a">${mdd.toFixed(2)}%</div>
                    </div>
                    <div class="portfolio-stat">
                        <div class="portfolio-stat-label">累计净值</div>
                        <div class="portfolio-stat-value">${latest.nav.toFixed(2)}</div>
                    </div>
                </div>
                <div class="portfolio-holdings">
                    <strong>核心持仓：</strong>${holdings ? holdings.slice(0, 10).join('、') : '大盘温度防守，现金管理中'}
                </div>
            `;
            grid.appendChild(card);
        });
    }

    function renderReturnsChart() {
        const chartDom = document.getElementById('returns-chart');
        if (!chartDom) return;

        if (typeof echarts === 'undefined') {
            chartDom.innerHTML = '<div style="padding:40px;color:#94a3b8;text-align:center;">图表库加载失败，请检查网络后刷新</div>';
            return;
        }

        if (!state.returnsChart) {
            state.returnsChart = echarts.init(chartDom);
            window.addEventListener('resize', () => state.returnsChart && state.returnsChart.resize());
        }

        // 收集所有组合与基准的有效日期（并集，升序）
        const allDates = new Set();
        Object.values(state.portfolios).forEach(p => p.series.forEach(pt => allDates.add(pt.date)));
        if (state.benchmark) state.benchmark.series.forEach(pt => allDates.add(pt.date));
        let dates = Array.from(allDates).sort();

        if (state.currentPeriod !== 'all') {
            const pDays = parseInt(state.currentPeriod, 10);
            if (dates.length > pDays) dates = dates.slice(-pDays);
        }
        const dateSet = new Set(dates);
        const toTs = d => new Date(d + 'T00:00:00+08:00').getTime();

        const series = [];

        // 全池等权基准线（虚线）
        if (state.benchmark) {
            const bPoints = state.benchmark.series
                .filter(pt => dateSet.has(pt.date))
                .map(pt => [toTs(pt.date), +pt.total.toFixed(2)]);
            if (bPoints.length) {
                series.push({
                    name: '全池等权基准',
                    type: 'line',
                    data: bPoints,
                    smooth: true,
                    showSymbol: false,
                    connectNulls: true,
                    lineStyle: { width: 2, type: 'dashed', color: '#94a3b8' },
                    itemStyle: { color: '#94a3b8' },
                    z: 2
                });
            }
        }

        // 六大组合曲线
        Object.keys(portfolioConfig).forEach(id => {
            const config = portfolioConfig[id];
            const data = state.portfolios[id];
            if (!data || !data.series.length) return;

            const points = data.series
                .filter(pt => dateSet.has(pt.date))
                .map(pt => [toTs(pt.date), +pt.total.toFixed(2)]);
            if (!points.length) return;

            const isKey = id === 'aggressive' || id === 'robust';
            series.push({
                name: config.name,
                type: 'line',
                data: points,
                smooth: true,
                showSymbol: false,
                connectNulls: true,
                lineStyle: { width: isKey ? 3.5 : 2.5, color: config.color },
                itemStyle: { color: config.color },
                emphasis: { focus: 'series', lineStyle: { width: 4.5 } },
                z: isKey ? 10 : 5
            });
        });

        if (!series.length) {
            chartDom.innerHTML = '<div style="padding:40px;color:#94a3b8;text-align:center;">暂无曲线数据</div>';
            return;
        }

        function fmtDate(ts) {
            const d = new Date(ts);
            const mm = String(d.getMonth() + 1).padStart(2, '0');
            const dd = String(d.getDate()).padStart(2, '0');
            return `${d.getFullYear()}-${mm}-${dd}`;
        }

        const option = {
            tooltip: {
                trigger: 'axis',
                backgroundColor: 'rgba(255, 255, 255, 0.96)',
                borderColor: '#e2e8f0',
                borderWidth: 1,
                padding: [12, 16],
                textStyle: { color: '#0f172a', fontSize: 13 },
                formatter: function (params) {
                    if (!params || !params.length) return '';
                    const first = params[0];
                    const tsVal = Array.isArray(first.value) ? first.value[0] : first.axisValue;
                    const dateStr = fmtDate(tsVal);
                    let html = `<div style="font-weight:800;margin-bottom:6px;border-bottom:1px solid #f1f5f9;padding-bottom:4px;">📅 ${dateStr}</div>`;
                    params.forEach(param => {
                        const v = Array.isArray(param.value) ? param.value[1] : param.value;
                        const valStr = (v !== null && v !== undefined)
                            ? ((v > 0 ? '+' : '') + Number(v).toFixed(2) + '%')
                            : '--';
                        const isMain = param.seriesName.includes('激进') || param.seriesName.includes('妖股');
                        html += `<div style="display:flex;justify-content:space-between;gap:15px;line-height:1.6;${isMain ? 'font-weight:700;' : ''}">
                            <span>${param.marker} ${param.seriesName}</span>
                            <span style="font-family:monospace;font-weight:800;">${valStr}</span>
                        </div>`;
                    });
                    return html;
                }
            },
            legend: {
                data: series.map(s => s.name),
                bottom: 0,
                textStyle: { fontSize: 13, fontWeight: 700, color: '#334155' }
            },
            grid: { left: '2%', right: '3%', top: '6%', bottom: '12%', containLabel: true },
            xAxis: {
                type: 'time',
                boundaryGap: false,
                axisLine: { lineStyle: { color: '#cbd5e1' } },
                axisLabel: {
                    color: '#64748b', fontSize: 12,
                    formatter: function (value) {
                        const d = new Date(value);
                        return `${d.getMonth() + 1}-${d.getDate()}`;
                    }
                }
            },
            yAxis: {
                type: 'value',
                name: '累计收益 (%)',
                nameTextStyle: { color: '#64748b', fontSize: 12 },
                axisLabel: { formatter: '{value}%', color: '#64748b', fontSize: 12 },
                splitLine: { lineStyle: { type: 'dashed', color: '#f1f5f9' } }
            },
            series: series
        };

        state.returnsChart.setOption(option, true);
    }

    function renderEvolution() {
        const sec = document.getElementById('evolution-section');
        if (!state.evolution) {
            if (sec) sec.style.display = 'none';
            return;
        }
        const evo = state.evolution;
        const content = document.getElementById('evolution-content');
        if (!content) return;

        if (evo.analysis_date && document.getElementById('evolution-date')) {
            document.getElementById('evolution-date').textContent = `分析日期: ${evo.analysis_date}`;
        }

        const champion = evo.champion || {};
        const champStats = champion.stats || {};
        const champName = friendlyName[champion.name] || champion.name || '—';

        // 组合横向对比表
        const all = evo.all_strategies || {};
        const variants = evo.variants || {};
        const rows = [];
        Object.keys(all).forEach(k => {
            const st = all[k] || {};
            rows.push({ key: k, name: friendlyName[k] || k, cum: st.cumulative_return, sharpe: st.sharpe, win: st.win_rate, isVariant: false });
        });
        Object.keys(variants).forEach(k => {
            const st = variants[k] || {};
            rows.push({ key: k, name: k, cum: st.cumulative_return, sharpe: st.sharpe, win: st.win_rate, isVariant: true });
        });
        rows.sort((a, b) => (b.cum || 0) - (a.cum || 0));

        const fmtNum = v => (v == null || isNaN(v)) ? '--' : Number(v).toFixed(2);

        content.innerHTML = `
            <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:12px; padding:18px; margin-bottom:16px;">
                <div style="font-size:16px; font-weight:800; color:#0f172a; margin-bottom:8px;">
                    🏆 阶段冠军策略：<span style="color:#2563eb;">${champName}</span>
                </div>
                <div style="font-size:13px; color:#475569; line-height:1.6;">
                    累计收益 <strong>${fmtNum(champStats.cumulative_return)}%</strong> ·
                    年化夏普 <strong>${fmtNum(champStats.sharpe)}</strong> ·
                    胜率 <strong>${fmtNum(champStats.win_rate)}%</strong> ·
                    最大回撤 <strong>${fmtNum(champStats.max_drawdown)}%</strong> ·
                    ${champStats.trading_days || '--'} 个交易日
                </div>
            </div>
            <div style="font-size:14px; font-weight:700; color:#0f172a; margin-bottom:8px;">💡 全策略与变体横向对比（按累计收益排序）</div>
            <div style="overflow-x:auto; border:1px solid #e2e8f0; border-radius:8px; background:#fff;">
                <table style="width:100%; border-collapse:collapse; font-size:13px; min-width:520px;">
                    <thead>
                        <tr style="background:#f1f5f9; color:#1e293b;">
                            <th style="padding:10px 14px; text-align:left;">组合 / 变体</th>
                            <th style="padding:10px 14px; text-align:right;">累计收益</th>
                            <th style="padding:10px 14px; text-align:right;">夏普</th>
                            <th style="padding:10px 14px; text-align:right;">胜率</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${rows.map(r => `
                            <tr style="border-top:1px solid #f1f5f9;">
                                <td style="padding:9px 14px; text-align:left; font-weight:${r.isVariant ? '500' : '700'}; color:${r.isVariant ? '#64748b' : '#0f172a'};">
                                    ${r.name}${r.key === champion.name ? ' 🏆' : ''}${r.isVariant ? ' <span style="font-size:11px;color:#94a3b8;">(变体)</span>' : ''}
                                </td>
                                <td style="padding:9px 14px; text-align:right; font-family:monospace; color:${(r.cum || 0) >= 0 ? '#dc2626' : '#16a34a'}; font-weight:700;">${fmtNum(r.cum)}%</td>
                                <td style="padding:9px 14px; text-align:right; font-family:monospace;">${fmtNum(r.sharpe)}</td>
                                <td style="padding:9px 14px; text-align:right; font-family:monospace;">${fmtNum(r.win)}%</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        `;
    }

    function setupEventListeners() {
        document.querySelectorAll('.period-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.period-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                state.currentPeriod = btn.dataset.period;
                renderReturnsChart();
            });
        });
    }
});
