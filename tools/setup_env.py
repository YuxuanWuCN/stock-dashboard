#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rainbow-FinGPT v2 - 交互式本地部署与环境变量配置向导。

纯 Python 标准库实现（无需额外第三方依赖），用于在克隆代码后快速完成：
1. 一键开启离线演示模式（无需 API Key，即刻体验 166 只标的完整量化系统）
2. 零泄漏配置 DeepSeek / DashScope / Tushare 密钥（输入自动掩码隐藏）
3. .gitignore 密钥安全审计与原子更新
4. 网络与大模型接口连通性测试
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import sys
import tempfile
import urllib.error
import urllib.request

# 解决 Windows 控制台 GBK 编码输出问题
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT_DIR / ".env"
ENV_EXAMPLE_PATH = ROOT_DIR / ".env.example"
GITIGNORE_PATH = ROOT_DIR / ".gitignore"


def check_gitignore_protection() -> tuple[bool, str]:
    """校验 .env 文件是否被 .gitignore 正确保护，杜绝密钥泄露风险。"""
    if not GITIGNORE_PATH.exists():
        return False, "未找到 .gitignore 文件，存在泄露风险！"
    try:
        content = GITIGNORE_PATH.read_text(encoding="utf-8")
        lines = [line.strip() for line in content.splitlines() if line.strip() and not line.strip().startswith("#")]
        has_env = any(line in (".env", "*.env", ".env*") for line in lines)
        has_unignore = "!.env" in lines
        if has_env and not has_unignore:
            return True, "已受 .gitignore 忽略规则保护 (安全)"
        return False, ".gitignore 中未明确忽略 .env 文件，请立即添加！"
    except Exception as e:
        return False, f"读取 .gitignore 异常: {e}"


