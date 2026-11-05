# -*- coding: utf-8 -*-
"""tests/test_net_guard.py —— 出站网络护栏回归。

## 事故背景（2026-11-02）

1. **IPv6 单向故障**：`push2his.eastmoney.com` 的 DNS 优先返回 IPv6，
   TCP/TLS 都能握手，但 HTTP 请求被对端 RST。Python 的 `requests`/`urllib3`/
   `http.client` 只尝试第一个地址、不做 Happy Eyeballs 回退，于是全部
   `RemoteDisconnected`；同机 `curl -4` 却是 200。受影响的是
   `stock_zh_a_hist` / `stock_board_industry_hist_em` / `fund_etf_hist_em`
   等 AkShare 核心接口。
2. **curl_cffi CA 路径**：`PYTHONUTF8=1` + 工程位于中文路径时，libcurl 收到
   编码错乱的 CA 路径，报 `curl: (77) error adding trust anchors`，
   `ak.stock_news_em` 100% 失败。

本文件只验证护栏的**行为契约**，不发起任何真实网络请求。
"""

from __future__ import annotations

import socket

import pytest

from src import net_guard


@pytest.fixture(autouse=True)
def _restore_socket_and_env(monkeypatch):
    """每个用例前后都恢复 socket.getaddrinfo 与相关环境变量。

    注意必须在 **yield 之前**也重置一次：``import src`` 会执行包级
    ``configure_outbound_network()``，护栏在测试开始前就已经是启用状态。
    只在结束后清理，会让第一个用例误以为补丁没装。
    """

    import os

    original = socket.getaddrinfo
    saved_env = {
        k: os.environ.get(k)
        for k in ("CURL_CA_BUNDLE", "SSL_CERT_FILE",
                  net_guard.IPV4_PREFERENCE_ENV, net_guard.CA_BUNDLE_ENV)
    }

    def _reset_state():
        socket.getaddrinfo = original
        net_guard._ipv4_preference_installed = False
        net_guard._original_getaddrinfo = None
        net_guard._ascii_ca_bundle_path = None

    _reset_state()
    yield
    _reset_state()
    for key, value in saved_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


# ============================================================================
# IPv4 优先
# ============================================================================


class TestPreferIPv4:
    def test_patch_pins_family_to_af_inet(self):
        """打补丁后，任何 family 参数都必须被钉成 AF_INET。"""

        seen: list[int] = []
        original = socket.getaddrinfo

        def fake(host, port, family=0, type=0, proto=0, flags=0):
            seen.append(family)
            return []

        socket.getaddrinfo = fake
        net_guard._original_getaddrinfo = fake
        net_guard.prefer_ipv4(enabled=True)

        socket.getaddrinfo("example.com", 443, socket.AF_INET6)
        socket.getaddrinfo("example.com", 443)
        socket.getaddrinfo = original

        assert seen == [socket.AF_INET, socket.AF_INET]

    def test_installation_is_idempotent(self):
        """重复调用不能把 getaddrinfo 套娃包裹。"""

        net_guard.prefer_ipv4(enabled=True)
        first = socket.getaddrinfo
        net_guard.prefer_ipv4(enabled=True)
        assert socket.getaddrinfo is first

    def test_disable_restores_original(self):
        """显式关闭后必须还原原始 getaddrinfo。"""

        original = socket.getaddrinfo
        net_guard.prefer_ipv4(enabled=True)
        assert socket.getaddrinfo is not original

        net_guard.prefer_ipv4(enabled=False)
        assert socket.getaddrinfo is original
        assert net_guard.ipv4_preference_active() is False

    def test_env_var_can_disable(self, monkeypatch):
        """STOCK_FORCE_IPV4=0 时默认不启用，方便 IPv6 健康的机器恢复默认。"""

        monkeypatch.setenv(net_guard.IPV4_PREFERENCE_ENV, "0")
        assert net_guard.prefer_ipv4() is False
        assert net_guard.ipv4_preference_active() is False

    @pytest.mark.parametrize("raw", ["1", "true", "yes", "on", "TRUE"])
    def test_env_var_truthy_values(self, monkeypatch, raw):
        monkeypatch.setenv(net_guard.IPV4_PREFERENCE_ENV, raw)
        assert net_guard.prefer_ipv4() is True

    def test_env_flag_falls_back_to_default_for_garbage(self, monkeypatch):
        monkeypatch.setenv(net_guard.IPV4_PREFERENCE_ENV, "maybe")
        assert net_guard._env_flag(net_guard.IPV4_PREFERENCE_ENV, True) is True


# ============================================================================
# CA bundle 归一化
# ============================================================================


