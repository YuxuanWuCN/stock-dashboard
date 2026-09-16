#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rainbow-FinGPT v2 - 本地一键启动器 (跨平台增强版)。

功能特性：
1. 自动探测当前 Python 运行时 (sys.executable)，彻底移除写死路径与平台限制。
2. 启动前核心依赖项检测 (flask, flask_cors, pandas, akshare)。
3. Socket 级端口冲突精确检测 (默认 API 5000, Web 8000)。
4. 服务就绪健康轮询 (轮询 /api/health)，杜绝过早弹窗导致 ERR_CONNECTION_REFUSED。
5. 托管子进程生命周期，监听 Ctrl+C / SIGINT 级联清理，零孤儿进程残留。
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

# 解决 Windows 控制台 GBK 编码输出问题
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
DOCS_DIR = BASE_DIR / "docs"
ENV_PATH = BASE_DIR / ".env"

HOST = "127.0.0.1"


def load_ports_from_env() -> tuple[int, int]:
    """从 .env 或环境变量加载端口，默认 Web 8000, API 5000。"""
    api_port = 5000
    web_port = 8000

    if ENV_PATH.exists():
        try:
            with open(ENV_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k == "API_PORT" and v.isdigit():
                        api_port = int(v)
                    elif k == "WEB_PORT" and v.isdigit():
                        web_port = int(v)
        except Exception:
            pass

    if os.environ.get("API_PORT", "").isdigit():
        api_port = int(os.environ["API_PORT"])
    if os.environ.get("WEB_PORT", "").isdigit():
        web_port = int(os.environ["WEB_PORT"])

    return api_port, web_port


def port_is_in_use(port: int) -> bool:
    """Socket 精准检测本地指定端口是否已被占用。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((HOST, port)) == 0


def check_dependencies() -> list[str]:
    """检测关键依赖项是否已安装。"""
    missing = []
    required_packages = ["flask", "flask_cors", "pandas", "akshare"]
    for pkg in required_packages:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    return missing


def wait_for_url(url: str, process: subprocess.Popen, timeout: float = 20.0) -> bool:
    """轮询 HTTP 端点，直到返回 200~399 或超时。"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with opener.open(url, timeout=1.0) as resp:
                if 200 <= resp.status < 400:
                    return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def stop_processes(processes: list[subprocess.Popen]) -> None:
    """级联优雅终止所有子进程，防止残留孤儿进程。"""
    for proc in reversed(processes):
        if proc.poll() is None:
            proc.terminate()
    for proc in reversed(processes):
        if proc.poll() is None:
            try:
                proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                proc.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description="Rainbow-FinGPT v2 研究终端启动器")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="不自动打开浏览器",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="环境前置自检模式 (校验依赖与端口后立即退出)",
    )
    args = parser.parse_args()

    api_port, web_port = load_ports_from_env()
    api_health_url = f"http://{HOST}:{api_port}/api/health"
    web_url = f"http://{HOST}:{web_port}/"

    print("=" * 65)
    print("      [Rainbow-FinGPT v2] 研究终端一键启动器")
    print("=" * 65)
    print(f" 项目路径   : {BASE_DIR}")
    print(f" Python 解释: {sys.executable}")
    print(f" API 服务端口: {api_port} (健康检查: {api_health_url})")
    print(f" 前端看板端口: {web_port} (访问地址: {web_url})")
    print("-" * 65)

    # 1. 依赖自检
    missing = check_dependencies()
    if missing:
        print("[FAIL] 缺失关键 Python 依赖库: " + ", ".join(missing))
        print(f'请执行安装: "{sys.executable}" -m pip install -r requirements.txt')
        return 1
    print("[OK] 核心运行环境依赖就绪 (flask, flask_cors, pandas, akshare)")

    # 2. 端口占用自检
    occupied = [p for p in (api_port, web_port) if port_is_in_use(p)]
    if occupied:
        print(f"[FAIL] 无法启动：检测到端口已被占用 -> {occupied}")
        print("排查建议: 请关闭先前启动的后台进程，或在 .env 中指定未被占用的 API_PORT / WEB_PORT。")
        return 1
    print(f"[OK] 端口 {api_port} 与 {web_port} 均可用")

    if args.dry_run:
        print("\n[OK] 环境前置自检通过 (Dry-Run 完成，服务未实际运行)。")
        return 0

    # 3. 启动子进程
    processes: list[subprocess.Popen] = []
    try:
        print("\n[START] 正在启动后端 Flask API 服务...")
        backend = subprocess.Popen(
            [sys.executable, "-m", "src.server"],
            cwd=str(BASE_DIR),
        )
        processes.append(backend)

        print("[START] 正在启动前端静态 Web 服务器...")
        frontend = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "http.server",
                str(web_port),
                "--bind",
                HOST,
                "--directory",
                str(DOCS_DIR),
            ],
            cwd=str(BASE_DIR),
        )
        processes.append(frontend)

        # 4. 轮询服务就绪
        print("[WAIT] 正在等待 API 服务就绪 (/api/health)...")
        if not wait_for_url(api_health_url, backend, timeout=20.0):
            print("[FAIL] API 服务启动超时或异常退出，请检查上方控制台报错。")
            return 1

        if not wait_for_url(web_url, frontend, timeout=10.0):
            print("[FAIL] 前端 Web 服务器启动失败。")
            return 1

        print("-" * 65)
        print("🎉 Rainbow-FinGPT v2 研究终端已就绪并对外提供服务:")
        print(f"   💻 研究终端看板: {web_url}")
        print(f"   🔌 后端健康接口: {api_health_url}")
        print("   ⌨️  按 Ctrl+C 可同时安全停止前后端服务")
        print("-" * 65)

        if not args.no_browser:
            time.sleep(0.3)
            webbrowser.open(web_url)

        # 5. 主事件循环与健康守护
        while all(p.poll() is None for p in processes):
            time.sleep(0.5)

        failed = next((p for p in processes if p.poll() is not None), None)
        if failed is not None:
            print(f"\n[WARN] 某个子进程异常退出 (退出码: {failed.returncode})。")
            return failed.returncode or 1
        return 0

    except KeyboardInterrupt:
        print("\n[STOP] 捕获中断信号，正在安全停止前后端服务...")
        return 0
    finally:
        stop_processes(processes)
        print("[DONE] 所有子进程已完全停止与回收。")


if __name__ == "__main__":
    sys.exit(main())
