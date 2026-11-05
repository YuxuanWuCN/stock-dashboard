"""Commit the daily data products, then push them with a local-proxy fallback.

## 为什么这个脚本既要 commit 又要 push

2026-11-02 排查发现：每日流水线的 9/9 步长期只做 ``git push``，从不 ``git add`` /
``git commit``。结果是工作区积累了几百个未提交的数据文件，而远端仓库的数据
停留在 2026-09-28，前端 Dashboard 展示了五周前的行情。同时本地分支落后
``origin/main`` 四个提交，``git push`` 每次都因 ``fetch first`` 被拒绝，
从 2026-10-09 起天天失败（退出码 1 / 128）。

因此本脚本按顺序做四件事，任一步失败都给出可诊断的退出码：

1. ``git add -- <paths>``：只暂存数据产物目录，不碰业务代码；
2. ``git commit``：仅在暂存区非空时提交；
3. ``git pull --rebase --autostash``：把远端新提交拉到本地之上，避免 ``fetch first``；
4. ``git push``：直连失败后走本机代理重试。

## 为什么提交在当前分支而不是硬编码 main

脚本运行在用户当前检出的分支上。静默切换分支会吞掉用户的工作现场，因此
**只在当前分支提交与推送**。若当前分支不是 ``main``，日志会明确提示数据
尚未进入默认分支，由用户决定何时合并——这比脚本擅自改写 ``main`` 安全。

## 为什么 pull 失败要 ``git rebase --abort``

``pull --rebase`` 遇到冲突会把仓库留在 rebase 中间态。脚本必须回滚到干净状态
再报错，否则下一次运行会在半途的 rebase 上继续，错误信息完全不可诊断。
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

DEFAULT_GIT_HTTP_PROXY = "http://127.0.0.1:7897"

#: 每日流水线产出的数据目录。只提交这些，避免把未完成的业务代码一起带上去。
DEFAULT_COMMIT_PATHS: tuple[str, ...] = ("docs/data",)

#: 推送当前分支（``git push origin <branch>``）。分支名由 ``--abbrev-ref`` 决定，
#: 这里只放固定的命令前缀，避免把用户正在用的分支硬编码成 main。
DIRECT_PUSH_COMMAND: tuple[str, ...] = ("git", "push", "origin", "HEAD")

GitRunner = Callable[..., subprocess.CompletedProcess[object]]


@dataclass(frozen=True)
class PushResult:
    """Result of a direct Git push and its optional proxy retry."""

    direct_exit_code: int
    proxy_exit_code: int | None = None

    @property
    def succeeded(self) -> bool:
        """Return whether either push attempt succeeded."""

        return self.direct_exit_code == 0 or self.proxy_exit_code == 0

    @property
    def exit_code(self) -> int:
        """Return the successful code, or the final failed attempt's code."""

        if self.direct_exit_code == 0:
            return 0
        if self.proxy_exit_code is not None:
            return self.proxy_exit_code
        return self.direct_exit_code


