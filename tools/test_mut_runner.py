"""mut_runner 单测（v2）。

不实际执行 mutmut：mock subprocess 调用，验证解析/聚合/fail-open。
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import mut_runner  # noqa: E402


EMOJI_STATUS = "123/456 🎉 100 ⏰ 5 🤔 2 🙁 6 🔇 0"
PLAIN_STATUS = "123/456 killed:100 survived:2 timeout:5 skipped:0"


class TestParseStatusLine(unittest.TestCase):
    def test_emoji_format_not_parsed(self):
        # emoji 状态行数字顺序不稳定，不解析（信任红线），计数以 result-ids 为准
        self.assertEqual(mut_runner.parse_status_line(EMOJI_STATUS), (0, 0, 0, 0))

    def test_plain_format(self):
        killed, survived, timeout, skipped = mut_runner.parse_status_line(PLAIN_STATUS)
        self.assertEqual((killed, survived, timeout, skipped), (100, 2, 5, 0))

    def test_no_status_fail_open(self):
        self.assertEqual(mut_runner.parse_status_line("nothing here"), (0, 0, 0, 0))


class TestAsResult(unittest.TestCase):
    def test_error_fail_open(self):
        res = mut_runner.as_result({"error": "mutmut 未安装"})
        self.assertTrue(res["passed"])
        self.assertIn("TRUST RED LINE", res["details"])

    def test_kill_rate_pass(self):
        res = mut_runner.as_result(
            {"kill_rate": 0.9, "killed": 90, "survived": 10, "timeout": 0, "skipped": 0, "total": 100, "error": None}
        )
        self.assertTrue(res["passed"])

    def test_kill_rate_fail(self):
        res = mut_runner.as_result(
            {"kill_rate": 0.5, "killed": 5, "survived": 5, "timeout": 0, "skipped": 0, "total": 10, "error": None}
        )
        self.assertFalse(res["passed"])
        self.assertIn("survived 5", res["details"])

    def test_zero_total_pass(self):
        res = mut_runner.as_result({"kill_rate": None, "total": 0, "error": None})
        self.assertTrue(res["passed"])

    def test_threshold_boundary(self):
        # 0.8 刚好达标
        res = mut_runner.as_result(
            {"kill_rate": 0.8, "killed": 80, "survived": 20, "timeout": 0, "skipped": 0, "total": 100, "error": None}
        )
        self.assertTrue(res["passed"])


class TestMutmutAvailable(unittest.TestCase):
    def test_available_when_returncode_zero(self):
        with mock.patch.object(mut_runner.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="2.4.1\n", stderr="")):
            ok, _ = mut_runner.mutmut_available()
            self.assertTrue(ok)

    def test_unavailable_when_missing(self):
        with mock.patch.object(mut_runner.subprocess, "run", side_effect=OSError):
            ok, reason = mut_runner.mutmut_available()
            self.assertFalse(ok)
            self.assertIn("未安装", reason)

    def test_wsl_denial_detected(self):
        # mutmut 3.x 在 Windows 输出 WSL 提示但 exit 0 —— 必须识别为不可用
        denial = "To run mutmut on Windows, please use the WSL. Native windows support is tracked in issue #397"
        with mock.patch.object(mut_runner.subprocess, "run", return_value=mock.Mock(returncode=0, stdout=denial, stderr="")):
            ok, reason = mut_runner.mutmut_available()
            self.assertFalse(ok)
            self.assertIn("WSL", reason)


class TestRunMutation(unittest.TestCase):
    def test_mutmut_missing_returns_error(self):
        with mock.patch.object(mut_runner, "mutmut_available", return_value=(False, "mutmut 未安装（pip install mutmut）")):
            report = mut_runner.run_mutation(["src"], workdir=Path("."))
        self.assertIn("mutmut 未安装", report["error"])
        self.assertIsNone(report["kill_rate"])

    def test_wsl_denial_fail_open(self):
        with mock.patch.object(mut_runner, "mutmut_available", return_value=(False, "mutmut 不支持 Windows 原生运行（需 WSL，issue #397）")):
            report = mut_runner.run_mutation(["src"], workdir=Path("."))
        self.assertIn("WSL", report["error"])
        res = mut_runner.as_result(report)
        self.assertTrue(res["passed"])  # fail-open

    def test_run_success(self):
        # status 行只有 killed: 标签 → killed 从标签取，survived 由 result-ids 兜底
        proc = mock.Mock(returncode=0, stdout="123/456 killed:100\n", stderr="")
        ids_proc = mock.Mock(returncode=0, stdout="M1\nM2\n", stderr="")
        with mock.patch.object(mut_runner, "mutmut_available", return_value=(True, "")), \
             mock.patch.object(mut_runner.subprocess, "run", side_effect=[proc, ids_proc, ids_proc]):
            report = mut_runner.run_mutation(["src"], workdir=Path("."))
        self.assertAlmostEqual(report["kill_rate"], 100 / 102, places=3)
        self.assertEqual(report["killed"], 100)
        self.assertEqual(report["survived"], 2)
        self.assertEqual(report["survivor_ids"], ["M1", "M2"])

    def test_timeout_returns_error(self):
        from subprocess import TimeoutExpired

        with mock.patch.object(mut_runner, "mutmut_available", return_value=(True, "")), \
             mock.patch.object(mut_runner.subprocess, "run", side_effect=TimeoutExpired("mutmut", 60)):
            report = mut_runner.run_mutation(["src"], workdir=Path("."))
        self.assertIn("超时", report["error"])


if __name__ == "__main__":
    unittest.main()
