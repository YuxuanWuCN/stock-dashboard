import unittest
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


if __name__ == "__main__":
    unittest.main()
