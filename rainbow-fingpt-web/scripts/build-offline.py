#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 dist-offline 合成一个自包含的单文件 HTML。

用法：
    npx vite build --config vite.config.offline.ts && python3 scripts/build-offline.py
    （或直接 npm run build:offline）

产物：dist-offline/Rainbow-FinGPT-新首页预览.html
该文件内联了 JS、CSS 与全部图片（data URI），双击即可在任意电脑上打开，
不需要 Python / Node / 后端服务。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist-offline"
OUT = DIST / "Rainbow-FinGPT-新首页预览.html"


def local_path(relative: str) -> Path:
    """把 HTML 里的 ./assets/xxx 转成 dist-offline 下的真实路径。"""
    cleaned = relative.removeprefix("./").lstrip("/")
    return DIST / cleaned


def main() -> int:
    index = DIST / "index.html"
    if not index.exists():
        print(f"找不到 {index}，请先执行：npx vite build --config vite.config.offline.ts", file=sys.stderr)
        return 1

    html = index.read_text(encoding="utf-8")

    def inline_css(match: re.Match[str]) -> str:
        path = local_path(match.group(1))
        if not path.exists():
            print(f"  ⚠ 找不到样式文件 {path}，跳过", file=sys.stderr)
            return match.group(0)
        return f"<style>\n{path.read_text(encoding='utf-8')}\n</style>"

    # 注意：Vite 原本输出的是 <script type="module">，它自带 defer 语义（DOM 解析完才执行）。
    # 打成 IIFE 变成经典脚本后没有 defer，而且内联脚本上的 defer 属性会被浏览器忽略，
    # 若仍留在 <head>，就会在 <div id="root"> 出现之前执行 → React 挂载失败、页面全白。
    # 因此这里先把它摘出来，最后插到 </body> 之前。
    inline_script: list[str] = []

    def inline_js(match: re.Match[str]) -> str:
        path = local_path(match.group(1))
        if not path.exists():
            print(f"  ⚠ 找不到脚本 {path}，跳过", file=sys.stderr)
            return match.group(0)
        code = path.read_text(encoding="utf-8")
        # 内联脚本以 </script> 结束，代码里若出现该串会提前截断
        code = code.replace("</script", "<\\/script")
        inline_script.append(f"<script>\n{code}\n</script>")
        return ""

    html = re.sub(r'<link[^>]*rel="stylesheet"[^>]*href="([^"]+)"[^>]*>', inline_css, html)
    html = re.sub(r'<script[^>]*src="([^"]+)"[^>]*></script>', inline_js, html)
    # 离线打开时不会有接口，去掉模块预加载等残留标签
    html = re.sub(r'<link[^>]*rel="modulepreload"[^>]*>\s*', "", html)

    if inline_script:
        html = html.replace("</body>", "\n".join(inline_script) + "\n</body>")

    OUT.write_text(html, encoding="utf-8")
    # 只把真正的 src="..."/href="..." 属性算作外部引用
    #（bundle 里会出现 "href=" 这样的字面量，不能只做子串判断）
    leftovers = re.findall(r'(?:\ssrc|\shref)="([^"]+)"', html)
    if leftovers:
        print(f"  ⚠ 仍有 {len(leftovers)} 处外部引用：{leftovers[:5]}", file=sys.stderr)

    size_kb = OUT.stat().st_size / 1024
    print(f"已生成单文件：{OUT.name}（{size_kb:.0f} KB，内联 JS/CSS/图片）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
