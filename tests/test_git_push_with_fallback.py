"""Tests for the daily-job GitHub push fallback."""

from pathlib import Path
from types import SimpleNamespace

import pytest

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


def _shared_push_helper_users(project_root: Path) -> dict[str, str]:
    """判定每个每日脚本是否**传递性地**使用共享推送助手。

    返回 ``{脚本名: 使用方式}``；既没有直接调用、也没有经由 daily_routine.py 调用时抛错。

    为什么是传递性而不是字面包含：本测试要守的是"晨间/晚间自动化共用同一个已测回退逻辑"
    这一**行为**，而不是脚本里写了哪一行路径。实测两个脚本的接线方式并不相同：
    ``daily_morning.ps1`` 直接调用助手；``daily_local.ps1`` 调用 ``tools/daily_routine.py``，
    后者在第 9/9 步调用同一个助手。断言"必须字面出现助手路径"会把这种等价接线误判为回归。
    """
    helper = "tools/git_push_with_fallback.py"
    helper_win = "tools\\git_push_with_fallback.py"
    routine_names = ("tools/daily_routine.py", "tools\\daily_routine.py")
    routine_text = (project_root / "tools" / "daily_routine.py").read_text(encoding="utf-8")
    usage: dict[str, str] = {}
    for script_name in ("daily_local.ps1", "daily_morning.ps1"):
        script = (project_root / "tools" / script_name).read_text(encoding="utf-8")
        if helper in script or helper_win in script:
            usage[script_name] = "direct"
            continue
        if any(name in script for name in routine_names):
            assert helper in routine_text, (
                f"{script_name} 经 daily_routine.py 间接推送，但 daily_routine.py 未调用共享助手 {helper}"
            )
            usage[script_name] = "via daily_routine"
            continue
        raise AssertionError(f"{script_name} 既未直接调用共享助手，也未经由 daily_routine.py 推送")
    return usage


def test_both_daily_jobs_use_the_shared_push_helper():
    """Morning and evening automation share the tested fallback behaviour."""

    project_root = Path(__file__).resolve().parents[1]
    for script_name in ("daily_routine.py", "daily_morning.ps1"):
        script = (project_root / "tools" / script_name).read_text(encoding="utf-8")
        assert "git_push_with_fallback.py" in script
        assert "git push origin main *>> $logFile" not in script


def test_transitive_guard_has_teeth(tmp_path):
    """反向守卫：把 daily_routine.py 里的助手调用删掉，传递性校验必须失败。"""
    project_root = Path(__file__).resolve().parents[1]
    fake = tmp_path / "tools"
    fake.mkdir()
    (fake / "daily_local.ps1").write_text("& $py tools\\daily_routine.py @args\n", encoding="utf-8")
    (fake / "daily_morning.ps1").write_text("Invoke-Step -StepArgs @('tools\\git_push_with_fallback.py')\n", encoding="utf-8")
    (fake / "daily_routine.py").write_text("# 助手调用被删除\n", encoding="utf-8")

    with pytest.raises(AssertionError, match="daily_routine.py 未调用共享助手"):
        _shared_push_helper_users(tmp_path)
