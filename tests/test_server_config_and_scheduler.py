"""Unit and integration tests for API Configuration Management and Daily Auto Scheduler in src/server.py."""

import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from src import server


class ServerConfigAndSchedulerTestCase(unittest.TestCase):
    def setUp(self):
        self.client = server.app.test_client()

    def test_mask_secret_logic(self):
        # Empty or None
        self.assertEqual(server._mask_secret(""), "")
        self.assertEqual(server._mask_secret(None), "")

        # Short strings
        self.assertEqual(server._mask_secret("abc"), "••••••••")
        self.assertEqual(server._mask_secret("1234567"), "••••••••")

        # Long strings
        val = "sk-1234567890abcdef"
        masked = server._mask_secret(val)
        self.assertTrue(masked.startswith("sk-"))
        self.assertTrue(masked.endswith("cdef"))
        self.assertIn("••••••••", masked)

    def test_read_and_save_env_dict_preserves_unmodified_keys(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_file = Path(tmp_dir) / ".env"
            initial_content = (
                "# System Config\n"
                "EXISTING_SECRET=super_secret_token_12345\n"
                "OTHER_VAR=keep_me\n"
            )
            env_file.write_text(initial_content, encoding="utf-8")

            # 1. Read
            data = server._read_env_dict(env_file)
            self.assertEqual(data["EXISTING_SECRET"], "super_secret_token_12345")
            self.assertEqual(data["OTHER_VAR"], "keep_me")

            # 2. Save with update
            server._save_env_dict(
                {
                    "NEW_VAR": "new_val",
                    "EXISTING_SECRET": "super_secret_••••••••",  # masked -> should NOT overwrite!
                    "OTHER_VAR": "updated_val",
                },
                env_file,
            )

            # 3. Read back
            data_after = server._read_env_dict(env_file)
            # Masked secret must remain the original secret
            self.assertEqual(data_after["EXISTING_SECRET"], "super_secret_token_12345")
            # Other updated var is updated
            self.assertEqual(data_after["OTHER_VAR"], "updated_val")
            # New var added
            self.assertEqual(data_after["NEW_VAR"], "new_val")

    def test_get_api_config_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_file = Path(tmp_dir) / ".env"
            env_file.write_text("DEEPSEEK_API_KEY=sk-test-secret-key-12345\n", encoding="utf-8")

            with patch.object(server, "_ENV_PATH", env_file):
                with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test-secret-key-12345", "LLM_BACKEND": "deepseek"}):
                    response = self.client.get("/api/config")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["has_api_key"])
        self.assertIn("••••••••", data["api_key"])
        self.assertEqual(data["provider"], "deepseek")

    def test_post_api_config_updates_env_and_process(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_file = Path(tmp_dir) / ".env"
            env_file.write_text("INITIAL=1\n", encoding="utf-8")

            with patch.object(server, "_ENV_PATH", env_file):
                payload = {
                    "provider": "dashscope",
                    "model": "qwen-plus",
                    "api_key": "sk-dashscope-real-key-9999",
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "offline_mode": False,
                    "scheduler_enabled": True,
                }
                response = self.client.post("/api/config", json=payload)

            self.assertEqual(response.status_code, 200)
            res_data = response.get_json()
            self.assertEqual(res_data["status"], "ok")

            # Check that os.environ was updated
            self.assertEqual(os.environ.get("DASHSCOPE_API_KEY"), "sk-dashscope-real-key-9999")
            self.assertEqual(os.environ.get("LLM_MODEL"), "qwen-plus")

    def test_post_api_config_test_connectivity_success(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "pong"}}]
        }

        with patch.object(server._requests, "post", return_value=mock_response):
            payload = {
                "provider": "deepseek",
                "model": "deepseek-chat",
                "api_key": "sk-valid-key-1234567890",
                "base_url": "https://api.deepseek.com/v1",
            }
            response = self.client.post("/api/config/test", json=payload)

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertGreaterEqual(data["latency_ms"], 0)

    def test_post_api_config_test_connectivity_error_handling(self):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = '{"error": "Invalid API key"}'

        with patch.object(server._requests, "post", return_value=mock_response):
            payload = {
                "provider": "deepseek",
                "model": "deepseek-chat",
                "api_key": "sk-bad-key-1234567890",
                "base_url": "https://api.deepseek.com/v1",
            }
            response = self.client.post("/api/config/test", json=payload)

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "error")
        self.assertIn("401", data["error"])

    def test_system_update_status_endpoint(self):
        response = self.client.get("/api/system/update-status")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("is_running", data)
        self.assertIn("last_status", data)
        self.assertIn("progress_pct", data)
        self.assertIn("next_scheduled_time", data)

    def test_system_run_update_endpoint(self):
        with patch.object(server.daily_scheduler, "trigger_update_now", return_value=True):
            response = self.client.post("/api/system/run-update", json={"force": True})
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "ok")

    def test_daily_scheduler_next_run_computation(self):
        scheduler = server.daily_scheduler
        next_run = scheduler._compute_next_run_time()
        self.assertIsInstance(next_run, datetime)
        self.assertEqual(next_run.hour, 17)
        self.assertEqual(next_run.minute, 30)
        # Weekday check: Monday (0) to Friday (4)
        self.assertIn(next_run.weekday(), [0, 1, 2, 3, 4])
        self.assertGreater(next_run, datetime.now())