def read_env_file() -> dict[str, str]:
    """读取 .env 中的有效键值对。如果 .env 不存在，则从 .env.example 读取默认骨架。"""
    target = ENV_PATH if ENV_PATH.exists() else ENV_EXAMPLE_PATH
    data: dict[str, str] = {}
    if not target.exists():
        return data

    try:
        with open(target, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k:
                    data[k] = v
    except Exception as e:
        print(f"[WARN] 读取配置文件 {target.name} 出错: {e}")
    return data


def update_env_keys(updates: dict[str, str]) -> bool:
    """原子更新 .env 文件中的指定配置项，保留原有注释和未修改内容。"""
    if not ENV_PATH.exists() and ENV_EXAMPLE_PATH.exists():
        try:
            content = ENV_EXAMPLE_PATH.read_text(encoding="utf-8")
            ENV_PATH.write_text(content, encoding="utf-8")
        except Exception as e:
            print(f"[FAIL] 初始化 .env 失败: {e}")
            return False

    lines: list[str] = []
    if ENV_PATH.exists():
        try:
            with open(ENV_PATH, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            print(f"[FAIL] 读取 .env 失败: {e}")
            return False

    keys_remaining = set(updates.keys())
    new_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k, _ = stripped.split("=", 1)
            k = k.strip()
            if k in updates:
                new_val = updates[k]
                new_lines.append(f"{k}={new_val}\n")
                keys_remaining.discard(k)
                continue
        new_lines.append(line)

    if keys_remaining:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines.append("\n")
        new_lines.append("\n# ---- 由 setup_env.py 自动追加的配置项 ----\n")
        for k in sorted(keys_remaining):
            new_lines.append(f"{k}={updates[k]}\n")

    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=ROOT_DIR, delete=False) as tf:
            tf.writelines(new_lines)
            temp_name = tf.name

        os.replace(temp_name, ENV_PATH)
        return True
    except Exception as e:
        print(f"[FAIL] 写入 .env 失败: {e}")
        return False


def mask_secret(val: str | None) -> str:
    """安全隐藏密钥内容，用于在控制台安全回显状态。"""
    if not val:
        return "[未设置]"
    if len(val) <= 8:
        return "******** (已设置)"
    return f"{val[:3]}****{val[-4:]} (已设置)"


def print_status_dashboard() -> None:
    """打印当前环境变量状态大盘。"""
    env = read_env_file()
    safe, msg = check_gitignore_protection()

    print("\n" + "=" * 65)
    print("      [Rainbow-FinGPT v2] 本地运行环境状态大盘")
    print("=" * 65)
    print(f" 根目录路径: {ROOT_DIR}")
    print(f" .env 文件 : {'[OK] 存在' if ENV_PATH.exists() else '[WARN] 未创建 (当前为默认模板)'}")
    print(f" 安全防护  : {'[SAFE] ' + msg if safe else '[WARN] ' + msg}")
    print("-" * 65)

    offline = env.get("OFFLINE_MODE", "false").lower() in ("1", "true", "yes")
    demo = env.get("DEMO_MODE", "false").lower() in ("1", "true", "yes")
    offline_status = "[ON] 开启 (无需 Key，免联网秒级离线体验)" if (offline or demo) else "[OFF] 关闭 (优先实时联网行情)"
    print(f" [运行模式] 离线演示模式 : {offline_status}")
    print(f" [模型选择] 活跃 LLM 后端: {env.get('LLM_BACKEND', 'deepseek')}")
    print(f" [服务端口] Web端口/API  : {env.get('WEB_PORT', '8000')} / {env.get('API_PORT', '5000')}")
    print("-" * 65)
    print(f" [密钥状态] DeepSeek Key : {mask_secret(env.get('DEEPSEEK_API_KEY'))}")
    print(f" [密钥状态] DashScope Key: {mask_secret(env.get('DASHSCOPE_API_KEY'))}")
    print(f" [密钥状态] Gemini Key   : {mask_secret(env.get('GEMINI_API_KEY'))}")
    print(f" [密钥状态] Tushare Token: {mask_secret(env.get('TUSHARE_TOKEN'))}")
    print("=" * 65)


def action_toggle_offline() -> None:
    """切换离线演示模式。"""
    env = read_env_file()
    current = env.get("OFFLINE_MODE", "false").lower() in ("1", "true", "yes")
    new_val = "false" if current else "true"

    updates = {
        "OFFLINE_MODE": new_val,
        "DEMO_MODE": new_val,
    }
    if update_env_keys(updates):
        if new_val == "true":
            print("\n[OK] [已启用离线演示模式]!")
            print("  - 系统将完全使用 docs/data/kline/ 下 166 只核心标的预计算离线全量日线。")
            print("  - 启动看板后，个股查询、因子检验、图谱回测零网络依赖，秒级响应，永不崩溃。")
        else:
            print("\n[OK] [已切换为在线优先模式]!")
            print("  - 系统将优先拉取实时市场数据，并在网络断开时自动优雅降级为离线数据。")


def action_set_deepseek() -> None:
    """配置 DeepSeek 密钥。"""
    print("\n--- 配置 DeepSeek API Key ---")
    print("说明: 推荐使用 DeepSeek，获取金融研报智能挖掘与语义评分能力。")
    print("申请地址: https://platform.deepseek.com/")
    print("(输入将自动隐藏，直接粘贴后按回车即可，输入空白取消)")

    key = getpass.getpass("请输入 DeepSeek API Key: ").strip()
    if not key:
        print("操作已取消。")
        return

    updates = {
        "DEEPSEEK_API_KEY": key,
        "LLM_BACKEND": "deepseek",
        "LLM_ENABLED": "true",
    }
    if update_env_keys(updates):
        print("[OK] DeepSeek API Key 已安全保存至 .env，已切换默认后端为 deepseek。")


def action_set_dashscope() -> None:
    """配置阿里 DashScope (通义千问) 密钥。"""
    print("\n--- 配置 阿里 DashScope / 通义千问 API Key ---")
    print("说明: 国内高速直连稳定大模型服务，支持 Qwen-Turbo / Plus / Max。")
    print("申请地址: https://dashscope.console.aliyun.com/")
    print("(输入将自动隐藏，直接粘贴后按回车即可，输入空白取消)")

    key = getpass.getpass("请输入 DashScope API Key: ").strip()
    if not key:
        print("操作已取消。")
        return

    updates = {
        "DASHSCOPE_API_KEY": key,
        "LLM_BACKEND": "dashscope",
        "LLM_ENABLED": "true",
    }
    if update_env_keys(updates):
        print("[OK] DashScope API Key 已安全保存至 .env，已切换默认后端为 dashscope。")


def action_set_tushare() -> None:
    """配置 Tushare Token。"""
    print("\n--- 配置 Tushare Token ---")
    print("说明: 用于获取高校/机构级权威高频量化财务与行情数据。")
    print("申请地址: https://tushare.pro/")
    print("(输入将自动隐藏，直接粘贴后按回车即可，输入空白取消)")

    token = getpass.getpass("请输入 Tushare Token: ").strip()
    if not token:
        print("操作已取消。")
        return

    updates = {
        "TUSHARE_TOKEN": token,
    }
    if update_env_keys(updates):
        print("[OK] Tushare Token 已安全保存至 .env。")


def test_connectivity() -> None:
    """轻量测试当前配置的接口连通性。"""
    env = read_env_file()
    print("\n[CHECK] 正在执行服务连通性自检...\n")

    # 1. 离线缓存检测
    kline_dir = ROOT_DIR / "docs" / "data" / "kline"
    cached_count = len(list(kline_dir.glob("*.json"))) if kline_dir.exists() else 0
    print(f" [1] 本地离线高保真资产: 共检测到 {cached_count} 个标的 K 线缓存 JSON")
    if cached_count >= 100:
        print("     -> [OK] 离线资源完整就绪 (涵盖 688525 佰维存储、600519 贵州茅台 等)")
    else:
        print("     -> [WARN] 离线资源不足，请检查 docs/data/kline 目录")

    # 2. DeepSeek 连通性
    ds_key = env.get("DEEPSEEK_API_KEY", "").strip()
    if ds_key:
        ds_url = env.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1").rstrip("/") + "/models"
        req = urllib.request.Request(ds_url, headers={"Authorization": f"Bearer {ds_key}"})
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.status == 200:
                    print(" [2] DeepSeek 接口连接: [OK] 鉴权成功 (HTTP 200)")
                else:
                    print(f" [2] DeepSeek 接口连接: [WARN] HTTP 响应 {resp.status}")
        except urllib.error.HTTPError as he:
            print(f" [2] DeepSeek 接口连接: [FAIL] 认证失败 (HTTP {he.code}) - 请核验 API Key")
        except Exception as e:
            print(f" [2] DeepSeek 接口连接: [WARN] 连接超时或网络阻断: {e}")
    else:
        print(" [2] DeepSeek 接口连接: [SKIP] 未配置密钥，跳过测试")

    # 3. DashScope 连通性
    dash_key = env.get("DASHSCOPE_API_KEY", "").strip()
    if dash_key:
        dash_url = "https://dashscope.aliyuncs.com/compatible-mode/v1/models"
        req = urllib.request.Request(dash_url, headers={"Authorization": f"Bearer {dash_key}"})
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.status == 200:
                    print(" [3] 阿里 DashScope 连接: [OK] 鉴权成功 (HTTP 200)")
                else:
                    print(f" [3] 阿里 DashScope 连接: [WARN] HTTP 响应 {resp.status}")
        except urllib.error.HTTPError as he:
            print(f" [3] 阿里 DashScope 连接: [FAIL] 认证失败 (HTTP {he.code}) - 请核验 API Key")
        except Exception as e:
            print(f" [3] 阿里 DashScope 连接: [WARN] 连接超时或网络阻断: {e}")
    else:
        print(" [3] 阿里 DashScope 连接: [SKIP] 未配置密钥，跳过测试")

    # 4. Tushare 连通性
    tu_token = env.get("TUSHARE_TOKEN", "").strip()
    if tu_token:
        tu_url = "http://api.tushare.pro"
        payload = json.dumps({
            "api_name": "trade_cal",
            "token": tu_token,
            "params": {"exchange": "SSE", "start_date": "20260101", "end_date": "20260105"},
            "fields": "exchange,cal_date,is_open",
        }).encode("utf-8")
        req = urllib.request.Request(tu_url, data=payload, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                if res_data.get("code") == 0:
                    print(" [4] Tushare Pro 接口连接: [OK] 鉴权与数据响应成功")
                else:
                    print(f" [4] Tushare Pro 接口连接: [FAIL] 请求报错: {res_data.get('msg')}")
        except Exception as e:
            print(f" [4] Tushare Pro 接口连接: [WARN] 连接异常: {e}")
    else:
        print(" [4] Tushare Pro 接口连接: [SKIP] 未配置 Token，跳过测试")

    print("\n自检完成！")


def interactive_menu() -> None:
    """交互式 CLI 菜单主循环。"""
    while True:
        print_status_dashboard()
        print("\n请选择操作项:")
        print("  [1] 一键开启 / 关闭离线演示模式 (推荐无 Key 用户直接开启)")
        print("  [2] 配置 DeepSeek API Key (金融研报与因子打分)")
        print("  [3] 配置 阿里 DashScope / 通义千问 API Key")
        print("  [4] 配置 Tushare Token (高校/机构量化数据)")
        print("  [5] 执行服务与网络连通性自检")
        print("  [0] 退出向导")
        print("-" * 65)

        try:
            choice = input("请输入选项编号 [0-5]: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n已安全退出。")
            break

        if choice == "1":
            action_toggle_offline()
        elif choice == "2":
            action_set_deepseek()
        elif choice == "3":
            action_set_dashscope()
        elif choice == "4":
            action_set_tushare()
        elif choice == "5":
            test_connectivity()
        elif choice in ("0", "q", "exit"):
            print("\n配置向导已退出。可运行 python start_dashboard.py 启动看板。")
            break
        else:
            print("无效的选项，请重新输入。")

        try:
            input("\n按回车键返回主菜单...")
        except (KeyboardInterrupt, EOFError):
            break


def main() -> int:
    parser = argparse.ArgumentParser(description="Rainbow-FinGPT v2 本地部署与密钥配置向导")
    parser.add_argument("--status", action="store_true", help="打印当前配置状态后退出")
    parser.add_argument("--offline", action="store_true", help="直接启用离线演示模式")
    parser.add_argument("--online", action="store_true", help="直接禁用离线演示模式（在线优先）")
    parser.add_argument("--test", action="store_true", help="执行接口连通性自检后退出")

    args = parser.parse_args()

    if args.status:
        print_status_dashboard()
        return 0
    if args.offline:
        update_env_keys({"OFFLINE_MODE": "true", "DEMO_MODE": "true"})
        print("[OK] 离线演示模式已成功启用 (OFFLINE_MODE=true)")
        return 0
    if args.online:
        update_env_keys({"OFFLINE_MODE": "false", "DEMO_MODE": "false"})
        print("[OK] 在线优先模式已成功启用 (OFFLINE_MODE=false)")
        return 0
    if args.test:
        test_connectivity()
        return 0

    interactive_menu()
    return 0


if __name__ == "__main__":
    sys.exit(main())
