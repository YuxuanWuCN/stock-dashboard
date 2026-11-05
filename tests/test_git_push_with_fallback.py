"""Tests for the daily-job GitHub commit + push helper."""

from pathlib import Path
from types import SimpleNamespace

import pytest

import tools.git_push_with_fallback as git_push


def _dispatch_runner(codes: dict[str, int], stdout: str = "main"):
    """Build a fake git runner keyed by command signature.

    ``codes`` maps a stable signature (``"add"`` / ``"diff"`` / ``"commit"`` /
    ``"pull"`` / ``"rebase --abort"`` / ``"push"`` / ``"rev-parse"``) to the exit
    code that invocation should return. Missing keys default to 0, so a test only
    spells out the calls it actually cares about. Every invocation is recorded so
    tests can assert ordering.
    """

    commands: list[list[str]] = []

    def signature(command: list[str]) -> str:
        if "rev-parse" in command:
            return "rev-parse"
        if "--name-only" in command:
            return "staged-paths"
        if "push" in command:
            return "push"
        for sub in ("add", "diff", "commit", "pull", "rebase"):
            if sub in command:
                return "rebase --abort" if sub == "rebase" and "--abort" in command else sub
        return " ".join(command)

    def runner(command: list[str], *, check: bool, **kwargs):
        assert check is False
        commands.append(command)
        result_stdout = codes.get("staged-paths-output", "") if signature(command) == "staged-paths" else stdout
        result_stdout = result_stdout.encode("utf-8") if signature(command) == "staged-paths" else result_stdout
        return SimpleNamespace(returncode=codes.get(signature(command), 0), stdout=result_stdout)

    return runner, commands


def _runner_with_codes(*exit_codes: int, stdout: str = ""):
    """Sequential runner used only by the pure-push tests."""

    remaining_codes = list(exit_codes)
    commands: list[list[str]] = []

    def runner(command: list[str], *, check: bool, **kwargs):
        assert check is False
        commands.append(command)
        return SimpleNamespace(returncode=remaining_codes.pop(0), stdout=stdout)

    return runner, commands


def test_direct_push_success_does_not_retry():
    """A successful direct push must not make a redundant proxy request."""

    runner, commands = _runner_with_codes(0)
    result = git_push.push_with_fallback(runner=runner, env={})

    assert result.succeeded is True
    assert result.exit_code == 0
    assert result.proxy_exit_code is None
    assert commands == [["git", "push", "origin", "HEAD"]]


