// 📈 量化组合看板 - 数据加载与可视化

document.addEventListener('DOMContentLoaded', () => {
    const state = {
        portfolios: {},
        sentiment: null,
        evolution: null,
        returnsChart: null,
        currentPeriod: 7
    };

    const portfolioConfig = {
        aggressive: { name: '激进成长', color: '#ff2d55' },
        robust: { name: '均衡稳健', color: '#5856d6' },
        defensive: { name: '防御保守', color: '#34c759' },
        tech: { name: '科技主题', color: '#007aff' },
        bluechip: { name: '蓝筹价值', color: '#ff9500' },
        global: { name: '全球配置', color: '#af52de' }
    };

    // 初始化
    init();

    async function init() {
        showLoading();
        await Promise.all([
            loadPortfolios(),
            loadSentiment(),
            loadEvolution()
        ]);
        render();
    }

    function showLoading() {
        document.getElementById('update-time').textContent = '数据加载中...';
    }

    // 加载组合表现数据（优先从 manifest.json 动态加载基础组合与衍生变体）
    async function loadPortfolios() {
        try {
            const manifestRes = await fetch('data/quantitative/manifest.json');
            if (manifestRes.ok) {
                const manifest = await manifestRes.json();
                if (manifest.portfolios && Array.isArray(manifest.portfolios)) {
                    for (const p of manifest.portfolios) {
                        if (p.is_benchmark) continue;
                        const key = p.key;
                        if (!portfolioConfig[key]) {
                            portfolioConfig[key] = {
                                name: p.name,
                                color: p.color || (p.is_variant ? '#f59e0b' : '#3b82f6'),
                                is_variant: !!p.is_variant,
                                parent_strategy: p.parent_strategy || ''
                            };
                        }
                        try {
                            const res = await fetch(`data/quantitative/performance_${key}.json`);
                            if (res.ok) {
                                state.portfolios[key] = await res.json();
                            }
                        } catch (e) {
                            console.warn(`加载 ${key} 失败:`, e);
                        }
                    }
                    return;
                }
            }
        } catch (err) {
            console.info('未找到 manifest.json，回退到默认静态组合列表');
        }

        const portfolioIds = ['aggressive', 'robust', 'defensive', 'tech', 'bluechip', 'global'];
        for (const id of portfolioIds) {
            try {
                const response = await fetch(`data/quantitative/performance_${id}.json`);
                if (!response.ok) continue;
                const data = await response.json();
                state.portfolios[id] = data;
            } catch (error) {
                console.warn(`加载 ${id} 失败:`, error);
            }
        }
    }

    // 加载市场情绪数据
    async function loadSentiment() {
        try {
            const response = await fetch('data/quantitative/latest_sentiment.json');
            if (!response.ok) return;
            state.sentiment = await response.json();
        } catch (error) {
            console.warn('加载市场情绪失败:', error);
        }
    }

    // 加载策略进化数据
    async function loadEvolution() {
        try {
            const response = await fetch('data/quantitative/latest_evolution.json');
            if (!response.ok) return;
            state.evolution = await response.json();
        } catch (error) {
            console.warn('加载策略进化失败:', error);
        }
    }

    // 渲染全部内容
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

        if (dates.length > 0) {
            const latestDate = dates.sort().reverse()[0];
            document.getElementById('update-time').textContent = `数据更新至: ${latestDate}`;
        } else {
            document.getElementById('update-time').textContent = '暂无数据';
        }
    }

    // 渲染市场情绪
    function renderSentiment() {
        if (!state.sentiment) {
            document.getElementById('sentiment-section').style.display = 'none';
            return;
        }

        const s = state.sentiment;
        const sa = (s && s.sentiment_analysis) || {};

        // 日期
        if (s.date) {
            document.getElementById('sentiment-date').textContent = s.date;
        }

        // 情绪（嵌套在 sentiment_analysis 中）
        if (sa.sentiment) {
            document.getElementById('sentiment-mood').textContent = sa.sentiment;
        }

        // 分数（0-10）
        if (typeof sa.sentiment_score === 'number') {
            const score = sa.sentiment_score;
            document.getElementById('sentiment-score-fill').style.width = `${score * 10}%`;
            document.getElementById('sentiment-score-text').textContent = `${score}/10`;
        }

        // 资金流向
        if (sa.capital_flow) {
            document.getElementById('capital-flow').textContent = sa.capital_flow;
        }

        // 热点板块
        if (sa.hot_sectors && Array.isArray(sa.hot_sectors)) {
            document.getElementById('hot-sectors').textContent = sa.hot_sectors.join('、');
        }

        // 推荐组合（trading_advice）
        if (sa.trading_advice) {
            const ta = sa.trading_advice;
            const portfolioName = portfolioConfig[ta.recommended_portfolio]?.name || ta.recommended_portfolio;
            document.getElementById('recommend-portfolio').textContent = portfolioName;
            document.getElementById('recommend-reason').textContent = ta.reasoning || '';

            if (ta.position_suggestion) {
                document.getElementById('recommend-position').textContent = `建议仓位: ${ta.position_suggestion}`;
            }
        }
    }

    // 渲染组合卡片
    function renderPortfolioCards() {
        const grid = document.getElementById('portfolios-grid');
        grid.innerHTML = '';

        Object.keys(portfolioConfig).forEach(id => {
            const data = state.portfolios[id];
            const config = portfolioConfig[id];

            if (!data || !data.history || data.history.length === 0) {
                return;
            }

            const history = data.history;
            const latest = history[history.length - 1];
            const dailyReturn = latest.daily_return || 0;
            const totalReturn = latest.total_return || 0;
            const sharpe = latest.sharpe_ratio || 0;

            const card = document.createElement('div');
            card.className = `portfolio-card ${id}`;

            const returnClass = dailyReturn >= 0 ? 'up' : 'down';
            const returnSign = dailyReturn >= 0 ? '+' : '';

            const variantBadge = config.is_variant ? '<span style="font-size:11px;background:#fef3c7;color:#d97706;padding:2px 6px;border-radius:4px;margin-left:6px;">🔬 衍生实验</span>' : '';
            card.innerHTML = `
                <div class="portfolio-name">${config.name}${variantBadge}</div>
                <div class="portfolio-return ${returnClass}">
                    ${returnSign}${dailyReturn.toFixed(2)}%
                </div>
                <div class="portfolio-stats">
                    <div class="portfolio-stat">
                        <div class="portfolio-stat-label">累计收益</div>
                        <div class="portfolio-stat-value">${totalReturn.toFixed(2)}%</div>
                    </div>
                    <div class="portfolio-stat">
                        <div class="portfolio-stat-label">夏普比率</div>
                        <div class="portfolio-stat-value">${sharpe.toFixed(2)}</div>
                    </div>
                </div>
                <div class="portfolio-holdings">
                    持仓: ${data.holdings ? data.holdings.map(h => h.name || h.code).join('、') : '无'}
                </div>
            `;

            grid.appendChild(card);
        });
    }

    // 渲染收益曲线图
    function renderReturnsChart() {
        const chartDom = document.getElementById('returns-chart');
        if (!chartDom) return;

        if (!state.returnsChart) {
            state.returnsChart = echarts.init(chartDom);
        }

        // 收集所有日期
        const allDates = new Set();
        Object.values(state.portfolios).forEach(portfolio => {
            if (portfolio.history) {
                portfolio.history.forEach(point => allDates.add(point.date));
            }
        });

        let dates = Array.from(allDates).sort();

        // 根据时间段过滤
        if (state.currentPeriod !== 'all' && dates.length > state.currentPeriod) {
            dates = dates.slice(-state.currentPeriod);
        }

        // 构建系列数据
        const series = Object.keys(portfolioConfig).map(id => {
            const data = state.portfolios[id];
            const config = portfolioConfig[id];

            if (!data || !data.history) return null;

            const values = dates.map(date => {
                const point = data.history.find(h => h.date === date);
                return point ? point.total_return : null;
            });

            return {
                name: config.name,
                type: 'line',
                data: values,
                smooth: true,
                symbol: 'circle',
                symbolSize: 6,
                lineStyle: { width: 3 },
                itemStyle: { color: config.color },
                emphasis: {
                    focus: 'series',
                    lineStyle: { width: 5 }
                }
            };
        }).filter(Boolean);

        const option = {
            tooltip: {
                trigger: 'axis',
                backgroundColor: 'rgba(255, 255, 255, 0.95)',
                borderColor: '#e5e7eb',
                borderWidth: 1,
                textStyle: { color: '#1f2937' },
                formatter: function(params) {
                    let html = `<strong>${params[0].axisValue}</strong><br/>`;
                    params.forEach(param => {
                        const value = param.value !== null ? param.value.toFixed(2) + '%' : '--';
                        html += `${param.marker} ${param.seriesName}: ${value}<br/>`;
                    });
                    return html;
                }
            },
            legend: {
                data: Object.values(portfolioConfig).map(c => c.name),
                bottom: 10,
                textStyle: { fontSize: 13, fontWeight: 600 }
            },
            grid: {
                left: 60,
                right: 40,
                top: 40,
                bottom: 80
            },
            xAxis: {
                type: 'category',
                data: dates,
                boundaryGap: false,
                axisLabel: {
                    rotate: 45,
                    fontSize: 12
                }
            },
            yAxis: {
                type: 'value',
                name: '累计收益 (%)',
                axisLabel: {
                    formatter: '{value}%',
                    fontSize: 12
                },
                splitLine: {
                    lineStyle: { type: 'dashed', color: '#e5e7eb' }
                }
            },
            series: series
        };

        state.returnsChart.setOption(option);
    }

    // 渲染策略进化
    function renderEvolution() {
        if (!state.evolution) {
            document.getElementById('evolution-section').style.display = 'none';
            return;
        }

        const evo = state.evolution;
        const content = document.getElementById('evolution-content');

        // 日期
        if (evo.analysis_date) {
            document.getElementById('evolution-date').textContent = `分析日期: ${evo.analysis_date}`;
        }

        let html = '';

        // 冠军信息（嵌套 champion.stats）
        if (evo.champion) {
            const champion = evo.champion;
            const st = champion.stats || {};
            const championName = portfolioConfig[champion.name]?.name || champion.name;

            html += `
                <div class="evolution-champion">
                    <div class="evolution-champion-title">🏆 本周冠军策略</div>
                    <div class="evolution-champion-name">${championName}</div>
                    <div class="evolution-champion-stats">
                        ${st.cumulative_return !== undefined ? `
                            <div class="evolution-stat">
                                <div class="evolution-stat-label">累计收益</div>
                                <div class="evolution-stat-value">${st.cumulative_return.toFixed(2)}%</div>
                            </div>
                        ` : ''}
                        ${st.sharpe !== undefined ? `
                            <div class="evolution-stat">
                                <div class="evolution-stat-label">夏普比率</div>
                                <div class="evolution-stat-value">${st.sharpe.toFixed(2)}</div>
                            </div>
                        ` : ''}
                        ${st.win_rate !== undefined ? `
                            <div class="evolution-stat">
                                <div class="evolution-stat-label">胜率</div>
                                <div class="evolution-stat-value">${st.win_rate.toFixed(1)}%</div>
                            </div>
                        ` : ''}
                        ${st.max_drawdown !== undefined ? `
                            <div class="evolution-stat">
                                <div class="evolution-stat-label">最大回撤</div>
                                <div class="evolution-stat-value">${st.max_drawdown.toFixed(2)}%</div>
                            </div>
                        ` : ''}
                    </div>
                </div>
            `;
        }

        // AI 深度分析（嵌套 champion.analysis.llm_analysis 对象）
        const llm = evo.champion && evo.champion.analysis && evo.champion.analysis.llm_analysis;
        if (llm) {
            const factors = (llm.success_factors || []).map(f => `<li>${f}</li>`).join('');
            const sust = llm.sustainability || {};
            html += `
                <div class="evolution-analysis">
                    <h3>🤖 AI深度分析</h3>
                    ${factors ? `<ul>${factors}</ul>` : ''}
                    ${sust.reasoning ? `<p>可持续性（评分 ${sust.score ?? '--'}）：${sust.reasoning}</p>` : ''}
                </div>
            `;
        }

        // 衍生策略
        if (evo.variants && Array.isArray(evo.variants) && evo.variants.length > 0) {
            html += `
                <div class="evolution-variants">
                    <h3>🧬 衍生策略（下周测试）</h3>
                    <div class="variants-grid">
            `;

            evo.variants.forEach((variant, index) => {
                html += `
                    <div class="variant-card">
                        <div class="variant-name">变体 ${index + 1}: ${variant.name || '未命名'}</div>
                        <div class="variant-description">${variant.description || variant.rationale || '无描述'}</div>
                    </div>
                `;
            });

            html += `
                    </div>
                </div>
            `;
        }

        content.innerHTML = html;
    }

    // 事件监听
    function setupEventListeners() {
        // 时间段切换
        document.querySelectorAll('.period-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.period-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');

                const period = btn.dataset.period;
                state.currentPeriod = period === 'all' ? 'all' : parseInt(period);
                renderReturnsChart();
            });
        });

        // 窗口resize重绘图表
        window.addEventListener('resize', () => {
            if (state.returnsChart) {
                state.returnsChart.resize();
            }
        });
    }
});