class TestAsciiCaBundle:
    def test_ascii_source_is_exported_without_copying(self, monkeypatch):
        """源路径本就是 ASCII 时，直接导出，不做无谓复制。

        这里刻意用系统临时目录而不是 ``tmp_path``：本工程的 ``tmp_path``
        落在 ``D:\\股票分析项目\\...`` 下，本身就不是 ASCII 路径。
        """

        import os
        import tempfile

        ca = os.path.join(tempfile.gettempdir(), "net_guard_ascii_ca.pem")
        with open(ca, "w", encoding="utf-8") as fh:
            fh.write("dummy")
        assert ca.isascii(), f"测试前置条件失败：{ca} 不是 ASCII 路径"

        monkeypatch.setattr("certifi.where", lambda: ca)
        monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
        net_guard._ascii_ca_bundle_path = None

        result = net_guard.ensure_ascii_ca_bundle(enabled=True)

        assert result == ca
        assert os.environ["CURL_CA_BUNDLE"] == ca

    def test_non_ascii_source_is_copied_to_ascii_temp(self, monkeypatch, tmp_path):
        """中文路径下的 CA 必须被复制到 ASCII 位置，否则 libcurl 打不开。

        关键：必须显式传 ``target_path``，否则会覆盖系统临时目录里的**真实**
        共享 CA 文件——本测试曾经真的把 18 字节的 dummy 写进
        ``%TEMP%/stock_dashboard_ca/cacert.pem``，导致后续所有 requests
        抓取 SSL 失败。
        """

        import os

        # 构造一个含非 ASCII 字符的源路径
        weird = tmp_path / "股票分析项目"
        weird.mkdir()
        ca = weird / "cacert.pem"
        ca.write_text("dummy-cert-content", encoding="utf-8")
        assert not str(ca).isascii()

        # 目标放到纯 ASCII 的独立目录（tmp_path 本身在中文路径下，不能直接用）
        ascii_target = os.path.join(
            os.path.abspath(os.sep), "Windows", "Temp",
            "net_guard_test_target", "cacert.pem",
        ) if os.name == "nt" else "/tmp/net_guard_test_target/cacert.pem"
        ascii_target = os.path.join(
            __import__("tempfile").gettempdir(),
            "net_guard_test_target", "cacert.pem",
        )

        monkeypatch.setattr("certifi.where", lambda: str(ca))
        monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
        net_guard._ascii_ca_bundle_path = None

        try:
            result = net_guard.ensure_ascii_ca_bundle(
                enabled=True, target_path=ascii_target
            )

            assert result is not None
            assert result.isascii(), f"归一化后的路径必须全 ASCII，实际: {result}"
            assert os.path.exists(result)
            assert open(result, encoding="utf-8").read() == "dummy-cert-content"
            assert os.environ["CURL_CA_BUNDLE"] == result
        finally:
            # 清理测试产生的临时 CA，避免残留污染
            if os.path.exists(ascii_target):
                os.remove(ascii_target)

    def test_ssl_cert_file_is_never_set(self, monkeypatch, tmp_path):
        """回归守卫：设置 SSL_CERT_FILE 会让 requests 丢失 Windows 系统根证书。

        实测后果：``17.push2.eastmoney.com`` 直接 SSL 验证失败，
        而这只发生在设置了 SSL_CERT_FILE 之后。
        """

        import os

        weird = tmp_path / "中文目录"
        weird.mkdir()
        ca = weird / "cacert.pem"
        ca.write_text("dummy", encoding="utf-8")
        ascii_target = os.path.join(
            __import__("tempfile").gettempdir(), "net_guard_ssl_test", "cacert.pem"
        )

        monkeypatch.setattr("certifi.where", lambda: str(ca))
        monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
        monkeypatch.delenv("SSL_CERT_FILE", raising=False)
        net_guard._ascii_ca_bundle_path = None

        try:
            net_guard.ensure_ascii_ca_bundle(enabled=True, target_path=ascii_target)
            assert os.environ["CURL_CA_BUNDLE"] == ascii_target
            assert "SSL_CERT_FILE" not in os.environ, (
                "绝不能设置 SSL_CERT_FILE：它会替换 requests 的系统证书链"
            )
        finally:
            if os.path.exists(ascii_target):
                os.remove(ascii_target)

    def test_existing_env_bundle_is_respected(self, monkeypatch, tmp_path):
        """运维已显式设置 CURL_CA_BUNDLE 时不得覆盖。"""

        preset = tmp_path / "preset.pem"
        preset.write_text("preset", encoding="utf-8")
        monkeypatch.setenv("CURL_CA_BUNDLE", str(preset))

        assert net_guard.ensure_ascii_ca_bundle(enabled=True) == str(preset)

    def test_missing_certifi_returns_none(self, monkeypatch):
        """certifi 缺失（异常环境）时静默跳过，不阻断抓取。"""

        def boom():
            raise ImportError("no certifi")

        monkeypatch.setattr("certifi.where", boom)
        monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)

        # certifi 能 import，但 where() 抛错 -> 走 OSError 分支之外；
        # 这里显式模拟 where() 返回不存在路径
        monkeypatch.setattr("certifi.where", lambda: "/nonexistent/cacert.pem")
        assert net_guard.ensure_ascii_ca_bundle(enabled=True) is None

    def test_disable_skips_work(self, monkeypatch):
        monkeypatch.setenv(net_guard.CA_BUNDLE_ENV, "0")
        assert net_guard.ensure_ascii_ca_bundle() is None


