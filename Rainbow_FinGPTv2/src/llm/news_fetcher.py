# src/llm/news_fetcher.py —— 新闻与公告抓取
#
# 通过 akshare 公共接口抓取个股新闻与公告，标准化字段后输出。
# 抓取失败不阻断主流程：返回 [] 并记录日志。

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .config import (
    NEWS_ENABLED,
    NEWS_DAYS_BACK,
    ANNOUNCEMENT_DAYS_BACK,
    NEWS_MAX_ITEMS,
    NEWS_REQUEST_INTERVAL,
    NEWS_REQUEST_TIMEOUT,
)

logger = logging.getLogger("stock-dashboard.llm.news")


@dataclass
class NewsItem:
    """标准化新闻/公告条目。"""
    title: str
    content: str = ""
    source: str = ""
    publish_time: str = ""
    url: str = ""
    code: str = ""
    name: str = ""
    item_type: str = "news"      # "news" | "announcement"

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "content": self.content,
            "source": self.source,
            "publish_time": self.publish_time,
            "url": self.url,
            "code": self.code,
            "name": self.name,
            "item_type": self.item_type,
        }


def _safe_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value != value:  # NaN
        return ""
    return str(value).strip()


def _parse_date(value) -> str:
    """把各种日期格式转成 'YYYY-MM-DD'。"""
    s = _safe_str(value)
    if not s:
        return ""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s[:19], fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return s[:10] if len(s) >= 10 else s


def _fetch_stock_news_akshare(code: str, name: str) -> list[NewsItem]:
    """从东方财富抓取个股新闻（akshare.stock_news_em）。"""
    import akshare as ak
    df = ak.stock_news_em(symbol=code)
    if df is None or df.empty:
        return []
    items = []
    for _, row in df.head(NEWS_MAX_ITEMS).iterrows():
        items.append(NewsItem(
            title=_safe_str(row.get("新闻标题") or row.get("title")),
            content=_safe_str(row.get("新闻内容") or row.get("content")),
            source=_safe_str(row.get("文章来源") or row.get("source")),
            publish_time=_parse_date(row.get("发布时间") or row.get("publish_time")),
            url=_safe_str(row.get("新闻链接") or row.get("url")),
            code=code,
            name=name,
            item_type="news",
        ))
    return [it for it in items if it.title]


def _fetch_announcements_akshare(code: str, name: str) -> list[NewsItem]:
    """从东方财富抓取个股公告（akshare.stock_individual_notice_report）。"""
    import akshare as ak
    df = ak.stock_individual_notice_report(security=code, symbol="全部", begin_date=None, end_date=None)
    if df is None or df.empty:
        return []
    items = []
    for _, row in df.head(NEWS_MAX_ITEMS).iterrows():
        items.append(NewsItem(
            title=_safe_str(row.get("公告标题") or row.get("title")),
            content=_safe_str(row.get("公告内容") or row.get("content")),
            source="东方财富",
            publish_time=_parse_date(row.get("公告日期") or row.get("announcement_date") or row.get("date")),
            url=_safe_str(row.get("公告链接") or row.get("url")),
            code=code,
            name=name,
            item_type="announcement",
        ))
    return [it for it in items if it.title]


class NewsFetcher:
    """
    新闻/公告抓取器。

    用法:
        fetcher = NewsFetcher()
        items = fetcher.fetch_stock(code, name)
    """

    def __init__(self, enabled: bool = NEWS_ENABLED):
        self.enabled = enabled
        self._last_request_time = 0.0

    def _throttle(self) -> None:
        """请求间隔限流。"""
        now = time.monotonic()
        delta = now - self._last_request_time
        if delta < NEWS_REQUEST_INTERVAL:
            time.sleep(NEWS_REQUEST_INTERVAL - delta)
        self._last_request_time = time.monotonic()

    def fetch_stock(self, code: str, name: str = "") -> list[NewsItem]:
        """抓取单只标的的新闻 + 公告。失败返回 []。

        使用线程 + 超时保护：akshare 内部请求无超时控制，网络卡死时会
        永久阻塞；这里强制在 NEWS_REQUEST_TIMEOUT 内返回。
        """
        if not self.enabled:
            return []
        return _fetch_with_timeout(code, name)

    def fetch_batch(self, watchlist: list[dict]) -> dict[str, list[NewsItem]]:
        """批量抓取自选股新闻。返回 {code: [NewsItem, ...]}。"""
        result: dict[str, list[NewsItem]] = {}
        for row in watchlist:
            code = str(row.get("code", "")).strip()
            name = str(row.get("name", "")).strip()
            if not code:
                continue
            result[code] = self.fetch_stock(code, name)
        return result


# ============================================================
# 超时保护（akshare 无内部超时，网络卡死会永久阻塞）
# ============================================================

def _fetch_with_timeout(code: str, name: str, timeout: float = NEWS_REQUEST_TIMEOUT) -> list[NewsItem]:
    """在线程中执行抓取，超时强制返回。"""
    import threading

    result: dict = {"items": []}

    def _worker():
        try:
            result["items"] = _fetch_stock_inner(code, name)
        except Exception:
            logger.warning("抓取线程异常 %s(%s)", name, code, exc_info=True)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        logger.warning("新闻抓取超时（%.0fs），跳过 %s(%s)", timeout, name, code)
        return []
    return result.get("items", [])


def _fetch_stock_inner(code: str, name: str) -> list[NewsItem]:
    """实际抓取逻辑（在线程中执行）。"""
    items: list[NewsItem] = []
    try:
        items.extend(_fetch_stock_news_akshare(code, name))
    except Exception:
        logger.warning("新闻抓取失败 %s(%s)", name, code, exc_info=True)
    # ETF 没有个股公告（akshare 接口对 ETF 会抛 KeyError），跳过公告抓取
    is_etf = code.startswith(("5", "1"))
    if not is_etf:
        try:
            items.extend(_fetch_announcements_akshare(code, name))
        except Exception:
            logger.warning("公告抓取失败 %s(%s)", name, code, exc_info=True)
    return items


# ============================================================
# 新闻采样（参考 FinGPT prompt.py sample_news）
# ============================================================

def sample_news(items: list, k: int = 5, seed: Optional[int] = None) -> list:
    """
    从新闻列表中随机采样 k 条（FinGPT 模式）。

    目的：避免把全部新闻塞给 LLM（40条=40次API调用），
    采样固定数量做代表性分析，大幅节省调用量。

    兼容 NewsItem 对象或 dict（to_dict() 输出）。
    seed 固定时结果可复现（测试用）。
    """
    if not items:
        return []
    if len(items) <= k:
        return list(items)

    def _item_type(it) -> str:
        return it.item_type if hasattr(it, "item_type") else it.get("item_type", "news")

    import random
    rng = random.Random(seed)
    # 优先保留公告（item_type=announcement 信息密度高），其余随机采样
    announcements = [it for it in items if _item_type(it) == "announcement"]
    news_only = [it for it in items if _item_type(it) != "announcement"]
    picked = list(announcements[: max(1, k // 4)])
    remaining = k - len(picked)
    if remaining > 0 and news_only:
        picked.extend(rng.sample(news_only, min(remaining, len(news_only))))
    return picked[:k]
