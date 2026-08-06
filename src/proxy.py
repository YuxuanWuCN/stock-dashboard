"""Proxy helpers for AkShare/requests based data fetching."""

from __future__ import annotations

import os
from typing import Optional


def get_windows_system_proxy() -> Optional[str]:
    """Read enabled Windows system proxy and return ``host:port``."""
    if os.name != "nt":
        return None

    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        )
        enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
        if not enabled:
            return None

        server, _ = winreg.QueryValueEx(key, "ProxyServer")
        if not server:
            return None

        if "=" in server:
            parts: dict[str, str] = {}
            for part in server.split(";"):
                if "=" in part:
                    name, value = part.split("=", 1)
                    parts[name.strip().lower()] = value.strip()
            server = parts.get("https") or parts.get("http") or next(iter(parts.values()), "")

        server = server.strip()
        return server or None
    except OSError:
        return None


def configure_proxy_from_system() -> Optional[str]:
    """Configure requests-compatible proxy environment variables.

    Returns the proxy URL if configured; otherwise returns ``None`` and keeps
    direct connections.
    """
    proxy = get_windows_system_proxy()

    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        os.environ.pop(key, None)

    if not proxy:
        os.environ["NO_PROXY"] = "*"
        os.environ["no_proxy"] = "*"
        return None

    proxy_url = proxy if "://" in proxy else f"http://{proxy}"
    os.environ["HTTP_PROXY"] = proxy_url
    os.environ["HTTPS_PROXY"] = proxy_url
    os.environ["http_proxy"] = proxy_url
    os.environ["https_proxy"] = proxy_url
    os.environ.pop("NO_PROXY", None)
    os.environ.pop("no_proxy", None)
    return proxy_url
