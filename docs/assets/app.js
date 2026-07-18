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
        indexChartLabel: document.getElementById('index-chart-label')
    };

    // 初始化应用
    async function init() {
        try {
            // 并行加载元数据与汇总数据
            const [metaRes, summaryRes] = await Promise.all([
                fetch('data/meta.json').then(r => r.json()).catch(err => {
                    console.error('Failed to fetch meta.json:', err);
                    return null;
                }),
                fetch('data/summary.json').then(r => r.json()).catch(err => {
                    console.error('Failed to fetch summary.json:', err);
                    return null;
                })
            ]);

            state.meta = metaRes;
            state.summary = summaryRes;

            // 渲染状态栏
            renderStatusBar();

            // 渲染自选股列表
            if (state.summary && state.summary.items && state.summary.items.length > 0) {
                renderStockList();
                
                // 默认选择第一只股票
                const firstItem = state.summary.items[0];
                selectStock(firstItem.code);
            } else {
                el.stockList.innerHTML = '<div class="list-loading text-down">暂无自选股数据</div>';
                showOverlay('未找到自选股汇总数据，请检查后台运行状态。');
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
                selectStock(item.code);
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

    // 运行初始化
    init();

    // ============================================================
    // 查询模块 —— 单股查询 + 大盘对比
    // ============================================================

    // API 地址：本地开发用 127.0.0.1，部署时改为你的后端地址
    var API_BASE = 'http://127.0.0.1:5000';
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
                showQueryHint('❌ ' + (err.message || '查询失败，请检查网络连接或后端服务'));
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
            items.forEach(it => addEditorRow({code: it.code, name: it.name, type: it.type}));
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
        var typeSel = item.type === 'etf' ? 'etf' : 'stock';

        tr.innerHTML =
            '<td><input class="editor-name" type="text" value="' + name + '" placeholder="股票名称" maxlength="20"></td>' +
            '<td><input class="editor-code" type="text" value="' + code + '" placeholder="6位代码" maxlength="6" pattern="[0-9]*" inputmode="numeric"></td>' +
            '<td><select class="editor-type">' +
                '<option value="stock"' + (typeSel === 'stock' ? ' selected' : '') + '>股票</option>' +
                '<option value="etf"'   + (typeSel === 'etf'   ? ' selected' : '') + '>ETF</option>' +
            '</select></td>' +
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
            rows.push({
                name: (nameInput.value || '').trim(),
                code: (codeInput.value || '').trim(),
                type: typeSelect.value,
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
        var lines = ['code,name,type'];
        rows.forEach(function (row) {
            if (row.code || row.name) {
                lines.push(row.code + ',' + row.name + ',' + row.type);
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
