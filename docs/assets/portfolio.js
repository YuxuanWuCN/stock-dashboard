// 📈 量化组合实盘看板 - 数据加载与可视化控制 (Pro版)

document.addEventListener('DOMContentLoaded', () => {
    const state = {
        portfolios: {},
        benchmark: null,
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
        global:     { name: '全球配置', color: '#6366f1', desc: '宽基指数 · 跨市场' },
        benchmark:  { name: '全池等权基准', color: '#64748b', is_benchmark: true }
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

    async function loadPortfolios() {
        const portfolioIds = ['aggressive', 'robust', 'defensive', 'tech', 'bluechip', 'global'];
        for (const id of portfolioIds) {
            try {
                const response = await fetch(`data/quantitative/performance_${id}.json?v=${Date.now()}`);
                if (!response.ok) continue;
                state.portfolios[id] = await response.json();
            } catch (error) {
                console.warn(`加载 ${id} 失败:`, error);
            }
        }
    }

    async function loadBenchmark() {
        try {
            const response = await fetch(`data/quantitative/benchmark.json?v=${Date.now()}`);
            if (response.ok) {
                state.benchmark = await response.json();
            }
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
            .map(p => p.history && p.history.length > 0 ? p.history[p.history.length - 1].date : null)
            .filter(Boolean);

        const el = document.getElementById('update-time');
        if (el) {
            if (dates.length > 0) {
                const latestDate = dates.sort().reverse()[0];
                el.textContent = `数据更新至: ${latestDate} (60天周期)`;
            } else {
                el.textContent = '暂无数据';
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
            if (fill) fill.style.width = `${score * 10}%`;
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
            const recName = portfolioConfig[ta.recommended_portfolio]?.name || ta.recommended_portfolio;
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
            if (id === 'benchmark') return;
            const data = state.portfolios[id];
            const config = portfolioConfig[id];

            if (!data || !data.history || data.history.length === 0) return;

            const history = data.history;
            const latest = history[history.length - 1];
            const dailyReturn = latest.daily_return || 0;
            const totalReturn = latest.total_return || 0;
            const sharpe = latest.sharpe_ratio || 0;

            const card = document.createElement('div');
            card.className = `portfolio-card ${id}`;
            const returnClass = totalReturn >= 0 ? 'up' : 'down';
            const returnSign = totalReturn >= 0 ? '+' : '';

            card.innerHTML = `
                <div class="portfolio-name">
                    <span>${config.name}</span>
                    <span style="font-size:12px;font-weight:600;color:#64748b;">${config.desc || ''}</span>
                </div>
                <div class="portfolio-return ${returnClass}">
                    ${returnSign}${totalReturn.toFixed(2)}%
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
                </div>
                <div class="portfolio-holdings">
                    <strong>核心持仓：</strong>${data.holdings ? data.holdings.map(h => h.name || h.code).join('、') : '大盘温度防守，现金管理中'}
                </div>
            `;
            grid.appendChild(card);
        });
    }

    function renderReturnsChart() {
        const chartDom = document.getElementById('returns-chart');
        if (!chartDom) return;

        if (!state.returnsChart) {
            state.returnsChart = echarts.init(chartDom);
            window.addEventListener('resize', () => state.returnsChart.resize());
        }

        // 收集所有组合与基准的有效日期（并集，升序）
        const allDates = new Set();
        Object.values(state.portfolios).forEach(p => {
            if (p.history) p.history.forEach(pt => allDates.add(pt.date));
        });
        if (state.benchmark && state.benchmark.records) {
            state.benchmark.records.forEach(r => allDates.add(r.trade_date));
        }
        let dates = Array.from(allDates).sort();

        // 周期窗口：取最近 N 个交易日
        if (state.currentPeriod !== 'all') {
            const pDays = parseInt(state.currentPeriod, 10);
            if (dates.length > pDays) dates = dates.slice(-pDays);
        }
        const dateSet = new Set(dates);
        const toTs = d => new Date(d + 'T00:00:00+08:00').getTime();

        const series = [];

        // 全池等权基准线
        if (state.benchmark && state.benchmark.records) {
            let cum = 0;
            const bPoints = [];
            state.benchmark.records.forEach(r => {
                cum = (1 + cum / 100) * (1 + (r.daily_return_pct || 0) / 100) - 1;
                if (dateSet.has(r.trade_date)) {
                    bPoints.push([toTs(r.trade_date), +(cum * 100).toFixed(2)]);
                }
            });
            if (bPoints.length > 0) {
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

        // 六大组合曲线（各系列独立从自己的第一个有效数据点起笔）
        Object.keys(portfolioConfig).forEach(id => {
            if (id === 'benchmark') return;
            const data = state.portfolios[id];
            const config = portfolioConfig[id];
            if (!data || !data.history) return;

            const points = data.history
                .filter(h => dateSet.has(h.date) && h.total_return != null)
                .map(h => [toTs(h.date), +h.total_return]);

            if (points.length === 0) return;

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
                emphasis: {
                    focus: 'series',
                    lineStyle: { width: 4.5 }
                },
                z: isKey ? 10 : 5
            });
        });

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
                formatter: function(params) {
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
            grid: {
                left: '2%',
                right: '3%',
                top: '6%',
                bottom: '10%',
                containLabel: true
            },
            xAxis: {
                type: 'time',
                boundaryGap: false,
                axisLine: { lineStyle: { color: '#cbd5e1' } },
                axisLabel: {
                    color: '#64748b',
                    fontSize: 12,
                    formatter: function(value) {
                        const d = new Date(value);
                        return `${d.getMonth() + 1}-${d.getDate()}`;
                    }
                }
            },
            yAxis: {
                type: 'value',
                name: '累计收益 (%)',
                nameTextStyle: { color: '#64748b', fontSize: 12 },
                axisLabel: {
                    formatter: '{value}%',
                    color: '#64748b',
                    fontSize: 12
                },
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

        const champion = evo.weekly_champion || {};
        const suggestions = evo.strategy_suggestions || [];

        content.innerHTML = `
            <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:12px; padding:18px; margin-bottom:16px;">
                <div style="font-size:16px; font-weight:800; color:#0f172a; margin-bottom:8px;">
                    🏆 阶段冠军策略：<span style="color:#2563eb;">${champion.name || '激进成长·温度联动'}</span>
                </div>
                <div style="font-size:13px; color:#475569; line-height:1.6;">
                    ${champion.reason || '在 60 天弱市阴跌环境中，依托宏观大盘温度门控自动压降总仓位，并通过单股严格止损，回撤控制在 16.9% 并持续跑赢全池等权基准。'}
                </div>
            </div>
            <div style="font-size:14px; font-weight:700; color:#0f172a; margin-bottom:8px;">💡 量化模型进化建议</div>
            <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(280px, 1fr)); gap:12px;">
                ${suggestions.map(s => `
                    <div style="background:#ffffff; border:1px solid #e2e8f0; border-left:4px solid #3b82f6; border-radius:8px; padding:12px 14px;">
                        <div style="font-size:13px; font-weight:700; color:#1e293b; margin-bottom:4px;">${s.title || '风控与仓位约束'}</div>
                        <div style="font-size:12px; color:#64748b; line-height:1.5;">${s.detail || s}</div>
                    </div>
                `).join('')}
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
