"""DuckDB 只读时序查询层（R-FOF 下周期成员 3 / SE）。

职责
----
把仓库里散落的 Parquet / CSV 行情与因子文件统一成**只读查询接口**，供 #12（信管 A）
快速取数回测、供账本服务灌入 ``lifecycle_ledger``。接口方法名与
``research-outputs/rfof_next_cycle/member1_asset_quant/market.py`` 中的
``MarketReader`` 协议保持一致，因此可以直接替换其 "pending" 本地实现：

    from duck_reader import open_reader
    reader = open_reader(root, market_dir, None)
    panel = reader.stock_panel()

只读保证（三层）
----------------
1. DuckDB 在内存库中运行，仅通过 ``read_parquet`` / ``read_csv`` 元表函数访问文件，
   不打开任何可写数据库文件；
2. ``_select`` 只放行 ``SELECT`` / ``WITH`` 开头的单条语句，拒绝 DDL / DML / 分号拼接；
3. 所有文件路径以参数绑定传入，不做字符串拼接，避免路径注入。

数据口径
--------
* ``data/task_split/csmar_master/csmar_factor_panel_master.parquet`` 为真实股票面板
  （2024-01-02 至 2026-08-28，299 只股票，192,199 行，见同目录 manifest）；
* 行情快照 CSV（etf_close / fund_nav / actions / futures_close）由 #12 的抓取脚本落盘，
  仓库不提交原始行情缓存；文件缺失时抛 ``FileNotFoundError``，由调用方决定兜底口径。
* 股票代码、交易日一律按字符串返回，杜绝 ``000037`` 被解析成 37 的经典事故。
"""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Iterable

import pandas as pd

PANEL = Path("data/task_split/csmar_master/csmar_factor_panel_master.parquet")
PANEL_MANIFEST = Path("data/task_split/csmar_master/csmar_factor_panel_master_manifest.json")
# 与 #12（member1_asset_quant/fetch_market.py）的落盘目录保持一致，抓取后即可直读。
DEFAULT_MARKET_DIR = Path("data/_raw_cache/rfof_issue12")
MARKET_DIR_ENV = "RFOF_MARKET_DIR"
MARKET_TABLES = {
    "etf_close.csv": "etf_closes",
    "fund_nav.csv": "fund_navs",
    "actions.csv": "actions",
    "futures_close.csv": "futures_closes",
}

_SELECT = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
# 允许出现在只读语句中的分号仅限结尾；出现多个语句直接拒绝。
_MULTI_STATEMENT = re.compile(r";\s*\S")


class ReadOnlyViolation(ValueError):
    """调用方试图通过只读层执行写操作或非查询语句。"""


def _guard(sql: str) -> str:
    if not isinstance(sql, str) or not _SELECT.match(sql):
        raise ReadOnlyViolation("only SELECT/WITH statements are allowed")
    if _MULTI_STATEMENT.search(sql):
        raise ReadOnlyViolation("multiple statements are not allowed")
    return sql


