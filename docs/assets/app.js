// 🏠 家庭股票自动看板 - 前端交互逻辑 (docs/assets/app.js)

document.addEventListener('DOMContentLoaded', () => {
    // 全局状态管理
    const state = {
        meta: null,
        summary: null,
        selectedCode: null,
        chart: null,
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
        chartElement: document.getElementById('kline-chart')
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
        });
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
});
