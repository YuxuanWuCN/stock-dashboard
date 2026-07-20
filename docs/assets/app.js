// 🏠 家庭股票自动看板 - 前端交互逻辑 (docs/assets/app.js)

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
        rankingMode: 'balanced',
        rankingSortKey: 'risk_adjusted_score',
        rankingSortDirection: 'desc',
        analysisSelectedCode: null,
        analysisCache: {},
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

    // DOM 元素缓存
    const el = {
        statusBar: document.getElementById('status-bar'),
        statusText: document.getElementById('status-text'),
        stockList: document.getElementById('stock-list'),
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
        analysisDisclaimer: document.getElementById('analysis-disclaimer')
    };

    // 初始化应用
    async function init() {
        try {
            // 并行加载元数据、汇总与 2.0 排行榜数据
            const [metaRes, summaryRes, rankingRes] = await Promise.all([
                fetch('data/meta.json').then(r => r.json()).catch(err => {
                    console.error('Failed to fetch meta.json:', err);
                    return null;
                }),
                fetch('data/summary.json').then(r => r.json()).catch(err => {
                    console.error('Failed to fetch summary.json:', err);
                    return null;
                }),
                fetch('data/analysis/ranking.json').then(r => {
                    if (!r.ok) throw new Error(`HTTP ${r.status}`);
                    return r.json();
                }).catch(err => {
                    console.error('Failed to fetch ranking.json:', err);
                    return null;
                })
            ]);

            state.meta = metaRes;
            state.summary = summaryRes;
            state.ranking = rankingRes;

            // 渲染状态栏
            renderStatusBar();

            // 渲染自选股列表
            if (state.summary && state.summary.items && state.summary.items.length > 0) {
                renderStockList();
                
            } else {
                el.stockList.innerHTML = '<div class="list-loading text-down">暂无自选股数据</div>';
                showOverlay('未找到自选股汇总数据，请检查后台运行状态。');
            }

            initRankingModule();

            const firstRankingItem = state.ranking && state.ranking.items && state.ranking.items[0];
            const firstSummaryItem = state.summary && state.summary.items && state.summary.items[0];
            const initialCode = firstRankingItem ? firstRankingItem.code : (firstSummaryItem ? firstSummaryItem.code : null);
            if (initialCode) {
                await selectTrackedStock(initialCode);
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

    // 渲染股票列表
    function renderStockList() {
        el.stockList.innerHTML = ''; // 清空加载状态
        
        state.summary.items.forEach(item => {
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

            // 类型标签 (股票/ETF)
            const typeLabel = item.type === 'etf' ? '基金' : '股票';
            const typeClass = item.type === 'etf' ? 'etf' : 'stock';

            // 失败或节假日数据可能没有价格/涨跌幅，仍然渲染卡片。
            const hasClose = Number.isFinite(item.last_close);
            const hasChange = Number.isFinite(item.change_pct);
            const closeText = hasClose ? item.last_close.toFixed(2) : '--';
            const changeText = hasChange ? `${changeSign}${item.change_pct.toFixed(2)}% ${arrow}` : '--';
            const changeBg = hasChange ? (item.change_pct >= 0 ? 'up' : 'down') : 'flat';

            // 构建卡片 HTML
            card.innerHTML = `
                <div class="stock-item-left">
                    <span class="stock-item-name">${item.name}</span>
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
                selectTrackedStock(item.code);
                // 移动端体验：点击卡片后平滑滚动到图表区域
                if (window.innerWidth < 900) {
                    el.detailHeader.scrollIntoView({ behavior: 'smooth' });
                }
            });

            // 暂存 DOM 引用，方便高亮切换
            card.dataset.code = item.code;
            el.stockList.appendChild(card);
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
            const response = await fetch(`data/kline/${code}.json`);
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
    // 2.0 排行榜与个股研究模块
    // ============================================================

    function initRankingModule() {
        bindRankingControls();

        if (!state.ranking) {
            showRankingState('分析数据尚未生成，请先运行每日分析任务。', true);
            el.rankingMeta.textContent = '排行榜不可用';
            return;
        }

        var schemaMajor = String(state.ranking.schema_version || '').split('.')[0];
        if (schemaMajor !== '2') {
            showRankingState('分析数据版本不兼容，请重新生成 2.0 数据。', true);
            el.rankingMeta.textContent = '数据版本不兼容';
            return;
        }

        var items = Array.isArray(state.ranking.items) ? state.ranking.items : [];
        populateIndustryFilter(items);

        var generated = state.ranking.generated_at || '--';
        var statusText = state.ranking.status === 'partial'
            ? '部分标的使用旧数据'
            : '全部分析完成';
        el.rankingMeta.textContent = '交易日 ' + (state.ranking.trade_date || '--')
            + ' · ' + items.length + ' 只自选股 · ' + statusText
            + ' · 生成于 ' + generated.substring(0, 16);

        renderRanking();
    }

    function bindRankingControls() {
        if (el.rankingSearch.dataset.bound === 'true') return;
        el.rankingSearch.dataset.bound = 'true';

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

    function renderRankingTableRow(item, rank) {
        var tr = document.createElement('tr');
        tr.tabIndex = 0;
        tr.setAttribute('role', 'button');
        tr.dataset.analysisCode = item.code;
        var firstReason = item.reasons && item.reasons[0];
        var reasonText = firstReason ? firstReason.title + '：' + firstReason.detail : '暂无明确加减分项';
        var risk = item.risk || {};

        tr.innerHTML = '<td class="ranking-number ' + (rank <= 3 ? 'top-three' : '') + '">' + rank + '</td>'
            + '<td><span class="ranking-stock-name">' + escapeHtml(item.name) + '</span>'
            + '<span class="ranking-stock-meta"><span>' + escapeHtml(item.code) + '</span><span>' + escapeHtml(displayCategory(item)) + '</span></span></td>'
            + '<td><span class="score-value">' + formatScore(item.risk_adjusted_score) + '</span></td>'
            + '<td>' + formatForecastHtml(item.forecast && item.forecast.return_3d_pct) + '</td>'
            + '<td>' + formatForecastHtml(item.forecast && item.forecast.return_5d_pct) + '</td>'
            + '<td><span class="risk-badge ' + riskClass(risk.level) + '">' + escapeHtml(risk.label || '未知风险') + ' ' + formatScore(risk.score) + '</span></td>'
            + '<td><span class="ranking-reason">' + escapeHtml(reasonText) + '</span></td>';

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
                var response = await fetch('data/analysis/' + encodeURIComponent(code) + '.json');
                if (!response.ok) throw new Error('HTTP ' + response.status);
                detail = await response.json();
                if (String(detail.schema_version || '').split('.')[0] !== '2') {
                    throw new Error('分析数据版本不兼容');
                }
                state.analysisCache[code] = detail;
            }

            if (state.analysisSelectedCode === code) renderAnalysisDetail(detail);
        } catch (error) {
            console.error('Failed to load analysis for ' + code + ':', error);
            if (state.analysisSelectedCode === code) showAnalysisError('该股票的分析详情暂时无法读取。');
        }
    }

    function showAnalysisLoading() {
        el.analysisDetail.hidden = false;
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
        if (Number.isFinite(fiveDayReturn)) {
            el.analysisSummary.textContent = '历史相似样本中，未来 5 日平均收益为 '
                + formatPct(fiveDayReturn) + '，上涨样本占 ' + formatProbability(fiveDayProbability)
                + '；当前技术状态为' + trendLabel(detail.technical && detail.technical.trend) + '。';
        } else {
            el.analysisSummary.textContent = '历史相似样本不足，当前仅展示风险和技术状态。';
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
        el.analysisDisclaimer.textContent = detail.disclaimer
            || '基于历史日线的统计分析，仅用于学习和研究，不构成投资建议或收益保证。';
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
    init();

    // ============================================================
    // 查询模块 —— 单股查询 + 大盘对比
    // ============================================================

    // 本地联调使用 Flask 开发服务，GitHub Pages 使用独立部署的 API。
    var isLocal = window.location.hostname === '127.0.0.1'
        || window.location.hostname === 'localhost';
    var API_BASE = isLocal
        ? 'http://127.0.0.1:5000'
        : 'https://yuxuanwucn-stock-dashboard-api.onrender.com';
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

        fetch(url)
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

        fetch(API_BASE + '/api/watchlist/add', {
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
                    throw new Error(data.error || ('HTTP ' + resp.status));
                });
            }
            return resp.json();
        })
        .then(function (data) {
            addWlModal.confirmBtn.disabled = false;
            addWlModal.confirmBtn.textContent = '✅ 确认添加';
            closeAddWatchlistModal();
            var verb = data.action === 'updated' ? '已更新' : '已添加';
            showQueryHint('✅ ' + verb + ' —— ' + addWlPending.name + ' (' + addWlPending.code + ') → 自选股列表');
            // 刷新自选股侧边栏（重新 fetch summary）
            refreshStockList();
        })
        .catch(function (err) {
            addWlModal.confirmBtn.disabled = false;
            addWlModal.confirmBtn.textContent = '✅ 确认添加';
            addWlModal.warn.textContent = '❌ ' + (err.message || '操作失败');
            addWlModal.warn.style.display = 'block';
            console.error('Add to watchlist error:', err);
        });
    }

    function refreshStockList() {
        fetch('data/summary.json')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data && data.items) {
                    state.summary = data;
                    renderStockList();
                }
            })
            .catch(function (err) {
                console.warn('刷新自选股列表失败:', err);
                // 本地数据无变化时仍然能用旧列表
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
                addEditorRow({
                    code: it.code,
                    name: it.name,
                    type: it.type,
                    category: rankingItem ? rankingItem.category : ''
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
