# -*- coding: utf-8 -*-
"""按进程号枚举极星客户端窗口的 UI Automation 控件树（纯文本输出）。

本模型不支持读图，因此不截图，只导出文本供解析。
用法: python src/trading/_uia_probe.py [pid]   默认 29488
输出: D:\\第九届郑商所杯_2026\\reports\\_uia_dump.txt
"""
import io
import sys

OUT = r"D:\第九届郑商所杯_2026\reports\_uia_dump.txt"
PID = int(sys.argv[1]) if len(sys.argv) > 1 else 29488

import uiautomation as auto

lines = []
counter = {"n": 0}


def emit(s):
    lines.append(s)
    print(s)


def safe(obj, attr, default=""):
    try:
        v = getattr(obj, attr)
        return default if v is None else v
    except Exception:
        return default


def dump(ctrl, depth, max_depth, max_children):
    if depth > max_depth:
        return
    try:
        children = ctrl.GetChildren()
    except Exception as exc:
        emit("%s<GetChildren 失败: %s>" % ("  " * depth, exc))
        return
    for c in children[:max_children]:
        counter["n"] += 1
        name = str(safe(c, "Name")).strip()
        ctype = str(safe(c, "ControlTypeName", "?"))
        aid = str(safe(c, "AutomationId"))
        cls = str(safe(c, "ClassName"))
        try:
            r = c.BoundingRectangle
            rect = "(%d,%d,%d,%d)" % (r.left, r.top, r.right, r.bottom)
        except Exception:
            rect = ""
        emit("%s- %s name=%r aid=%r cls=%r %s" % ("  " * depth, ctype, name[:90], aid[:40], cls[:40], rect))
        dump(c, depth + 1, max_depth, max_children)


def main():
    root = auto.GetRootControl()
    tops = root.GetChildren()
    targets = []
    for w in tops:
        try:
            if w.ProcessId == PID:
                targets.append(w)
        except Exception:
            continue

    emit("=== 进程 %d 的顶层控件: %d 个 ===" % (PID, len(targets)))
    for w in targets:
        emit("")
        emit("=== 控件树 name=%r ===" % (safe(w, "Name"),))
        dump(w, 0, 6, 80)
    emit("")
    emit("总控件数: %d" % counter["n"])


main()
with io.open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("\n已写入 %s (%d 行, %d 控件)" % (OUT, len(lines), counter["n"]))
