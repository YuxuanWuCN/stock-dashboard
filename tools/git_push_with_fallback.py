"""Push dashboard data to GitHub with a local-proxy fallback.

The local daily jobs fetch market data directly because some market sources are
less reliable through Clash. GitHub can have the opposite network behaviour,
so this helper retries a failed direct Git push through the locally configured
HTTP proxy without exposing proxy credentials in logs.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass


DEFAULT_GIT_HTTP_PROXY = "http://127.0.0.1:7897"
DIRECT_PUSH_COMMAND = ("git", "push", "origin", "main")

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


def get_proxy_url(env: Mapping[str, str] | None = None) -> str:
    """Return the configured Git proxy or the local Clash-compatible default."""

    source = os.environ if env is None else env
    return source.get("GIT_HTTP_PROXY", "").strip() or DEFAULT_GIT_HTTP_PROXY


def push_with_fallback(
    runner: GitRunner = subprocess.run,
    env: Mapping[str, str] | None = None,
) -> PushResult:
    """Push ``main`` directly, then retry through the local HTTP proxy.

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
    proxy_command = [
        "git",
        "-c",
        f"http.proxy={proxy}",
        "push",
        "origin",
        "main",
    ]
    proxy_result = runner(proxy_command, check=False)
    return PushResult(
        direct_exit_code=direct_exit_code,
        proxy_exit_code=int(proxy_result.returncode),
    )


def main() -> int:
    """Run the push and emit a credential-safe status line for job logs."""

    result = push_with_fallback()
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
