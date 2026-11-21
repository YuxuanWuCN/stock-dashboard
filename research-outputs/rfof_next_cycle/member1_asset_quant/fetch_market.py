
"""Capture the public price, NAV and corporate-action inputs for Issue #12."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO, StringIO
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from xml.etree import ElementTree
from zipfile import ZipFile

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from market import CASH, ETF_CODES, EXTRA_ETF, FUTURES, PRODUCTS, ROOT

START = "2010-01-01"
CUTOFF = "2026-11-13"
MARKET_DIR = ROOT / "data/_raw_cache/rfof_issue12"
NAV_URL = "https://fund.eastmoney.com/pingzhongdata/{code}.js"
ACTIONS_URL = "https://fundf10.eastmoney.com/fhsp_{code}.html"
STATUS_URL = "https://api.fund.eastmoney.com/f10/lsjz"
QUOTE_URL = "https://finance.sina.com.cn/realstock/company/{symbol}/hisdata_klc2/klc_kl.js"
FUTURES_URL = "https://stock2.finance.sina.com.cn/futures/api/json.php/InnerFuturesNewService.getDailyKLine"
CSRC_PAGE = "https://www.csrc.gov.cn/csrc/c101900/c6551799/content.shtml"
CSRC_DOC = (
    "https://www.csrc.gov.cn/csrc/c101900/c6551799/6551799/files/"
    "个人养老金基金名录（截至2026年9月30日）.docx"
)
CHINA_TZ = timezone(timedelta(hours=8))


def get(url: str, **params) -> requests.Response:
    with requests.Session() as session:
        session.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://fundf10.eastmoney.com/",
        })
        session.mount("https://", HTTPAdapter(max_retries=Retry(
            total=3, backoff_factor=0.75, status_forcelist=(429, 500, 502, 503, 504),
        )))
        response = session.get(url, params=params, timeout=(10, 40))
        response.raise_for_status()
        return response


def read_actions(page: str) -> list[tuple[str, float, float]]:
    """Parse the cash per old unit and the new units per old unit."""
    tables = pd.read_html(StringIO(page))
    dividends = [t for t in tables if {"除息日", "每10份分红"} <= set(t.columns)]
    splits = [t for t in tables if {"拆分折算日", "拆分折算比例"} <= set(t.columns)]
    if len(dividends) != 1 or len(splits) != 1:
        raise ValueError("missing corporate action table")
    out = []
    for when, amount in dividends[0][["除息日", "每10份分红"]].itertuples(index=False, name=None):
        if when == "暂无分红信息!":
            continue
        match = re.fullmatch(r"每10份派现金\s*(\d+(?:\.\d+)?)\s*元", str(amount))
        if not match:
            raise ValueError(f"unrecognized corporate action amount: {amount!r}")
        out.append((date.fromisoformat(when).isoformat(), float(match[1]) / 10, 1.0))
    for when, amount in splits[0][["拆分折算日", "拆分折算比例"]].itertuples(index=False, name=None):
        if when == "暂无拆分信息!":
            continue
        match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*[:：]\s*(\d+(?:\.\d+)?)", str(amount))
        if not match:
            raise ValueError(f"unrecognized corporate action ratio: {amount!r}")
        out.append((date.fromisoformat(when).isoformat(), 0.0, float(match[2]) / float(match[1])))
    return sorted(out)


def get_fund(code: str, cutoff: str) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    nav_source = get(NAV_URL.format(code=code), v=cutoff.replace("-", ""))
    text = nav_source.content.decode("utf-8-sig")
    identity = re.search(r'var fS_code\s*=\s*"(\d+)";', text)
    name = re.search(r'var fS_name\s*=\s*"([^"]+)";', text)
    trend = re.search(r"Data_netWorthTrend\s*=\s*(\[[^;]*\]);", text)
    if not identity or identity[1] != code or not name or not trend:
        raise ValueError(f"missing or mismatched NAV history for {code}")
    records = json.loads(trend[1])
    nav_rows = []
    for record in records:
        day = datetime.fromtimestamp(record["x"] / 1_000, CHINA_TZ).date().isoformat()
        if START <= day <= cutoff:
            nav_rows.append((code, day, record["y"]))
    if not nav_rows:
        raise ValueError(f"empty NAV history for {code}")
    action_source = get(ACTIONS_URL.format(code=code))
    action_rows = [
        (code, day, cash, ratio)
        for day, cash, ratio in read_actions(action_source.content.decode("utf-8"))
        if START <= day <= cutoff
    ]
    details = {
        "code": code, "name": name[1], "nav_source": NAV_URL.format(code=code),
        "actions_source": ACTIONS_URL.format(code=code),
        "nav_response_sha256": sha256(nav_source.content).hexdigest(),
        "actions_response_sha256": sha256(action_source.content).hexdigest(),
    }
    if code in PRODUCTS:
        response = get(STATUS_URL, fundCode=code, pageIndex=1, pageSize=20, endDate=cutoff)
        latest = response.json()["Data"]["LSJZList"][0]
        details.update(
            status_date=latest["FSRQ"], subscription_status=latest["SGZT"],
            status_source=response.url,
        )
    return (
        pd.DataFrame(nav_rows, columns=["code", "trade_date", "nav"]),
        pd.DataFrame(action_rows, columns=["code", "trade_date", "cash", "ratio"]),
        details,
    )


def get_etf(code: str, cutoff: str) -> tuple[pd.DataFrame, dict]:
    import akshare

    symbol = ("sz" if code.startswith("1") else "sh") + code
    prices = akshare.fund_etf_hist_sina(symbol)
    if prices.empty:
        raise ValueError(f"missing ETF close history for {code}")
    frame = prices.rename(columns={"date": "trade_date"})[["trade_date", "close"]].copy()
    frame["trade_date"] = frame["trade_date"].astype(str)
    frame = frame.loc[frame["trade_date"].between(START, cutoff)].copy()
    if frame.empty:
        raise ValueError(f"ETF close history outside requested dates for {code}")
    frame.insert(0, "code", code)
    return frame, {"code": code, "symbol": symbol, "source": QUOTE_URL.format(symbol=symbol),
                   "decoder": f"akshare {akshare.__version__}"}

def get_futures(code: str, cutoff: str) -> tuple[pd.DataFrame, dict]:
    response = get(FUTURES_URL, symbol=code + "0")
    rows = [(code, record["d"], record["c"]) for record in response.json()
            if START <= record["d"] <= cutoff]
    if not rows:
        raise ValueError(f"missing continuous futures history for {code}")
    return (pd.DataFrame(rows, columns=["code", "trade_date", "close"]),
            {"code": code, "source": response.url, "response_sha256": sha256(response.content).hexdigest()})


def registry_records(payload: bytes) -> dict[str, list[str]]:
    with ZipFile(BytesIO(payload)) as docx:
        document = ElementTree.fromstring(docx.read("word/document.xml"))
    rows = [
        ["".join(t.text or "" for t in cell.findall(".//{*}t")) for cell in row.findall("{*}tc")]
        for row in document.findall(".//{*}tr")
    ]
    matches = {code: next((row for row in rows if code in row), []) for code in PRODUCTS}
    if not all(matches.values()):
        raise ValueError("Y-share code missing from the frozen CSRC register")
    return matches


def capture(destination: Path, cutoff: str) -> None:
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    etfs = (*ETF_CODES, CASH, EXTRA_ETF)
    with ThreadPoolExecutor(max_workers=5) as pool:
        funds = [pool.submit(get_fund, code, cutoff) for code in (*etfs, *PRODUCTS)]
        quotes = [pool.submit(get_etf, code, cutoff) for code in etfs]
        contracts = [pool.submit(get_futures, code, cutoff) for code in FUTURES]
        registry = pool.submit(get, CSRC_DOC)
        nav, actions, funds_meta = zip(*(task.result() for task in funds))
        prices, quote_meta = zip(*(task.result() for task in quotes))
        futures, futures_meta = zip(*(task.result() for task in contracts))
        register = registry.result()
    manifest = {
        "requested_start_date": START, "cutoff": cutoff, "registry_page": CSRC_PAGE,
        "registry_doc": CSRC_DOC, "registry_sha256": sha256(register.content).hexdigest(),
        "registry_rows": registry_records(register.content),
        "funds": funds_meta, "etf_quotes": quote_meta, "futures": futures_meta,
    }
    with TemporaryDirectory(dir=destination.parent, prefix=".capture-") as temp:
        stage = Path(temp) / "market"
        stage.mkdir()
        for name, frames in (("fund_nav", nav), ("actions", actions),
                             ("etf_close", prices), ("futures_close", futures)):
            nonempty = [frame for frame in frames if not frame.empty]
            pd.concat(nonempty or [frames[0]], ignore_index=True).sort_values(["code", "trade_date"]).to_csv(
                stage / f"{name}.csv", index=False, lineterminator="\n",
            )
        manifest["snapshot_sha256"] = {
            p.name: sha256(p.read_bytes()).hexdigest() for p in sorted(stage.glob("*.csv"))
        }
        (stage / "sources.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        stage.rename(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market-dir", type=Path, default=MARKET_DIR)
    parser.add_argument("--cutoff", default=CUTOFF, type=lambda arg: date.fromisoformat(arg).isoformat())
    args = parser.parse_args()
    capture(args.market_dir, args.cutoff)
    print(args.market_dir.resolve())
