import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

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
