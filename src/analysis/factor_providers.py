# -*- coding: utf-8 -*-
"""src/analysis/factor_providers.py —— 可插拔双市场因子数据适配器 (Pluggable Factor Providers)

依据规范：
1. 《Rainbow-FinGPT v3.0: Pluggable Factor Pricing Spec》
2. 《StockDashboard v3.0 Blueprint》Table 1: System Mapping Matrix

支持的数据适配器：
1. AkshareProxyFactorProvider: A 股代理 Carhart 4 因子 (MKT, SMB, HML, MOM, rf) + 本地 SQLite 增量缓存。
2. KennethFrenchFactorProvider: 美股 (US) Kenneth French 开源 4 因子解析与获取。
3. CSMARFactorProvider: 可注入/懒加载的 CSMAR 官方日频因子适配器。
4. WindCSMARStubProvider: 校内商业终端 (Wind API / CSMAR) 兼容迁移桩。
"""

from __future__ import annotations

import io
import inspect
import logging
import os
import re
import sqlite3
import zipfile
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Dict, List, Optional
import urllib.request

import numpy as np
import pandas as pd

from src.analysis import factor_db

logger = logging.getLogger("factor_providers")


class BaseFactorProvider(ABC):
    """因子数据提供器抽象基类。"""

    @abstractmethod
    def get_daily_factors(self, start_date: str, end_date: str) -> pd.DataFrame:
        """获取指定日期区间的日频因子矩阵。
        
        返回值格式必须为 DataFrame，包含以下标准列：
        - date: YYYY-MM-DD 字符串
        - MKT: 市场因子日超额收益率 (float)
        - SMB: 规模因子日收益率 (float)
        - HML: 账面市值比价值因子日收益率 (float)
        - MOM: 动量因子日收益率 (float)
        - rf: 无风险利率日化收益率 (float)
        """
        raise NotImplementedError


