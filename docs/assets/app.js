// 🏠 股票研究看板 2.5 - 前端交互与 Toast/ResizeObserver 核心逻辑 (docs/assets/app.js)

// 全局 Toast 提示组件 API
window.showToast = function(message, type = 'info', duration = 3000) {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    const iconMap = {
        success: '✓',
        warning: '⚠',
        error: '✕',
        info: 'ℹ'
    };
    toast.innerHTML = `<span style="font-weight:bold;margin-right:6px;">${iconMap[type] || 'ℹ'}</span><span>${message}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
        toast.classList.add('toast-fadeOut');
        setTimeout(() => toast.remove(), 300);
    }, duration);
};

// ECharts ResizeObserver 自适应尺寸绑定
window.bindChartResize = function(chartInstance, containerElem) {
    if (!chartInstance || !containerElem) return;
    if (window.ResizeObserver) {
        const ro = new ResizeObserver(() => {
            chartInstance.resize();
        });
        ro.observe(containerElem);
    } else {
        window.addEventListener('resize', () => chartInstance.resize());
    }
};

document.addEventListener('DOMContentLoaded', () => {
    // 全局状态管理
    const state = {
        meta: null,
        summary: null,
        selectedCode: null,
        chart: null,
        indexChart: null,
        queryActive: false,
        ranking: null,
        rankingEngine: 'v3',
        rankingV2: null,
        rankingV3: null,
        rankingMode: 'balanced',
        rankingSortKey: 'risk_adjusted_score',
        rankingSortDirection: 'desc',
        analysisSelectedCode: null,
        analysisCache: {},
        watchlist: [],
        lastQueryStock: null,
        // v2.5 策略数据
        selection: null,
        huntingGround: null,
        marketTemperature: null,
        // v2.10 明日重点关注
        dailyBrief: null,
        // v2.11 自选股分区筛选
        watchlistRegion: 'all',
        // v2.12 自选股搜索
        watchlistSearch: '',
        // 当前选中的股票切片数据，供 tooltip 使用
        activeData: {
            dates: [],
            kline: [],
            volume: [],
            ma5: [],
            ma10: [],
            ma20: [],
            ma60: []
        }
    };

    const isLocal = window.location.hostname === '127.0.0.1'
        || window.location.hostname === 'localhost';
    const DATA_VERSION = '2';
    function dataUrl(path) {
        return path + (path.indexOf('?') === -1 ? '?v=' + DATA_VERSION : '&v=' + DATA_VERSION);
    }

    const API_BASE = isLocal
        ? 'http://127.0.0.1:5000'
        : 'https://yuxuanwucn-stock-dashboard-api.onrender.com';
    const BROWSER_WATCHLIST_KEY = 'stock-dashboard-browser-watchlist-v1';

    // DOM 元素缓存
    const el = {
        statusBar: document.getElementById('status-bar'),
        statusText: document.getElementById('status-text'),
        // v2.5 市场温度与今日可买
        marketTempBar: document.getElementById('market-temp-bar'),
        marketTempValue: document.getElementById('market-temp-value'),
        marketTempStatus: document.getElementById('market-temp-status'),
        marketTempFill: document.getElementById('market-temp-fill'),
        marketTempRatio: document.getElementById('market-temp-ratio'),
        buyTodaySection: document.getElementById('buy-today-section'),
        buyTodayList: document.getElementById('buy-today-list'),
        // v3.0 首页全榜单 Top 3 精选矩阵
        top3MatrixSection: document.getElementById('top3-matrix-section'),
        top3MatrixGrid: document.getElementById('top3-matrix-grid'),
        // v2.10 明日重点关注
        dailyBriefSection: document.getElementById('daily-brief-section'),
        dailyBriefTitle: document.getElementById('daily-brief-title'),
        dailyBriefMeta: document.getElementById('daily-brief-meta'),
        dailyBriefSummary: document.getElementById('daily-brief-summary'),
        dailyBriefFocus: document.getElementById('daily-brief-focus'),
        dailyBriefPosition: document.getElementById('daily-brief-position'),
        dailyBriefDisclaimer: document.getElementById('daily-brief-disclaimer'),
        // 模拟盘对比
        paperMeta: document.getElementById('paper-meta'),
        paperCards: document.getElementById('paper-cards'),
        paperCurve: document.getElementById('paper-curve'),
        paperCompareTbody: document.getElementById('paper-compare-tbody'),
        paperCompareWrap: document.getElementById('paper-compare-wrap'),
        stockList: document.getElementById('stock-list'),
        watchlistFilter: document.getElementById('watchlist-filter'),
        watchlistSearchInput: document.getElementById('watchlist-search-input'),
        watchlistSearchClear: document.getElementById('watchlist-search-clear'),
        detailHeader: document.getElementById('detail-header'),
        detailName: document.getElementById('detail-name'),
        detailCode: document.getElementById('detail-code'),
        detailTypeBadge: document.getElementById('detail-type-badge'),
        detailPrice: document.getElementById('detail-price'),
        detailChange: document.getElementById('detail-change'),
        detailDateLabel: document.getElementById('detail-date-label'),
        chartOverlay: document.getElementById('chart-overlay'),
        chartElement: document.getElementById('kline-chart'),
        // 查询相关
        queryCodeInput: document.getElementById('query-code-input'),
        queryDateInput: document.getElementById('query-date-input'),
        queryGoBtn: document.getElementById('query-go-btn'),
        queryHint: document.getElementById('query-hint'),
        queryResultHeader: document.getElementById('query-result-header'),
        queryStockName: document.getElementById('query-stock-name'),
        queryStockCode: document.getElementById('query-stock-code'),
        queryResultHint: document.getElementById('query-result-hint'),
        addToWatchlistBtn: document.getElementById('add-to-watchlist-btn'),
        indexChartCard: document.getElementById('index-chart-card'),
        indexChartElement: document.getElementById('index-chart'),
        indexChartLabel: document.getElementById('index-chart-label'),
        rankingMeta: document.getElementById('ranking-meta'),
        rankingState: document.getElementById('ranking-state'),
        rankingTableWrap: document.getElementById('ranking-table-wrap'),
        rankingTbody: document.getElementById('ranking-tbody'),
        rankingMobileList: document.getElementById('ranking-mobile-list'),
        rankingSearch: document.getElementById('ranking-search'),
        rankingIndustryFilter: document.getElementById('ranking-industry-filter'),
        analysisDetail: document.getElementById('analysis-detail'),
        analysisObservation: document.getElementById('analysis-observation'),
        analysisObservationStatus: document.getElementById('analysis-observation-status'),
        analysisObservationReason: document.getElementById('analysis-observation-reason'),
        analysisSummary: document.getElementById('analysis-summary'),
        analysisRiskBadge: document.getElementById('analysis-risk-badge'),
        analysisCompositeScore: document.getElementById('analysis-composite-score'),
        analysisRiskScore: document.getElementById('analysis-risk-score'),
        analysisReturn3d: document.getElementById('analysis-return-3d'),
        analysisReturn5d: document.getElementById('analysis-return-5d'),
        analysisUpProbability: document.getElementById('analysis-up-probability'),
        analysisReasons: document.getElementById('analysis-reasons'),
        analysisMarketMetrics: document.getElementById('analysis-market-metrics'),
        similarityConfidence: document.getElementById('similarity-confidence'),
        similarityGrid: document.getElementById('similarity-grid'),
        analysisDisclaimer: document.getElementById('analysis-disclaimer'),
        fundamentalSection: document.getElementById('fundamental-section'),
        fundamentalReportDate: document.getElementById('fundamental-report-date'),
        fundamentalScoreBadge: document.getElementById('fundamental-score-badge'),
        fundamentalDimensions: document.getElementById('fundamental-dimensions'),
        fundamentalMetrics: document.getElementById('fundamental-metrics'),
        fundamentalPositiveView: document.getElementById('fundamental-positive-view'),
        fundamentalNegativeView: document.getElementById('fundamental-negative-view'),
        // AI 研究报告
        reportSection: document.getElementById('report-section'),
        reportMeta: document.getElementById('report-meta'),
        reportConfidence: document.getElementById('report-confidence'),
        reportStatus: document.getElementById('report-status'),
        reportElder: document.getElementById('report-elder'),
        reportSections: document.getElementById('report-sections'),
        reportCitations: document.getElementById('report-citations'),
        reportCitationList: document.getElementById('report-citation-list'),
        reportDisclaimer: document.getElementById('report-disclaimer'),
    };

    // ============================================================
    // v2.6 页面导航：今日关注 / 自选股 / 排行榜 / 单股查询 / 个股研究
    // ============================================================
    const PAGE_IDS = ['today', 'watchlist', 'ranking', 'query', 'detail', 'paper'];

    function currentPageFromHash() {
        const m = (window.location.hash || '').match(/^#\/([a-z]+)/);
        return m && PAGE_IDS.indexOf(m[1]) !== -1 ? m[1] : 'today';
    }

    function navigateTo(page) {
        if (PAGE_IDS.indexOf(page) === -1) page = 'today';
        PAGE_IDS.forEach(function (id) {
            const section = document.getElementById('page-' + id);
            if (section) section.hidden = (id !== page);
        });
        document.querySelectorAll('[data-page]').forEach(function (btn) {
            btn.classList.toggle('active', btn.getAttribute('data-page') === page);
        });
        // 进入个股研究页时重绘图表（页面从隐藏变为可见）
        if (page === 'detail') {
            setTimeout(function () {
                if (state.chart) state.chart.resize();
                if (state.indexChart) state.indexChart.resize();
            }, 60);
        }
        const hash = '#/' + page;
        if (window.location.hash !== hash) {
            try { window.location.hash = hash; } catch (e) { /* ignore */ }
        }
    }

    document.querySelectorAll('[data-page]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            navigateTo(btn.getAttribute('data-page'));
        });
    });

    window.addEventListener('hashchange', function () {
        navigateTo(currentPageFromHash());
    });

    // 初始页面：默认今日关注（支持 #/watchlist 等直达链接）
    navigateTo(currentPageFromHash());

    // v2.6.1：给外部 API 调用加超时，避免 Render 冷启动/无响应导致页面卡住
    function fetchWithTimeout(url, options, timeoutMs) {
        var controller = new AbortController();
        var timer = setTimeout(function () { controller.abort(); }, timeoutMs || 10000);
        return fetch(url, Object.assign({}, options || {}, { signal: controller.signal }))
            .finally(function () { clearTimeout(timer); });
    }

    function readBrowserWatchlist() {
        try {
            var parsed = JSON.parse(localStorage.getItem(BROWSER_WATCHLIST_KEY) || '[]');
            return Array.isArray(parsed) ? parsed : [];
        } catch (error) {
            console.warn('读取浏览器自选股失败:', error);
            return [];
        }
    }

    function saveBrowserWatchlist(items) {
        try {
            localStorage.setItem(BROWSER_WATCHLIST_KEY, JSON.stringify(items));
        } catch (error) {
            console.warn('保存浏览器自选股失败:', error);
        }
    }

    function combineWatchlists() {
        var byCode = {};
        Array.prototype.slice.call(arguments).forEach(function (items) {
            if (!Array.isArray(items)) return;
            items.forEach(function (item) {
                if (!item || !item.code) return;
        if (!/^\d{6}$/.test(item.code) && !(item.type === 'us' && /^[A-Za-z]{1,6}$/.test(item.code))) return;
                byCode[item.code] = Object.assign({}, byCode[item.code] || {}, item);
            });
        });
        return Object.keys(byCode).map(function (code) { return byCode[code]; });
    }

    function mergeWatchlistIntoSummary() {
        if (!state.summary) state.summary = {items: []};
        if (!Array.isArray(state.summary.items)) state.summary.items = [];

        state.watchlist.forEach(function (item) {
            var existing = state.summary.items.find(function (summaryItem) {
                return summaryItem.code === item.code;
            });
            if (existing) {
                existing.name = (item.name && item.name !== item.code)
                    ? item.name
                    : (existing.name || item.name);
                existing.type = item.type || existing.type;
                existing.category = item.category || existing.category || '';
                return;
            }
            state.summary.items.push({
                code: item.code,
                name: item.name || item.code,
                type: item.type || 'stock',
                category: item.category || '',
                last_close: null,
                change_pct: null,
                change_amt: null,
                last_date: null,
                status: 'pending',
                dynamic_only: true,
                storage: item.storage || 'server'
            });
        });
    }

    function buildSummaryFromQuery(item, stockData) {
        var dates = stockData && Array.isArray(stockData.dates) ? stockData.dates : [];
        var kline = stockData && Array.isArray(stockData.kline) ? stockData.kline : [];
        var lastCandle = kline.length ? kline[kline.length - 1] : null;
        var previousCandle = kline.length > 1 ? kline[kline.length - 2] : null;
        var lastClose = lastCandle && Number.isFinite(lastCandle[1]) ? lastCandle[1] : null;
        var previousClose = previousCandle && Number.isFinite(previousCandle[1]) ? previousCandle[1] : null;
        var changeAmount = lastClose !== null && previousClose !== null ? lastClose - previousClose : null;
        var changePct = changeAmount !== null && previousClose
            ? changeAmount / previousClose * 100
            : null;
        return {
            code: item.code,
            name: item.name || item.code,
            type: item.type || 'stock',
            category: item.category || '',
            last_close: lastClose,
            change_pct: changePct,
            change_amt: changeAmount,
            last_date: dates.length ? dates[dates.length - 1] : null,
            status: 'pending',
            dynamic_only: true,
            storage: item.storage || 'server'
        };
    }

    function upsertWatchlistItem(item, stockData, saveInBrowser) {
        var normalized = {
            code: item.code,
            name: item.name || item.code,
            type: item.type || 'stock',
            category: item.category || '',
            storage: saveInBrowser ? 'browser' : (item.storage || 'server')
        };
        state.watchlist = combineWatchlists(state.watchlist, [normalized]);

        if (saveInBrowser) {
            var browserItems = combineWatchlists(readBrowserWatchlist(), [normalized]);
            saveBrowserWatchlist(browserItems);
        }

        if (!state.summary) state.summary = {items: []};
        var existing = state.summary.items.find(function (summaryItem) {
            return summaryItem.code === normalized.code;
        });
        if (existing && !existing.dynamic_only) {
            existing.name = normalized.name;
            existing.type = normalized.type;
            existing.category = normalized.category;
        } else {
            var summaryItem = buildSummaryFromQuery(normalized, stockData);
            if (existing) Object.assign(existing, summaryItem);
            else state.summary.items.push(summaryItem);
        }
        renderStockList();
    }

    // 初始化应用
    async function init() {
        try {
            // 并行加载元数据、汇总、排行榜(v3 & v2)、自选股与 v2.5 策略数据
            const [metaRes, summaryRes, rankingV3Res, rankingV2Res, watchlistRes, selectionRes, huntingRes, tempRes, briefRes, manifestRes] = await Promise.all([
                fetch(dataUrl('data/meta.json')).then(r => r.json()).catch(err => {
                    console.error('Failed to fetch meta.json:', err);
                    return null;
                }),
                fetch(dataUrl('data/summary.json')).then(r => r.json()).catch(err => {
                    console.error('Failed to fetch summary.json:', err);
                    return null;
                }),
                fetch(dataUrl('data/analysis/ranking_v3.json')).then(r => {
                    if (!r.ok) throw new Error(`HTTP ${r.status}`);
                    return r.json();
                }).catch(err => {
                    console.warn('Failed to fetch ranking_v3.json:', err);
                    return null;
                }),
                fetch(dataUrl('data/analysis/ranking.json')).then(r => {
                    if (!r.ok) throw new Error(`HTTP ${r.status}`);
                    return r.json();
                }).catch(err => {
                    console.error('Failed to fetch ranking.json:', err);
                    return null;
                }),
                fetchWithTimeout(API_BASE + '/api/watchlist', null, 8000).then(r => {
                    if (!r.ok) throw new Error(`HTTP ${r.status}`);
                    return r.json();
                }).catch(err => {
                    console.warn('Failed to fetch configured watchlist:', err);
                    return null;
                }),
                fetch(dataUrl('data/strategy/selection.json')).then(r => {
                    if (!r.ok) throw new Error(`HTTP ${r.status}`);
                    return r.json();
                }).catch(err => {
                    console.warn('v2.5 选股数据未加载（可跳过）:', err);
                    return null;
                }),
                fetch(dataUrl('data/strategy/hunting_ground.json')).then(r => {
                    if (!r.ok) throw new Error(`HTTP ${r.status}`);
                    return r.json();
                }).catch(err => {
                    console.warn('v2.5 狩猎场数据未加载（可跳过）:', err);
                    return null;
                }),
                fetch(dataUrl('data/strategy/market_temperature.json')).then(r => {
                    if (!r.ok) throw new Error(`HTTP ${r.status}`);
                    return r.json();
                }).catch(err => {
                    console.warn('v2.5 市场温度未加载（可跳过）:', err);
                    return null;
                }),
                fetch(dataUrl('data/strategy/daily_brief.json')).then(r => {
                    if (!r.ok) throw new Error(`HTTP ${r.status}`);
                    return r.json();
                }).catch(err => {
                    console.warn('v2.10 明日重点关注未加载（可跳过）:', err);
                    return null;
                }),
                fetch(dataUrl('data/paper/manifest.json')).then(r => {
                    if (!r.ok) throw new Error(`HTTP ${r.status}`);
                    return r.json();
                }).catch(err => {
                    console.warn('模拟盘清单未加载（可跳过）:', err);
                    return null;
                })
            ]);

            state.meta = metaRes;
            state.summary = summaryRes;
            state.rankingV3 = rankingV3Res;
            state.rankingV2 = rankingV2Res;
            state.ranking = (state.rankingEngine === 'v3' && state.rankingV3) ? state.rankingV3 : (state.rankingV2 || state.rankingV3);
            state.selection = selectionRes;
            state.huntingGround = huntingRes;
            state.marketTemperature = tempRes;
            state.dailyBrief = briefRes;
            state.paperManifest = manifestRes;
            state.paperSeries = [];
            state.watchlist = combineWatchlists(
                watchlistRes && watchlistRes.items,
                readBrowserWatchlist()
            );
            mergeWatchlistIntoSummary();

            // 渲染状态栏
            renderStatusBar();

            // 渲染 v2.5 市场温度与今日可买
            renderMarketTemperature();
            renderDailyBrief();
            renderBuyToday();
            renderTop3Matrix();

            // 渲染自选股列表
            if (state.summary && state.summary.items && state.summary.items.length > 0) {
                renderStockList();
                initWatchlistFilter();
                initWatchlistSearch();

            } else {
                el.stockList.innerHTML = '<div class="list-loading text-down">暂无自选股数据</div>';
                showOverlay('未找到自选股汇总数据，请检查后台运行状态。');
            }

            initRankingModule();

            // 渲染模拟盘对比：按清单加载全部组合（数据缺失时静默降级）
            await loadPaperSeries();
            renderPaper();

            const firstRankingItem = state.ranking && state.ranking.items && state.ranking.items[0];
            const firstSummaryItem = state.summary && state.summary.items && state.summary.items[0];
            const initialCode = firstRankingItem ? firstRankingItem.code : (firstSummaryItem ? firstSummaryItem.code : null);
            if (initialCode) {
                state.suppressDetailNavigation = true;
                await selectTrackedStock(initialCode);
                state.suppressDetailNavigation = false;
            }
        } catch (error) {
            console.error('Initialization error:', error);
            showOverlay('系统初始化失败，请稍后刷新重试。', true);
        }

        // 监听窗口大小变化以重绘图表
        window.addEventListener('resize', () => {
            if (state.chart) {
                state.chart.resize();
            }
            if (state.indexChart) {
                state.indexChart.resize();
            }
        });

        // 初始化查询栏
        initQueryBar();
    }

    // v2.5 渲染市场温度条
    function renderMarketTemperature() {
        const temp = state.marketTemperature;
        if (!temp || typeof temp.temperature !== 'number') {
            return; // 无数据则保持 hidden
        }
        el.marketTempBar.hidden = false;
        el.marketTempValue.textContent = temp.temperature.toFixed(1);
        el.marketTempStatus.textContent = '（' + (temp.status || '--') + '）';
        el.marketTempFill.style.width = Math.max(0, Math.min(100, temp.temperature)) + '%';
        el.marketTempRatio.textContent = '仓位参考：' + (temp.position_ratio != null ? (temp.position_ratio * 100) + '%' : '--');
        // 颜色：活跃=红/正常=橙/偏冷=蓝/寒冷以下=灰
        const status = temp.status || '';
        let color = '#8a8a8a';
        if (status === '活跃') color = '#e05252';
        else if (status === '正常') color = '#e8963c';
        else if (status === '偏冷') color = '#3c7fe8';
        el.marketTempFill.style.background = color;
    }

    // v2.10 渲染"明日重点关注"（AI 每日总结，置顶）
    function renderDailyBrief() {
        const brief = state.dailyBrief;
        if (!brief || !brief.summary) {
            return; // 无数据保持 hidden
        }
        el.dailyBriefSection.hidden = false;
        // 标题：周一重点关注（基于上一交易日分析）
        const briefWeekdays = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
        const nextLabel = brief.next_trade_label || '';
        el.dailyBriefTitle.textContent = '📋 ' + (nextLabel ? nextLabel + '重点关注' : '明日重点关注');
        const modeText = (brief.mode === 'deepseek_api') ? 'AI 生成' : '自动生成';
        let tradeWeek = '';
        if (brief.trade_date) {
            const d = new Date(String(brief.trade_date) + 'T00:00:00');
            if (!isNaN(d.getTime())) tradeWeek = '（' + briefWeekdays[d.getDay()] + '）';
        }
        el.dailyBriefMeta.textContent = '基于 ' + (brief.trade_date || '--') + tradeWeek + ' 收盘分析 · 推荐 ' + (brief.next_trade_date || '--') + (nextLabel ? '（' + nextLabel + '）' : '') + ' 关注 · ' + modeText + '（研究参考，不构成买卖建议）';
        el.dailyBriefSummary.textContent = brief.summary;
        const focus = brief.focus || [];
        if (focus.length > 0) {
            el.dailyBriefFocus.innerHTML = focus.map(item => {
                const code = escapeHtml(item.code || '');
                const name = escapeHtml(item.name || item.code || '');
                const reason = escapeHtml(item.reason || '');
                const risk = escapeHtml(item.risk || '');
                return `
                    <div class="daily-brief-item" data-code="${escapeHtml(item.code || '')}">
                        <div class="daily-brief-item-main">
                            <span class="daily-brief-item-name">${name}</span>
                            <span class="daily-brief-item-code">${code}</span>
                        </div>
                        <div class="daily-brief-item-reason">${reason}</div>
                        <div class="daily-brief-item-risk">${risk}</div>
                    </div>`;
            }).join('');
            el.dailyBriefFocus.querySelectorAll('.daily-brief-item').forEach(card => {
                card.addEventListener('click', () => {
                    const code = card.dataset.code;
                    if (code) selectTrackedStock(code);
                });
            });
        } else {
            el.dailyBriefFocus.innerHTML = '';
        }
        el.dailyBriefPosition.textContent = brief.position_hint || '';
        el.dailyBriefDisclaimer.textContent = brief.disclaimer || '';
    }
    // v2.5 渲染"今日可以关注"（策略信号 + 关注区间，置顶大字号）
    function renderBuyToday() {
        const sel = state.selection;
        const hunt = state.huntingGround;
        if (!sel || !hunt) {
            return; // 无数据保持 hidden
        }
        const huntingMap = {};
        const huntingData = hunt.hunting_ground || {};
        Object.keys(huntingData).forEach(strategyName => {
            (huntingData[strategyName] || []).forEach(entry => {
                if (!huntingMap[entry.code]) {
                    huntingMap[entry.code] = [];
                }
                huntingMap[entry.code].push(entry);
            });
        });

        // 收集所有策略命中的标的（去重，按买点距离升序）
        const seen = new Set();
        const items = [];
        const results = sel.results || {};
        Object.keys(results).forEach(strategyName => {
            (results[strategyName] || []).forEach(item => {
                if (seen.has(item.code)) return;
                seen.add(item.code);
                const entries = huntingMap[item.code] || [];
                // 取该标的最优买点判断（距离最近的）
                let best = null;
                entries.forEach(entry => {
                    const judge = entry.buy_judge || {};
                    if (judge.distance_pct == null) return;
                    if (!best || judge.distance_pct < best.distance_pct) best = judge;
                });
                items.push({
                    code: item.code,
                    name: item.name || item.code,
                    signals: item.signals || [],
                    buyJudge: best,
                    strategies: entries.map(e => e.support_method || '')
                });
            });
        });

        if (items.length === 0) {
            el.buyTodaySection.hidden = false;
            el.buyTodayList.innerHTML = '<div class="buy-today-empty">今日没有策略信号，可继续查看下方排行榜</div>';
            return;
        }

        // 排序：关注区间内的优先，其次距离近的
        items.sort((a, b) => {
            const aZone = a.buyJudge && a.buyJudge.in_buy_zone ? 0 : 1;
            const bZone = b.buyJudge && b.buyJudge.in_buy_zone ? 0 : 1;
            if (aZone !== bZone) return aZone - bZone;
            const aDist = a.buyJudge && a.buyJudge.distance_pct != null ? a.buyJudge.distance_pct : 999;
            const bDist = b.buyJudge && b.buyJudge.distance_pct != null ? b.buyJudge.distance_pct : 999;
            return aDist - bDist;
        });

        el.buyTodaySection.hidden = false;
        el.buyTodayList.innerHTML = items.map(item => {
            const judge = item.buyJudge;
            const reasons = (item.signals.length > 0 ? item.signals[0].reasons : ['策略命中']) || [];
            const reasonText = reasons.join('、');
            let zoneHtml = '';
            if (judge && judge.in_buy_zone) {
                zoneHtml = '<span class="buy-today-zone buy-today-zone-hot">✓ 在关注区间</span>';
            } else if (judge && judge.action === 'near_support') {
                zoneHtml = '<span class="buy-today-zone">接近支撑位</span>';
            } else if (judge && judge.action === 'below_support') {
                zoneHtml = '<span class="buy-today-zone buy-today-zone-warn">跌破支撑位</span>';
            } else if (judge) {
                zoneHtml = '<span class="buy-today-zone buy-today-zone-far">离支撑较远</span>';
            } else {
                zoneHtml = '<span class="buy-today-zone">--</span>';
            }
            const distText = judge && judge.distance_pct != null
                ? '距支撑 ' + judge.distance_pct.toFixed(1) + '%'
                : '';
            return `
                <div class="buy-today-card" data-code="${item.code}">
                    <div class="buy-today-card-main">
                        <div class="buy-today-card-name">${escapeHtml(item.name)}</div>
                        <div class="buy-today-card-code">${item.code}</div>
                        ${zoneHtml}
                    </div>
                    <div class="buy-today-card-detail">
                        <div class="buy-today-card-reasons">${escapeHtml(reasonText)}</div>
                        <div class="buy-today-card-dist">${distText}</div>
                    </div>
                </div>`;
        }).join('');

        // 点击卡片 → 选中该股查看详情
        el.buyTodayList.querySelectorAll('.buy-today-card').forEach(card => {
            card.addEventListener('click', () => {
                const code = card.dataset.code;
                if (code) selectTrackedStock(code);
            });
        });
    }

    // v3.0 首页全榜单 Top 3 精选矩阵（突破单一低风险偏好）
    function numOf(obj, path) {
        var v = obj;
        for (var i = 0; i < path.length; i++) {
            if (v == null) return 0;
            v = v[path[i]];
        }
        var n = Number(v);
        return isNaN(n) ? 0 : n;
    }

    function leadingReason(item) {
        var ld = item.leading || {};
        var inf = ld.inflection || 'none';
        var mom = ld.momentum || 'flat';
        var src = ld.source_name || (ld.data_source === 'synthetic_fallback' ? '合成降级' : '');
        var infMap = {
            positive_reversal: '前沿向上反转',
            accelerating: '前沿加速',
            decelerating: '前沿减速',
            negative_reversal: '前沿向下反转'
        };
        if (infMap[inf]) return infMap[inf] + (src ? ' · ' + src : '');
        if (mom === 'rising') return '动能上行' + (src ? ' · ' + src : '');
        if (mom === 'falling') return '动能下行' + (src ? ' · ' + src : '');
        return (src || '中性') + ' · 中短期趋势向上';
    }

    function gainReason(item) {
        var fc = item.forecast || {};
        var up = numOf(item, ['forecast', 'up_probability_5d_pct']);
        var conf = fc.confidence === 'high' ? '高置信' : (fc.confidence === 'medium' ? '中置信' : '低置信');
        return '5日上涨概率 ' + up.toFixed(0) + '% · ' + conf + ' · 样本 ' + (fc.sample_size || 0);
    }

    function betReason(item) {
        var rec = item.strategy_recommendation || {};
        if (rec.description) return rec.description;
        if (item.bet_type === 'trend') return '趋势主升 · 长动量半衰期';
        if (item.bet_type === 'volatile') return '高波动题材 · 短线择时';
        return '震荡筑底 · 等待突破';
    }

    function lowRiskReason(item) {
        var label = (item.risk || {}).label || '低风险';
        return label + ' · ' + (item.category || '综合') + ' · 低回撤防御';
    }

    function renderTop3Matrix() {
        var rank = state.ranking;
        if (!rank || !Array.isArray(rank.items) || rank.items.length === 0) {
            return;
        }
        var items = rank.items;

        function sortBy(list, path, dir) {
            return list.slice().sort(function (a, b) {
                var av = numOf(a, path);
                var bv = numOf(b, path);
                if (av === bv) return 0;
                return dir === 'asc' ? av - bv : bv - av;
            });
        }

        var leading = sortBy(items, ['leading', 'score'], 'desc').slice(0, 3);
        var gain = sortBy(items, ['forecast', 'return_5d_pct'], 'desc').slice(0, 3);
        var trend = sortBy(items.filter(function (i) { return i.bet_type === 'trend'; }), ['risk_adjusted_score'], 'desc').slice(0, 3);
        var volatile = sortBy(items.filter(function (i) { return i.bet_type === 'volatile'; }), ['risk_adjusted_score'], 'desc').slice(0, 3);
        var rangeBound = sortBy(items.filter(function (i) { return i.bet_type === 'range_bound'; }), ['risk_adjusted_score'], 'desc').slice(0, 3);
        var lowRisk = sortBy(items, ['risk', 'score'], 'asc').slice(0, 3);

        var cards = [
            { icon: '⚡', title: '前沿供需驱动', desc: '现货/期货/订单动能最强', list: leading, metric: function (i) { return '领先 ' + numOf(i, ['leading', 'score']).toFixed(0); }, reason: leadingReason },
            { icon: '🚀', title: '高弹性预期收益', desc: 'KNN 5日期望收益最高', list: gain, metric: function (i) { return '5日 ' + numOf(i, ['forecast', 'return_5d_pct']).toFixed(1) + '%'; }, reason: gainReason },
            { icon: '🎯', title: '趋势主升浪', desc: '长动量半衰期 · 稳健主升', list: trend, metric: function (i) { return '综合 ' + numOf(i, ['risk_adjusted_score']).toFixed(0); }, reason: betReason },
            { icon: '🔥', title: '妖股题材弹性', desc: '高波动 · 短线择时博弈', list: volatile, metric: function (i) { return '综合 ' + numOf(i, ['risk_adjusted_score']).toFixed(0); }, reason: betReason },
            { icon: '🧱', title: '震荡筑底', desc: '低位蓄势 · 等待突破', list: rangeBound, metric: function (i) { return '综合 ' + numOf(i, ['risk_adjusted_score']).toFixed(0); }, reason: betReason },
            { icon: '🛡️', title: '低风险稳健', desc: '极低回撤 · 防御配置', list: lowRisk, metric: function (i) { return '风险 ' + numOf(i, ['risk', 'score']).toFixed(0); }, reason: lowRiskReason }
        ];

        el.top3MatrixSection.hidden = false;
        el.top3MatrixGrid.innerHTML = cards.map(function (card) {
            var rows = card.list.map(function (item, idx) {
                var rankNo = idx + 1;
                return '<div class="top3-item top3-rank-' + rankNo + '" data-code="' + escapeHtml(item.code || '') + '">' +
                    '<span class="top3-rank">#' + rankNo + '</span>' +
                    '<div class="top3-item-body">' +
                        '<div class="top3-item-name">' + escapeHtml(item.name || item.code || '') + ' <span class="top3-item-code">' + escapeHtml(item.code || '') + '</span></div>' +
                        '<div class="top3-item-reason">' + escapeHtml(card.reason(item)) + '</div>' +
                    '</div>' +
                    '<span class="top3-item-metric">' + escapeHtml(card.metric(item)) + '</span>' +
                '</div>';
            }).join('');
            return '<div class="top3-card">' +
                '<div class="top3-card-head">' +
                    '<span class="top3-card-icon">' + card.icon + '</span>' +
                    '<div class="top3-card-title">' + escapeHtml(card.title) + '<span class="top3-card-desc">' + escapeHtml(card.desc) + '</span></div>' +
                '</div>' +
                '<div class="top3-list">' + rows + '</div>' +
            '</div>';
        }).join('');

        el.top3MatrixGrid.querySelectorAll('.top3-item').forEach(function (row) {
            row.addEventListener('click', function () {
                var code = row.dataset.code;
                if (code) selectTrackedStock(code);
            });
        });
    }

    // HTML 转义（防止策略内容注入）—— 使用文件底部已有的 escapeHtml

    // 渲染顶部状态栏
    function renderStatusBar() {
        const bar = el.statusBar;
        const text = el.statusText;

        bar.className = 'status-bar'; // 重置类名
        
        if (!state.meta) {
            bar.classList.add('failed');
            text.textContent = '运行元信息加载失败';
            return;
        }

        const timeStr = state.meta.updated_at ? state.meta.updated_at.substring(0, 16) : '未知时间';
        const tradeDateStr = state.meta.trade_date || '未知';

        switch (state.meta.run_status) {
            case 'ok':
                bar.classList.add('ok');
                text.textContent = `数据已更新：${timeStr} (交易日: ${tradeDateStr})`;
                break;
            case 'partial':
                bar.classList.add('partial');
                text.textContent = `部分更新成功 (更新时间: ${timeStr}, 交易日: ${tradeDateStr})`;
                break;
            case 'failed':
            default:
                bar.classList.add('failed');
                text.textContent = `今日更新失败，当前显示为上次数据 (更新时间: ${timeStr}, 交易日: ${tradeDateStr})`;
                break;
        }
    }

    // v2.11 自选股分区筛选（顶部标签切换）
    function initWatchlistFilter() {
        if (!el.watchlistFilter) return;
        el.watchlistFilter.querySelectorAll('.watchlist-filter-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                state.watchlistRegion = btn.dataset.region || 'all';
                el.watchlistFilter.querySelectorAll('.watchlist-filter-btn').forEach(b => {
                    b.classList.toggle('active', b === btn);
                });
                renderStockList();
            });
        });
    }
    // 自选股搜索（v2.12：名称/代码包含，与分区筛选组合生效）
    function initWatchlistSearch() {
        if (!el.watchlistSearchInput) return;
        el.watchlistSearchInput.addEventListener('input', function (ev) {
            if (ev.isComposing) return; // 中文输入法组合期间不触发
            state.watchlistSearch = el.watchlistSearchInput.value;
            if (el.watchlistSearchClear) el.watchlistSearchClear.hidden = !state.watchlistSearch;
            renderStockList();
        });
        if (el.watchlistSearchClear) {
            el.watchlistSearchClear.addEventListener('click', function () {
                el.watchlistSearchInput.value = '';
                state.watchlistSearch = '';
                el.watchlistSearchClear.hidden = true;
                renderStockList();
            });
        }
    }

    // 渲染股票列表（v2.11 分区：A股/港股/美股/韩股/基金）
    function renderStockList() {
        const regionOrder = ['stock', 'hk', 'us', 'kr', 'etf'];
        const regionLabels = { stock: 'A股', hk: '港股', us: '美股', kr: '韩股', etf: '基金' };
        const regionOf = function (item) {
            const t = item.type || 'stock';
            return (t === 'etf' || t === 'fund') ? 'etf' : t;
        };

        el.stockList.innerHTML = ''; // 清空加载状态

        // 按行业分组（尊重顶部市场筛选）
        const groups = {};
        const searchQ = (state.watchlistSearch || '').trim().toLowerCase();
        state.summary.items.forEach(item => {
            const region = regionOf(item);
            if (state.watchlistRegion !== 'all' && region !== state.watchlistRegion) return;
            if (searchQ && !((item.name || item.code).toLowerCase().includes(searchQ) || String(item.code || '').toLowerCase().includes(searchQ))) return;
            const industry = item.category || (region === 'etf' ? '基金' : '未分类');
            if (!groups[industry]) groups[industry] = [];
            groups[industry].push(item);
        });
        const orderedRegions = Object.keys(groups).sort((a, b) => groups[b].length - groups[a].length);
        if (orderedRegions.length === 0) {
            el.stockList.innerHTML = searchQ
                ? '<div class="list-loading">没有找到匹配的股票</div>'
                : '<div class="list-loading">该分区暂无股票</div>';
            return;
        }

        orderedRegions.forEach(region => {
            // 分区标题
            const title = document.createElement('div');
            title.className = 'watchlist-section-title';
            title.innerHTML = '<span class="watchlist-section-name">' + (regionLabels[region] || region) + '</span>'
                + '<span class="watchlist-section-count">' + groups[region].length + ' 只</span>';
            el.stockList.appendChild(title);

            groups[region].forEach(item => {
                const card = document.createElement('div');

                // 基础样式和状态标记
                card.className = 'stock-item';
                if (item.status === 'stale') {
                    card.classList.add('stale-stock');
                } else if (item.status === 'failed') {
                    card.classList.add('failed-stock');
                }

                // 涨跌判断
                let changeClass = 'text-flat';
                let changeSign = '';
                let arrow = '';
                if (item.change_pct > 0) {
                    changeClass = 'text-up';
                    changeSign = '+';
                    arrow = '↑';
                } else if (item.change_pct < 0) {
                    changeClass = 'text-down';
                    changeSign = '';
                    arrow = '↓';
                }

                // 类型标签 (股票/ETF/美股/港股/韩股)
                const typeLabel = item.type === 'etf' ? '基金' : item.type === 'us' ? '美股' : item.type === 'kr' ? '韩股' : item.type === 'hk' ? '港股' : '股票';
                const typeClass = item.type === 'etf' ? 'etf' : 'stock';

                // 失败或节假日数据可能没有价格/涨跌幅，仍然渲染卡片。
                const hasClose = Number.isFinite(item.last_close);
                const hasChange = Number.isFinite(item.change_pct);
                const closeText = hasClose ? item.last_close.toFixed(2) : '--';
                const changeText = hasChange ? `${changeSign}${item.change_pct.toFixed(2)}% ${arrow}` : '--';
                const changeBg = hasChange ? (item.change_pct >= 0 ? 'up' : 'down') : 'flat';

                // 名称未识别时给出提示（name === code）
                const displayName = item.name === item.code
                    ? `${item.code} (名称未识别)`
                    : item.name;
                // 构建卡片 HTML
                card.innerHTML = `
                    <div class="stock-item-left">
                        <span class="stock-item-name">${displayName}</span>
                        <div class="stock-item-meta">
                            <span class="stock-item-code">${item.code}</span>
                            <span class="type-badge ${typeClass}">${typeLabel}</span>
                        </div>
                    </div>
                    <div class="stock-item-right">
                        <span class="stock-item-price ${changeClass}">${closeText}</span>
                        <span class="stock-item-pct bg-${changeBg}">${changeText}</span>
                    </div>
                `;

                // 点击事件
                card.addEventListener('click', () => {
                    if (item.dynamic_only) {
                        el.queryCodeInput.value = item.code;
                        doQuery();
                    } else {
                        selectTrackedStock(item.code);
                    }
                    // 移动端体验：点击卡片后平滑滚动到图表区域
                    if (window.innerWidth < 900) {
                        el.detailHeader.scrollIntoView({ behavior: 'smooth' });
                    }
                });

                // 暂存 DOM 引用，方便高亮切换
                card.dataset.code = item.code;
                el.stockList.appendChild(card);
            });
        });
    }

    // 选中并加载特定股票
    async function selectStock(code) {
            if (state.selectedCode === code) return;
        state.selectedCode = code;

        // 更新列表卡片高亮状态
        const items = el.stockList.querySelectorAll('.stock-item');
        items.forEach(card => {
            if (card.dataset.code === code) {
                card.classList.add('active');
            } else {
                card.classList.remove('active');
            }
        });

        // 查找该标的的最新汇总信息
        const summaryItem = state.summary.items.find(i => i.code === code);
        if (summaryItem) {
            updateDetailHeader(summaryItem);
        }

        // 显示图表加载遮罩
        showLoadingOverlay();

        try {
            const response = await fetch(dataUrl(`data/kline/${code}.json`));
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            const klineData = await response.json();
            
            // 渲染 K 线图
            renderChart(klineData);
            hideOverlay();
        } catch (error) {
            console.error(`Failed to load kline for ${code}:`, error);
            showOverlay(`《${summaryItem ? summaryItem.name : code}》K 线数据加载失败`, true);
        }
    }

    // 更新详情区顶部的大字价钱与涨跌幅
    function updateDetailHeader(item) {
        el.detailName.textContent = item.name;
        el.detailCode.textContent = item.code;
        
        const typeLabel = item.type === 'etf' ? '场内基金/ETF' : 'A股股票';
        el.detailTypeBadge.textContent = typeLabel;
        el.detailTypeBadge.className = `type-badge ${item.type}`;

        el.detailPrice.textContent = item.last_close.toFixed(2);
        
        let changeClass = 'text-flat';
        let changeSign = '';
        let arrow = '';
        if (item.change_pct > 0) {
            changeClass = 'text-up';
            changeSign = '+';
            arrow = '↑';
        } else if (item.change_pct < 0) {
            changeClass = 'text-down';
            changeSign = '';
            arrow = '↓';
        }
        
        el.detailChange.textContent = `${changeSign}${item.change_pct.toFixed(2)}% (${changeSign}${item.change_amt.toFixed(2)}元) ${arrow}`;
        el.detailChange.className = `detail-change ${changeClass}`;
        el.detailPrice.className = `detail-price ${changeClass}`;
        
        el.detailDateLabel.textContent = `最新交易日期：${item.last_date || '--'}`;
        el.detailHeader.style.display = 'block';
    }

    // 渲染 ECharts K 线图与成交量图
    function renderChart(data) {
        // 数据校验与截取：默认截取最近 1 年 (250 个交易日)
        const dates = data.dates || [];
        const kline = data.kline || [];
        const volume = data.volume || [];
        const ma5 = data.ma5 || [];
        const ma10 = data.ma10 || [];
        const ma20 = data.ma20 || [];
        const ma60 = data.ma60 || [];

        if (dates.length === 0) {
            throw new Error('No historical data points found.');
        }

        // 切片截取最近最多 250 天的数据点
        const MAX_POINTS = 250;
        const startIndex = Math.max(0, dates.length - MAX_POINTS);

        state.activeData.dates = dates.slice(startIndex);
        state.activeData.kline = kline.slice(startIndex);
        state.activeData.volume = volume.slice(startIndex);
        state.activeData.ma5 = ma5.slice(startIndex);
        state.activeData.ma10 = ma10.slice(startIndex);
        state.activeData.ma20 = ma20.slice(startIndex);
        state.activeData.ma60 = ma60.slice(startIndex);

        // 处理成交量颜色：收盘 >= 开盘 为红色，否则为绿色
        const volumeData = state.activeData.volume.map((vol, idx) => {
            const dayKline = state.activeData.kline[idx];
            const open = dayKline[0];
            const close = dayKline[1];
            return {
                value: vol,
                itemStyle: {
                    color: close >= open ? '#e63946' : '#10b981'
                }
            };
        });

        // 初始化或获取已存在的 ECharts 实例
        if (!state.chart) {
            state.chart = echarts.init(el.chartElement);
        }

        // 配置参数 (中老年优化版：图表更大，手势平滑，提示框信息大)
        const option = {
            // 支持无缝动画
            animation: false,
            // 提示框配置
            tooltip: {
                trigger: 'axis',
                axisPointer: {
                    type: 'cross',
                    label: {
                        backgroundColor: '#6b7280',
                        fontSize: 13
                    }
                },
                backgroundColor: 'rgba(255, 255, 255, 0.96)',
                borderColor: '#cbd5e1',
                borderWidth: 1,
                padding: 12,
                textStyle: {
                    color: '#1f2937'
                },
                position: function (pos, params, dom, rect, size) {
                    // 让提示框始终浮在上方，避免遮挡蜡烛图
                    const obj = { top: 30 };
                    obj[['left', 'right'][+(pos[0] < size.viewSize[0] / 2)]] = 30;
                    return obj;
                },
                formatter: function (params) {
                    if (params.length === 0) return '';
                    // 获取当前数据索引
                    const idx = params[0].dataIndex;
                    
                    const date = state.activeData.dates[idx];
                    const dayKline = state.activeData.kline[idx];
                    const vol = state.activeData.volume[idx];
                    
                    const open = dayKline[0];
                    const close = dayKline[1];
                    const low = dayKline[2];
                    const high = dayKline[3];

                    const m5 = state.activeData.ma5[idx];
                    const m10 = state.activeData.ma10[idx];
                    const m20 = state.activeData.ma20[idx];
                    const m60 = state.activeData.ma60[idx];

                    // 算今天盘中涨跌幅
                    const changeVal = close - open;
                    const changePct = ((changeVal / open) * 100).toFixed(2);
                    const changeClass = changeVal >= 0 ? 'text-up' : 'text-down';
                    const changeSign = changeVal >= 0 ? '+' : '';
                    const arrow = changeVal >= 0 ? '↑' : '↓';

                    // 格式化输出
                    const toFixedStr = (val) => (val !== null && val !== undefined) ? val.toFixed(2) : '--';

                    return `
                        <div style="font-family: var(--font-sans); min-width: 200px; font-size: 15px; line-height: 1.6;">
                            <div style="font-weight: bold; font-size: 16px; margin-bottom: 6px; border-bottom: 1px solid #e5e7eb; padding-bottom: 4px;">
                                日期：${date}
                            </div>
                            <div style="display: flex; justify-content: space-between;">
                                <span>开盘/收盘:</span>
                                <strong>${open.toFixed(2)} / ${close.toFixed(2)}</strong>
                            </div>
                            <div style="display: flex; justify-content: space-between;">
                                <span>单日涨跌:</span>
                                <strong class="${changeClass}">${changeSign}${changePct}% ${arrow}</strong>
                            </div>
                            <div style="display: flex; justify-content: space-between;">
                                <span>最高/最低:</span>
                                <span>${high.toFixed(2)} / ${low.toFixed(2)}</span>
                            </div>
                            <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
                                <span>成交量:</span>
                                <span>${(vol / 10000).toFixed(2)} 万手</span>
                            </div>
                            <div style="border-top: 1px dashed #e5e7eb; padding-top: 4px; font-size: 14px;">
                                <span style="color:#eab308">●</span> MA5: ${toFixedStr(m5)}<br/>
                                <span style="color:#ec4899">●</span> MA10: ${toFixedStr(m10)}<br/>
                                <span style="color:#3b82f6">●</span> MA20: ${toFixedStr(m20)}<br/>
                                <span style="color:#14b8a6">●</span> MA60: ${toFixedStr(m60)}
                            </div>
                        </div>
                    `;
                }
            },
            // 图表组件位置布局
            grid: [
                {
                    left: '8%',
                    right: '4%',
                    top: '8%',
                    height: '56%'
                },
                {
                    left: '8%',
                    right: '4%',
                    top: '72%',
                    height: '16%'
                }
            ],
            // 坐标轴配置
            xAxis: [
                {
                    type: 'category',
                    data: state.activeData.dates,
                    boundaryGap: false,
                    axisLine: { onZero: false, lineStyle: { color: '#9ca3af' } },
                    splitLine: { show: true, lineStyle: { color: '#f3f4f6' } },
                    axisLabel: { fontSize: 13, color: '#4b5563' },
                    min: 'dataMin',
                    max: 'dataMax'
                },
                {
                    type: 'category',
                    gridIndex: 1,
                    data: state.activeData.dates,
                    boundaryGap: false,
                    axisLine: { onZero: false, lineStyle: { color: '#9ca3af' } },
                    axisTick: { show: false },
                    splitLine: { show: false },
                    axisLabel: { show: false }
                }
            ],
            yAxis: [
                {
                    scale: true,
                    axisLine: { lineStyle: { color: '#9ca3af' } },
                    splitArea: { show: false },
                    splitLine: { show: true, lineStyle: { color: '#f3f4f6' } },
                    axisLabel: { fontSize: 13, color: '#4b5563', formatter: '{value}' }
                },
                {
                    scale: true,
                    gridIndex: 1,
                    splitNumber: 2,
                    axisLabel: { show: false },
                    axisLine: { show: false },
                    axisTick: { show: false },
                    splitLine: { show: false }
                }
            ],
            // 缩放滑块：手机端缩放和平移极重要
            dataZoom: [
                {
                    type: 'inside',
                    xAxisIndex: [0, 1],
                    start: 60, // 默认显示最新的 40% 数据，大约 100 个交易日（近半年），保证字够大，双指捏合可看全貌
                    end: 100
                },
                {
                    show: true,
                    xAxisIndex: [0, 1],
                    type: 'slider',
                    top: '91%',
                    height: '5%',
                    start: 60,
                    end: 100,
                    textStyle: {
                        color: '#6b7280'
                    }
                }
            ],
            // 数据源序列
            series: [
                {
                    name: '日K',
                    type: 'candlestick',
                    data: state.activeData.kline,
                    itemStyle: {
                        color: '#e63946',     // 阳线填充（红）
                        color0: '#10b981',    // 阴线填充（绿）
                        borderColor: '#e63946',
                        borderColor0: '#10b981'
                    }
                },
                {
                    name: 'MA5',
                    type: 'line',
                    data: state.activeData.ma5,
                    smooth: true,
                    showSymbol: false,
                    lineStyle: {
                        width: 2,
                        color: '#eab308',
                        opacity: 0.8
                    }
                },
                {
                    name: 'MA10',
                    type: 'line',
                    data: state.activeData.ma10,
                    smooth: true,
                    showSymbol: false,
                    lineStyle: {
                        width: 2,
                        color: '#ec4899',
                        opacity: 0.8
                    }
                },
                {
                    name: 'MA20',
                    type: 'line',
                    data: state.activeData.ma20,
                    smooth: true,
                    showSymbol: false,
                    lineStyle: {
                        width: 2,
                        color: '#3b82f6',
                        opacity: 0.8
                    }
                },
                {
                    name: 'MA60',
                    type: 'line',
                    data: state.activeData.ma60,
                    smooth: true,
                    showSymbol: false,
                    lineStyle: {
                        width: 2.5,
                        color: '#14b8a6',
                        opacity: 0.8
                    }
                },
                {
                    name: '成交量',
                    type: 'bar',
                    xAxisIndex: 1,
                    yAxisIndex: 1,
                    data: volumeData
                }
            ]
        };

        // 应用配置
        state.chart.setOption(option, true);
    }

    // 加载动画与遮罩管理
    function showLoadingOverlay() {
        el.chartOverlay.style.display = 'flex';
        el.chartOverlay.innerHTML = `
            <div class="overlay-content loading">
                正在读取 K 线走势数据...
            </div>
        `;
    }

    function hideOverlay() {
        el.chartOverlay.style.display = 'none';
    }

    function showOverlay(message, isError = false) {
        el.chartOverlay.style.display = 'flex';
        el.chartOverlay.innerHTML = `
            <div class="overlay-content ${isError ? 'error' : ''}">
                ${message}
            </div>
        `;
    }

    // ============================================================
    // 2.1 排行榜与个股研究模块
    // ============================================================

    function initRankingModule() {
        bindRankingControls();

        if (!state.ranking) {
            showRankingState('分析数据尚未生成，请先运行每日分析任务。', true);
            el.rankingMeta.textContent = '排行榜不可用';
            return;
        }

        var schemaMajor = String(state.ranking.schema_version || '').split('.')[0];
        if (schemaMajor !== '2' && schemaMajor !== '3') {
            showRankingState('分析数据版本不兼容，请重新生成当前版本数据。', true);
            el.rankingMeta.textContent = '数据版本不兼容';
            return;
        }

        var items = Array.isArray(state.ranking.items) ? state.ranking.items : [];
        populateIndustryFilter(items);

        var generated = state.ranking.generated_at || '--';
        var statusText = state.ranking.status === 'partial'
            ? '部分标的使用旧数据'
            : '全部分析完成';
        var engineTag = (state.rankingEngine === 'v3')
            ? '⚡ 3.0 前沿驱动 (Leading-45%)'
            : '📜 2.0 传统财报 (Legacy-50%)';
        el.rankingMeta.textContent = '[' + engineTag + '] · 交易日 ' + (state.ranking.trade_date || '--')
            + ' · ' + items.length + ' 只标的 · ' + statusText
            + ' · ' + generated.substring(0, 16);

        renderRanking();
    }

    function bindRankingControls() {
        if (el.rankingSearch.dataset.bound === 'true') return;
        el.rankingSearch.dataset.bound = 'true';

        // 3.0 前沿驱动 vs 2.0 传统财报 双轨切换器
        document.querySelectorAll('.ranking-engine-btn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                state.rankingEngine = btn.dataset.engine;
                document.querySelectorAll('.ranking-engine-btn').forEach(function (b) {
                    b.classList.toggle('active', b === btn);
                });
                state.ranking = (state.rankingEngine === 'v3' && state.rankingV3) ? state.rankingV3 : state.rankingV2;
                initRankingModule();
                renderTop3Matrix();
            });
        });

        document.querySelectorAll('.ranking-tab').forEach(function (tab) {
            tab.addEventListener('click', function () {
                state.rankingMode = tab.dataset.mode;
                if (state.rankingMode === 'return') {
                    state.rankingSortKey = 'return_5d_pct';
                    state.rankingSortDirection = 'desc';
                } else if (state.rankingMode === 'risk') {
                    state.rankingSortKey = 'risk_score';
                    state.rankingSortDirection = 'asc';
                } else {
                    state.rankingSortKey = 'risk_adjusted_score';
                    state.rankingSortDirection = 'desc';
                }

                document.querySelectorAll('.ranking-tab').forEach(function (item) {
                    var active = item === tab;
                    item.classList.toggle('active', active);
                    item.setAttribute('aria-selected', active ? 'true' : 'false');
                });
                renderRanking();
            });
        });

        document.querySelectorAll('.ranking-table th button[data-sort]').forEach(function (button) {
            button.addEventListener('click', function () {
                var key = button.dataset.sort;
                if (state.rankingSortKey === key) {
                    state.rankingSortDirection = state.rankingSortDirection === 'desc' ? 'asc' : 'desc';
                } else {
                    state.rankingSortKey = key;
                    state.rankingSortDirection = key === 'risk_score' ? 'asc' : 'desc';
                }
                renderRanking();
            });
        });

        el.rankingSearch.addEventListener('input', renderRanking);
        el.rankingIndustryFilter.addEventListener('change', renderRanking);
    }

    function populateIndustryFilter(items) {
        while (el.rankingIndustryFilter.options.length > 1) {
            el.rankingIndustryFilter.remove(1);
        }
        var categories = Array.from(new Set(items.map(displayCategory))).filter(Boolean).sort();
        categories.forEach(function (category) {
            var option = document.createElement('option');
            option.value = category;
            option.textContent = category;
            el.rankingIndustryFilter.appendChild(option);
        });
    }

    function displayCategory(item) {
        if (item.category) return item.category;
        if (item.type === 'etf') return 'ETF';
        return (item.industry && item.industry.name) || '未分类';
    }

    function showRankingState(message, isError) {
        el.rankingState.hidden = false;
        el.rankingState.textContent = message;
        el.rankingState.classList.toggle('error', Boolean(isError));
        el.rankingTableWrap.hidden = true;
        el.rankingMobileList.hidden = true;
    }

    function getRankingValue(item, key) {
        if (key === 'return_3d_pct') return item.forecast && item.forecast.return_3d_pct;
        if (key === 'return_5d_pct') return item.forecast && item.forecast.return_5d_pct;
        if (key === 'risk_score') return item.risk && item.risk.score;
        return item.risk_adjusted_score;
    }

    function getVisibleRankingItems() {
        var items = state.ranking && Array.isArray(state.ranking.items)
            ? state.ranking.items.slice()
            : [];
        var search = el.rankingSearch.value.trim().toLowerCase();
        var category = el.rankingIndustryFilter.value;

        items = items.filter(function (item) {
            var matchesSearch = !search
                || String(item.code).toLowerCase().includes(search)
                || String(item.name).toLowerCase().includes(search);
            var matchesCategory = !category || displayCategory(item) === category;
            return matchesSearch && matchesCategory;
        });

        var direction = state.rankingSortDirection === 'asc' ? 1 : -1;
        items.sort(function (a, b) {
            var av = getRankingValue(a, state.rankingSortKey);
            var bv = getRankingValue(b, state.rankingSortKey);
            var aMissing = !Number.isFinite(av);
            var bMissing = !Number.isFinite(bv);
            if (aMissing && bMissing) return String(a.code).localeCompare(String(b.code));
            if (aMissing) return 1;
            if (bMissing) return -1;
            if (av === bv) return String(a.code).localeCompare(String(b.code));
            return (av - bv) * direction;
        });
        return items;
    }

    function renderRanking() {
        if (!state.ranking || !Array.isArray(state.ranking.items)) return;
        var items = getVisibleRankingItems();

        document.querySelectorAll('.ranking-table th button[data-sort]').forEach(function (button) {
            var active = button.dataset.sort === state.rankingSortKey;
            button.classList.toggle('active', active);
            button.textContent = button.textContent.replace(/[↑↓]\s*$/, '')
                + (active ? (state.rankingSortDirection === 'asc' ? ' ↑' : ' ↓') : '');
        });

        if (items.length === 0) {
            showRankingState('没有符合当前筛选条件的股票。', false);
            return;
        }

        el.rankingState.hidden = true;
        el.rankingTableWrap.hidden = false;
        el.rankingMobileList.hidden = false;
        el.rankingTbody.innerHTML = '';
        el.rankingMobileList.innerHTML = '';

        items.forEach(function (item, index) {
            renderRankingTableRow(item, index + 1);
            renderRankingMobileRow(item, index + 1);
        });
        highlightRankingSelection();
    }

    function leadingBadgeHtml(leading) {
        if (!leading) return '';
        var text = '';
        var cls = 'leading-badge';
        if (leading.inflection === 'positive_reversal') { text = '领先拐点↑'; cls += ' leading-up'; }
        else if (leading.inflection === 'negative_reversal') { text = '领先拐点↓'; cls += ' leading-down'; }
        else if (leading.momentum === 'accelerating') { text = '领先加速'; cls += ' leading-up'; }
        else if (leading.momentum === 'decelerating') { text = '领先减速'; cls += ' leading-down'; }
        else if (leading.data_source === 'synthetic_fallback') { text = '领先·合成'; }
        else { return ''; }
        return '<span class="' + cls + '" title="领先指标信号（前沿供需拐点）">' + text + '</span> ';
    }

    function renderRankingTableRow(item, rank) {
        var tr = document.createElement('tr');
        tr.tabIndex = 0;
        tr.setAttribute('role', 'button');
        tr.dataset.analysisCode = item.code;
        var firstReason = item.reasons && item.reasons[0];
        var reasonText = firstReason ? firstReason.title + '：' + firstReason.detail : '暂无明确加减分项';
        var risk = item.risk || {};
        var leadingBadge = leadingBadgeHtml(item.leading);

        tr.innerHTML = '<td class="ranking-number ' + (rank <= 3 ? 'top-three' : '') + '">' + rank + '</td>'
            + '<td><span class="ranking-stock-name">' + escapeHtml(item.name) + '</span>'
            + '<span class="ranking-stock-meta"><span>' + escapeHtml(item.code) + '</span><span>' + escapeHtml(displayCategory(item)) + '</span></span></td>'
            + '<td><span class="score-value">' + formatScore(item.risk_adjusted_score) + '</span></td>'
            + '<td>' + formatForecastHtml(item.forecast && item.forecast.return_3d_pct) + '</td>'
            + '<td>' + formatForecastHtml(item.forecast && item.forecast.return_5d_pct) + '</td>'
            + '<td><span class="risk-badge ' + riskClass(risk.level) + '">' + escapeHtml(risk.label || '未知风险') + ' ' + formatScore(risk.score) + '</span></td>'
            + '<td><span class="ranking-reason">' + leadingBadge + escapeHtml(reasonText) + '</span></td>';

        tr.addEventListener('click', function () { selectTrackedStock(item.code, true); });
        tr.addEventListener('keydown', function (event) {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                selectTrackedStock(item.code, true);
            }
        });
        el.rankingTbody.appendChild(tr);
    }

    function renderRankingMobileRow(item, rank) {
        var button = document.createElement('button');
        button.type = 'button';
        button.className = 'ranking-mobile-card';
        button.dataset.analysisCode = item.code;
        var risk = item.risk || {};
        button.innerHTML = '<div class="ranking-mobile-top">'
            + '<div class="ranking-mobile-name">' + rank + '. ' + escapeHtml(item.name)
            + '<small>' + escapeHtml(item.code) + ' · ' + escapeHtml(displayCategory(item)) + '</small></div>'
            + '<span class="risk-badge ' + riskClass(risk.level) + '">' + escapeHtml(risk.label || '未知风险') + '</span>'
            + '</div>'
            + '<div class="ranking-mobile-metrics">'
            + mobileMetric('风险收益分', formatScore(item.risk_adjusted_score), '')
            + mobileMetric('3日统计', formatPct(item.forecast && item.forecast.return_3d_pct), returnClass(item.forecast && item.forecast.return_3d_pct))
            + mobileMetric('5日统计', formatPct(item.forecast && item.forecast.return_5d_pct), returnClass(item.forecast && item.forecast.return_5d_pct))
            + '</div>';
        button.addEventListener('click', function () { selectTrackedStock(item.code, true); });
        el.rankingMobileList.appendChild(button);
    }

    function mobileMetric(label, value, className) {
        return '<div class="ranking-mobile-metric"><span>' + label + '</span><strong class="' + className + '">' + value + '</strong></div>';
    }

    function formatScore(value) {
        return Number.isFinite(value) ? Number(value).toFixed(1) : '--';
    }

    function formatPct(value) {
        if (!Number.isFinite(value)) return '样本不足';
        return (value > 0 ? '+' : '') + Number(value).toFixed(2) + '%';
    }

    function formatProbability(value) {
        return Number.isFinite(value) ? Number(value).toFixed(1) + '%' : '样本不足';
    }

    function returnClass(value) {
        if (!Number.isFinite(value) || value === 0) return 'text-flat';
        return value > 0 ? 'text-up' : 'text-down';
    }

    function formatForecastHtml(value) {
        if (!Number.isFinite(value)) return '<span class="forecast-empty">样本不足</span>';
        return '<span class="forecast-value ' + returnClass(value) + '">' + formatPct(value) + '</span>';
    }

    function riskClass(level) {
        if (level === 'low') return 'risk-low';
        if (level === 'high') return 'risk-high';
        return 'risk-medium';
    }

    function confidenceLabel(confidence) {
        if (confidence === 'high') return '高置信';
        if (confidence === 'medium') return '中等置信';
        return '低置信';
    }

    function trendLabel(trend) {
        var labels = {
            strong_uptrend: '强势上升',
            uptrend: '上升趋势',
            range: '震荡整理',
            rebound: '反弹修复',
            downtrend: '下降趋势',
            insufficient: '数据不足'
        };
        return labels[trend] || '趋势未明';
    }

    async function selectTrackedStock(code, scrollToDetail) {
        state.queryActive = false;
        el.queryResultHeader.style.display = 'none';
        el.indexChartCard.style.display = 'none';

        var summaryItem = state.summary && state.summary.items
            ? state.summary.items.find(function (item) { return item.code === code; })
            : null;
        if (summaryItem) updateDetailHeader(summaryItem);

        await Promise.all([selectStock(code), loadAnalysisDetail(code)]);

        // v2.6：用户点击进入个股研究页；初始化预载时由 init 标记跳过
        if (!state.suppressDetailNavigation) navigateTo('detail');

        if (scrollToDetail && window.innerWidth < 900) {
            el.analysisDetail.scrollIntoView({behavior: 'smooth', block: 'start'});
        }
    }

    async function loadAnalysisDetail(code) {
        state.analysisSelectedCode = code;
        highlightRankingSelection();
        showAnalysisLoading();

        try {
            var detail = state.analysisCache[code];
            if (!detail) {
                var response = await fetch(dataUrl('data/analysis/' + encodeURIComponent(code) + '.json'));
                if (!response.ok) throw new Error('HTTP ' + response.status);
                detail = await response.json();
                if (String(detail.schema_version || '').split('.')[0] !== '2') {
                    throw new Error('分析数据版本不兼容');
                }
                state.analysisCache[code] = detail;
            }

            if (state.analysisSelectedCode === code) {
                renderAnalysisDetail(detail);
                loadResearchReport(code, detail.trade_date);
            }
        } catch (error) {
            console.error('Failed to load analysis for ' + code + ':', error);
            if (state.analysisSelectedCode === code) showAnalysisError('该股票的分析详情暂时无法读取。');
        }
    }

    // ---- AI 研究报告渲染（模块四） ----
    function isNonNegativeNumber(value) {
        return typeof value === 'number' && Number.isFinite(value) && value >= 0;
    }

    function isCompatibleResearchReport(report) {
        var researchReport = report && report.research_report;
        var audit = report && report.citation_audit;
        var metadata = report && report.llm_metadata;
        if (!report || typeof report !== 'object' || !researchReport || typeof researchReport !== 'object') {
            return false;
        }
        if (String(report.schema_version || '').split('.')[0] !== '2') return false;
        if (typeof report.code !== 'string' || !report.code.trim()
            || typeof report.name !== 'string' || !report.name.trim()
            || typeof report.trade_date !== 'string' || !report.trade_date.trim()
            || typeof report.disclaimer !== 'string') {
            return false;
        }
        if (typeof researchReport.summary !== 'string'
            || (researchReport.elder_friendly !== undefined
                && typeof researchReport.elder_friendly !== 'string')
            || !Array.isArray(researchReport.sections)) {
            return false;
        }
        if (!researchReport.sections.every(function (section) {
            if (!section || typeof section.heading !== 'string' || typeof section.content !== 'string') {
                return false;
            }
            return section.citations === undefined || (Array.isArray(section.citations)
                && section.citations.every(function (citation) {
                    return citation && typeof citation.source === 'string';
                }));
        })) {
            return false;
        }
        if (!audit || typeof audit !== 'object'
            || !isNonNegativeNumber(audit.total)
            || !isNonNegativeNumber(audit.evidence)
            || !isNonNegativeNumber(audit.inference)
            || !isNonNegativeNumber(audit.uncertain)) {
            return false;
        }
        return !!metadata && typeof metadata === 'object'
            && typeof metadata.backend === 'string'
            && typeof metadata.mode === 'string'
            && typeof metadata.model === 'string'
            && typeof metadata.pipeline === 'string';
    }

    function isSafeCitationUrl(value) {
        if (typeof value !== 'string') return false;
        try {
            var url = new URL(value);
            return url.protocol === 'https:' || url.protocol === 'http:';
        } catch (error) {
            return false;
        }
    }

    function hideResearchReport() {
        el.reportSection.hidden = true;
        el.reportStatus.hidden = true;
        el.reportStatus.textContent = '';
        el.reportMeta.textContent = '--';
        el.reportConfidence.textContent = '--';
        el.reportConfidence.className = 'confidence-badge';
        el.reportElder.hidden = true;
        el.reportElder.textContent = '';
        el.reportSections.textContent = '';
        el.reportCitations.hidden = true;
        el.reportCitationList.textContent = '';
        el.reportDisclaimer.textContent = '';
    }

    function showResearchReportUnavailable(message) {
        el.reportSection.hidden = false;
        el.reportMeta.textContent = '研究报告';
        el.reportConfidence.textContent = '暂不可用';
        el.reportConfidence.className = 'confidence-badge confidence-low';
        el.reportStatus.hidden = false;
        el.reportStatus.textContent = message;
        el.reportElder.hidden = true;
        el.reportSections.textContent = '';
        el.reportCitations.hidden = true;
        el.reportCitationList.textContent = '';
        el.reportDisclaimer.textContent = '研究报告无法使用，不影响既有风险收益分析。';
    }

    function appendCitationDetail(container, citation) {
        if (!citation || typeof citation.source !== 'string' || !citation.source.trim()) return;
        var details = document.createElement('details');
        details.className = 'report-citation-detail';
        var summary = document.createElement('summary');
        summary.textContent = '来源：' + citation.source
            + (typeof citation.date === 'string' && citation.date ? ' · ' + citation.date : '');
        details.appendChild(summary);

        if (typeof citation.claim === 'string' && citation.claim.trim()) {
            var claim = document.createElement('p');
            claim.className = 'report-citation-claim';
            claim.textContent = citation.claim;
            details.appendChild(claim);
        }
        if (typeof citation.snippet === 'string' && citation.snippet.trim()) {
            var snippet = document.createElement('p');
            snippet.className = 'report-citation-snippet';
            snippet.textContent = citation.snippet;
            details.appendChild(snippet);
        }
        if (isSafeCitationUrl(citation.url)) {
            var link = document.createElement('a');
            link.className = 'report-citation-link';
            link.href = citation.url;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            link.textContent = '打开原文';
            details.appendChild(link);
        }
        container.appendChild(details);
    }
    async function loadResearchReport(code, tradeDate) {
        if (typeof tradeDate !== 'string' || !tradeDate.trim()) {
            if (state.analysisSelectedCode === code) hideResearchReport();
            return;
        }
        try {
            var reportPath = 'data/llm/reports/' + encodeURIComponent(code)
                + '_' + encodeURIComponent(tradeDate) + '.json';
            var resp = await fetch(dataUrl(reportPath));
            if (!resp.ok) {
                if (resp.status === 404) {
                    if (state.analysisSelectedCode === code) hideResearchReport();
                    return;
                }
                throw new Error('HTTP ' + resp.status);
            }
            var report = await resp.json();
            if (!isCompatibleResearchReport(report)) {
                if (state.analysisSelectedCode === code) {
                    showResearchReportUnavailable('研究报告数据版本不兼容或结构不完整。');
                }
                return;
            }
            if (state.analysisSelectedCode === code) renderResearchReport(report);
        } catch (error) {
            if (state.analysisSelectedCode === code) {
                showResearchReportUnavailable('研究报告暂时无法读取。');
            }
        }
    }
    function renderResearchReport(report) {
        var rr = report.research_report || {};
        el.reportSection.hidden = false;
        el.reportStatus.hidden = true;
        el.reportStatus.textContent = '';

        // 元信息
        el.reportMeta.textContent = report.name + '（' + report.code + '）'
            + (report.trade_date ? ' · ' + report.trade_date : '');
        var conf = ['high', 'medium', 'low'].indexOf(report.confidence) >= 0
            ? report.confidence : 'low';
        el.reportConfidence.textContent = '置信度 ' + confLabel(conf);
        el.reportConfidence.className = 'confidence-badge confidence-' + conf;

        // 父母版简明摘要
        el.reportElder.hidden = !(rr.elder_friendly || rr.summary);
        el.reportElder.textContent = rr.elder_friendly || rr.summary || '';

        // 章节
        el.reportSections.textContent = '';
        var sections = rr.sections || [];
        sections.forEach(function (sec) {
            if (!sec || !sec.content) return;
            var block = document.createElement('div');
            block.className = 'report-section-block';
            var h = document.createElement('h4');
            h.textContent = sec.heading || '说明';
            block.appendChild(h);
            var p = document.createElement('p');
            p.textContent = sec.content;
            block.appendChild(p);
            if (sec.citations && sec.citations.length) {
                var citList = document.createElement('div');
                citList.className = 'report-section-citations';
                sec.citations.forEach(function (citation) {
                    appendCitationDetail(citList, citation);
                });
                if (citList.childElementCount) block.appendChild(citList);
            }
            el.reportSections.appendChild(block);
        });

        // 来源引用
        var audit = report.citation_audit || {};
        el.reportCitations.hidden = true;
        el.reportCitationList.textContent = '';
        if (audit.total > 0) {
            el.reportCitations.hidden = false;
            var info = document.createElement('p');
            info.className = 'report-cite-stat';
            info.textContent = '共 ' + audit.total + ' 条引用：可核验证据 ' + audit.evidence
                + '、推断 ' + audit.inference + '、不确定 ' + audit.uncertain;
            el.reportCitationList.appendChild(info);
            if (audit.evidence === 0) {
                var caution = document.createElement('p');
                caution.className = 'report-cite-caution';
                caution.textContent = '当前没有可核验证据，相关表述应视为不确定信息。';
                el.reportCitationList.appendChild(caution);
            }
        }

        // 免责声明
        el.reportDisclaimer.textContent = report.disclaimer || '';
    }

    function confLabel(conf) {
        return { high: '较高', medium: '中等', low: '较低' }[conf] || '未知';
    }

    function deriveObservationAdvice(detail) {
        var forecast = detail && detail.forecast ? detail.forecast : {};
        var risk = detail && detail.risk ? detail.risk : {};
        var fiveDayReturn = forecast.return_5d_pct;

        if (risk.level === 'high') {
            return {
                tone: 'high',
                status: '高风险',
                reason: '模型标为高风险，历史波动与回撤可能较大；本页仅提示重点观察风险变化。'
            };
        }
        if (!Number.isFinite(fiveDayReturn) || forecast.confidence === 'low') {
            return {
                tone: 'medium',
                status: '谨慎观察',
                reason: '5 日统计收益不可用或样本置信度较低，无法形成稳定的短线参考。'
            };
        }
        if (risk.level === 'low' && fiveDayReturn > 0) {
            return {
                tone: 'low',
                status: '低风险观察',
                reason: '风险等级较低，历史相似样本的 5 日平均收益为 ' + formatPct(fiveDayReturn)
                    + '；仍需结合新数据与正式公告持续观察。'
            };
        }
        return {
            tone: 'medium',
            status: '谨慎观察',
            reason: '风险或统计收益尚未同时满足低风险正收益条件，建议结合风险、样本和公告继续观察。'
        };
    }

    function resetObservationAdvice() {
        el.analysisObservation.hidden = true;
        el.analysisObservation.className = 'analysis-observation';
        el.analysisObservationStatus.textContent = '--';
        el.analysisObservationReason.textContent = '--';
    }

    function renderObservationAdvice(detail) {
        var advice = deriveObservationAdvice(detail);
        el.analysisObservation.hidden = false;
        el.analysisObservation.className = 'analysis-observation observation-' + advice.tone;
        el.analysisObservationStatus.textContent = advice.status;
        el.analysisObservationReason.textContent = advice.reason;
    }

    function showAnalysisLoading() {
        el.analysisDetail.hidden = false;
        resetObservationAdvice();
        el.analysisSummary.textContent = '正在读取风险、行业和历史相似走势...';
        el.analysisRiskBadge.className = 'risk-badge risk-medium';
        el.analysisRiskBadge.textContent = '分析中';
        [el.analysisCompositeScore, el.analysisRiskScore, el.analysisReturn3d,
            el.analysisReturn5d, el.analysisUpProbability].forEach(function (node) {
                node.textContent = '--';
                node.className = '';
            });
        el.analysisReasons.textContent = '';
        el.analysisMarketMetrics.textContent = '';
        el.similarityGrid.textContent = '';
        el.similarityConfidence.textContent = '--';
        el.fundamentalSection.hidden = true;
        hideResearchReport();
        el.analysisDisclaimer.textContent = '';
    }

    function showAnalysisError(message) {
        showAnalysisLoading();
        el.analysisSummary.textContent = message;
        el.analysisRiskBadge.textContent = '分析不可用';
    }

    function renderAnalysisDetail(detail) {
        var forecast = detail.forecast || {};
        var risk = detail.risk || {};
        var scores = detail.scores || {};
        var similarity = detail.similarity || {};
        var fiveDayReturn = forecast.return_5d_pct;
        var fiveDayProbability = forecast.up_probability_5d_pct;

        el.analysisDetail.hidden = false;
        renderObservationAdvice(detail);
        if (Number.isFinite(fiveDayReturn)) {
            el.analysisSummary.textContent = '历史相似样本中，未来 5 日平均收益为 '
                + formatPct(fiveDayReturn) + '，上涨样本占 ' + formatProbability(fiveDayProbability)
                + '；当前技术状态为' + trendLabel(detail.technical && detail.technical.trend) + '。';
        } else {
            el.analysisSummary.textContent = '历史相似样本不足，当前仅展示风险和技术状态。';
        }

        // 赌注类型与策略建议（师门框架融合 v2.6）
        var betInfo = state.betTypes && detail.code ? state.betTypes[detail.code] : null;
        if (betInfo) {
            el.analysisSummary.textContent += ' ｜ ' + betInfo.advice;
        }

        // 领先指标信号（005 融合：前沿供需拐点，真实数据才参与评分）
        var leadingDetail = detail.leading || {};
        if (leadingDetail.data_source === 'akshare') {
            var mm = leadingDetail.momentum_metrics || {};
            var ledTxt = mm.inflection_flag === 'positive_reversal' ? '触底反转（供需拐点向上）'
                : mm.inflection_flag === 'negative_reversal' ? '见顶回落（供需拐点向下）'
                : mm.momentum === 'accelerating' ? '动能加速'
                : mm.momentum === 'decelerating' ? '动能减速' : '中性';
            el.analysisSummary.textContent += ' ｜ 领先指标：' + ledTxt
                + '（' + (leadingDetail.source_name || '真实数据') + '）';
        } else if (leadingDetail.data_source) {
            el.analysisSummary.textContent += ' ｜ 领先指标：暂无真实数据（合成降级，不参与评分）';
        }

        el.analysisRiskBadge.className = 'risk-badge ' + riskClass(risk.level);
        el.analysisRiskBadge.textContent = (risk.label || '未知风险') + ' ' + formatScore(scores.risk);
        el.analysisCompositeScore.textContent = formatScore(scores.risk_adjusted);
        el.analysisRiskScore.textContent = formatScore(scores.risk);
        setReturnMetric(el.analysisReturn3d, forecast.return_3d_pct);
        setReturnMetric(el.analysisReturn5d, forecast.return_5d_pct);
        el.analysisUpProbability.textContent = formatProbability(forecast.up_probability_5d_pct);

        renderAnalysisReasons(detail.reasons || []);
        renderMarketMetrics(detail);
        renderSimilarity(similarity);
        renderFundamental(detail.fundamental);
        el.analysisDisclaimer.textContent = detail.disclaimer
            || '基于历史日线的统计分析，仅用于学习和研究，不构成投资建议或收益保证。';
    }

    // ---- 基本面渲染 ----
    function renderFundamental(fundamental) {
        el.fundamentalSection.hidden = true;
        el.fundamentalDimensions.innerHTML = '';
        el.fundamentalMetrics.innerHTML = '';

        if (!fundamental || typeof fundamental.score !== 'number') {
            el.fundamentalSection.hidden = true;
            return;
        }

        el.fundamentalSection.hidden = false;

        var reportDate = fundamental.report_date || '--';
        el.fundamentalReportDate.textContent = '财务报告期：' + reportDate
            + (fundamental.dual_view && fundamental.dual_view.cycle_note ? ' · ' + fundamental.dual_view.cycle_note : '');

        el.fundamentalScoreBadge.textContent = '基本面 ' + fundamental.score.toFixed(1);
        el.fundamentalScoreBadge.className = 'confidence-badge'
            + (fundamental.score >= 60 ? ' score-high'
                : fundamental.score >= 40 ? ' score-mid' : ' score-low');

        // 四维度
        var dims = fundamental.dimensions || {};
        var dimLabels = {
            asset_quality: '资产质量',
            liability_safety: '负债安全',
            profit_quality: '盈利质量',
            cash_health: '现金健康'
        };
        Object.keys(dimLabels).forEach(function (key) {
            var val = dims[key];
            var block = document.createElement('div');
            block.className = 'fundamental-dim';
            var label = document.createElement('span');
            label.textContent = dimLabels[key];
            var barWrap = document.createElement('div');
            barWrap.className = 'fundamental-bar-wrap';
            var bar = document.createElement('div');
            bar.className = 'fundamental-bar ' + (val >= 60 ? 'score-high' : val >= 40 ? 'score-mid' : 'score-low');
            bar.style.width = (Number.isFinite(val) ? val : 0) + '%';
            barWrap.appendChild(bar);
            var value = document.createElement('strong');
            value.textContent = Number.isFinite(val) ? val.toFixed(1) : '--';
            block.appendChild(label);
            block.appendChild(barWrap);
            block.appendChild(value);
            el.fundamentalDimensions.appendChild(block);
        });

        // 关键指标
        var m = fundamental.metrics || {};
        var metricRows = [
            ['资产负债率', fmtRatio(m.debt_ratio)],
            ['存货+预付占总资产', fmtRatio(m.inventory_prepay_ratio)],
            ['应收账款/营收', fmtRatio(m.receivable_revenue)],
            ['ROE', fmtPercent(m.roe !== null && m.roe !== undefined ? m.roe * 100 : null)],
            ['毛利率', fmtPercent(m.gross_margin)],
            ['净利润同比', fmtPercent(m.netprofit_yoy)],
            ['经营现金流/净利润', Number.isFinite(m.ocf_np_ratio) ? Number(m.ocf_np_ratio).toFixed(2) : '--'],
            ['总资产同比', fmtPercent(m.total_assets_yoy)],
            ['未分配利润/归母权益', fmtRatio(m.retained_profit_equity)]
        ];
        metricRows.forEach(function (row) {
            var cell = document.createElement('div');
            cell.className = 'fundamental-metric';
            var name = document.createElement('span');
            var value = document.createElement('strong');
            name.textContent = row[0];
            value.textContent = row[1];
            cell.appendChild(name);
            cell.appendChild(value);
            el.fundamentalMetrics.appendChild(cell);
        });

        // 两面解读
        if (fundamental.dual_view) {
            el.fundamentalPositiveView.textContent = fundamental.dual_view.positive_view || '--';
            el.fundamentalNegativeView.textContent = fundamental.dual_view.negative_view || '--';
        }
    }

    function fmtRatio(v) {
        return Number.isFinite(v) ? (Number(v) * 100).toFixed(1) + '%' : '--';
    }

    function fmtPercent(v) {
        return Number.isFinite(v) ? (Number(v) > 0 ? '+' : '') + Number(v).toFixed(1) + '%' : '--';
    }

    function setReturnMetric(node, value) {
        node.textContent = formatPct(value);
        node.className = returnClass(value);
    }

    function renderAnalysisReasons(reasons) {
        el.analysisReasons.textContent = '';
        var seen = new Set();
        var unique = reasons.filter(function (reason) {
            var titleText = String(reason.title || '');
            var key = titleText.includes('回撤') ? '回撤'
                : (titleText.includes('波动') ? '波动' : titleText + '|' + String(reason.detail || ''));
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
        }).slice(0, 5);

        if (unique.length === 0) {
            var empty = document.createElement('p');
            empty.className = 'analysis-summary';
            empty.textContent = '当前没有形成贡献度明显的加分或扣分项。';
            el.analysisReasons.appendChild(empty);
            return;
        }

        unique.forEach(function (reason) {
            var item = document.createElement('div');
            item.className = 'analysis-reason-item ' + (reason.type || 'warning');
            var title = document.createElement('strong');
            title.textContent = reason.title || '评分依据';
            var detail = document.createElement('p');
            detail.textContent = reason.detail || '';
            item.appendChild(title);
            item.appendChild(detail);
            el.analysisReasons.appendChild(item);
        });
    }

    function renderMarketMetrics(detail) {
        el.analysisMarketMetrics.textContent = '';
        var technical = detail.technical || {};
        var industry = detail.industry || {};
        var risk = detail.risk || {};
        var scores = detail.scores || {};
        var reference = industry.reference_type === 'industry' ? '行业板块' : '指数参照';
        var metrics = [
            ['技术状态', trendLabel(technical.trend)],
            ['技术分', formatScore(scores.technical)],
            ['RSI14', Number.isFinite(technical.rsi14) ? Number(technical.rsi14).toFixed(1) : '--'],
            ['近20日收益', formatPct(technical.return_20d_pct)],
            ['近5日量能比', Number.isFinite(technical.volume_ratio_5d) ? Number(technical.volume_ratio_5d).toFixed(2) + '倍' : '--'],
            ['行业/参照', (industry.name || '未分类') + ' · ' + reference],
            ['行业分', formatScore(scores.industry)],
            ['行业20日表现', formatPct(industry.return_20d_pct)],
            ['20日年化波动', formatUnsignedPct(risk.annualized_volatility_20d_pct)],
            ['60日最大回撤', formatPct(risk.max_drawdown_60d_pct)]
        ];

        metrics.forEach(function (metric) {
            var row = document.createElement('div');
            row.className = 'analysis-metric-row';
            var term = document.createElement('dt');
            var value = document.createElement('dd');
            term.textContent = metric[0];
            value.textContent = metric[1];
            row.appendChild(term);
            row.appendChild(value);
            el.analysisMarketMetrics.appendChild(row);
        });
    }

    function formatUnsignedPct(value) {
        return Number.isFinite(value) ? Number(value).toFixed(2) + '%' : '--';
    }

    function renderSimilarity(similarity) {
        el.similarityGrid.textContent = '';
        var sampleSize = similarity.sample_size || 0;
        el.similarityConfidence.textContent = confidenceLabel(similarity.confidence)
            + ' · ' + sampleSize + ' 个样本';
        el.similarityGrid.appendChild(createSimilarityHorizon('未来 3 日', similarity.horizon_3d || {}));
        el.similarityGrid.appendChild(createSimilarityHorizon('未来 5 日', similarity.horizon_5d || {}));
    }

    function createSimilarityHorizon(label, data) {
        var block = document.createElement('div');
        block.className = 'similarity-horizon';
        var title = document.createElement('h4');
        title.textContent = label;
        block.appendChild(title);
        var values = document.createElement('div');
        values.className = 'similarity-values';
        [
            ['上涨样本', formatProbability(data.up_probability_pct)],
            ['平均收益', formatPct(data.average_return_pct)],
            ['中位收益', formatPct(data.median_return_pct)],
            ['最好结果', formatPct(data.best_return_pct)],
            ['最差结果', formatPct(data.worst_return_pct)]
        ].forEach(function (entry) {
            var cell = document.createElement('div');
            cell.className = 'similarity-value';
            var name = document.createElement('span');
            var value = document.createElement('strong');
            name.textContent = entry[0];
            value.textContent = entry[1];
            cell.appendChild(name);
            cell.appendChild(value);
            values.appendChild(cell);
        });
        block.appendChild(values);
        return block;
    }

    function highlightRankingSelection() {
        document.querySelectorAll('[data-analysis-code]').forEach(function (node) {
            node.classList.toggle('active', node.dataset.analysisCode === state.analysisSelectedCode);
        });
    }

    // 运行初始化
    // ---------- 模拟盘对比 ----------
    function _paperPct(v) {
        if (v === null || v === undefined || isNaN(Number(v))) return '--';
        var n = Number(v);
        return (n > 0 ? '+' : '') + n.toFixed(2) + '%';
    }

    function buildPaperSeries(records) {
        if (!records || !records.length) return [];
        var out = [];
        var nav = 100;
        records.forEach(function (r) {
            // 兼容字段名：portfolio_return_pct（新）或 daily_return_pct（旧）
            var dailyReturn = r.portfolio_return_pct != null ? r.portfolio_return_pct : (r.daily_return_pct || 0);
            nav = nav * (1 + dailyReturn / 100);
            out.push({ date: r.trade_date, nav: nav, daily: dailyReturn });
        });
        return out;
    }

    async function loadPaperSeries() {
        var manifest = state.paperManifest;
        var list = (manifest && manifest.portfolios) || [];
        var loaded = [];
        for (var i = 0; i < list.length; i++) {
            var p = list[i];
            try {
                var res = await fetch(dataUrl('data/' + p.file));
                if (!res.ok) continue;
                var j = await res.json();
                loaded.push({
                    key: p.key,
                    name: p.name,
                    color: p.color,
                    description: p.description,
                    isBenchmark: !!p.is_benchmark,
                    points: buildPaperSeries(j.records || [])
                });
            } catch (e) {
                console.warn('加载组合数据失败:', p.file, e);
            }
        }
        state.paperSeries = loaded;
    }

    function renderPaper() {
        var portfolios = state.paperSeries || [];
        if (!portfolios.length) {
            el.paperMeta.textContent = '暂无模拟盘数据，每日收盘后自动记录。';
            return;
        }
        var starts = portfolios.map(function (s) {
            return s.points.length ? s.points[0].date : null;
        }).filter(Boolean);
        el.paperMeta.textContent = starts.length
            ? ('对照起点：' + starts.join(' / ') + '，每日收盘后自动更新。')
            : '';

        el.paperCards.innerHTML = portfolios.map(function (s) {
            var last = s.points.length ? s.points[s.points.length - 1] : null;
            var first = s.points.length ? s.points[0] : null;
            var total = (last && first) ? (last.nav / 100 - 1) * 100 : null;
            return '<div class="paper-card" style="border-top-color:' + s.color + '">' +
                '<div class="paper-card-name">' + (s.isBenchmark ? '📊 ' : '') + s.name + '</div>' +
                '<div class="paper-card-row">当日 <span class="paper-card-value">' + _paperPct(last ? last.daily : null) + '</span></div>' +
                '<div class="paper-card-row">累计 <span class="paper-card-value">' + _paperPct(total) + '</span></div>' +
                '<div class="paper-card-row">' + s.points.length + ' 个交易日' + (first ? '（自 ' + first.date + '）' : '') + '</div>' +
                '</div>';
        }).join('');

        renderPaperCurve(portfolios);

        var thead = document.querySelector('#paper-compare-wrap thead tr');
        if (thead) {
            thead.innerHTML = '<th>日期</th>' + portfolios.map(function (s) {
                return '<th>' + s.name + '</th>';
            }).join('');
        }
        var dates = {};
        portfolios.forEach(function (s) {
            s.points.forEach(function (p) {
                dates[p.date] = dates[p.date] || {};
                dates[p.date][s.key] = p.daily;
            });
        });
        var dateList = Object.keys(dates).sort();
        if (dateList.length) {
            el.paperCompareWrap.hidden = false;
            el.paperCompareTbody.innerHTML = dateList.slice().reverse().map(function (d) {
                return '<tr><td>' + d + '</td>' + portfolios.map(function (s) {
                    return '<td>' + _paperPct(dates[d][s.key]) + '</td>';
                }).join('') + '</tr>';
            }).join('');
        }
    }

    function renderPaperCurve(portfolios) {
        var W = 720, H = 260, padL = 46, padR = 12, padT = 16, padB = 28;
        var allDates = {};
        portfolios.forEach(function (s) {
            s.points.forEach(function (p) { allDates[p.date] = 1; });
        });
        var dates = Object.keys(allDates).sort();
        if (dates.length < 2) {
            el.paperCurve.innerHTML = '<div class="paper-empty">数据不足，暂无法绘制曲线</div>';
            return;
        }
        function align(s) {
            var map = {};
            s.points.forEach(function (p) { map[p.date] = p.nav; });
            var last = 100;
            return dates.map(function (d) { last = map[d] || last; return last; });
        }
        var lines = portfolios.map(function (s) {
            return { key: s.key, name: s.name, color: s.color, vals: align(s) };
        });
        var allVals = [100];
        lines.forEach(function (l) { allVals = allVals.concat(l.vals); });
        var minV = Math.min.apply(null, allVals) - 2;
        var maxV = Math.max.apply(null, allVals) + 2;
        function x(i) { return padL + (dates.length > 1 ? i / (dates.length - 1) * (W - padL - padR) : 0); }
        function y(v) { return padT + (maxV - v) / (maxV - minV) * (H - padT - padB); }
        function path(vals) {
            return vals.map(function (v, i) {
                return (i ? 'L' : 'M') + x(i).toFixed(1) + ',' + y(v).toFixed(1);
            }).join(' ');
        }
        var gridY = '';
        for (var g = 0; g <= 4; g++) {
            var gy = padT + g / 4 * (H - padT - padB);
            var gv = maxV - (maxV - minV) * g / 4;
            gridY += '<line x1="' + padL + '" y1="' + gy + '" x2="' + (W - padR) + '" y2="' + gy + '" stroke="#e5e7eb" stroke-width="1"/>' +
                '<text x="' + (padL - 8) + '" y="' + (gy + 4) + '" text-anchor="end" font-size="11" fill="#6b7280">' + gv.toFixed(0) + '</text>';
        }
        var legend = lines.map(function (l) {
            return '<span class="paper-legend-item"><i style="background:' + l.color + '"></i>' + l.name + '</span>';
        }).join('');
        var xEvery = Math.max(1, Math.floor(dates.length / 6));
        var xLabels = dates.map(function (d, i) {
            if (i % xEvery !== 0 && i !== dates.length - 1) return '';
            return '<text x="' + x(i).toFixed(1) + '" y="' + (H - 8) + '" text-anchor="middle" font-size="10" fill="#6b7280">' + d.slice(5) + '</text>';
        }).join('');
        var svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="累计净值曲线" style="width:100%;height:auto">' +
            gridY + xLabels +
            lines.map(function (l) {
                return '<path d="' + path(l.vals) + '" fill="none" stroke="' + l.color + '" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>';
            }).join('') +
            '</svg><div class="paper-legend">' + legend + '</div>';
        el.paperCurve.innerHTML = svg;
    }

    init();

    // ============================================================
    // 查询模块 —— 单股查询 + 大盘对比
    // ============================================================

    // 本地联调使用 Flask 开发服务，GitHub Pages 使用独立部署的 API。
    var queryMeta = null; // 缓存最近一次查询的 meta 信息

    function initQueryBar() {
        // 设置默认日期为一年前
        var d = new Date();
        d.setFullYear(d.getFullYear() - 1);
        el.queryDateInput.value = d.toISOString().substring(0, 10);

        // 查询按钮点击
        el.queryGoBtn.addEventListener('click', doQuery);

        // 添加到自选股按钮
        el.addToWatchlistBtn.addEventListener('click', function () {
            if (queryMeta) {
                showAddToWatchlistModal(queryMeta.stock_code, queryMeta.stock_name, queryMeta.stock_type || 'stock');
            }
        });

        // 回车键触发查询
        el.queryCodeInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') { doQuery(); }
        });
    }

    function doQuery() {
        var code = el.queryCodeInput.value.trim();
        var startDate = el.queryDateInput.value.trim();

        // ---- 输入校验 ----
        if (!code) {
            showQueryHint('⚠️ 请输入股票代码');
            return;
        }
        if (!/^\d{6}$/.test(code)) {
            showQueryHint('⚠️ 股票代码必须是6位数字');
            return;
        }
        if (!startDate) {
            showQueryHint('⚠️ 请选择起始日期');
            return;
        }

        // ---- 开始查询 ----
        showQueryHint('⏳ 正在查询数据，请稍候...');
        el.queryGoBtn.disabled = true;
        el.queryGoBtn.textContent = '查询中...';
        el.analysisDetail.hidden = true;
        state.analysisSelectedCode = null;
        highlightRankingSelection();
        showLoadingOverlay();

        var url = API_BASE + '/api/query?code=' + encodeURIComponent(code) + '&start_date=' + encodeURIComponent(startDate);

        fetchWithTimeout(url, null, 20000)
            .then(function (resp) {
                if (!resp.ok) {
                    return resp.json().then(function (data) {
                        throw new Error(data.error || ('HTTP ' + resp.status));
                    });
                }
                return resp.json();
            })
            .then(function (data) {
                el.queryGoBtn.disabled = false;
                el.queryGoBtn.textContent = '查询对比';

                // 标记查询模式
                state.queryActive = true;

                // 缓存 meta 供添加到自选股使用
                queryMeta = data.meta;
                queryMeta.stock_type = data.stock.type;
                state.lastQueryStock = data.stock;

                // 更新查询结果概要
                el.queryResultHeader.style.display = 'block';
                el.queryStockName.textContent = data.meta.stock_name || data.stock.name;
                el.queryStockCode.textContent = code;
                el.queryResultHint.textContent = '对比指数：' + data.meta.index_name
                    + ' (' + data.meta.index_code + ')'
                    + ' ｜ 数据范围：' + data.meta.start_date + ' ~ ' + data.meta.end_date;

                // 隐藏原有 detail-header（来自自选股列表的），显示查询结果的 header
                el.detailHeader.style.display = 'none';

                // 显示指数图表卡片
                el.indexChartCard.style.display = 'block';

                // 渲染个股 K 线
                renderStockChart(data.stock);

                // 渲染指数对比图
                if (data.index) {
                    renderIndexChart(data.index);
                    el.indexChartLabel.textContent = '📊 大盘指数对比 —— ' + data.meta.index_name + ' (' + data.meta.index_code + ')';
                } else {
                    showQueryHint('ℹ️ 指数数据暂未获取到，仅展示个股 K 线');
                    el.indexChartCard.style.display = 'none';
                }

                // 更新指数标签
                updateQueryHintForCode(code, data.meta.index_name);

                hideOverlay();

                showQueryHint('✅ 查询成功！个股 ' + data.stock.name + ' + ' + data.meta.index_name + ' 对比');
                navigateTo('detail');
            })
            .catch(function (err) {
                el.queryGoBtn.disabled = false;
                el.queryGoBtn.textContent = '查询对比';
                hideOverlay();
                var detail = err.message || '查询失败，请检查网络连接或后端服务';
                if (!isLocal && detail === 'Failed to fetch') {
                    detail = '在线查询服务暂不可用，请稍后重试';
                }
                showQueryHint('❌ ' + detail);
                console.error('Query error:', err);
            });
    }

    function renderStockChart(data) {
        // 复用现有 renderChart 逻辑，但不改变 state.selectedCode
        var dates = data.dates || [];
        var kline = data.kline || [];
        var volume = data.volume || [];
        var ma5 = data.ma5 || [];
        var ma10 = data.ma10 || [];
        var ma20 = data.ma20 || [];
        var ma60 = data.ma60 || [];

        if (dates.length === 0) {
            showOverlay('未找到该股票的 K 线数据', true);
            return;
        }

        // 切片最多 250 天
        var MAX_POINTS = 250;
        var startIndex = Math.max(0, dates.length - MAX_POINTS);

        state.activeData.dates = dates.slice(startIndex);
        state.activeData.kline = kline.slice(startIndex);
        state.activeData.volume = volume.slice(startIndex);
        state.activeData.ma5 = ma5.slice(startIndex);
        state.activeData.ma10 = ma10.slice(startIndex);
        state.activeData.ma20 = ma20.slice(startIndex);
        state.activeData.ma60 = ma60.slice(startIndex);

        // 成交量颜色
        var volumeData = state.activeData.volume.map(function (vol, idx) {
            var dayKline = state.activeData.kline[idx];
            return {
                value: vol,
                itemStyle: {
                    color: dayKline[1] >= dayKline[0] ? '#e63946' : '#10b981'
                }
            };
        });

        if (!state.chart) {
            state.chart = echarts.init(el.chartElement);
        }

        var option = {
            animation: false,
            tooltip: buildTooltipConfig(),
            grid: [
                { left: '8%', right: '4%', top: '8%', height: '56%' },
                { left: '8%', right: '4%', top: '72%', height: '16%' }
            ],
            xAxis: [
                {
                    type: 'category',
                    data: state.activeData.dates,
                    boundaryGap: false,
                    axisLine: { onZero: false, lineStyle: { color: '#9ca3af' } },
                    splitLine: { show: true, lineStyle: { color: '#f3f4f6' } },
                    axisLabel: { fontSize: 13, color: '#4b5563' },
                    min: 'dataMin',
                    max: 'dataMax'
                },
                {
                    type: 'category',
                    gridIndex: 1,
                    data: state.activeData.dates,
                    boundaryGap: false,
                    axisLine: { onZero: false, lineStyle: { color: '#9ca3af' } },
                    axisTick: { show: false },
                    splitLine: { show: false },
                    axisLabel: { show: false }
                }
            ],
            yAxis: [
                {
                    scale: true,
                    axisLine: { lineStyle: { color: '#9ca3af' } },
                    splitArea: { show: false },
                    splitLine: { show: true, lineStyle: { color: '#f3f4f6' } },
                    axisLabel: { fontSize: 13, color: '#4b5563', formatter: '{value}' }
                },
                {
                    scale: true,
                    gridIndex: 1,
                    splitNumber: 2,
                    axisLabel: { show: false },
                    axisLine: { show: false },
                    axisTick: { show: false },
                    splitLine: { show: false }
                }
            ],
            dataZoom: [
                { type: 'inside', xAxisIndex: [0, 1], start: 60, end: 100 },
                { show: true, xAxisIndex: [0, 1], type: 'slider', top: '91%', height: '5%', start: 60, end: 100, textStyle: { color: '#6b7280' } }
            ],
            series: [
                {
                    name: '日K',
                    type: 'candlestick',
                    data: state.activeData.kline,
                    itemStyle: { color: '#e63946', color0: '#10b981', borderColor: '#e63946', borderColor0: '#10b981' }
                },
                { name: 'MA5',  type: 'line', data: state.activeData.ma5,  smooth: true, showSymbol: false, lineStyle: { width: 2, color: '#eab308', opacity: 0.8 } },
                { name: 'MA10', type: 'line', data: state.activeData.ma10, smooth: true, showSymbol: false, lineStyle: { width: 2, color: '#ec4899', opacity: 0.8 } },
                { name: 'MA20', type: 'line', data: state.activeData.ma20, smooth: true, showSymbol: false, lineStyle: { width: 2, color: '#3b82f6', opacity: 0.8 } },
                { name: 'MA60', type: 'line', data: state.activeData.ma60, smooth: true, showSymbol: false, lineStyle: { width: 2.5, color: '#14b8a6', opacity: 0.8 } },
                { name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: volumeData }
            ]
        };

        state.chart.setOption(option, true);
    }

    function buildTooltipConfig() {
        return {
            trigger: 'axis',
            axisPointer: { type: 'cross', label: { backgroundColor: '#6b7280', fontSize: 13 } },
            backgroundColor: 'rgba(255, 255, 255, 0.96)',
            borderColor: '#cbd5e1',
            borderWidth: 1,
            padding: 12,
            textStyle: { color: '#1f2937' },
            position: function (pos, params, dom, rect, size) {
                var obj = { top: 30 };
                obj[['left', 'right'][+(pos[0] < size.viewSize[0] / 2)]] = 30;
                return obj;
            },
            formatter: function (params) {
                if (params.length === 0) return '';
                var idx = params[0].dataIndex;
                var date = state.activeData.dates[idx];
                var dayKline = state.activeData.kline[idx];
                var vol = state.activeData.volume[idx];
                var open = dayKline[0], close = dayKline[1], low = dayKline[2], high = dayKline[3];
                var m5 = state.activeData.ma5[idx], m10 = state.activeData.ma10[idx];
                var m20 = state.activeData.ma20[idx], m60 = state.activeData.ma60[idx];
                var changeVal = close - open;
                var changePct = ((changeVal / open) * 100).toFixed(2);
                var changeClass = changeVal >= 0 ? 'text-up' : 'text-down';
                var changeSign = changeVal >= 0 ? '+' : '';
                var arrow = changeVal >= 0 ? '↑' : '↓';
                var toS = function (v) { return (v !== null && v !== undefined) ? v.toFixed(2) : '--'; };

                return '<div style="font-family: var(--font-sans); min-width: 200px; font-size: 15px; line-height: 1.6;">' +
                    '<div style="font-weight: bold; font-size: 16px; margin-bottom: 6px; border-bottom: 1px solid #e5e7eb; padding-bottom: 4px;">日期：' + date + '</div>' +
                    '<div style="display: flex; justify-content: space-between;"><span>开盘/收盘:</span><strong>' + open.toFixed(2) + ' / ' + close.toFixed(2) + '</strong></div>' +
                    '<div style="display: flex; justify-content: space-between;"><span>单日涨跌:</span><strong class="' + changeClass + '">' + changeSign + changePct + '% ' + arrow + '</strong></div>' +
                    '<div style="display: flex; justify-content: space-between;"><span>最高/最低:</span><span>' + high.toFixed(2) + ' / ' + low.toFixed(2) + '</span></div>' +
                    '<div style="display: flex; justify-content: space-between; margin-bottom: 6px;"><span>成交量:</span><span>' + (vol / 10000).toFixed(2) + ' 万手</span></div>' +
                    '<div style="border-top: 1px dashed #e5e7eb; padding-top: 4px; font-size: 14px;">' +
                    '<span style="color:#eab308">●</span> MA5: ' + toS(m5) + '<br/>' +
                    '<span style="color:#ec4899">●</span> MA10: ' + toS(m10) + '<br/>' +
                    '<span style="color:#3b82f6">●</span> MA20: ' + toS(m20) + '<br/>' +
                    '<span style="color:#14b8a6">●</span> MA60: ' + toS(m60) + '</div></div>';
            }
        };
    }

    function renderIndexChart(data) {
        // 指数用折线图展示趋势，而不是蜡烛图
        var dates = data.dates || [];
        var kline = data.kline || [];
        var volume = data.volume || [];

        if (dates.length === 0) return;

        // 与个股使用相同的切片逻辑
        var MAX_POINTS = 250;
        var startIndex = Math.max(0, dates.length - MAX_POINTS);
        var slicedDates = dates.slice(startIndex);
        var slicedKline = kline.slice(startIndex);
        var slicedVolume = volume.slice(startIndex);

        // 提取收盘价作为主折线，外加一个区间带（high-low）
        var closeVals = slicedKline.map(function (k) { return k[1]; });
        var highVals = slicedKline.map(function (k) { return k[3]; });
        var lowVals = slicedKline.map(function (k) { return k[2]; });

        // 计算涨跌颜色：今日收盘 vs 昨日收盘，或 开盘-收盘
        var changeColors = slicedKline.map(function (k, idx) {
            return k[1] >= k[0] ? '#e63946' : '#10b981';
        });

        // 成交量颜色
        var volumeData = slicedVolume.map(function (vol, idx) {
            return {
                value: vol,
                itemStyle: { color: changeColors[idx] }
            };
        });

        // 第一个点用于区间带
        var bandData = slicedKline.map(function (k) { return [k[2], k[3]]; });

        if (!state.indexChart) {
            state.indexChart = echarts.init(el.indexChartElement);
        }

        var option = {
            animation: false,
            tooltip: {
                trigger: 'axis',
                axisPointer: { type: 'cross' },
                backgroundColor: 'rgba(255, 255, 255, 0.96)',
                borderColor: '#cbd5e1',
                borderWidth: 1,
                padding: 10,
                textStyle: { color: '#1f2937' },
                formatter: function (params) {
                    if (!params || params.length === 0) return '';
                    var idx = params[0].dataIndex;
                    var date = slicedDates[idx];
                    var k = slicedKline[idx];
                    var vol = slicedVolume[idx];
                    var chg = k[1] - k[0];
                    var sign = chg >= 0 ? '+' : '';
                    var arrow = chg >= 0 ? '↑' : '↓';
                    return '<div style="font-size: 14px; line-height: 1.7;">' +
                        '<div style="font-weight: bold; font-size: 15px; border-bottom: 1px solid #e5e7eb; padding-bottom: 4px; margin-bottom: 4px;">' + date + '</div>' +
                        '开盘: ' + k[0].toFixed(2) + ' ｜ 收盘: <strong>' + k[1].toFixed(2) + '</strong><br/>' +
                        '最高: ' + k[3].toFixed(2) + ' ｜ 最低: ' + k[2].toFixed(2) + '<br/>' +
                        '涨跌: <strong style="color:' + (chg >= 0 ? '#e63946' : '#10b981') + '">' + sign + chg.toFixed(2) + ' ' + arrow + '</strong><br/>' +
                        '成交量: ' + (vol / 10000).toFixed(2) + ' 万手' +
                        '</div>';
                }
            },
            grid: [
                { left: '8%', right: '4%', top: '8%', height: '56%' },
                { left: '8%', right: '4%', top: '72%', height: '16%' }
            ],
            xAxis: [
                {
                    type: 'category',
                    data: slicedDates,
                    boundaryGap: false,
                    axisLine: { onZero: false, lineStyle: { color: '#9ca3af' } },
                    splitLine: { show: true, lineStyle: { color: '#f3f4f6' } },
                    axisLabel: { fontSize: 13, color: '#4b5563' },
                    min: 'dataMin', max: 'dataMax'
                },
                {
                    type: 'category',
                    gridIndex: 1,
                    data: slicedDates,
                    boundaryGap: false,
                    axisLine: { onZero: false },
                    axisTick: { show: false },
                    splitLine: { show: false },
                    axisLabel: { show: false }
                }
            ],
            yAxis: [
                {
                    scale: true,
                    axisLine: { lineStyle: { color: '#9ca3af' } },
                    splitLine: { show: true, lineStyle: { color: '#f3f4f6' } },
                    axisLabel: { fontSize: 13, color: '#4b5563' }
                },
                {
                    scale: true,
                    gridIndex: 1,
                    splitNumber: 2,
                    axisLabel: { show: false },
                    axisLine: { show: false },
                    axisTick: { show: false },
                    splitLine: { show: false }
                }
            ],
            dataZoom: [
                { type: 'inside', xAxisIndex: [0, 1], start: 60, end: 100 },
                { show: true, xAxisIndex: [0, 1], type: 'slider', top: '91%', height: '5%', start: 60, end: 100, textStyle: { color: '#6b7280' } }
            ],
            series: [
                {
                    name: '区间带',
                    type: 'line',
                    data: closeVals,
                    smooth: false,
                    showSymbol: false,
                    lineStyle: { color: 'transparent' },
                    areaStyle: {
                        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                            { offset: 0, color: 'rgba(230, 57, 70, 0.25)' },
                            { offset: 1, color: 'rgba(16, 185, 129, 0.06)' }
                        ])
                    }
                },
                {
                    name: '收盘价',
                    type: 'line',
                    data: closeVals,
                    smooth: true,
                    showSymbol: false,
                    lineStyle: { width: 2.5, color: '#e63946' },
                    itemStyle: { color: '#e63946' }
                },
                {
                    name: '成交量',
                    type: 'bar',
                    xAxisIndex: 1,
                    yAxisIndex: 1,
                    data: volumeData
                }
            ]
        };

        state.indexChart.setOption(option, true);
    }

    function showQueryHint(msg) {
        el.queryHint.textContent = msg;
        el.queryHint.style.display = 'block';
    }

    function updateQueryHintForCode(code, indexName) {
        var first = code.substring(0, 1);
        if (code.indexOf('688') === 0) first = '688';
        var maps = {
            '6': '沪市主板 → ' + indexName,
            '0': '深市主板 → ' + indexName,
            '3': '创业板 → ' + indexName,
            '688': '科创板 → ' + indexName,
            '5': '沪市基金 → ' + indexName,
            '1': '深市基金 → ' + indexName
        };
        var label = maps[first] || ('其他 → ' + indexName);
        el.queryHint.textContent = '📌 ' + label + ' ｜ 6开头→上证｜0开头→深证｜3开头→创业板｜688→科创50';
    }

    // ============================================================
    // 添加到自选股模块 —— 分类选择弹窗 + API 调用
    // ============================================================

    var addWlModal = {
        modal: document.getElementById('add-watchlist-modal'),
        closeBtn: document.getElementById('add-watchlist-close-btn'),
        cancelBtn: document.getElementById('add-watchlist-cancel-btn'),
        confirmBtn: document.getElementById('add-watchlist-confirm-btn'),
        warn: document.getElementById('add-watchlist-warn'),
        info: document.getElementById('add-watchlist-info'),
        categoryInput: document.getElementById('add-category-select'),
    };
    var addWlPending = null; // {code, name, type}

    // 打开添加到自选股弹窗
    function showAddToWatchlistModal(stockCode, stockName, stockType) {
        addWlPending = {code: stockCode, name: stockName, type: stockType || 'stock'};
        addWlModal.info.innerHTML =
            '<span class="add-watchlist-stock-name">' + escapeHtml(stockName) + '</span>' +
            '<span class="add-watchlist-stock-code">(' + stockCode + ')</span>';
        addWlModal.categoryInput.value = '';
        addWlModal.warn.style.display = 'none';
        addWlModal.modal.style.display = 'flex';
        addWlModal.categoryInput.focus();
    }

    function closeAddWatchlistModal() {
        addWlModal.modal.style.display = 'none';
    }

    function doAddToWatchlist() {
        var category = addWlModal.categoryInput.value.trim();
        if (!addWlPending) return;

        addWlModal.confirmBtn.disabled = true;
        addWlModal.confirmBtn.textContent = '提交中...';

        fetchWithTimeout(API_BASE + '/api/watchlist/add', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                code: addWlPending.code,
                name: addWlPending.name,
                type: addWlPending.type,
                category: category
            })
        })
        .then(function (resp) {
            if (!resp.ok) {
                return resp.json().then(function (data) {
                    var error = new Error(data.error || ('HTTP ' + resp.status));
                    error.status = resp.status;
                    throw error;
                });
            }
            return resp.json();
        })
        .then(function (data) {
            addWlModal.confirmBtn.disabled = false;
            addWlModal.confirmBtn.textContent = '✅ 确认添加';
            closeAddWatchlistModal();
            var verb = data.action === 'updated' ? '已更新' : '已添加';
            upsertWatchlistItem(
                data.item || {
                    code: addWlPending.code,
                    name: addWlPending.name,
                    type: addWlPending.type,
                    category: category
                },
                state.lastQueryStock,
                false
            );
            showQueryHint('✅ ' + verb + ' —— ' + addWlPending.name + ' (' + addWlPending.code + ') → 自选股列表');
        })
        .catch(function (err) {
            addWlModal.confirmBtn.disabled = false;
            addWlModal.confirmBtn.textContent = '✅ 确认添加';
            if (!isLocal) {
                var browserItem = {
                    code: addWlPending.code,
                    name: addWlPending.name,
                    type: addWlPending.type,
                    category: category,
                    storage: 'browser'
                };
                upsertWatchlistItem(browserItem, state.lastQueryStock, true);
                closeAddWatchlistModal();
                showQueryHint('✅ 已保存到当前浏览器 —— ' + addWlPending.name + ' (' + addWlPending.code + ')');
                return;
            }
            addWlModal.warn.textContent = '❌ ' + (err.message || '操作失败');
            addWlModal.warn.style.display = 'block';
            console.error('Add to watchlist error:', err);
        });
    }

    // 弹窗事件绑定
    addWlModal.closeBtn.addEventListener('click', closeAddWatchlistModal);
    addWlModal.cancelBtn.addEventListener('click', closeAddWatchlistModal);
    addWlModal.modal.querySelector('.editor-overlay').addEventListener('click', closeAddWatchlistModal);
    addWlModal.confirmBtn.addEventListener('click', doAddToWatchlist);

    // 预设分类 chips
    var chips = addWlModal.modal.querySelectorAll('.preset-chip');
    chips.forEach(function (chip) {
        chip.addEventListener('click', function () {
            addWlModal.categoryInput.value = chip.dataset.cat;
            addWlModal.categoryInput.focus();
        });
    });

    // ESC 关闭
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && addWlModal.modal.style.display !== 'none') {
            closeAddWatchlistModal();
        }
    });

    // ============================================================
    // 编辑器模块 —— 前端编辑自选股列表，导出 watchlist.csv
    // ============================================================

    const editorEl = {
        modal: document.getElementById('editor-modal'),
        tbody: document.getElementById('editor-tbody'),
        warn: document.getElementById('editor-warn'),
        openBtn: document.getElementById('open-editor-btn'),
        closeBtn: document.getElementById('editor-close-btn'),
        cancelBtn: document.getElementById('editor-cancel-btn'),
        addBtn: document.getElementById('editor-add-row-btn'),
        copyBtn: document.getElementById('editor-copy-btn'),
        downloadBtn: document.getElementById('editor-download-btn'),
    };

    function openEditor() {
        clearWarn();
        editorEl.tbody.innerHTML = '';
        const items = state.summary && state.summary.items ? state.summary.items : [];
        if (items.length === 0) {
            // 无数据时给一行空白
            addEditorRow('');
        } else {
            items.forEach(function (it) {
                var rankingItem = state.ranking && state.ranking.items
                    ? state.ranking.items.find(function (ranked) { return ranked.code === it.code; })
                    : null;
                var watchlistItem = state.watchlist.find(function (configured) {
                    return configured.code === it.code;
                });
                addEditorRow({
                    code: it.code,
                    name: it.name,
                    type: it.type,
                    category: watchlistItem
                        ? watchlistItem.category
                        : (rankingItem ? rankingItem.category : '')
                });
            });
        }
        editorEl.modal.style.display = 'flex';
    }

    function closeEditor() {
        editorEl.modal.style.display = 'none';
    }

    function addEditorRow(item) {
        // item: {code?, name?, type?} | string (老兼容) | undefined
        if (typeof item === 'string') { item = {code: item, name: '', type: 'stock'}; }
        if (!item) { item = {code: '', name: '', type: 'stock'}; }

        var tr = document.createElement('tr');
        var code = escapeHtml(item.code || '');
        var name = escapeHtml(item.name || '');
        var category = escapeHtml(item.category || '');
        var typeSel = item.type === 'etf' ? 'etf' : 'stock';

        tr.innerHTML =
            '<td><input class="editor-name" type="text" value="' + name + '" placeholder="股票名称" maxlength="20"></td>' +
            '<td><input class="editor-code" type="text" value="' + code + '" placeholder="6位代码" maxlength="6" pattern="[0-9]*" inputmode="numeric"></td>' +
            '<td><select class="editor-type">' +
                '<option value="stock"' + (typeSel === 'stock' ? ' selected' : '') + '>股票</option>' +
                '<option value="etf"'   + (typeSel === 'etf'   ? ' selected' : '') + '>ETF</option>' +
                '</select></td>' +
            '<td><input class="editor-category" type="text" value="' + category + '" placeholder="如：银行" maxlength="20"></td>' +
            '<td><button class="editor-del-btn" type="button" title="删除此行">✕</button></td>';

        // 删除事件
        tr.querySelector('.editor-del-btn').addEventListener('click', function () {
            tr.remove();
            clearWarn();
        });

        editorEl.tbody.appendChild(tr);
    }

    function escapeHtml(str) {
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function collectEditorRows() {
        var rows = [];
        var trs = editorEl.tbody.querySelectorAll('tr');
        trs.forEach(function (tr) {
            var nameInput = tr.querySelector('.editor-name');
            var codeInput = tr.querySelector('.editor-code');
            var typeSelect = tr.querySelector('.editor-type');
            var categoryInput = tr.querySelector('.editor-category');
            rows.push({
                name: (nameInput.value || '').trim(),
                code: (codeInput.value || '').trim(),
                type: typeSelect.value,
                category: (categoryInput.value || '').trim(),
                nameInput: nameInput,
                codeInput: codeInput,
            });
        });
        return rows;
    }

    function validateEditorRows(rows) {
        // 清除旧错误标记
        editorEl.tbody.querySelectorAll('input.input-error').forEach(function (el) { el.classList.remove('input-error'); });
        var errors = [];
        var seenCodes = {};

        rows.forEach(function (row, i) {
            // 跳过空行（code 和 name 都为空）
            if (row.code === '' && row.name === '') return;

            if (!row.code) {
                errors.push('第' + (i + 1) + '行：代码不能为空');
                if (row.codeInput) row.codeInput.classList.add('input-error');
            } else if (!/^\d{6}$/.test(row.code)) {
                errors.push('第' + (i + 1) + '行："' + row.code + '" 不是6位数字');
                if (row.codeInput) row.codeInput.classList.add('input-error');
            }
            if (!row.name && row.code) {
                errors.push('第' + (i + 1) + '行：名称不能为空（代码 ' + row.code + '）');
                if (row.nameInput) row.nameInput.classList.add('input-error');
            }
            if (row.code && seenCodes[row.code]) {
                errors.push('第' + (i + 1) + '行：代码 "' + row.code + '" 重复');
                if (row.codeInput) row.codeInput.classList.add('input-error');
            }
            if (row.code) seenCodes[row.code] = true;
        });

        return errors;
    }

    function buildWatchlistCsv(rows) {
        var lines = ['code,name,type,category'];
        rows.forEach(function (row) {
            if (row.code || row.name) {
                lines.push(row.code + ',' + row.name + ',' + row.type + ',' + row.category);
            }
        });
        return lines.join('\n');
    }

    function showWarn(msg) {
        editorEl.warn.textContent = msg;
        editorEl.warn.style.display = 'block';
    }

    function clearWarn() {
        editorEl.warn.style.display = 'none';
    }

    function doCopy() {
        var rows = collectEditorRows();
        var errs = validateEditorRows(rows);
        if (errs.length > 0) {
            showWarn('⚠️ ' + errs.join('；'));
            return;
        }
        var csv = buildWatchlistCsv(rows);
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(csv).then(function () {
                showWarn('✅ 已复制到剪贴板！请粘贴到 GitHub 仓库的 watchlist.csv');
            }).catch(function () {
                fallbackCopy(csv);
            });
        } else {
            fallbackCopy(csv);
        }
    }

    function fallbackCopy(text) {
        var ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.left = '-9999px';
        ta.style.top = '-9999px';
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        try {
            document.execCommand('copy');
            showWarn('✅ 已复制到剪贴板！');
        } catch (e) {
            showWarn('⚠️ 复制失败，请改用「下载」按钮');
        }
        document.body.removeChild(ta);
    }

    function doDownload() {
        var rows = collectEditorRows();
        var errs = validateEditorRows(rows);
        if (errs.length > 0) {
            showWarn('⚠️ ' + errs.join('；'));
            return;
        }
        var csv = buildWatchlistCsv(rows);
        var blob = new Blob(['﻿' + csv], {type: 'text/csv;charset=utf-8'});
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = 'watchlist.csv';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        clearWarn();
    }

    // 事件绑定
    editorEl.openBtn.addEventListener('click', openEditor);
    editorEl.closeBtn.addEventListener('click', closeEditor);
    editorEl.cancelBtn.addEventListener('click', closeEditor);
    editorEl.addBtn.addEventListener('click', function () { addEditorRow(); });
    editorEl.copyBtn.addEventListener('click', doCopy);
    editorEl.downloadBtn.addEventListener('click', doDownload);
    // 点击遮罩关闭
    editorEl.modal.querySelector('.editor-overlay').addEventListener('click', closeEditor);
    // ESC 关闭
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && editorEl.modal.style.display !== 'none') {
            closeEditor();
        }
    });
});