# ============================================================================
# 组合入口
# ============================================================================


def test_configure_outbound_network_reports_both_switches(monkeypatch):
    """组合入口必须同时报告两个护栏的状态，便于日志诊断。"""

    import os
    import tempfile

    ca = os.path.join(tempfile.gettempdir(), "net_guard_combo_ca.pem")
    with open(ca, "w", encoding="utf-8") as fh:
        fh.write("dummy")
    monkeypatch.setattr("certifi.where", lambda: ca)
    monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
    net_guard._ascii_ca_bundle_path = None

    info = net_guard.configure_outbound_network()

    assert info["ipv4_preference"] is True
    assert info["ca_bundle"] == ca
    assert net_guard.ipv4_preference_active() is True


def test_configure_outbound_network_can_disable_everything(monkeypatch):
    info = net_guard.configure_outbound_network(ipv4=False, ca_bundle=False)
    assert info == {"ipv4_preference": False, "ca_bundle": None}


# ============================================================================
# 接线守卫：入口脚本必须在 import akshare 之前装好护栏
# ============================================================================


class TestEntryPointsInstallTheGuard:
    """护栏没接线等于没修——用源码顺序钉住接线位置。"""

    @pytest.mark.parametrize(
        "relative_path",
        ["src/fetch_data.py", "src/build_ranking.py"],
    )
    def test_guard_runs_before_akshare_import(self, relative_path):
        """护栏调用必须在真正的 ``import akshare`` 语句之前。

        注意：不能用 ``str.find`` 找 "import akshare" ——注释里也常出现这串字，
        会误判成 import 在前。这里按行定位**真实语句**（行首非注释）。
        """
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        lines = (root / relative_path).read_text(encoding="utf-8").splitlines()

        guard_line = None
        akshare_line = None
        for idx, raw in enumerate(lines, start=1):
            stripped = raw.strip()
            if stripped.startswith("#"):
                continue
            if guard_line is None and stripped.startswith("configure_outbound_network("):
                guard_line = idx
            if akshare_line is None and stripped in ("import akshare", "import akshare as ak"):
                akshare_line = idx

        assert guard_line is not None, f"{relative_path} 未调用 configure_outbound_network"
        assert akshare_line is not None, f"{relative_path} 未导入 akshare"
        assert guard_line < akshare_line, (
            f"{relative_path}: configure_outbound_network（第 {guard_line} 行）必须在 "
            f"import akshare（第 {akshare_line} 行）之前调用，"
            "否则 curl_cffi 已把 CA 路径固化成模块级常量"
        )

    def test_package_init_installs_the_guard(self):
        """包级 __init__ 是唯一能先于所有子模块 akshare 导入的位置。"""

        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        text = (root / "src" / "__init__.py").read_text(encoding="utf-8")
        assert "configure_outbound_network()" in text


class TestIndustryPeriodToken:
    """东财行业板块接口的 period 取值与其它接口不同，传错必 KeyError。"""

    def test_period_token_is_the_chinese_one(self):
        from src.analysis.industry import BOARD_HIST_PERIOD

        assert BOARD_HIST_PERIOD == "日k"

    def test_industry_module_does_not_use_daily_token(self):
        """反向守卫：把 "daily" 传给 stock_board_industry_hist_em 会 KeyError。"""

        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        text = (root / "src" / "analysis" / "industry.py").read_text(encoding="utf-8")

        # 定位调用块，确认传给板块接口的不是 "daily"
        call_at = text.find("ak.stock_board_industry_hist_em(")
        assert call_at != -1
        block = text[call_at:call_at + 400]
        assert 'period="daily"' not in block, (
            "stock_board_industry_hist_em 只接受 {'日k','周k','月k'}，"
            "传 'daily' 会在 period_map 里 KeyError"
        )
        assert "period=BOARD_HIST_PERIOD" in block