def test_failed_direct_push_retries_using_default_local_proxy():
    """The known local Clash port is tried after a direct connection failure."""

    runner, commands = _runner_with_codes(128, 0)
    result = git_push.push_with_fallback(runner=runner, env={})

    assert result.succeeded is True
    assert result.direct_exit_code == 128
    assert result.proxy_exit_code == 0
    assert commands == [
        ["git", "push", "origin", "HEAD"],
        [
            "git",
            "-c",
            "http.proxy=http://127.0.0.1:7897",
            "push",
            "origin",
            "HEAD",
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
        "commit_worktree",
        lambda **_: git_push.CommitResult(staged_exit_code=0, committed=False),
    )
    monkeypatch.setattr(
        git_push,
        "push_with_fallback",
        lambda **_: git_push.PushResult(direct_exit_code=128, proxy_exit_code=7),
    )

    assert git_push.main() == 7
    captured = capsys.readouterr()
    assert "direct=128, proxy=7" in captured.err


# ============================================================================
# commit_worktree —— 9/9 步必须真的提交，而不是只 push
# ============================================================================


def test_commit_stages_commits_then_rebases_before_push():
    """回归守卫：2026-11-02 事故的根因是只 push 不 commit。

    这条用例钉住完整顺序 add -> diff --cached -> commit -> pull --rebase，
    并断言暂存范围只覆盖数据目录，不把业务代码一起带走。
    """

    runner, commands = _dispatch_runner({"diff": 1}, stdout="fix/real-data-rebuild")
    result = git_push.commit_worktree(runner=runner, env={}, message="chore(data): test")

    assert result.ok is True
    assert result.committed is True
    assert result.exit_code == 0
    assert commands[0] == ["git", "rev-parse", "--abbrev-ref", "HEAD"]
    assert commands[1] == ["git", "diff", "--cached", "--name-only", "-z"]
    assert commands[2] == ["git", "add", "--", "docs/data"]
    assert commands[3] == ["git", "diff", "--cached", "--quiet"]
    assert commands[4] == ["git", "commit", "-m", "chore(data): test"]
    assert commands[5] == ["git", "pull", "--rebase", "--autostash", "--quiet"]


@pytest.mark.parametrize(
    "staged_path",
    ["README.md", "src/deleted_module.py"],
    ids=["staged-modification", "staged-deletion"],
)
def test_commit_refuses_out_of_scope_staged_paths_before_staging(staged_path):
    runner, commands = _dispatch_runner(
        {"staged-paths-output": f"{staged_path}\\0"},
        stdout="fix/real-data-rebuild",
    )

    result = git_push.commit_worktree(runner=runner, env={})

    assert result.ok is False
    assert result.exit_code == 1
    assert staged_path in result.notes[0]
    assert not any("add" in command or "commit" in command for command in commands)


def test_commit_skips_when_index_is_clean():
    """没有改动时不应产生空提交，也不算失败。"""

    runner, commands = _dispatch_runner({"diff": 0}, stdout="main")
    result = git_push.commit_worktree(runner=runner, env={})

    assert result.ok is True
    assert result.committed is False
    assert result.exit_code == 0
    assert [c[1] for c in commands] == ["rev-parse", "diff", "add", "diff"]
    assert "跳过提交" in result.notes[0]


def test_commit_failure_is_surfaced_not_swallowed():
    """commit 失败必须返回非零，且不能继续做 pull。"""

    runner, commands = _dispatch_runner({"diff": 1, "commit": 1}, stdout="main")
    result = git_push.commit_worktree(runner=runner, env={})

    assert result.ok is False
    assert result.exit_code == 1
    assert result.committed is False
    assert all("pull" not in c for c in commands)


def test_stage_failure_returns_the_git_code():
    """git add 失败（例如路径被 .gitignore 全部覆盖）要原样透出退出码。"""

    runner, commands = _dispatch_runner({"add": 2})
    result = git_push.commit_worktree(runner=runner, env={})

    assert result.ok is False
    assert result.exit_code == 2
    assert commands[-1][1] == "add"
    assert commands[-2] == ["git", "diff", "--cached", "--name-only", "-z"]


def test_pull_conflict_aborts_rebase_and_keeps_commit():
    """pull --rebase 冲突时必须 git rebase --abort，避免留下中间态。"""

    runner, commands = _dispatch_runner(
        {"diff": 1, "pull": 1, "rebase --abort": 0}, stdout="main"
    )
    result = git_push.commit_worktree(runner=runner, env={})

    assert result.committed is True
    assert result.pull_exit_code == 1
    assert result.rebase_aborted is True
    assert commands[-1] == ["git", "rebase", "--abort"]
    assert any("已回滚到干净状态" in note for note in result.notes)


def test_non_main_branch_is_reported_not_silently_merged():
    """在特性分支上提交时，必须提示 main 未更新，而不是静默切分支。"""

    runner, _ = _dispatch_runner({"diff": 1}, stdout="fix/real-data-rebuild")
    result = git_push.commit_worktree(runner=runner, env={})

    assert result.branch == "fix/real-data-rebuild"
    assert any("main 未更新" in note for note in result.notes)


def test_commit_paths_can_be_overridden_by_env():
    """运维可用 GIT_COMMIT_PATHS 收窄或放宽暂存范围。"""

    runner, commands = _dispatch_runner({"diff": 0}, stdout="main")
    git_push.commit_worktree(
        runner=runner,
        env={"GIT_COMMIT_PATHS": "docs/data,reports"},
    )

    assert ["git", "add", "--", "docs/data", "reports"] in commands


def test_commit_paths_fall_back_when_env_is_blank():
    """空字符串不应把暂存范围变成空列表。"""

    assert git_push.get_commit_paths({"GIT_COMMIT_PATHS": "   "}) == ("docs/data",)


def test_main_runs_commit_before_push(monkeypatch):
    """main() 必须先提交再推送；提交失败时不应调用推送。"""

    calls: list[str] = []
    monkeypatch.setattr(
        git_push,
        "commit_worktree",
        lambda **_: (
            calls.append("commit")
            or git_push.CommitResult(staged_exit_code=0, committed=True)
        ),
    )
    monkeypatch.setattr(
        git_push,
        "push_with_fallback",
        lambda **_: calls.append("push") or git_push.PushResult(direct_exit_code=0),
    )

    assert git_push.main() == 0
    assert calls == ["commit", "push"]


def test_main_stops_when_commit_fails(monkeypatch):
    """提交失败时直接返回，不推送半成品。"""

    pushed: list[int] = []
    monkeypatch.setattr(
        git_push,
        "commit_worktree",
        lambda **_: git_push.CommitResult(staged_exit_code=0, commit_exit_code=1),
    )
    monkeypatch.setattr(
        git_push,
        "push_with_fallback",
        lambda **_: pushed.append(1) or git_push.PushResult(direct_exit_code=0),
    )

    assert git_push.main() == 1
    assert pushed == []


# ============================================================================
# 接线守卫：晨间/晚间自动化必须共用同一个已测助手
# ============================================================================


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
