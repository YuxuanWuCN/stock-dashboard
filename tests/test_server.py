import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src import server


class ServerTestCase(unittest.TestCase):
    def setUp(self):
        self.client = server.app.test_client()

    def test_health(self):
        response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")

    def test_query_rejects_invalid_code(self):
        response = self.client.get("/api/query?code=abc")

        self.assertEqual(response.status_code, 400)

    def test_query_rejects_invalid_date(self):
        response = self.client.get(
            "/api/query?code=600519&start_date=not-a-date"
        )

        self.assertEqual(response.status_code, 400)

    def test_resolve_stock_name_uses_tencent_quote(self):
        response = type(
            "QuoteResponse",
            (),
            {"text": 'v_sz000021="51~深科技~000021~...";'},
        )()

        with (
            patch.dict(server._STOCK_NAME_CACHE, {}, clear=True),
            patch.object(server._requests, "get", return_value=response) as get,
        ):
            name = server.resolve_stock_name("000021")

        self.assertEqual(name, "深科技")
        get.assert_called_once_with(
            "https://qt.gtimg.cn/q=sz000021", timeout=10
        )

    def test_query_returns_resolved_name_in_both_payload_sections(self):
        with (
            patch.object(server, "resolve_stock_name", return_value="深科技"),
            patch.object(
                server,
                "fetch_one",
                return_value=pd.DataFrame({"close": [10.0]}),
            ),
            patch.object(server, "compute_derived", side_effect=lambda frame: frame),
            patch.object(
                server,
                "build_kline_json",
                return_value={"code": "000021", "name": "深科技", "type": "stock"},
            ),
            patch.object(server, "fetch_index", return_value=None),
        ):
            response = self.client.get(
                "/api/query?code=000021&start_date=2026-01-01"
            )

        data = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["stock"]["name"], "深科技")
        self.assertEqual(data["meta"]["stock_name"], "深科技")

    def test_cloud_watchlist_write_is_disabled(self):
        with patch.object(server, "WATCHLIST_WRITE_ENABLED", False):
            response = self.client.post(
                "/api/watchlist/add",
                json={"code": "600519", "name": "贵州茅台"},
            )

        self.assertEqual(response.status_code, 503)

    def test_watchlist_returns_configured_items(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            watchlist_path = Path(tmp_dir) / "watchlist.csv"
            watchlist_path.write_text(
                "code,name,type,category\n600519,贵州茅台,stock,白酒\n",
                encoding="utf-8",
            )
            with patch.object(server, "_WATCHLIST_PATH", str(watchlist_path)):
                response = self.client.get("/api/watchlist")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["items"][0]["code"], "600519")
        self.assertEqual(data["items"][0]["category"], "白酒")

    def test_local_watchlist_add_persists_item(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            watchlist_path = Path(tmp_dir) / "watchlist.csv"
            watchlist_path.write_text(
                "code,name,type,category\n600519,贵州茅台,stock,白酒\n",
                encoding="utf-8",
            )
            with (
                patch.object(server, "_WATCHLIST_PATH", str(watchlist_path)),
                patch.object(server, "WATCHLIST_WRITE_ENABLED", True),
            ):
                response = self.client.post(
                    "/api/watchlist/add",
                    json={
                        "code": "688525",
                        "name": "佰维存储",
                        "type": "stock",
                        "category": "科技",
                    },
                )
                listed = self.client.get("/api/watchlist").get_json()["items"]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["action"], "added")
        self.assertIn("688525", {item["code"] for item in listed})


if __name__ == "__main__":
    unittest.main()


