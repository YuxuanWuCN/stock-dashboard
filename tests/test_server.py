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
