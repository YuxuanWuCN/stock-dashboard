# -*- coding: utf-8 -*-
"""Rainbow-FinGPT v2 - 离线演示模式与零崩溃弹性容灾测试用例集。

覆盖范围：
1. 本地离线 K 线缓存安全读取 (_get_offline_kline)
2. 大盘基准指数离线映射与兜底 (_get_offline_index)
3. /api/query 路由在 OFFLINE_MODE 下的零网络依赖响应
4. /api/query 在实时接口故障时的自动优雅降级与 HTTP 200 返回 (meta.offline_demo = True)
5. 未收录代码的友好 404 提示
6. tools/setup_env.py 的 .gitignore 安全防泄漏校验
"""

from unittest.mock import patch
import pytest

from src.server import (
    app,
    _get_offline_kline,
    _get_offline_index,
    get_index_for_code,
)
from src.config import _env_flag
from tools.setup_env import check_gitignore_protection, mask_secret


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_offline_kline_loader_existing_stock():
    """验证 688525 离线 K 线缓存正确读取。"""
    data = _get_offline_kline("688525")
    assert data is not None
    assert data.get("code") == "688525"
    assert data.get("name") == "佰维存储"
    assert "dates" in data
    assert len(data["dates"]) > 50
    assert "kline" in data
    assert len(data["kline"]) == len(data["dates"])


def test_offline_kline_loader_nonexistent():
    """验证不存在的股票代码返回 None 而非抛出异常。"""
    data = _get_offline_kline("999999")
    assert data is None


def test_offline_index_fallback_kechuang50():
    """验证科创50 (000688) 自动映射至 588000 离线 ETF 数据。"""
    idx_data = _get_offline_index("000688", "科创50")
    assert idx_data is not None
    assert idx_data.get("name") == "科创50"
    assert idx_data.get("code") == "000688"
    assert "dates" in idx_data
    assert len(idx_data["dates"]) > 50


def test_offline_index_fallback_shanghai():
    """验证上证指数 (000001) 自动映射至 510050 离线 ETF 数据。"""
    idx_data = _get_offline_index("000001", "上证指数")
    assert idx_data is not None
    assert idx_data.get("name") == "上证指数"
    assert idx_data.get("code") == "000001"
    assert "dates" in idx_data


def test_api_query_offline_mode_returns_200(client):
    """验证在 OFFLINE_MODE 激活时，/api/query 返回 200 且标记 offline_demo。"""
    with patch("src.server.OFFLINE_MODE", True):
        resp = client.get("/api/query?code=688525")
        assert resp.status_code == 200
        json_data = resp.get_json()
        assert json_data is not None
        assert json_data["stock"]["code"] == "688525"
        assert json_data["stock"]["name"] == "佰维存储"
        assert json_data["meta"]["offline_demo"] is True
        assert "离线演示模式" in json_data["meta"]["message"]
        assert json_data["index"] is not None
        assert json_data["index"]["name"] == "科创50"


def test_api_query_network_failure_automatic_fallback(client):
    """验证在线模式下，若网络拉取返回 None，自动回退至离线数据并返回 HTTP 200。"""
    with patch("src.server.OFFLINE_MODE", False), patch("src.server.fetch_one", return_value=None):
        resp = client.get("/api/query?code=688525")
        assert resp.status_code == 200
        json_data = resp.get_json()
        assert json_data["meta"]["offline_demo"] is True
        assert json_data["stock"]["code"] == "688525"
        assert json_data["stock"]["name"] == "佰维存储"


def test_api_query_nonexistent_offline_stock(client):
    """验证未被离线缓存收录且无网络的股票代码返回规范的 404 与指引信息。"""
    with patch("src.server.OFFLINE_MODE", True):
        resp = client.get("/api/query?code=999999")
        assert resp.status_code == 404
        json_data = resp.get_json()
        assert "166" in json_data["error"]


def test_api_query_invalid_params(client):
    """验证参数校验（少于6位、非数字、非法日期）。"""
    resp1 = client.get("/api/query?code=123")
    assert resp1.status_code == 400

    resp2 = client.get("/api/query?code=ABCDEF")
    assert resp2.status_code == 400

    resp3 = client.get("/api/query?code=688525&start_date=invalid-date")
    assert resp3.status_code == 400


def test_env_flag_utility():
    """验证 _env_flag 对各种真假值的解析。"""
    with patch.dict("os.environ", {"TEST_FLAG_TRUE_1": "true", "TEST_FLAG_TRUE_2": "1", "TEST_FLAG_FALSE": "false"}):
        assert _env_flag("TEST_FLAG_TRUE_1") is True
        assert _env_flag("TEST_FLAG_TRUE_2") is True
        assert _env_flag("TEST_FLAG_FALSE") is False
        assert _env_flag("NONEXISTENT_FLAG", default=True) is True
        assert _env_flag("NONEXISTENT_FLAG", default=False) is False


def test_gitignore_security_check():
    """验证 setup_env 的 .gitignore 审计功能正确识别 .env 受保护。"""
    is_safe, msg = check_gitignore_protection()
    assert is_safe is True
    assert "安全" in msg


def test_mask_secret():
    """验证密钥掩码逻辑杜绝明文回显。"""
    assert mask_secret("") == "[未设置]"
    assert mask_secret(None) == "[未设置]"
    assert mask_secret("short") == "******** (已设置)"
    assert mask_secret("sk-1234567890abcdef") == "sk-****cdef (已设置)"
