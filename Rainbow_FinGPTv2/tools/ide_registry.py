"""IDE adapter 注册表（彩虹找虫 v2）。

把门禁 hook 装到各 IDE 的原生格式。借鉴 peaks-cli 的 ide-registry：
一个 adapter 表，每个 adapter 填 settings 路径 / hook 事件名 / matcher。

已实现：claude（PreToolUse + .claude/settings.json）、codex（PreToolUse + ~/.codex/hooks.json）
预留：trae（beforeToolCall，未实现 → NotImplementedError）

设计约束：
- 复用现有 hook-pre-bash 命令（双协议 hook_json 已兼容 Claude + Codex）
- 幂等合并（按 matcher+command 去重），保留已有 hooks 条目
- 只写用户级/项目级配置文件，不读 stdin
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

# 各 IDE 配置路径（相对项目根）
IDE_ADAPTERS: dict[str, dict] = {
    "claude": {
        "name": "Claude Code",
        "settings_path": ".claude/settings.json",
        "hook_event": "PreToolUse",
        "matchers": ["Edit", "Write", "NotebookEdit", "MultiEdit", "Bash"],
        "input_field": "tool_input",
        "implemented": True,
    },
    "codex": {
        "name": "Codex",
        "settings_path": "~/.codex/hooks.json",
        "hook_event": "PreToolUse",
        "matchers": ["Bash", "apply_patch"],
        "input_field": "tool_input",
        "implemented": True,
    },
    "trae": {
        "name": "Trae",
        "settings_path": ".trae/hooks.json",
        "hook_event": "beforeToolCall",
        "matchers": ["*"],
        "input_field": "tool_input",
        "implemented": False,
    },
}


def gate_argv(project_root: Path, python: str | None = None) -> list[str]:
    """构造 hook 命令 argv（复用 run_quality.ps1 → hook-pre-bash）。"""
    ps1 = project_root / "tools" / "run_quality.ps1"
    return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1), "hook-pre-bash"]


def claude_settings_entry(project_root: Path) -> dict:
    """Claude .claude/settings.json 的 hooks 键格式。"""
    return {
        "PreToolUse": [
            {
                "matcher": "|".join(IDE_ADAPTERS["claude"]["matchers"]),
                "hooks": [
                    {
                        "type": "command",
                        "shell": "powershell",
                        "command": " ".join(f'"{p}"' if " " in p else p for p in gate_argv(project_root)),
                        "timeout": 120,
                    }
                ],
            }
        ]
    }


def codex_hooks_entry(project_root: Path) -> dict:
    """Codex ~/.codex/hooks.json 格式。"""
    return {
        "PreToolUse": [
            {
                "matcher": "Bash",
                "hooks": [
                    {
                        "type": "command",
                        "command": " ".join(f'"{p}"' if " " in p else p for p in gate_argv(project_root)),
                        "timeout": 600,
                    }
                ],
            }
        ]
    }


def _merge_hooks(existing: dict, entry: dict) -> dict:
    """幂等合并 hooks 配置（按 matcher+command 去重），保留已有条目。"""
    result = dict(existing)
    for event, new_rules in entry.items():
        if not isinstance(new_rules, list):
            continue
        old_rules = result.get(event)
        if not isinstance(old_rules, list):
            result[event] = new_rules
            continue
        merged = list(old_rules)
        for new_rule in new_rules:
            if not isinstance(new_rule, dict):
                continue
            if any(
                isinstance(r, dict)
                and r.get("matcher") == new_rule.get("matcher")
                and r.get("hooks") == new_rule.get("hooks")
                for r in merged
            ):
                continue
            merged.append(new_rule)
        result[event] = merged
    return result


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def install(ide: str, project_root: Path) -> dict:
    """安装指定 IDE 的 hook 条目。返回安装信息。"""
    adapter = IDE_ADAPTERS.get(ide)
    if adapter is None:
        raise ValueError(f"未知 IDE: {ide}（可选: {', '.join(IDE_ADAPTERS)}）")
    if not adapter["implemented"]:
        raise NotImplementedError(f"{adapter['name']} adapter 预留未实现（v2 仅支持 claude/codex）")

    if ide == "claude":
        settings_path = project_root / adapter["settings_path"]
        existing = _read_json(settings_path)
        entry = claude_settings_entry(project_root)
        if "hooks" not in existing or not isinstance(existing.get("hooks"), dict):
            existing = {"hooks": {}}
        existing["hooks"] = _merge_hooks(existing.get("hooks", {}), entry)
        _write_json(settings_path, existing)
        return {"ide": ide, "path": str(settings_path), "entry": entry}

    if ide == "codex":
        settings_path = Path(adapter["settings_path"]).expanduser()
        existing = _read_json(settings_path)
        entry = codex_hooks_entry(project_root)
        existing = _merge_hooks(existing, entry)
        _write_json(settings_path, existing)
        return {
            "ide": ide,
            "path": str(settings_path),
            "entry": entry,
            "notice": "Codex hooks 首次使用需在 Codex 中执行 /hooks 批准信任（未信任的 hook 会静默跳过）",
        }

    raise NotImplementedError(f"{adapter['name']} adapter 预留未实现")


def uninstall(ide: str, project_root: Path) -> None:
    """移除指定 IDE 的 hook 条目（只删本工具装的 matcher+command）。"""
    adapter = IDE_ADAPTERS.get(ide)
    if adapter is None or not adapter["implemented"]:
        return
    if ide == "claude":
        settings_path = project_root / adapter["settings_path"]
        existing = _read_json(settings_path)
        hooks = existing.get("hooks")
        if isinstance(hooks, dict):
            entry = claude_settings_entry(project_root)
            for event, new_rules in entry.items():
                if not isinstance(hooks.get(event), list):
                    continue
                kept = [
                    r for r in hooks[event]
                    if not (
                        isinstance(r, dict)
                        and any(
                            isinstance(nr, dict)
                            and r.get("matcher") == nr.get("matcher")
                            and r.get("hooks") == nr.get("hooks")
                            for nr in new_rules
                        )
                    )
                ]
                hooks[event] = kept
            existing["hooks"] = hooks
            _write_json(settings_path, existing)
    elif ide == "codex":
        settings_path = Path(adapter["settings_path"]).expanduser()
        existing = _read_json(settings_path)
        entry = codex_hooks_entry(project_root)
        for event, new_rules in entry.items():
            if not isinstance(existing.get(event), list):
                continue
            existing[event] = [
                r for r in existing[event]
                if not (
                    isinstance(r, dict)
                    and any(
                        isinstance(nr, dict)
                        and r.get("matcher") == nr.get("matcher")
                        and r.get("hooks") == nr.get("hooks")
                        for nr in new_rules
                    )
                )
            ]
        _write_json(settings_path, existing)


def run(argv: list[str] | None = None) -> int:
    """CLI 入口：python tools/ide_registry.py install --ide claude [--dry-run]"""
    parser = argparse.ArgumentParser(prog="ide_registry")
    sub = parser.add_subparsers(dest="cmd", required=True)
    inst = sub.add_parser("install")
    inst.add_argument("--ide", required=True, choices=list(IDE_ADAPTERS))
    inst.add_argument("--root", default=".")
    inst.add_argument("--dry-run", action="store_true")
    uninst = sub.add_parser("uninstall")
    uninst.add_argument("--ide", required=True, choices=list(IDE_ADAPTERS))
    uninst.add_argument("--root", default=".")
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    project_root = Path(args.root).resolve()
    if args.cmd == "install":
        if args.dry_run:
            adapter = IDE_ADAPTERS[args.ide]
            entry = claude_settings_entry(project_root) if args.ide == "claude" else codex_hooks_entry(project_root)
            print(json.dumps({"dry_run": True, "ide": args.ide, "entry": entry}, ensure_ascii=False, indent=2))
            return 0
        try:
            info = install(args.ide, project_root)
        except NotImplementedError as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 2
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0
    uninstall(args.ide, project_root)
    print(f"已卸载 {args.ide} hook 条目")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
