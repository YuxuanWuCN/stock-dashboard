"""Tests for the daily-job GitHub push fallback."""

from pathlib import Path
from types import SimpleNamespace

import tools.git_push_with_fallback as git_push


def _runner_with_codes(*exit_codes: int):
    """Build a fake subprocess runner and capture the commands it receives."""

    remaining_codes = list(exit_codes)
    commands: list[list[str]] = []

    def runner(command: list[str], *, check: bool):
        assert check is False
        commands.append(command)
        return SimpleNamespace(returncode=remaining_codes.pop(0))

    return runner, commands


def test_direct_push_success_does_not_retry():
    """A successful direct push must not make a redundant proxy request."""

    runner, commands = _runner_with_codes(0)
    result = git_push.push_with_fallback(runner=runner, env={})

    assert result.succeeded is True
    assert result.exit_code == 0
    assert result.proxy_exit_code is None
    assert commands == [["git", "push", "origin", "main"]]


def test_failed_direct_push_retries_using_default_local_proxy():
    """The known local Clash port is tried after a direct connection failure."""

    runner, commands = _runner_with_codes(128, 0)
    result = git_push.push_with_fallback(runner=runner, env={})

    assert result.succeeded is True
    assert result.direct_exit_code == 128
    assert result.proxy_exit_code == 0
    assert commands == [
        ["git", "push", "origin", "main"],
        [
            "git",
            "-c",
            "http.proxy=http://127.0.0.1:7897",
            "push",
            "origin",
            "main",
        ],
    ]


def test_configured_proxy_overrides_the_default_and_failure_is_returned():
    """A user override is honored, and a double failure remains nonzero."""

    runner, commands = _runner_with_codes(128, 7)
    result = git_push.push_with_fallback(
        runner=runner,
        env={"GIT_HTTP_PROXY": "http://127.0.0.1:8899"},
    )

    assert result.succeeded is False
    assert result.exit_code == 7
    assert commands[-1][2] == "http.proxy=http://127.0.0.1:8899"


def test_main_logs_both_exit_codes_when_the_retry_also_fails(monkeypatch, capsys):
    """A failed retry remains visible in the daily job log and exits nonzero."""

    monkeypatch.setattr(
        git_push,
        "push_with_fallback",
        lambda: git_push.PushResult(direct_exit_code=128, proxy_exit_code=7),
    )

    assert git_push.main() == 7
    captured = capsys.readouterr()
    assert "direct=128, proxy=7" in captured.err


def test_both_daily_jobs_use_the_shared_push_helper():
    """Morning and evening automation share the tested fallback behaviour."""

    project_root = Path(__file__).resolve().parents[1]
    for script_name in ("daily_local.ps1", "daily_morning.ps1"):
        script = (project_root / "tools" / script_name).read_text(encoding="utf-8")
        assert "tools\\git_push_with_fallback.py" in script
        assert "git push origin main *>> $logFile" not in script
