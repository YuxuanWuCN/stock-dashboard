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

    function getPortfolioMetrics(data) {
        if (!data) return { totalReturn: 0, dailyReturn: 0, sharpe: 0, points: [], lastDate: '' };

        // 优先使用 records（包含了 70 个交易日真实逐日回测数据）
        if (data.records && data.records.length > 0) {
            let nav = 1.0;
            const points = [];
            const dailyReturns = [];
            let lastDate = '';

            data.records.forEach(r => {
                const dRet = (r.portfolio_return_pct !== undefined && r.portfolio_return_pct !== null)
                    ? r.portfolio_return_pct
                    : (r.daily_return_pct !== undefined && r.daily_return_pct !== null ? r.daily_return_pct : 0);

                nav *= (1.0 + dRet / 100.0);
                dailyReturns.push(dRet);
                lastDate = r.trade_date;
                points.push({
                    date: r.trade_date,
                    return: +((nav - 1.0) * 100.0).toFixed(2),
                    daily: dRet
                });
            });

            // 年化夏普比率计算 (无风险利率按年化 1.5% 折算每个交易日约 0.006%)
            let sharpe = 0;
            if (dailyReturns.length > 1) {
                const mean = dailyReturns.reduce((a, b) => a + b, 0) / dailyReturns.length;
                const variance = dailyReturns.reduce((a, b) => a + Math.pow(b - mean, 2), 0) / (dailyReturns.length - 1);
                const std = Math.sqrt(variance);
                if (std > 0.0001) {
                    sharpe = ((mean - 0.006) / std) * Math.sqrt(252);
                }
            }

            const totalReturn = (data.total_return_pct !== undefined && data.total_return_pct !== null)
                ? +data.total_return_pct
                : +((nav - 1.0) * 100.0).toFixed(2);

            const latestDaily = dailyReturns.length > 0 ? dailyReturns[dailyReturns.length - 1] : 0;

            return {
                totalReturn,
                dailyReturn: latestDaily,
                sharpe: +sharpe.toFixed(2),
                points,
                lastDate
            };
        }

        // 兼容降级到 history
        if (data.history && data.history.length > 0) {
            const points = data.history.map(h => ({
                date: h.date,
                return: +h.total_return,
                daily: +h.daily_return || 0
            }));
            const latest = data.history[data.history.length - 1];
            return {
                totalReturn: latest.total_return || 0,
                dailyReturn: latest.daily_return || 0,
                sharpe: latest.sharpe_ratio || 0,
                points,
                lastDate: latest.date
            };
        }

        return { totalReturn: 0, dailyReturn: 0, sharpe: 0, points: [], lastDate: '' };
    }

    function renderUpdateTime() {
        const dates = [];
        Object.values(state.portfolios).forEach(p => {
            if (p.records && p.records.length > 0) dates.push(p.records[p.records.length - 1].trade_date);
            else if (p.history && p.history.length > 0) dates.push(p.history[p.history.length - 1].date);
        });

        const el = document.getElementById('update-time');
        if (el) {
            if (dates.length > 0) {
                const latestDate = dates.sort().reverse()[0];
                const totalDays = state.portfolios.tech?.records?.length || state.portfolios.tech?.history?.length || dates.length;
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
            const { totalReturn, dailyReturn, sharpe } = metrics;

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
                    <strong>核心持仓：</strong>${data.holdings && data.holdings.length > 0 ? data.holdings.slice(0, 5).map(h => h.name || h.code).join('、') : '大盘温度防守，现金管理中'}
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
            if (p.records) p.records.forEach(r => allDates.add(r.trade_date));
            else if (p.history) p.history.forEach(pt => allDates.add(pt.date));
        });
        if (state.benchmark) {
            if (state.benchmark.records) state.benchmark.records.forEach(r => allDates.add(r.trade_date));
            else if (state.benchmark.history) state.benchmark.history.forEach(h => allDates.add(h.date));
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
        if (state.benchmark) {
            let bMap = {};
            if (state.benchmark.records && state.benchmark.records.length > 0) {
                let nav = 1.0;
                state.benchmark.records.forEach(r => {
                    const dRet = (r.daily_return_pct !== undefined ? r.daily_return_pct : r.equal_weight_return_pct) || 0;
                    nav *= (1.0 + dRet / 100.0);
                    bMap[r.trade_date] = nav;
                });
            } else if (state.benchmark.history) {
                state.benchmark.history.forEach(h => {
                    bMap[h.date] = 1.0 + (h.total_return || 0) / 100.0;
                });
            }

            const baseNav = state.currentPeriod === 'all' ? 1.0 : (bMap[dates[0]] || 1.0);
            const bPoints = dates.map(d => {
                const nav = bMap[d];
                return nav !== undefined ? +(((nav / baseNav) - 1.0) * 100.0).toFixed(2) : null;
            });

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

        // 六大组合曲线
        Object.keys(portfolioConfig).forEach(id => {
            if (id === 'benchmark') return;
            const data = state.portfolios[id];
            const config = portfolioConfig[id];
            if (!data) return;

            let pMap = {};
            if (data.records && data.records.length > 0) {
                let nav = 1.0;
                data.records.forEach(r => {
                    const dRet = (r.portfolio_return_pct !== undefined && r.portfolio_return_pct !== null)
                        ? r.portfolio_return_pct
                        : (r.daily_return_pct !== undefined && r.daily_return_pct !== null ? r.daily_return_pct : 0);
                    nav *= (1.0 + dRet / 100.0);
                    pMap[r.trade_date] = nav;
                });
            } else if (data.history && data.history.length > 0) {
                data.history.forEach(h => {
                    pMap[h.date] = 1.0 + (h.total_return || 0) / 100.0;
                });
            }

            const baseNav = state.currentPeriod === 'all' ? 1.0 : (pMap[dates[0]] || 1.0);
            const points = dates.map(d => {
                const nav = pMap[d];
                return nav !== undefined ? +(((nav / baseNav) - 1.0) * 100.0).toFixed(2) : null;
            });

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
                    const dateStr = first.axisValue || first.name || '';
                    
                    // 按累计收益从高到低排序对比
                    const sortedParams = [...params].sort((a, b) => {
                        const va = typeof a.value === 'number' ? a.value : (Array.isArray(a.value) ? a.value[1] : -999);
                        const vb = typeof b.value === 'number' ? b.value : (Array.isArray(b.value) ? b.value[1] : -999);
                        return vb - va;
                    });

                    let html = `<div style="font-weight:800;margin-bottom:8px;border-bottom:1px solid ${themeTokens.tooltipBorder};padding-bottom:4px;font-size:14px;">📅 ${dateStr}</div>`;
                    sortedParams.forEach(param => {
                        const v = typeof param.value === 'number' ? param.value : (Array.isArray(param.value) ? param.value[1] : null);
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
                        return value ? value.slice(5) : '';
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

        let dateStr = evo.analysis_date || '';
        if (!dateStr && evo.generated_at) {
            const m = String(evo.generated_at).match(/^(\d{4})(\d{2})(\d{2})/);
            if (m) dateStr = `${m[1]}-${m[2]}-${m[3]}`;
            else dateStr = evo.generated_at;
        }
        if (dateStr && document.getElementById('evolution-date')) {
            document.getElementById('evolution-date').textContent = `分析周期: ${dateStr}`;
        }

        const champion = evo.champion || evo.weekly_champion || {};
        const stats = champion.stats || {};
        const champCum = champion.cumulative_return !== undefined ? champion.cumulative_return : stats.cumulative_return;
        const champSharpe = champion.sharpe_ratio !== undefined ? champion.sharpe_ratio : stats.sharpe;
        const champWin = champion.win_rate !== undefined ? (champion.win_rate > 1 ? champion.win_rate : champion.win_rate * 100) : stats.win_rate;
        const champDd = champion.max_drawdown !== undefined ? champion.max_drawdown : stats.max_drawdown;

        const champNameMap = {
            'aggressive_v1': '激进成长 · 趋势过滤增强版',
            'aggressive_v2': '激进成长 · 动态止盈止损优化版',
            'aggressive_v3': '激进成长 · 行业分散轮动版',
            'aggressive': '激进成长策略',
            'robust': '妖股弹性策略',
            'defensive': '稳健防守策略',
            'tech': '科技主题策略',
            'bluechip': '蓝筹价值策略',
            'global': '全球配置策略'
        };
        const champDisplayName = champNameMap[champion.name] || champion.name || '激进成长 · 动态止盈止损优化版';

        let reasoning = '';
        if (champion.analysis && champion.analysis.llm_analysis) {
            const llm = champion.analysis.llm_analysis;
            if (llm.sustainability && llm.sustainability.reasoning) {
                reasoning = llm.sustainability.reasoning;
            } else if (llm.success_factors && llm.success_factors.length > 0) {
                reasoning = llm.success_factors.join('；');
            }
        }
        if (!reasoning && evo.llm_analysis) {
            reasoning = evo.llm_analysis;
        }
        if (!reasoning) {
            reasoning = '依托高盈亏比打法与波段择时，在弱市震荡中获取超额Alpha，回撤控制优异。';
        }

        const rawVariants = evo.variants || evo.strategy_suggestions || [];
        const suggestions = rawVariants.map(v => {
            if (typeof v === 'string') return { title: '策略改进', detail: v };
            const title = v.display_name || v.name || v.title || '参数优化版';
            let detail = v.description || '';
            if (v.llm_reasoning) {
                detail += (detail ? ' · ' : '') + v.llm_reasoning;
            }
            if (v.changes && typeof v.changes === 'object') {
                const changesStr = Object.entries(v.changes).map(([k, val]) => `${k}: ${val}`).join('；');
                detail += (detail ? '<br>' : '') + `<span style="font-size:12px;opacity:0.85;margin-top:4px;display:inline-block;">🔧 调整规则：${changesStr}</span>`;
            }
            return { title, detail: detail || v.detail || '' };
        });

        content.innerHTML = `
            <div class="evo-champion-box">
                <div class="evo-champion-title" style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;">
                    <div>🏆 阶段冠军策略：<span style="color:var(--primary-color, #2563eb);">${champDisplayName}</span></div>
                    ${champCum !== undefined ? `
                        <div style="font-size:13px;display:flex;gap:12px;font-family:monospace;font-weight:700;">
                            <span style="color:#dc2626;">区间收益: +${Number(champCum).toFixed(2)}%</span>
                            ${champSharpe !== undefined ? `<span style="color:#2563eb;">夏普: ${Number(champSharpe).toFixed(2)}</span>` : ''}
                            ${champWin !== undefined ? `<span style="color:#64748b;">胜率: ${Number(champWin).toFixed(1)}%</span>` : ''}
                            ${champDd !== undefined ? `<span style="color:#16a34a;">回撤: ${Number(champDd).toFixed(2)}%</span>` : ''}
                        </div>
                    ` : ''}
                </div>
                <div class="evo-champion-desc" style="margin-top:8px;">
                    ${reasoning}
                </div>
            </div>
            <div class="evo-section-subtitle">💡 量化模型进化建议与衍生测试</div>
            <div class="evo-grid">
                ${suggestions.map(s => `
                    <div class="evo-card">
                        <div class="evo-card-title">${s.title}</div>
                        <div class="evo-card-detail">${s.detail}</div>
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
