"""src/net_guard.py —— 出站网络可靠性护栏（地址族策略 + CA bundle 归一化）。

## 为什么需要这个模块

本机（以及部分家庭宽带 / 校园网）的 IPv6 出口存在单向故障：
DNS 会优先返回 IPv6 地址，TCP 握手也能成功，但 HTTP 请求会被对端直接 RST，
表现为 ``RemoteDisconnected('Remote end closed connection without response')``。

Python 的 ``socket.getaddrinfo`` 会返回 IPv6 优先的顺序，而 ``requests`` /
``urllib3`` / ``http.client`` 只尝试**第一个**地址、不做 Happy Eyeballs 回退，
于是所有走 IPv6 优先的主机全部失败，而同一台机器上的 ``curl -4`` 却完全正常。

实测证据（2026-11-02，``push2his.eastmoney.com``）：

===================  ==========================================
方式                 结果
===================  ==========================================
``curl -4``          200
``curl -6``          000（连接被对端关闭）
Python 默认地址族     RemoteDisconnected
强制 IPv4            200
===================  ==========================================

东方财富的 ``push2his`` / ``push2`` 域名承载 ``stock_zh_a_hist``、
``stock_board_industry_hist_em``、``fund_etf_hist_em`` 等 AkShare 核心接口，
因此该故障会让整条行情抓取链路静默降级（行业板块数据 100% 缺失、回落到指数）。

## 模块职责

1. :func:`prefer_ipv4` —— 进程级地址族策略。在 ``import akshare`` **之前**调用，
   之后所有 ``getaddrinfo`` 只返回 A 记录，从根上绕开坏掉的 IPv6 出口。
2. :func:`ensure_ascii_ca_bundle` —— 把 CA bundle 落到纯 ASCII 路径并导出
   ``CURL_CA_BUNDLE``。``curl_cffi`` 在 ``PYTHONUTF8=1`` 且工程位于中文路径时，
   会在 C 层拼出错误的 CA 路径并报 ``curl: (77) error adding trust anchors``。
3. :func:`configure_outbound_network` —— 上面两者的组合入口，供各抓取入口脚本
   在 ``import akshare`` 前统一调用。

## 约束

- 本模块只做「让请求能发出去」，不改变任何业务语义；
- 所有开关都可被环境变量覆盖，便于在 IPv6 健康的机器上恢复默认行为；
- 不吞异常：配置失败只记日志，不阻断主流程。
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import tempfile
from typing import Callable, Optional

logger = logging.getLogger("stock-dashboard.net_guard")

#: 设为 ``0`` / ``false`` / ``no`` 可关闭 IPv4 优先（默认开启）。
IPV4_PREFERENCE_ENV = "STOCK_FORCE_IPV4"
#: 设为 ``0`` 可关闭 CA bundle 归一化。
CA_BUNDLE_ENV = "STOCK_ASCII_CA_BUNDLE"

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}

#: 进程级标记，避免重复打补丁（重复包裹 getaddrinfo 会逐层套娃）。
_ipv4_preference_installed = False
_original_getaddrinfo: Optional[Callable[..., list]] = None
#: 已归一化到 ASCII 路径的 CA bundle 缓存。
_ascii_ca_bundle_path: Optional[str] = None


def _env_flag(name: str, default: bool) -> bool:
    """读取布尔型环境变量；未设置或无法识别时返回 ``default``。"""
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    value = str(raw).strip().lower()
    if value in _TRUTHY:
        return True
    if value in _FALSY:
        return False
    return default


def prefer_ipv4(enabled: Optional[bool] = None) -> bool:
    """让本进程的 DNS 解析只返回 IPv4 地址。

    Args:
        enabled: 显式开关；``None`` 时读 ``STOCK_FORCE_IPV4``（默认开启）。

    Returns:
        是否已处于「IPv4 优先」生效状态。

    幂等：重复调用不会叠加包装。被包装的 ``getaddrinfo`` 保留原始函数的所有
    参数与返回值形状，只把 ``family`` 钉成 ``AF_INET``；调用方显式请求
    ``AF_INET6`` 时仍返回空列表而非异常，与系统在无 IPv6 环境下的行为一致。
    """
    global _ipv4_preference_installed, _original_getaddrinfo

    should_enable = _env_flag(IPV4_PREFERENCE_ENV, True) if enabled is None else bool(enabled)

    if not should_enable:
        if _ipv4_preference_installed and _original_getaddrinfo is not None:
            socket.getaddrinfo = _original_getaddrinfo  # type: ignore[assignment]
            _ipv4_preference_installed = False
        return False

    if _ipv4_preference_installed:
        return True

    _original_getaddrinfo = socket.getaddrinfo

    def ipv4_only_getaddrinfo(
        host: str,
        port,
        family: int = 0,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
    ) -> list:
        return _original_getaddrinfo(  # type: ignore[misc]
            host, port, socket.AF_INET, type, proto, flags
        )

    socket.getaddrinfo = ipv4_only_getaddrinfo  # type: ignore[assignment]
    _ipv4_preference_installed = True
    logger.debug("已启用 IPv4 优先解析（%s）", IPV4_PREFERENCE_ENV)
    return True


def ipv4_preference_active() -> bool:
    """当前进程是否处于 IPv4 优先状态（供测试与诊断使用）。"""
    return _ipv4_preference_installed


def ensure_ascii_ca_bundle(
    enabled: Optional[bool] = None,
    target_path: Optional[str] = None,
) -> Optional[str]:
    """把 CA bundle 复制到纯 ASCII 路径并导出 ``CURL_CA_BUNDLE``。

    Args:
        enabled: 显式开关；``None`` 时读 ``STOCK_ASCII_CA_BUNDLE``（默认开启）。
        target_path: 目标文件路径（仅供测试注入）。``None`` 时落到系统临时目录
            下的固定位置，避免每次启动换路径。

    Returns:
        生效的 CA bundle 路径；无法处理时返回 ``None``。

    触发条件：``curl_cffi`` 通过 ``libcurl`` 的 ``CAINFO`` 选项加载证书，
    当 Python 运行在 ``PYTHONUTF8=1`` 且工程位于非 ASCII 路径（如
    ``D:\\股票分析项目\\...``）时，传给 C 层的路径编码与 libcurl 的期望不一致，
    报 ``curl: (77) error adding trust anchors from locations``，
    导致 ``ak.stock_news_em`` 等基于 curl_cffi 的接口 100% 失败。

    修复方式：把 certifi 的 ``cacert.pem`` 复制到 ASCII 临时目录，并用
    ``CURL_CA_BUNDLE`` 显式指向它——``curl_cffi._default_cacert()`` 会优先读
    这个环境变量。若原路径本就是纯 ASCII，则不复制，直接返回原路径。

    **只设 CURL_CA_BUNDLE，绝不设 SSL_CERT_FILE**：后者会被 Python ``ssl`` 模块
    当作默认验证路径，把 ``requests`` 的证书链从「Windows 系统根证书」换成
    「certifi 单文件」。实测这会让 ``17.push2.eastmoney.com`` 等站点验证失败
    （certifi 单文件缺部分根证书），是比原问题更严重的回归。
    """
    global _ascii_ca_bundle_path

    should_enable = _env_flag(CA_BUNDLE_ENV, True) if enabled is None else bool(enabled)
    if not should_enable:
        return None
    existing = os.environ.get("CURL_CA_BUNDLE")
    if existing and os.path.exists(existing):
        return existing

    try:
        import certifi
    except ImportError:  # pragma: no cover - certifi 是 requests 的硬依赖
        logger.debug("certifi 不可用，跳过 CA bundle 归一化")
        return None

    source = certifi.where()
    if not os.path.exists(source):
        logger.warning("certifi CA bundle 不存在: %s", source)
        return None

    if source.isascii():
        # 路径本身没问题，显式导出即可，省掉一次磁盘复制。
        os.environ["CURL_CA_BUNDLE"] = source
        _ascii_ca_bundle_path = source
        return source

    if _ascii_ca_bundle_path and os.path.exists(_ascii_ca_bundle_path):
        os.environ["CURL_CA_BUNDLE"] = _ascii_ca_bundle_path
        return _ascii_ca_bundle_path

    try:
        if target_path:
            # 测试注入：绝不碰真实临时目录里的共享 CA 文件，
            # 否则一个用例的 dummy 内容会污染后续所有抓取。
            target = target_path
            parent = os.path.dirname(target)
            if parent:
                os.makedirs(parent, exist_ok=True)
        else:
            target_dir = os.path.join(tempfile.gettempdir(), "stock_dashboard_ca")
            os.makedirs(target_dir, exist_ok=True)
            target = os.path.join(target_dir, "cacert.pem")

        # 只在源文件更新或目标缺失时复制，避免每次启动都写盘。
        need_copy = True
        if os.path.exists(target):
            try:
                need_copy = os.path.getmtime(source) > os.path.getmtime(target)
            except OSError:
                need_copy = True
        if need_copy:
            shutil.copyfile(source, target)
        os.environ["CURL_CA_BUNDLE"] = target
        _ascii_ca_bundle_path = target
        logger.info("CA bundle 已归一化到 ASCII 路径: %s", target)
        return target
    except OSError as exc:
        logger.warning("CA bundle 归一化失败（%s），保持原路径 %s", exc, source)
        return source


def configure_outbound_network(
    *,
    ipv4: Optional[bool] = None,
    ca_bundle: Optional[bool] = None,
) -> dict:
    """统一配置出站网络护栏，供抓取入口脚本在 ``import akshare`` 前调用。

    Returns:
        ``{"ipv4_preference": bool, "ca_bundle": Optional[str]}`` 诊断信息。
    """
    return {
        "ipv4_preference": prefer_ipv4(ipv4),
        "ca_bundle": ensure_ascii_ca_bundle(ca_bundle),
    }
