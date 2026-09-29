"""Start the local API and dashboard with one command."""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path


HOST = "127.0.0.1"
API_PORT = 5000
WEB_PORT = 8001
API_HEALTH_URL = f"http://{HOST}:{API_PORT}/api/health"
WEB_URL = f"http://{HOST}:{WEB_PORT}/"


def port_is_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((HOST, port)) == 0


def wait_for_url(url: str, process: subprocess.Popen, timeout: float = 20.0) -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with opener.open(url, timeout=1) as response:
                if 200 <= response.status < 400:
                    return True
        except OSError:
            pass
        time.sleep(0.25)
    return False


def stop_processes(processes: list[subprocess.Popen]) -> None:
    for process in reversed(processes):
        if process.poll() is None:
            process.terminate()
    for process in reversed(processes):
        if process.poll() is None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def check_dependencies() -> list[str]:
    missing = []
    for module in ("akshare", "flask", "flask_cors", "numpy", "pandas"):
        try:
            __import__(module)
        except ImportError:
            missing.append(module)
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description="Start Stock Dashboard 2.1 locally")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the dashboard in the default browser",
    )
    parser.add_argument(
        "--frontend-only",
        action="store_true",
        help="Only start the frontend static web server (port 8001)",
    )
    args = parser.parse_args()

    project_dir = Path(__file__).resolve().parent
    if not args.frontend_only:
        missing = check_dependencies()
        if missing:
            print("Missing Python dependencies: " + ", ".join(missing))
            print(f'Run: "{sys.executable}" -m pip install -r requirements.txt')
            return 1

    ports_to_check = [WEB_PORT] if args.frontend_only else [API_PORT, WEB_PORT]
    occupied = [port for port in ports_to_check if port_is_in_use(port)]
    if occupied:
        print("Cannot start because these ports are already in use: " + ", ".join(map(str, occupied)))
        print("Close the old dashboard window/process and run this launcher again.")
        return 1

    processes: list[subprocess.Popen] = []
    backend: subprocess.Popen | None = None
    try:
        if not args.frontend_only:
            backend = subprocess.Popen(
                [sys.executable, "-m", "src.server"],
                cwd=project_dir,
            )
            processes.append(backend)

        frontend = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "http.server",
                str(WEB_PORT),
                "--bind",
                HOST,
                "--directory",
                str(project_dir / "docs"),
            ],
            cwd=project_dir,
        )
        processes.append(frontend)

        if backend is not None and not wait_for_url(API_HEALTH_URL, backend):
            print("The API failed to start. Review the error shown above.")
            return 1
        if not wait_for_url(WEB_URL, frontend):
            print("The dashboard web server failed to start. Review the error shown above.")
            return 1

        print()
        print("Stock Dashboard 2.1 is running:")
        print(f"  Dashboard: {WEB_URL}")
        print(f"  Wealth Terminal: {WEB_URL}index_wealth.html")
        if backend is not None:
            print(f"  API health: {API_HEALTH_URL}")
        print("Press Ctrl+C to stop services.")

        if not args.no_browser:
            webbrowser.open(f"{WEB_URL}index_wealth.html")

        backend_warned = False
        while frontend.poll() is None:
            if backend is not None and backend.poll() is not None and not backend_warned:
                print(f"\n[Notice] Backend API process exited (code {backend.poll()}).")
                print(f"[Notice] Static dashboard remains active at {WEB_URL}index_wealth.html")
                backend_warned = True
            time.sleep(0.5)

        if frontend.poll() is not None:
            print(f"Frontend server stopped (exit code {frontend.returncode}).")
            return frontend.returncode or 1
        return 0
    except KeyboardInterrupt:
        print("\nStopping Stock Dashboard 2.1...")
        return 0
    finally:
        stop_processes(processes)


if __name__ == "__main__":
    raise SystemExit(main())
