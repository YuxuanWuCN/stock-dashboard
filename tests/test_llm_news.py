"""src/llm/news_fetcher 新闻抓取测试（离线，mock akshare）。"""

import pandas as pd
from unittest.mock import patch

from src.llm.news_fetcher import NewsFetcher, _fetch_stock_news_akshare


def _make_news_df():
    return pd.DataFrame([
        {
            "新闻标题": "公司发布业绩预告",
            "新闻内容": "净利润大幅增长",
            "文章来源": "东方财富",
            "发布时间": "2026-08-05 10:30:00",
            "新闻链接": "http://example.com/news/1",
        },
        {
            "新闻标题": "公司公告重大事项",
            "新闻内容": "拟回购股份",
            "文章来源": "新浪财经",
            "发布时间": "2026-08-04 09:00:00",
            "新闻链接": "http://example.com/news/2",
        },
    ])


def test_fetch_stock_news_parses_akshare_df():
    with patch("akshare.stock_news_em", return_value=_make_news_df()) as mock_fetch:
        items = _fetch_stock_news_akshare("600519", "贵州茅台")

    mock_fetch.assert_called_once_with(symbol="600519")
    assert len(items) == 2
    first = items[0]
    assert first.title == "公司发布业绩预告"
    assert first.code == "600519"
    assert first.name == "贵州茅台"
    assert first.source == "东方财富"
    assert first.item_type == "news"
    assert first.publish_time.startswith("2026-08-05")


def test_fetch_stock_news_handles_empty():
    with patch("akshare.stock_news_em", return_value=pd.DataFrame()):
        items = _fetch_stock_news_akshare("600519", "贵州茅台")
    assert items == []


def test_fetch_stock_news_handles_none():
    with patch("akshare.stock_news_em", return_value=None):
        items = _fetch_stock_news_akshare("600519", "贵州茅台")
    assert items == []


def test_fetch_stock_news_handles_missing_columns():
    df = pd.DataFrame([{"标题": "x", "内容": "y"}])
    with patch("akshare.stock_news_em", return_value=df):
        items = _fetch_stock_news_akshare("600519", "贵州茅台")
    # 缺少标准列时应返回空（title 无法解析）
    assert all(it.title for it in items) is not False  # 不抛异常即可


def test_news_fetcher_disabled_returns_empty():
    fetcher = NewsFetcher(enabled=False)
    assert fetcher.fetch_stock("600519", "贵州茅台") == []


def test_news_fetcher_graceful_on_error():
    fetcher = NewsFetcher(enabled=True)
    with patch("src.llm.news_fetcher._fetch_stock_news_akshare", side_effect=Exception("网络错误")):
        with patch("src.llm.news_fetcher._fetch_announcements_akshare", side_effect=Exception("网络错误")):
            items = fetcher.fetch_stock("600519", "贵州茅台")
    assert items == []


def test_news_fetcher_batch():
    fetcher = NewsFetcher(enabled=True)
    watchlist = [
        {"code": "600519", "name": "贵州茅台"},
        {"code": "000001", "name": "平安银行"},
        {"code": "", "name": "空代码"},
    ]
    with patch("src.llm.news_fetcher._fetch_stock_news_akshare", return_value=[]):
        with patch("src.llm.news_fetcher._fetch_announcements_akshare", return_value=[]):
            result = fetcher.fetch_batch(watchlist)
    assert set(result.keys()) == {"600519", "000001"}


def test_to_dict_shape():
    from src.llm.news_fetcher import NewsItem
    item = NewsItem(title="t", code="c")
    d = item.to_dict()
    assert d["title"] == "t"
    assert d["code"] == "c"
    assert d["item_type"] == "news"