class DuckDBMarketReader:
    """只读实现：DuckDB 内存库 + Parquet/CSV 元表函数。"""

    def __init__(self, root: Path, market_dir: Path | None = None):
        self.root = Path(root)
        if market_dir is not None:
            self.market_dir = Path(market_dir)
        else:
            configured = os.environ.get(MARKET_DIR_ENV)
            if configured:
                candidate = Path(configured)
                self.market_dir = candidate if candidate.is_absolute() else self.root / candidate
            else:
                self.market_dir = self.root / DEFAULT_MARKET_DIR

    # ------------------------------------------------------------------ 查询
    def _query(self, sql: str, path: Path) -> pd.DataFrame:
        import duckdb

        sql = _guard(sql)
        if not path.is_file():
            raise FileNotFoundError(path)
        with duckdb.connect(":memory:") as db:
            return db.execute(sql, [str(path)]).fetchdf()

    def _csv(self, name: str) -> pd.DataFrame:
        """CSV 全量按 VARCHAR 读取，代码/日期不做隐式数值转换。"""
        return self._query(
            "SELECT * FROM read_csv(?, all_varchar = true)", self.market_dir / name
        )

    # ------------------------------------------------- MarketReader 协议方法
    def stock_panel(self) -> pd.DataFrame:
        """真实股票面板全列，按交易日 + 代码排序。"""
        return self._query(
            "SELECT * FROM read_parquet(?) ORDER BY trade_date, stock_code",
            self.root / PANEL,
        )

    def stock_window(
        self,
        start: str,
        end: str,
        codes: Iterable[str] | None = None,
    ) -> pd.DataFrame:
        """按区间取面板；``codes`` 为可选股票代码白名单。"""
        codes = list(codes or [])
        sql = (
            "SELECT * FROM read_parquet(?) "
            "WHERE trade_date BETWEEN ? AND ? "
            + ("AND stock_code IN (" + ",".join(["?"] * len(codes)) + ") " if codes else "")
            + "ORDER BY trade_date, stock_code"
        )
        import duckdb

        path = self.root / PANEL
        if not path.is_file():
            raise FileNotFoundError(path)
        with duckdb.connect(":memory:") as db:
            return db.execute(_guard(sql), [str(path), start, end, *codes]).fetchdf()

    def etf_closes(self) -> pd.DataFrame:
        return self._csv("etf_close.csv")

    def fund_navs(self) -> pd.DataFrame:
        return self._csv("fund_nav.csv")

    def actions(self) -> pd.DataFrame:
        return self._csv("actions.csv")

    def futures_closes(self) -> pd.DataFrame:
        return self._csv("futures_close.csv")

    # ---------------------------------------------------------- 元信息 / 审计
    def panel_provenance(self) -> dict:
        """面板文件的体量与哈希，写入 run manifest 供独立复核。"""
        path = self.root / PANEL
        if not path.is_file():
            raise FileNotFoundError(path)
        digest = sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        frame = self.query_frame(
            "SELECT COUNT(*) AS rows, COUNT(DISTINCT stock_code) AS stocks, "
            "COUNT(DISTINCT trade_date) AS sessions, MIN(trade_date) AS first_date, "
            "MAX(trade_date) AS last_date FROM read_parquet(?)",
            self.root / PANEL,
        )
        row = frame.iloc[0].to_dict()
        manifest = self.root / PANEL_MANIFEST
        declared = json.loads(manifest.read_text(encoding="utf-8")) if manifest.is_file() else {}
        reported = declared.get("rows")
        return {
            "path": str(PANEL),
            "sha256": digest.hexdigest(),
            "rows": int(row["rows"]),
            "stocks": int(row["stocks"]),
            "sessions": int(row["sessions"]),
            "first_date": str(row["first_date"]),
            "last_date": str(row["last_date"]),
            "manifest_rows": reported,
            "rows_match_manifest": (reported is None or int(reported) == int(row["rows"])),
        }

    def market_availability(self) -> dict[str, bool]:
        """仓库未提交行情缓存，这里显式报告每张表的可用性。"""
        return {name: (self.market_dir / name).is_file() for name in MARKET_TABLES}

    def query_frame(self, sql: str, path: Path, params: Iterable[object] | None = None) -> pd.DataFrame:
        """受控的临时查询入口（仍受只读守卫约束）。"""
        import duckdb

        sql = _guard(sql)
        if not Path(path).is_file():
            raise FileNotFoundError(path)
        with duckdb.connect(":memory:") as db:
            return db.execute(sql, [str(path), *(params or [])]).fetchdf()


def open_reader(root: Path, market_dir: Path | None, factory: str | None):
    """与 member1 ``market.open_reader`` 同一签名的工厂。

    ``factory`` 形如 ``module:function``，必须接收 ``root`` 与 ``market_dir`` 关键字参数；
    传 ``None`` 时返回本模块的默认只读实现。
    """
    if factory is None:
        return DuckDBMarketReader(root, market_dir)
    module_name, sep, attribute = factory.partition(":")
    if not sep or not module_name or not attribute:
        raise ValueError("reader must be module:factory")
    from importlib import import_module

    return getattr(import_module(module_name), attribute)(root=root, market_dir=market_dir)