class GitHubSyncTest(unittest.TestCase):
    """v2.5：网页加自选股自动入库 GitHub（Contents API）。"""

    def setUp(self):
        self.client = server.app.test_client()

    def _set_github_env(self):
        patch.object(server, "GITHUB_TOKEN", "ghp_test_token")
        patch.object(server, "GITHUB_REPO", "user/stock-dashboard")
        patch.object(server, "GITHUB_SYNC_ENABLED", True).start()
        return patch.object(server, "GITHUB_TOKEN", "ghp_test_token").start() or None

    def test_sync_disabled_without_token(self):
        """未配置 token 时同步关闭，api_watchlist_add 返回 github_sync 缺失。"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            watchlist_path = Path(tmp_dir) / "watchlist.csv"
            watchlist_path.write_text(
                "code,name,type,category\n600519,贵州茅台,stock,白酒\n",
                encoding="utf-8",
            )
            with (
                patch.object(server, "_WATCHLIST_PATH", str(watchlist_path)),
                patch.object(server, "WATCHLIST_WRITE_ENABLED", True),
                patch.object(server, "GITHUB_SYNC_ENABLED", False),
            ):
                response = self.client.post(
                    "/api/watchlist/add",
                    json={"code": "688525", "name": "佰维存储", "type": "stock"},
                )
        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertIn("github_sync", body)
        self.assertFalse(body["github_sync"]["success"])
        self.assertEqual(body["github_sync"]["error"], "github_sync_not_configured")

    def test_sync_push_uses_sha_and_commits(self):
        """配置 token 时调用 GitHub Contents API（GET SHA → PUT 提交）。"""
        from unittest.mock import Mock

        with tempfile.TemporaryDirectory() as tmp_dir:
            watchlist_path = Path(tmp_dir) / "watchlist.csv"
            watchlist_path.write_text(
                "code,name,type,category\n600519,贵州茅台,stock,白酒\n",
                encoding="utf-8",
            )
            get_resp = Mock(status_code=200)
            get_resp.json.return_value = {"sha": "abc123sha"}
            put_resp = Mock(status_code=201)
            put_resp.json.return_value = {"commit": {"sha": "def456commit"}}
            requests_mock = Mock()
            requests_mock.get.return_value = get_resp
            requests_mock.put.return_value = put_resp

            with (
                patch.object(server, "_WATCHLIST_PATH", str(watchlist_path)),
                patch.object(server, "WATCHLIST_WRITE_ENABLED", True),
                patch.object(server, "GITHUB_TOKEN", "ghp_test_token"),
                patch.object(server, "GITHUB_REPO", "user/stock-dashboard"),
                patch.object(server, "GITHUB_SYNC_ENABLED", True),
                patch.object(server, "_requests", requests_mock),
            ):
                response = self.client.post(
                    "/api/watchlist/add",
                    json={"code": "688525", "name": "佰维存储", "type": "stock"},
                )
                # 验证 PUT 请求带 SHA 与 base64 内容
                put_kwargs = requests_mock.put.call_args
                self.assertEqual(put_kwargs[0][0],
                                 "https://api.github.com/repos/user/stock-dashboard/contents/watchlist.csv")
                payload = put_kwargs[1]["json"]
                self.assertEqual(payload["sha"], "abc123sha")
                self.assertIn("message", payload)
                self.assertIn("content", payload)  # base64
                import base64
                decoded = base64.b64decode(payload["content"]).decode("utf-8")
                self.assertIn("688525,佰维存储", decoded)
                self.assertIn("600519,贵州茅台", decoded)

        body = response.get_json()
        self.assertEqual(body["github_sync"]["success"], True)
        self.assertEqual(body["github_sync"]["commit_sha"], "def456commit")

    def test_sync_read_404_still_creates_file(self):
        """仓库无文件时（404）不带 SHA 直接创建。"""
        from unittest.mock import Mock

        with tempfile.TemporaryDirectory() as tmp_dir:
            watchlist_path = Path(tmp_dir) / "watchlist.csv"
            watchlist_path.write_text("code,name,type,category\n", encoding="utf-8")
            get_resp = Mock(status_code=404)
            put_resp = Mock(status_code=201)
            put_resp.json.return_value = {"commit": {"sha": "newcommit"}}
            requests_mock = Mock()
            requests_mock.get.return_value = get_resp
            requests_mock.put.return_value = put_resp

            with (
                patch.object(server, "_WATCHLIST_PATH", str(watchlist_path)),
                patch.object(server, "WATCHLIST_WRITE_ENABLED", True),
                patch.object(server, "GITHUB_TOKEN", "ghp_test_token"),
                patch.object(server, "GITHUB_REPO", "user/stock-dashboard"),
                patch.object(server, "GITHUB_SYNC_ENABLED", True),
                patch.object(server, "_requests", requests_mock),
            ):
                self.client.post(
                    "/api/watchlist/add",
                    json={"code": "000001", "name": "平安银行", "type": "stock"},
                )
                payload = requests_mock.put.call_args[1]["json"]
                self.assertNotIn("sha", payload)  # 404 时无 SHA

    def test_sync_failure_does_not_block_add(self):
        """GitHub 同步失败不应阻断本地添加（降级）。"""
        from unittest.mock import Mock

        with tempfile.TemporaryDirectory() as tmp_dir:
            watchlist_path = Path(tmp_dir) / "watchlist.csv"
            watchlist_path.write_text("code,name,type,category\n", encoding="utf-8")
            requests_mock = Mock()
            requests_mock.get.side_effect = RuntimeError("network down")
            with (
                patch.object(server, "_WATCHLIST_PATH", str(watchlist_path)),
                patch.object(server, "WATCHLIST_WRITE_ENABLED", True),
                patch.object(server, "GITHUB_TOKEN", "ghp_test_token"),
                patch.object(server, "GITHUB_REPO", "user/stock-dashboard"),
                patch.object(server, "GITHUB_SYNC_ENABLED", True),
                patch.object(server, "_requests", requests_mock),
            ):
                response = self.client.post(
                    "/api/watchlist/add",
                    json={"code": "600036", "name": "招商银行", "type": "stock"},
                )
        body = response.get_json()
        self.assertEqual(response.status_code, 200)  # 本地添加成功
        self.assertFalse(body["github_sync"]["success"])
        self.assertIn("error", body["github_sync"])


if __name__ == "__main__":
    unittest.main()