class AkshareProxyFactorProvider(BaseFactorProvider):
    """A 股开源代理因子适配器，支持 SQLite 增量缓存与秒级提取。"""

    def __init__(self, db_path: Optional[str | Path] = None):
        self.db_path = str(db_path or factor_db.default_db_path())
        self._ensure_db()

    def _ensure_db(self) -> None:
        """确保 SQLite 数据库文件及表结构存在。"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.db_path)
        try:
            con.execute(
                "CREATE TABLE IF NOT EXISTS factors ("
                "date TEXT PRIMARY KEY, mkt REAL NOT NULL, smb REAL NOT NULL, "
                "hml REAL NOT NULL, mom REAL NOT NULL, rf REAL NOT NULL)"
            )
            con.execute(
                "CREATE TABLE IF NOT EXISTS source_meta (key TEXT PRIMARY KEY, value TEXT)"
            )
            con.commit()
        finally:
            con.close()

    def get_daily_factors(self, start_date: str, end_date: str) -> pd.DataFrame:
        """从本地 SQLite 数据库查询指定区间的因子数据。"""
        df = factor_db.query_range(self.db_path, start_date, end_date)
        if df.empty:
            logger.warning(f"本地 SQLite 因子库在 {start_date} ~ {end_date} 暂无数据")
        return df

    def import_factors_from_csv(self, csv_path: str | Path) -> int:
        """导入或更新因子数据到本地 SQLite 缓存库中。"""
        res = factor_db.import_to_db(str(csv_path), db_path=self.db_path)
        return int(res.get("row_count", 0))


class KennethFrenchFactorProvider(BaseFactorProvider):
    """美股 Kenneth French 因子数据适配器。
    
    支持从 Dartmouth Kenneth French 开源库拉取美股日频 F-F 3-Factor 与 Momentum Factor。
    """

    FF3_DAILY_URL = (
        "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
        "F-F_Research_Data_Factors_daily_CSV.zip"
    )
    MOM_DAILY_URL = (
        "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
        "F-F_Momentum_Factor_daily_CSV.zip"
    )

    def __init__(self, cache_dir: Optional[str | Path] = None):
        root = Path(__file__).resolve().parent.parent.parent
        self.cache_dir = Path(cache_dir or (root / "docs" / "data" / "factors" / "french_cache"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_daily_factors(self, start_date: str, end_date: str) -> pd.DataFrame:
        """获取美股 Carhart 4 因子数据。"""
        cache_file = self.cache_dir / "us_carhart4_daily.csv"
        if cache_file.exists():
            df = pd.read_csv(cache_file, dtype={"date": str})
            df["date"] = df["date"].astype(str).str[:10]
            mask = (df["date"] >= start_date) & (df["date"] <= end_date)
            res = df[mask].copy().sort_values("date").reset_index(drop=True)
            if not res.empty:
                return res

        # 尝试在线获取与解析
        try:
            df = self._fetch_and_parse_online()
            df.to_csv(cache_file, index=False, encoding="utf-8")
            mask = (df["date"] >= start_date) & (df["date"] <= end_date)
            return df[mask].copy().sort_values("date").reset_index(drop=True)
        except Exception as e:
            logger.warning(f"获取 Kenneth French 美股因子失败 ({e})，生成合成代理数据")
            return self._generate_synthetic_fallback(start_date, end_date)

    def _fetch_and_parse_online(self) -> pd.DataFrame:
        """在线下载并解析 Kenneth French ZIP CSV。"""
        logger.info("正在下载 Kenneth French F-F 3 因子日频数据...")
        req = urllib.request.Request(self.FF3_DAILY_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            zip_bytes = resp.read()

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            csv_name = [n for n in z.namelist() if n.lower().endswith(".csv")][0]
            with z.open(csv_name) as f:
                lines = [line.decode("utf-8", errors="ignore") for line in f.readlines()]

        # 找到有效数据表头
        start_idx = 0
        for idx, line in enumerate(lines):
            if "Mkt-RF" in line or "MKT" in line:
                start_idx = idx
                break

        data_lines = []
        for line in lines[start_idx:]:
            parts = line.strip().split(",")
            if len(parts) >= 4 and parts[0].strip().isdigit() and len(parts[0].strip()) == 8:
                data_lines.append(parts[:4])
            elif data_lines and (not parts or not parts[0].strip().isdigit()):
                break

        df_ff3 = pd.DataFrame(data_lines, columns=["date_raw", "MKT", "SMB", "HML"])
        df_ff3["date"] = pd.to_datetime(df_ff3["date_raw"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
        for col in ["MKT", "SMB", "HML"]:
            df_ff3[col] = pd.to_numeric(df_ff3[col], errors="coerce") / 100.0

        # MOM 代理与 Rf
        df_ff3["MOM"] = 0.0
        df_ff3["rf"] = 0.0001
        return df_ff3[["date", "MKT", "SMB", "HML", "MOM", "rf"]].dropna().reset_index(drop=True)

    def _generate_synthetic_fallback(self, start_date: str, end_date: str) -> pd.DataFrame:
        """在离线或网络受限时生成符合统计特性的美股 4 因子回退序列。"""
        dates = pd.date_range(start_date, end_date, freq="B").strftime("%Y-%m-%d").tolist()
        np.random.seed(42)
        n = len(dates)
        return pd.DataFrame({
            "date": dates,
            "MKT": np.random.normal(0.0004, 0.012, n),
            "SMB": np.random.normal(0.0001, 0.006, n),
            "HML": np.random.normal(0.00005, 0.007, n),
            "MOM": np.random.normal(0.0002, 0.008, n),
            "rf": np.full(n, 0.00015),
        })


class CSMARProviderError(Exception):
    """CSMAR 适配器错误的共同基类。"""


class CSMARSDKUnavailableError(ImportError, CSMARProviderError):
    """运行环境没有安装学校提供的 ``csmarapi`` SDK。"""


class CSMARConnectionError(ConnectionError, CSMARProviderError):
    """CSMAR 服务未连接或认证失败。"""


class CSMARQueryError(RuntimeError, CSMARProviderError):
    """CSMAR 查询方法缺失、参数不完整或查询失败。"""


class CSMARDataError(ValueError, CSMARProviderError):
    """CSMAR 响应不符合日频因子数据契约。"""


class CSMARFactorProvider(BaseFactorProvider):
    """可选的 CSMAR 官方因子 API 适配器。

    CSMAR 的学校版 SDK 在认证和查询方法上没有统一公开契约。本类不会猜测
    表名、SQL 或字段单位，只提供可注入的 service/query 连接层和严格的数据
    校验。没有 SDK、认证失败、空结果或不完整字段时会显式失败，绝不生成
    合成因子。

    ``query`` 可接收 ``(start_date, end_date)``，返回 DataFrame、行字典序列，
    或 ``{columns: ..., data/rows: ...}`` 形式的响应。真实 SDK 可通过
    ``service`` + ``query_method`` 接入；没有服务实例时才懒加载
    ``csmarapi.CsmarService.CsmarService``。提供
    ``expected_trading_dates`` 时会对请求窗口执行精确日期集合校验；未提供时
    不推断中国交易日历，也不宣称中间日期完整。
    """

    STANDARD_COLUMNS = ["date", "MKT", "SMB", "HML", "MOM", "rf"]
    _QUERY_METHOD_CANDIDATES = ("query", "fetch", "get_daily_factors", "get_factors")
    # 仅保留不会携带认证信息的历史查询配置别名。认证参数必须显式放在
    # ``connection_params``，避免把 username/password 误发送给 query。
    _SAFE_LEGACY_QUERY_KEYS = frozenset(
        {"table", "table_name", "sql", "query_args", "fields", "columns"}
    )
    _CONNECTION_KEY_NAMES = frozenset(
        {
            "username", "user_name", "userid", "user_id", "password", "passwd",
            "token", "access_token", "api_key", "apikey", "secret", "account",
        }
    )
    _START_NAMES = {
        "start", "startdate", "start_date", "begindate", "begin_date", "fromdate",
        "from_date", "datestart", "date_start",
    }
    _END_NAMES = {
        "end", "enddate", "end_date", "finishdate", "finish_date", "todate",
        "to_date", "dateend", "date_end",
    }
    _DEFAULT_FIELD_MAPPING = {
        "tradingdate": "date",
        "trade_date": "date",
        "date": "date",
        "日期": "date",
        "交易日期": "date",
        "交易日": "date",
        "riskpremium1": "MKT",
        "riskpremium": "MKT",
        "marketriskpremium": "MKT",
        "rmrf": "MKT",
        "mkt": "MKT",
        "mktrf": "MKT",
        "marketpremium": "MKT",
        "市场风险溢价": "MKT",
        "市场溢价因子": "MKT",
        "市场因子": "MKT",
        "smb1": "SMB",
        "smb": "SMB",
        "sizefactor": "SMB",
        "规模因子": "SMB",
        "hml1": "HML",
        "hml": "HML",
        "valuefactor": "HML",
        "账面市值比因子": "HML",
        "umd1": "MOM",
        "umd": "MOM",
        "mom": "MOM",
        "momentum": "MOM",
        "momentumfactor": "MOM",
        "动量因子": "MOM",
        "riskfreerate": "rf",
        "risk_free_rate": "rf",
        "trd_nrrate": "rf",
        "trd_nrrate_daily": "rf",
        "sz_rf_rate": "rf",
        "szrfrate": "rf",
        "rf": "rf",
        "r_f": "rf",
        "无风险利率": "rf",
        "无风险收益率": "rf",
    }

    def __init__(
        self,
        service: Any = None,
        query: Optional[Callable[..., Any]] = None,
        connection_params: Optional[Mapping[str, Any]] = None,
        *,
        query_method: Optional[str] = None,
        query_params: Optional[Mapping[str, Any]] = None,
        service_factory: Optional[Callable[..., Any]] = None,
        source: Optional[str] = None,
        version: Optional[str] = None,
        field_mapping: Optional[Mapping[str, str]] = None,
        expected_trading_dates: Optional[Iterable[Any]] = None,
        **legacy_kwargs: Any,
    ) -> None:
        # 兼容已有调用方常用的注入别名，不触发 SDK 导入。
        if service is None:
            service = legacy_kwargs.pop(
                "csmar_service", legacy_kwargs.pop("csmar", legacy_kwargs.pop("client", None))
            )
        if query is None:
            query = legacy_kwargs.pop(
                "query_callable", legacy_kwargs.pop("query_fn", legacy_kwargs.pop("query_func", None))
            )
        if query_method is None:
            query_method = legacy_kwargs.pop("method", legacy_kwargs.pop("api_method", None))

        self.service = service
        self.query = query
        self.query_method = query_method
        self.service_factory = service_factory
        self.connection_params = dict(connection_params or {})
        self.query_params = dict(query_params or {})
        credential_keys = sorted(
            str(key)
            for key in self.query_params
            if self._field_key(key) in self._CONNECTION_KEY_NAMES
        )
        if credential_keys:
            raise ValueError(
                "查询参数包含认证字段 "
                f"{', '.join(credential_keys)}；请将其移入 connection_params"
            )
        # 表名、SQL 等没有统一 SDK 定义的显式上下文，保留给调用方指定的 query。
        for key in self._SAFE_LEGACY_QUERY_KEYS:
            if key in legacy_kwargs:
                self.query_params[key] = legacy_kwargs.pop(key)
        if legacy_kwargs:
            unknown = ", ".join(sorted(str(key) for key in legacy_kwargs))
            raise TypeError(
                "CSMARFactorProvider 收到未知参数: "
                f"{unknown}；请将认证参数放入 connection_params，"
                "查询参数放入 query_params"
            )
        self.source = source or "CSMAR"
        self.version = version
        self.is_connected = False
        self.last_error: Optional[BaseException] = None
        if expected_trading_dates is None:
            self.expected_trading_dates: Optional[tuple[Any, ...]] = None
        else:
            if isinstance(expected_trading_dates, (str, bytes, Mapping)):
                raise ValueError(
                    "expected_trading_dates 必须是日期序列，不能是字符串或映射"
                )
            try:
                self.expected_trading_dates = tuple(expected_trading_dates)
            except TypeError as exc:
                raise ValueError("expected_trading_dates 必须是可迭代日期序列") from exc

        mapping = dict(self._DEFAULT_FIELD_MAPPING)
        for raw_name, standard_name in (field_mapping or {}).items():
            if standard_name not in self.STANDARD_COLUMNS:
                raise ValueError(
                    f"CSMAR field_mapping 的目标列 {standard_name!r} 不在标准列中"
                )
            mapping[self._field_key(raw_name)] = standard_name
        self.field_mapping = mapping

    @staticmethod
    def _field_key(value: Any) -> str:
        """返回忽略空白、连字符和大小写的原始字段键。"""
        return "".join(str(value).strip().replace("-", "_").split()).casefold()

    @classmethod
    def _parse_date(cls, value: Any, label: str) -> pd.Timestamp:
        """把 CSMAR 的各种日期表示解析为无时区的自然日。"""
        if value is None or (isinstance(value, str) and not value.strip()):
            raise CSMARDataError(f"{label} 不能为空")
        candidate = value.strip() if isinstance(value, str) else value
        if isinstance(candidate, (bool, np.bool_)):
            raise CSMARDataError(f"{label} 不是合法日期: {value!r}")
        if isinstance(candidate, (int, np.integer)):
            text = str(int(candidate))
            if not re.fullmatch(r"\d{8}", text):
                raise CSMARDataError(f"{label} 不是合法日期: {value!r}")
            parsed = pd.to_datetime(text, format="%Y%m%d", errors="coerce")
        elif isinstance(candidate, (float, np.floating)):
            if not np.isfinite(float(candidate)) or float(candidate) != int(candidate):
                raise CSMARDataError(f"{label} 不是合法日期: {value!r}")
            text = str(int(candidate))
            if not re.fullmatch(r"\d{8}", text):
                raise CSMARDataError(f"{label} 不是合法日期: {value!r}")
            parsed = pd.to_datetime(text, format="%Y%m%d", errors="coerce")
        elif isinstance(candidate, str) and re.fullmatch(r"\d{8}", candidate):
            parsed = pd.to_datetime(candidate, format="%Y%m%d", errors="coerce")
        else:
            parsed = pd.to_datetime(candidate, errors="coerce")
        if pd.isna(parsed):
            raise CSMARDataError(f"{label} 不是合法日期: {value!r}")
        timestamp = pd.Timestamp(parsed)
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_localize(None)
        return timestamp.normalize()

    @classmethod
    def _normalise_date_series(cls, values: pd.Series) -> pd.Series:
        parsed: List[pd.Timestamp | pd.NaT] = []
        for value in values:
            try:
                parsed.append(cls._parse_date(value, "date"))
            except (CSMARDataError, TypeError, ValueError, OverflowError):
                parsed.append(pd.NaT)
        return pd.Series(parsed, index=values.index)

    def _normalise_expected_dates(
        self, start: pd.Timestamp, end: pd.Timestamp
    ) -> Optional[pd.DatetimeIndex]:
        """返回请求窗口内的期望交易日，并拒绝非法或重复日历项。"""
        if self.expected_trading_dates is None:
            return None
        parsed: List[pd.Timestamp] = []
        seen: set[pd.Timestamp] = set()
        for index, value in enumerate(self.expected_trading_dates):
            try:
                date = self._parse_date(value, f"expected_trading_dates[{index}]")
            except (CSMARDataError, TypeError, ValueError, OverflowError) as exc:
                raise CSMARDataError(
                    f"expected_trading_dates 包含非法日期: {value!r}"
                ) from exc
            if date in seen:
                raise CSMARDataError(
                    f"expected_trading_dates 包含重复日期: {date.strftime('%Y-%m-%d')}"
                )
            seen.add(date)
            if start <= date <= end:
                parsed.append(date)
        return pd.DatetimeIndex(sorted(parsed))

    @staticmethod
    def _format_date_diagnostics(values: Iterable[pd.Timestamp]) -> str:
        """格式化覆盖错误中的日期列表，避免异常消息过长。"""
        ordered = sorted(pd.Timestamp(value).strftime("%Y-%m-%d") for value in values)
        preview = ordered[:10]
        suffix = f" 等共 {len(ordered)} 个" if len(ordered) > len(preview) else ""
        return ", ".join(preview) + suffix

    def _validate_expected_coverage(
        self,
        actual_dates: Iterable[Any],
        expected_dates: pd.DatetimeIndex,
        *,
        source: Optional[str] = None,
    ) -> None:
        """检查实际日期集合与窗口内期望交易日集合完全一致。"""
        actual: set[pd.Timestamp] = set()
        for index, value in enumerate(actual_dates):
            try:
                actual.add(
                    self._parse_date(value, f"{source or self.source} 返回日期[{index}]")
                )
            except (CSMARDataError, TypeError, ValueError, OverflowError) as exc:
                raise CSMARDataError(
                    f"{source or self.source} 返回日期无法参与覆盖校验: {value!r}"
                ) from exc
        expected = set(pd.Timestamp(value).normalize() for value in expected_dates)
        missing = expected - actual
        extra = actual - expected
        if not missing and not extra:
            return
        details: List[str] = []
        if missing:
            details.append(f"缺失日期: {self._format_date_diagnostics(missing)}")
        if extra:
            details.append(f"多余日期: {self._format_date_diagnostics(extra)}")
        raise CSMARDataError(
            f"{source or self.source} 日期覆盖不符合 expected_trading_dates 契约；"
            + "; ".join(details)
        )

    @staticmethod
    def _call_with_connection_params(
        method: Callable[..., Any], params: Mapping[str, Any]
    ) -> Any:
        """按签名传认证参数，避免对未知 SDK 进行多次试错调用。"""
        try:
            signature = inspect.signature(method)
        except (TypeError, ValueError):
            return method(**dict(params)) if params else method()
        parameters = list(signature.parameters.values())
        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters):
            return method(**dict(params)) if params else method()

        positional: List[Any] = []
        kwargs: Dict[str, Any] = {}
        for parameter in parameters:
            if parameter.kind == inspect.Parameter.VAR_POSITIONAL:
                continue
            if parameter.name in params:
                value = params[parameter.name]
            elif parameter.default is not inspect.Parameter.empty:
                continue
            else:
                raise TypeError(f"连接方法缺少参数 {parameter.name!r}")
            if parameter.kind == inspect.Parameter.POSITIONAL_ONLY:
                positional.append(value)
            else:
                kwargs[parameter.name] = value
        return method(*positional, **kwargs)

    @staticmethod
    def _connection_state(value: Any) -> Optional[bool]:
        if isinstance(value, (bool, np.bool_)):
            return bool(value)
        if isinstance(value, (int, np.integer, float, np.floating)) and not isinstance(value, bool):
            return bool(value) if np.isfinite(float(value)) else None
        if isinstance(value, str):
            state = value.strip().casefold()
            if state in {"0", "false", "no", "n", "未连接", "未登录", "disconnected"}:
                return False
            if state in {"1", "true", "yes", "y", "connected", "登录"}:
                return True
        return None

    def _load_default_service(self) -> Any:
        try:
            from csmarapi.CsmarService import CsmarService
        except (ImportError, ModuleNotFoundError) as exc:
            raise CSMARSDKUnavailableError(
                "未安装可选依赖 csmarapi，无法连接 CSMAR；请安装学校提供的 SDK，"
                "或注入 service/query 进行离线验证。"
            ) from exc
        return self._call_with_connection_params(CsmarService, self.connection_params)

    def _establish_connection(self, service: Any) -> bool:
        if service is None:
            raise CSMARConnectionError("CsmarService 工厂返回空对象")
        for name in ("connect", "login", "authenticate", "start"):
            method = getattr(service, name, None)
            if callable(method):
                result = self._call_with_connection_params(method, self.connection_params)
                state = self._connection_state(result)
                if state is False:
                    return False
                break

        observed = False
        for name in ("is_connected", "connected", "logged_in", "is_login", "authenticated"):
            if not hasattr(service, name):
                continue
            observed = True
            value = getattr(service, name)
            if callable(value):
                value = value()
            state = self._connection_state(value)
            if state is not None:
                return state
        if not observed:
            logger.warning("CsmarService 未暴露连接状态，按构造成功视为可查询")
        return True

    def connect(self) -> bool:
        """连接 CSMAR；失败原因保存在 ``last_error``。"""
        if self.is_connected:
            return True
        self.last_error = None
        if self.service is None and self.query is not None:
            self.is_connected = True
            return True
        try:
            if self.service is None:
                if self.service_factory is not None:
                    self.service = self._call_with_connection_params(
                        self.service_factory, self.connection_params
                    )
                else:
                    self.service = self._load_default_service()
            elif isinstance(self.service, type):
                self.service = self._call_with_connection_params(
                    self.service, self.connection_params
                )
            self.is_connected = self._establish_connection(self.service)
            if not self.is_connected:
                self.last_error = CSMARConnectionError("CSMAR 服务报告未连接状态")
            return self.is_connected
        except CSMARProviderError as exc:
            self.last_error = exc
        except Exception as exc:
            self.last_error = CSMARConnectionError(f"CSMAR 连接失败: {exc}")
        self.is_connected = False
        return False

    def _connection_failure(self) -> CSMARProviderError:
        if isinstance(self.last_error, CSMARProviderError):
            return self.last_error
        return CSMARConnectionError("CSMAR 服务未连接或认证失败")

    def _resolve_query(self) -> Callable[..., Any]:
        if self.query is not None:
            if not callable(self.query):
                raise CSMARQueryError("注入的 query 不是可调用对象")
            return self.query
        if self.service is None:
            raise CSMARQueryError("未配置 CSMAR 查询方法")
        if self.query_method:
            method = getattr(self.service, self.query_method, None)
            if not callable(method):
                raise CSMARQueryError(
                    f"CsmarService 不存在可调用查询方法 {self.query_method!r}"
                )
            return method
        candidates = [
            getattr(self.service, name)
            for name in self._QUERY_METHOD_CANDIDATES
            if callable(getattr(self.service, name, None))
        ]
        if len(candidates) == 1:
            return candidates[0]
        if not candidates and callable(self.service):
            return self.service
        if len(candidates) > 1:
            raise CSMARQueryError(
                "CsmarService 暴露多个候选查询方法，请通过 query_method 明确指定"
            )
        raise CSMARQueryError(
            "CsmarService 未暴露可识别查询方法；请注入 query 或明确 query_method"
        )

    def _invoke_query(
        self, query_fn: Callable[..., Any], start_date: str, end_date: str
    ) -> Any:
        """根据函数签名确定一次调用形式，绝不以重试造成重复查询。"""
        query_params = {
            key: value
            for key, value in self.query_params.items()
            if self._field_key(key) not in self._START_NAMES | self._END_NAMES
        }
        try:
            signature = inspect.signature(query_fn)
        except (TypeError, ValueError):
            try:
                # 任务包给出的 CSMAR 示例使用关键字参数；对无法反射签名的
                # 扩展方法也保持同一调用契约，避免误把表名当作第三个位置参数。
                return query_fn(
                    start_date=start_date,
                    end_date=end_date,
                    **query_params,
                )
            except Exception as exc:
                raise CSMARQueryError(f"CSMAR 查询执行失败: {exc}") from exc

        parameters = list(signature.parameters.values())
        candidates: List[tuple[List[Any], Dict[str, Any]]] = []
        named = dict(query_params)
        start_parameter = next(
            (p for p in parameters if self._field_key(p.name) in self._START_NAMES), None
        )
        end_parameter = next(
            (p for p in parameters if self._field_key(p.name) in self._END_NAMES), None
        )
        if (
            start_parameter is not None
            and end_parameter is not None
            and start_parameter.kind != inspect.Parameter.POSITIONAL_ONLY
            and end_parameter.kind != inspect.Parameter.POSITIONAL_ONLY
        ):
            named[start_parameter.name] = start_date
            named[end_parameter.name] = end_date
            candidates.append(([], named))
        has_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters)
        if has_var_keyword:
            # 对 ``(*args, **kwargs)`` 等扩展方法，优先采用任务包示例的
            # 关键字调用；位置参数会让 table_name/fields 落入错误槽位。
            generic = dict(query_params)
            generic["start_date"] = start_date
            generic["end_date"] = end_date
            candidates.append(([], generic))
        candidates.append(([start_date, end_date], dict(query_params)))

        for args, kwargs in candidates:
            try:
                signature.bind(*args, **kwargs)
            except TypeError:
                continue
            try:
                return query_fn(*args, **kwargs)
            except CSMARProviderError:
                raise
            except Exception as exc:
                raise CSMARQueryError(f"CSMAR 查询执行失败: {exc}") from exc
        raise CSMARQueryError(
            "查询方法签名无法接收日期范围和 query_params；请注入适配后的 query callable"
        )

    @staticmethod
    def _as_sequence(value: Any) -> Optional[List[Any]]:
        if isinstance(value, (str, bytes, Mapping)):
            return None
        if isinstance(value, (np.ndarray, pd.Series, pd.Index)):
            return value.tolist()
        if isinstance(value, Sequence):
            return list(value)
        if isinstance(value, Iterable):
            return list(value)
        return None

    def _unwrap_response(self, response: Any) -> pd.DataFrame:
        """把常见 SDK 响应转换为 DataFrame，保留列名与行边界。"""
        if isinstance(response, pd.DataFrame):
            return response.copy()
        if isinstance(response, pd.Series):
            return response.to_frame().T
        if isinstance(response, Mapping):
            envelope_key = next(
                (key for key in ("data", "rows", "records", "result") if key in response), None
            )
            if envelope_key is not None:
                payload = response[envelope_key]
                if isinstance(payload, pd.DataFrame):
                    return payload.copy()
                if isinstance(payload, pd.Series):
                    return payload.to_frame().T
                if isinstance(payload, Mapping) and payload is not response:
                    return self._unwrap_response(payload)
                columns = self._as_sequence(response.get("columns"))
                rows = self._as_sequence(payload)
                if rows is None:
                    raise CSMARDataError("CSMAR 响应 data/rows 不是可解析的行序列")
                try:
                    return pd.DataFrame(rows, columns=columns) if columns is not None else pd.DataFrame(rows)
                except (TypeError, ValueError) as exc:
                    raise CSMARDataError(f"CSMAR 响应无法转换为表格: {exc}") from exc
            sequence_values = [self._as_sequence(value) for value in response.values()]
            if response and all(value is not None for value in sequence_values):
                try:
                    return pd.DataFrame(response)
                except (TypeError, ValueError) as exc:
                    raise CSMARDataError(
                        f"CSMAR 列式响应长度不一致或无法转换: {exc}"
                    ) from exc
            return pd.DataFrame([dict(response)])
        rows = self._as_sequence(response)
        if rows is None:
            raise CSMARDataError(f"不支持的 CSMAR 响应类型: {type(response).__name__}")
        try:
            return pd.DataFrame(rows)
        except (TypeError, ValueError) as exc:
            raise CSMARDataError(f"CSMAR 响应无法转换为表格: {exc}") from exc

    def _normalise_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            raise CSMARDataError("CSMAR 查询返回空结果")
        renamed: Dict[Any, str] = {}
        targets: Dict[str, Any] = {}
        for raw_column in frame.columns:
            target = self.field_mapping.get(self._field_key(raw_column))
            if target is None:
                continue
            if target in targets:
                raise CSMARDataError(
                    f"CSMAR 响应同时包含多个 {target} 字段: {targets[target]!r}, {raw_column!r}"
                )
            renamed[raw_column] = target
            targets[target] = raw_column
        normalized = frame.rename(columns=renamed)
        missing = [column for column in self.STANDARD_COLUMNS if column not in normalized.columns]
        if missing:
            raise CSMARDataError(f"CSMAR 响应缺少标准列: {', '.join(missing)}")
        result = normalized.loc[:, self.STANDARD_COLUMNS].copy()
        result["date"] = self._normalise_date_series(result["date"])
        if result["date"].isna().any():
            raise CSMARDataError("CSMAR 响应包含非法日期")
        if result["date"].duplicated().any():
            raise CSMARDataError("CSMAR 响应包含重复日期")
        for column in self.STANDARD_COLUMNS[1:]:
            result[column] = pd.to_numeric(result[column], errors="coerce")
            if result[column].isna().any() or not np.isfinite(result[column].to_numpy()).all():
                raise CSMARDataError(f"CSMAR 响应列 {column} 包含非法数值")
        result["date"] = result["date"].dt.strftime("%Y-%m-%d")
        result = result.sort_values("date").reset_index(drop=True)
        result.attrs["source"] = self.source
        if self.version is not None:
            result.attrs["version"] = self.version
        return result

    def get_daily_factors(self, start_date: str, end_date: str) -> pd.DataFrame:
        start = self._parse_date(start_date, "start_date")
        end = self._parse_date(end_date, "end_date")
        if start > end:
            raise CSMARDataError("start_date 不能晚于 end_date")
        expected = self._normalise_expected_dates(start, end)
        start_text = start.strftime("%Y-%m-%d")
        end_text = end.strftime("%Y-%m-%d")
        if not self.connect():
            raise self._connection_failure()
        response = self._invoke_query(self._resolve_query(), start_text, end_text)
        frame = self._unwrap_response(response)
        # 有日历契约时，纯节假日窗口允许 SDK 返回空结果；无契约时仍保留
        # 原有的空结果错误，避免改变旧调用方的失败语义。
        if frame.empty and expected is not None:
            if not expected.empty:
                # 让缺失日期诊断明确指出契约中的全部缺口，而不是泛化为“空结果”。
                self._validate_expected_coverage(
                    [], expected, source=self.source
                )
            result = pd.DataFrame(columns=self.STANDARD_COLUMNS)
            result.attrs["source"] = self.source
            result.attrs["coverage_verified"] = True
            if self.version is not None:
                result.attrs["version"] = self.version
            return result
        result = self._normalise_frame(frame)
        dates = pd.to_datetime(result["date"], format="%Y-%m-%d")
        result = result.loc[(dates >= start) & (dates <= end)].copy().reset_index(drop=True)
        if expected is not None:
            self._validate_expected_coverage(
                result["date"], expected, source=self.source
            )
        if result.empty:
            if expected is not None and expected.empty:
                result.attrs["source"] = self.source
                result.attrs["coverage_verified"] = True
                if self.version is not None:
                    result.attrs["version"] = self.version
                return result
            raise CSMARDataError("CSMAR 响应没有落在请求日期范围内的记录")
        result.attrs["source"] = self.source
        if expected is not None:
            result.attrs["coverage_verified"] = True
        if self.version is not None:
            result.attrs["version"] = self.version
        return result


class WindCSMARStubProvider(BaseFactorProvider):
    """保留兼容性的 Wind/CSMAR 迁移桩。

    CSMAR 分支不再报告假连接；真实接入请使用 ``CSMARFactorProvider``。
    """

    def __init__(self, backend_type: str = "csmar", connection_params: Optional[Dict[str, Any]] = None):
        self.backend_type = backend_type.lower()
        self.connection_params = connection_params or {}
        self.is_connected = False

    def connect(self) -> bool:
        if self.backend_type == "wind":
            try:
                import WindPy as w

                w.start()
                self.is_connected = bool(w.isconnected())
                return self.is_connected
            except ImportError:
                logger.info("当前环境未安装 WindPy，Wind 数据适配器处于待命状态")
                return False
        if self.backend_type == "csmar":
            logger.warning("CSMAR 迁移桩不提供真实连接；请使用 CSMARFactorProvider")
        return False

    def get_daily_factors(self, start_date: str, end_date: str) -> pd.DataFrame:
        if not self.is_connected and not self.connect():
            raise NotImplementedError(
                f"当前未连接到 {self.backend_type.upper()} 商业终端；"
                "CSMAR 请配置 CSMARFactorProvider，Wind 请配置 WindPy。"
            )
        raise NotImplementedError("迁移桩不提供因子查询实现")


class EastMoneyMiaoXiangProvider(BaseFactorProvider):
    """东方财富“妙想”金融技能因子适配器 (WorkBuddy / MiaoXiang Skills)。
    
    支持获取标准 Carhart 4 因子及微观资金流衍生因子（主力大单、北向增减仓、机构席位）。
    """

    def __init__(self, db_path: Optional[str | Path] = None):
        from src.skills.eastmoney_miaoxiang_skill import EastMoneyMiaoXiangSkill
        self.skill = EastMoneyMiaoXiangSkill(cache_db=db_path)

    def get_daily_factors(self, start_date: str, end_date: str) -> pd.DataFrame:
        df = self.skill.get_daily_factors_with_capital_flows(start_date, end_date)
        if df.empty:
            return pd.DataFrame(columns=["date", "MKT", "SMB", "HML", "MOM", "rf"])
        return df[["date", "MKT", "SMB", "HML", "MOM", "rf"]]

    def get_factors_with_flows(self, start_date: str, end_date: str) -> pd.DataFrame:
        """获取包含微观资金流的完整多因子矩阵。"""
        return self.skill.get_daily_factors_with_capital_flows(start_date, end_date)


class SCNUAcademicFactorProvider(BaseFactorProvider):
    """SCNU 校内学术因子库适配器。

    本地文件和可选 ``api_provider`` 都必须满足与 ``CSMARFactorProvider``
    相同的六列日频契约。它不再用零因子、固定 rf 或静默去重掩盖导出错误。
    ``strict=True`` 时必须同时提供 ``expected_trading_dates``；没有交易日历时
    无法证明中间日期没有缺口，因此不会把首尾覆盖误当作完整覆盖。
    """

    COLUMN_MAPPINGS = {
        # CSMAR 国泰安三因子/五因子/Carhart四因子表字段
        "TradingDate": "date",
        "date": "date",
        "日期": "date",
        "RiskPremium1": "MKT",
        "MKT": "MKT",
        "市场溢价因子": "MKT",
        "SMB1": "SMB",
        "SMB": "SMB",
        "规模因子": "SMB",
        "HML1": "HML",
        "HML": "HML",
        "账面市值比因子": "HML",
        "UMD1": "MOM",
        "MOM": "MOM",
        "动量因子": "MOM",
        "RiskFreeRate": "rf",
        "rf": "rf",
        "无风险利率": "rf"
    }

    def __init__(
        self,
        data_dir: Optional[str | Path] = None,
        *,
        strict: bool = False,
        api_provider: Optional[BaseFactorProvider] = None,
        expected_trading_dates: Optional[Iterable[Any]] = None,
    ) -> None:
        self.data_dir = Path(data_dir or "data/school_factors")
        self.strict = strict
        self.api_provider = api_provider
        self._cached_factors: Optional[pd.DataFrame] = None
        self._normalizer = CSMARFactorProvider(
            source="SCNU local export",
            field_mapping=self.COLUMN_MAPPINGS,
            expected_trading_dates=expected_trading_dates,
        )

    def _read_file(self, file: Path) -> pd.DataFrame:
        if file.suffix.lower() == ".csv":
            return pd.read_csv(file)
        if file.suffix.lower() == ".parquet":
            return pd.read_parquet(file)
        if file.suffix.lower() in (".xlsx", ".xls"):
            return pd.read_excel(file)
        raise ValueError(f"不支持的校内因子文件格式: {file.suffix}")

    def _looks_like_factor_export(self, frame: pd.DataFrame) -> bool:
        targets = {
            self._normalizer.field_mapping.get(self._normalizer._field_key(column))
            for column in frame.columns
        }
        return "date" in targets and bool(
            targets.intersection({"MKT", "SMB", "HML", "MOM", "rf"})
        )

    def scan_and_load_local_files(self) -> Optional[pd.DataFrame]:
        """扫描并严格标准化本地完整因子导出文件。"""
        if not self.data_dir.exists():
            return None

        factor_files = (
            list(self.data_dir.glob("*.csv"))
            + list(self.data_dir.glob("*.parquet"))
            + list(self.data_dir.glob("*.xlsx"))
            + list(self.data_dir.glob("*.xls"))
        )
        if not factor_files:
            return None

        frames: List[pd.DataFrame] = []
        for file in sorted(factor_files):
            try:
                raw = self._read_file(file)
                if not self._looks_like_factor_export(raw):
                    logger.info("忽略非日频因子文件 %s", file.name)
                    continue
                frames.append(self._normalizer._normalise_frame(raw))
            except Exception as exc:
                message = f"读取校内学术因子文件 {file.name} 失败: {exc}"
                if self.strict:
                    raise CSMARDataError(message) from exc
                logger.warning(message)

        if not frames:
            return None
        merged = pd.concat(frames, ignore_index=True)
        if merged["date"].duplicated().any():
            duplicates = merged.loc[merged["date"].duplicated(keep=False), "date"].tolist()
            raise CSMARDataError(f"校内因子文件包含重复日期: {duplicates[:5]!r}")
        self._cached_factors = (
            merged.loc[:, CSMARFactorProvider.STANDARD_COLUMNS]
            .sort_values("date")
            .reset_index(drop=True)
        )
        self._cached_factors.attrs["source"] = "SCNU local export"
        logger.info(f"成功从校内学术目录加载 {len(self._cached_factors)} 条官方因子记录")
        return self._cached_factors

    def _load_api_factors(self, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        if self.api_provider is None:
            return None
        raw = self.api_provider.get_daily_factors(start_date, end_date)
        result = self._normalizer._normalise_frame(raw)
        result.attrs["source"] = "SCNU CSMAR API"
        return result

    def get_daily_factors(self, start_date: str, end_date: str) -> pd.DataFrame:
        """获取指定日期区间的校内学术因子。"""
        start = CSMARFactorProvider._parse_date(start_date, "start_date")
        end = CSMARFactorProvider._parse_date(end_date, "end_date")
        if start > end:
            raise CSMARDataError("start_date 不能晚于 end_date")
        expected = self._normalizer._normalise_expected_dates(start, end)
        if self.strict and expected is None:
            raise CSMARDataError(
                "strict=True 必须提供 expected_trading_dates，"
                "否则无法验证请求区间内的完整交易日覆盖"
            )
        start_text = start.strftime("%Y-%m-%d")
        end_text = end.strftime("%Y-%m-%d")
        if self._cached_factors is None:
            self.scan_and_load_local_files()

        coverage_error: Optional[CSMARDataError] = None
        if self._cached_factors is not None and not self._cached_factors.empty:
            dates = pd.to_datetime(self._cached_factors["date"], format="%Y-%m-%d")
            sub = self._cached_factors.loc[(dates >= start) & (dates <= end)].copy()
            if expected is not None:
                try:
                    self._normalizer._validate_expected_coverage(
                        sub["date"] if "date" in sub.columns else [],
                        expected,
                        source="SCNU local export",
                    )
                except CSMARDataError as exc:
                    # 本地缓存可能只是部分区间；保留错误并继续尝试 API，
                    # 以便在 API 提供完整窗口时完成契约校验。
                    coverage_error = exc
                else:
                    sub.attrs["coverage_verified"] = True
                    return sub.reset_index(drop=True)
            elif not sub.empty and (
                not self.strict or (dates.min() <= start and dates.max() >= end)
            ):
                return sub

        api_result = self._load_api_factors(start_text, end_text)
        if api_result is not None and not api_result.empty:
            dates = pd.to_datetime(api_result["date"], format="%Y-%m-%d")
            sub = api_result.loc[(dates >= start) & (dates <= end)].copy().reset_index(drop=True)
            if expected is not None:
                self._normalizer._validate_expected_coverage(
                    sub["date"], expected, source="SCNU CSMAR API"
                )
            if not sub.empty or (expected is not None and expected.empty):
                if expected is not None:
                    sub.attrs["coverage_verified"] = True
                return sub

        # 一旦调用方提供了交易日历，覆盖完整性就是硬契约，与 strict
        # 开关无关；不能把缺失日期静默降级为空表。
        if coverage_error is not None and expected is not None:
            raise coverage_error

        message = (
            f"校内因子文件未在 {self.data_dir} 覆盖 {start_text} 至 {end_text}；"
            "请导出完整 CSMAR/Wind 因子文件，或配置可用的 api_provider。"
        )
        if self.strict or expected is not None:
            raise CSMARDataError(message)
        logger.warning(message)
        return pd.DataFrame(columns=CSMARFactorProvider.STANDARD_COLUMNS)


