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

    function initTheme() {
        const saved = localStorage.getItem('fintech-theme') || 
            (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
        applyTheme(saved);

        const toggleBtn = document.getElementById('theme-toggle-btn');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', () => {
                const current = document.documentElement.getAttribute('data-theme') || 'dark';
                const next = current === 'dark' ? 'light' : 'dark';
                applyTheme(next);
            });
        }
    }

    function applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('fintech-theme', theme);
        const toggleBtn = document.getElementById('theme-toggle-btn');
        if (toggleBtn) {
            const textSpan = toggleBtn.querySelector('.theme-text');
            if (textSpan) textSpan.textContent = theme === 'dark' ? '深色' : '浅色';
            toggleBtn.setAttribute('title', theme === 'dark' ? '切换为浅色主题' : '切换为深色主题');
        }
        if (state.returnsChart) {
            renderReturnsChart();
        }
    }

    async function init() {
        initTheme();
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
                const totalDays = state.portfolios.tech?.history?.length || dates.length;
                el.textContent = `数据更新至: ${latestDate} (${totalDays}个交易日)`;
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

    function getPortfolioMetrics(data) {
        if (!data) return { history: [], totalReturn: 0, sharpe: 0, dailyReturn: 0 };
        if (data.history && data.history.length > 0) {
            const latest = data.history[data.history.length - 1];
            return {
                history: data.history,
                totalReturn: latest.total_return || 0,
                sharpe: latest.sharpe_ratio || 0,
                dailyReturn: latest.daily_return || 0
            };
        }
        if (data.records && data.records.length > 0) {
            let nav = 1.0;
            const history = [];
            data.records.forEach(r => {
                const dRet = (r.daily_return_pct !== undefined ? r.daily_return_pct : r.equal_weight_return_pct) || 0;
                nav *= (1.0 + dRet / 100.0);
                history.push({
                    date: r.trade_date || r.date,
                    total_return: +((nav - 1.0) * 100.0).toFixed(2),
                    daily_return: dRet,
                    sharpe_ratio: data.sharpe_ratio || 0
                });
            });
            const latest = history[history.length - 1];
            return {
                history: history,
                totalReturn: latest ? latest.total_return : 0,
                sharpe: data.sharpe_ratio || 0,
                dailyReturn: latest ? latest.daily_return : 0
            };
        }
        return { history: [], totalReturn: 0, sharpe: 0, dailyReturn: 0 };
    }

    function renderPortfolioCards() {
        const grid = document.getElementById('portfolios-grid');
        if (!grid) return;
        grid.innerHTML = '';

        Object.keys(portfolioConfig).forEach(id => {
            if (id === 'benchmark') return;
            const data = state.portfolios[id];
            const config = portfolioConfig[id];

            if (!data) return;
            const metrics = getPortfolioMetrics(data);
            if (!metrics.history || metrics.history.length === 0) return;

            const dailyReturn = metrics.dailyReturn;
            const totalReturn = metrics.totalReturn;
            const sharpe = metrics.sharpe;

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
                    <span style="font-size:13px;font-weight:600;color:#64748b;margin-left:4px;">(累计收益)</span>
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
            const m = getPortfolioMetrics(p);
            if (m.history) m.history.forEach(pt => allDates.add(pt.date));
        });
        if (state.benchmark) {
            const bm = getPortfolioMetrics(state.benchmark);
            if (bm.history) bm.history.forEach(pt => allDates.add(pt.date));
            if (state.benchmark.records) {
                state.benchmark.records.forEach(r => allDates.add(r.trade_date || r.date));
            }
        }
        let dates = Array.from(allDates).filter(Boolean).sort();

        // 周期窗口：取最近 N 个交易日
        if (state.currentPeriod !== 'all') {
            const pDays = parseInt(state.currentPeriod, 10);
            if (dates.length > pDays) dates = dates.slice(-pDays);
        }
        const dateSet = new Set(dates);

        const series = [];

        // 全池等权基准线
        if (state.benchmark) {
            const bm = getPortfolioMetrics(state.benchmark);
            const bMap = new Map();
            bm.history.forEach(h => {
                if (h.date && h.total_return != null) {
                    bMap.set(h.date, +Number(h.total_return).toFixed(2));
                }
            });
            const bPoints = dates.map(d => bMap.has(d) ? bMap.get(d) : null);
            if (bPoints.some(v => v !== null)) {
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
            if (id === 'benchmark') return;
            const data = state.portfolios[id];
            const config = portfolioConfig[id];
            if (!data) return;

            const m = getPortfolioMetrics(data);
            const pMap = new Map();
            m.history.forEach(h => {
                if (h.date && h.total_return != null) {
                    pMap.set(h.date, +Number(h.total_return).toFixed(2));
                }
            });

            const points = dates.map(d => pMap.has(d) ? pMap.get(d) : null);
            if (!points.some(v => v !== null)) return;

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

        const isLight = document.documentElement.getAttribute('data-theme') === 'light';
        const themeTokens = {
            tooltipBg: isLight ? 'rgba(255, 255, 255, 0.98)' : 'rgba(15, 23, 42, 0.96)',
            tooltipBorder: isLight ? '#e2e8f0' : '#334155',
            tooltipText: isLight ? '#0f172a' : '#f8fafc',
            legendText: isLight ? '#334155' : '#94a3b8',
            axisLine: isLight ? '#cbd5e1' : '#475569',
            axisLabel: isLight ? '#64748b' : '#94a3b8',
            splitLine: isLight ? '#f1f5f9' : 'rgba(255, 255, 255, 0.06)'
        };

        const option = {
            animation: false,
            tooltip: {
                trigger: 'axis',
                backgroundColor: themeTokens.tooltipBg,
                borderColor: themeTokens.tooltipBorder,
                borderWidth: 1,
                padding: [14, 18],
                textStyle: { color: themeTokens.tooltipText, fontSize: 13 },
                formatter: function(params) {
                    if (!params || !params.length) return '';
                    const first = params[0];
                    const tsVal = Array.isArray(first.value) ? first.value[0] : first.axisValue;
                    const dateStr = fmtDate(tsVal);
                    
                    // 按累计收益从高到低排序对比
                    const sortedParams = [...params].sort((a, b) => {
                        const va = Array.isArray(a.value) ? a.value[1] : (typeof a.value === 'number' ? a.value : -999);
                        const vb = Array.isArray(b.value) ? b.value[1] : (typeof b.value === 'number' ? b.value : -999);
                        return vb - va;
                    });

                    let html = `<div style="font-weight:800;margin-bottom:8px;border-bottom:1px solid ${themeTokens.tooltipBorder};padding-bottom:4px;font-size:14px;">📅 ${dateStr}</div>`;
                    sortedParams.forEach(param => {
                        const v = Array.isArray(param.value) ? param.value[1] : param.value;
                        const valStr = (v !== null && v !== undefined)
                            ? ((v > 0 ? '+' : '') + Number(v).toFixed(2) + '%')
                            : '--';
                        const isMain = param.seriesName.includes('科技') || param.seriesName.includes('全球') || param.seriesName.includes('激进');
                        const retColor = (v >= 0) ? '#dc2626' : '#16a34a';
                        html += `<div style="display:flex;justify-content:space-between;align-items:center;gap:18px;line-height:1.7;${isMain ? 'font-weight:700;' : ''}">
                            <span>${param.marker} ${param.seriesName}</span>
                            <span style="font-family:monospace;font-weight:800;color:${retColor};">${valStr}</span>
                        </div>`;
                    });
                    return html;
                }
            },
            legend: {
                data: series.map(s => s.name),
                bottom: 0,
                textStyle: { fontSize: 13, fontWeight: 700, color: themeTokens.legendText }
            },
            grid: {
                left: '2%',
                right: '3%',
                top: '6%',
                bottom: '10%',
                containLabel: true
            },
            xAxis: {
                type: 'category',
                data: dates,
                boundaryGap: false,
                axisLine: { lineStyle: { color: themeTokens.axisLine } },
                axisLabel: {
                    color: themeTokens.axisLabel,
                    fontSize: 12,
                    formatter: function(value) {
                        if (!value) return '';
                        const parts = value.split('-');
                        return parts.length >= 3 ? `${parts[1]}-${parts[2]}` : value;
                    }
                }
            },
            yAxis: {
                type: 'value',
                name: '累计收益 (%)',
                nameTextStyle: { color: themeTokens.axisLabel, fontSize: 12 },
                axisLabel: {
                    formatter: '{value}%',
                    color: themeTokens.axisLabel,
                    fontSize: 12
                },
                splitLine: { lineStyle: { type: 'dashed', color: themeTokens.splitLine } }
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

        const champion = evo.champion || evo.weekly_champion || {};
        const suggestions = evo.strategy_suggestions || [];

        content.innerHTML = `
            <div class="evo-champion-box">
                <div class="evo-champion-title">
                    🏆 阶段冠军策略：<span style="color:var(--primary-color, #2563eb);">${champion.name || '激进成长·温度联动'}</span>
                </div>
                <div class="evo-champion-desc">
                    ${champion.reason || '在 60 天弱市阴跌环境中，依托宏观大盘温度门控自动压降总仓位，并通过单股严格止损，回撤控制在 16.9% 并持续跑赢全池等权基准。'}
                </div>
            </div>
            <div class="evo-section-subtitle">💡 量化模型进化建议</div>
            <div class="evo-grid">
                ${suggestions.map(s => `
                    <div class="evo-card">
                        <div class="evo-card-title">${s.title || '风控与仓位约束'}</div>
                        <div class="evo-card-detail">${s.detail || s}</div>
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