@dataclass(frozen=True)
class CommitResult:
    """Result of staging and committing the daily data products."""

    staged_exit_code: int
    commit_exit_code: int | None = None
    committed: bool = False
    message: str = ""
    pull_exit_code: int | None = None
    rebase_aborted: bool = False
    branch: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Staging and (when needed) committing both succeeded."""

        if self.staged_exit_code != 0:
            return False
        return self.commit_exit_code in (None, 0)

    @property
    def exit_code(self) -> int:
        """Return the first failing code, or 0 when the whole step is clean."""

        if self.staged_exit_code != 0:
            return self.staged_exit_code
        if self.commit_exit_code not in (None, 0):
            return int(self.commit_exit_code)
        return 0


def get_proxy_url(env: Mapping[str, str] | None = None) -> str:
    """Return the configured Git proxy or the local Clash-compatible default."""

    source = os.environ if env is None else env
    return source.get("GIT_HTTP_PROXY", "").strip() or DEFAULT_GIT_HTTP_PROXY


def get_commit_paths(env: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """Return the paths staged by the daily commit.

    ``GIT_COMMIT_PATHS`` accepts a comma-separated override so an operator can
    widen or narrow the scope without editing code.
    """

    source = os.environ if env is None else env
    raw = str(source.get("GIT_COMMIT_PATHS", "") or "").strip()
    if not raw:
        return DEFAULT_COMMIT_PATHS
    parts = tuple(part.strip() for part in raw.split(",") if part.strip())
    return parts or DEFAULT_COMMIT_PATHS


def _current_branch(runner: GitRunner) -> str:
    """Return the checked-out branch name, or ``""`` when it cannot be read."""

    try:
        result = runner(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
    except (OSError, TypeError):
        return ""
    branch = str(getattr(result, "stdout", "") or "").strip()
    return branch


def commit_worktree(
    paths: Sequence[str] | None = None,
    message: str = "",
    runner: GitRunner = subprocess.run,
    env: Mapping[str, str] | None = None,
) -> CommitResult:
    """Stage ``paths`` and commit them when the index has changes.

    Args:
        paths: Repository-relative paths to stage. Defaults to
            :data:`DEFAULT_COMMIT_PATHS`, or ``GIT_COMMIT_PATHS`` when set.
        message: Commit message. Defaults to a dated ``chore(data):`` line.
        runner: Injectable command runner used by tests.
        env: Optional environment mapping for overrides.

    Returns:
        A :class:`CommitResult` describing staging, committing and the
        pre-push rebase. ``committed`` is ``False`` when the index was clean,
        which is a success rather than a failure.
    """

    target_paths = tuple(paths) if paths is not None else get_commit_paths(env)
    branch = _current_branch(runner)

    staged_paths = runner(
        ["git", "diff", "--cached", "--name-only", "-z"],
        check=False,
        capture_output=True,
    )
    if int(staged_paths.returncode) != 0:
        return CommitResult(
            staged_exit_code=int(staged_paths.returncode),
            branch=branch,
            message=message,
            notes=["无法检查暂存区范围，拒绝提交"],
        )

    raw_staged_paths = getattr(staged_paths, "stdout", "") or ""
    if isinstance(raw_staged_paths, bytes):
        raw_staged_paths = raw_staged_paths.decode("utf-8", errors="replace")
    existing_paths = [path for path in str(raw_staged_paths).split("\\0") if path]
    outside_paths = [
        path
        for path in existing_paths
        if not any(path == target or path.startswith(target.rstrip("/") + "/") for target in target_paths)
    ]
    if outside_paths:
        preview = ", ".join(outside_paths[:20])
        if len(outside_paths) > 20:
            preview += f", ... 共 {len(outside_paths)} 项"
        return CommitResult(
            staged_exit_code=1,
            branch=branch,
            message=message,
            notes=[f"暂存区包含提交范围外的改动，拒绝提交：{preview}"],
        )

    staged = runner(["git", "add", "--", *target_paths], check=False)
    staged_code = int(staged.returncode)
    if staged_code != 0:
        return CommitResult(
            staged_exit_code=staged_code,
            branch=branch,
            message=message,
            notes=[f"git add 失败，未做任何提交（paths={list(target_paths)}）"],
        )

    diff = runner(["git", "diff", "--cached", "--quiet"], check=False)
    if int(diff.returncode) == 0:
        return CommitResult(
            staged_exit_code=0,
            branch=branch,
            message=message,
            notes=["暂存区无变化，跳过提交"],
        )

    commit_message = message or "chore(data): update dashboard data"
    committed = runner(["git", "commit", "-m", commit_message], check=False)
    commit_code = int(committed.returncode)
    if commit_code != 0:
        return CommitResult(
            staged_exit_code=0,
            commit_exit_code=commit_code,
            committed=False,
            message=commit_message,
            branch=branch,
            notes=["git commit 失败"],
        )

    notes: list[str] = []
    pull_code: int | None = None
    rebase_aborted = False
    try:
        pull = runner(
            ["git", "pull", "--rebase", "--autostash", "--quiet"],
            check=False,
        )
        pull_code = int(pull.returncode)
    except (OSError, TypeError):  # pragma: no cover - runner 缺少 returncode
        pull_code = None

    if pull_code not in (None, 0):
        # 冲突会让仓库停在 rebase 中间态，必须回滚后再报错。
        try:
            abort = runner(["git", "rebase", "--abort"], check=False)
            rebase_aborted = int(abort.returncode) == 0
        except (OSError, TypeError):  # pragma: no cover
            rebase_aborted = False
        notes.append(
            f"git pull --rebase 失败（退出码 {pull_code}），"
            + ("已回滚到干净状态" if rebase_aborted else "回滚失败，需人工处理")
        )

    if branch and branch != "main":
        notes.append(
            f"当前分支为 {branch}，数据已提交到该分支；"
            "默认分支 main 未更新，需由人决定何时合并"
        )

    return CommitResult(
        staged_exit_code=0,
        commit_exit_code=0,
        committed=True,
        message=commit_message,
        pull_exit_code=pull_code,
        rebase_aborted=rebase_aborted,
        branch=branch,
        notes=notes,
    )


def push_with_fallback(
    runner: GitRunner = subprocess.run,
    env: Mapping[str, str] | None = None,
) -> PushResult:
    """Push the current branch, then retry through the local HTTP proxy.

    Args:
        runner: Injectable command runner used by tests. It must return an
            object with a ``returncode`` attribute like ``subprocess.run``.
        env: Optional environment mapping used to obtain ``GIT_HTTP_PROXY``.

    Returns:
        The exit codes for the direct attempt and, when needed, proxy retry.
    """

    direct = runner(list(DIRECT_PUSH_COMMAND), check=False)
    direct_exit_code = int(direct.returncode)
    if direct_exit_code == 0:
        return PushResult(direct_exit_code=0)

    proxy = get_proxy_url(env)
    # DIRECT_PUSH_COMMAND 已经是 ("git", "push", "origin", "HEAD")，
    # 代理重试只需在 "git" 之后插入 -c http.proxy=...，不能再补一个 push。
    proxy_command = [
        DIRECT_PUSH_COMMAND[0],
        "-c",
        f"http.proxy={proxy}",
        *DIRECT_PUSH_COMMAND[1:],
    ]
    proxy_result = runner(proxy_command, check=False)
    return PushResult(
        direct_exit_code=direct_exit_code,
        proxy_exit_code=int(proxy_result.returncode),
    )


def main() -> int:
    """Commit the daily data products, push them, and report status."""

    env = os.environ
    commit = commit_worktree(env=env)
    for note in commit.notes:
        print(f"[commit] {note}", file=sys.stderr)

    if not commit.ok:
        print(
            f"[commit] 提交失败（staged={commit.staged_exit_code}, "
            f"commit={commit.commit_exit_code}）",
            file=sys.stderr,
        )
        return commit.exit_code

    result = push_with_fallback(env=env)
    if result.direct_exit_code == 0:
        print("GitHub push succeeded through the direct connection.")
    elif result.proxy_exit_code == 0:
        print("Direct GitHub push failed; local-proxy retry succeeded.")
    else:
        print(
            "GitHub push failed after direct and local-proxy attempts "
            f"(direct={result.direct_exit_code}, proxy={result.proxy_exit_code}).",
            file=sys.stderr,
        )
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
