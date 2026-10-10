# -*- coding: utf-8 -*-
"""从极星客户端语言资源中提取界面菜单项（UTF-16LE）。

用于确认客户端是否存在「量化」入口及其确切名称与进入方式。
"""
import os
import traceback

CFG = r"C:\Users\ASUS\AppData\Roaming\Epolestar000450v9.5\config"

FILES = [
    r"LanguageApi\LanguageApi.QuantFrame.pub",
    r"MainFrame\MainFrame.Selfs.pub",
    r"MainFrame\MainFrame.WorkZone.pub",
    r"MainFrame\MainFrame.Restore.pub",
    r"LanguageApi\LanguageApi.StrategyOrder.pub",
]

INTEREST = ["量化", "策略", "模块", "插入", "启动", "账户", "账号", "下单", "自动", "实盘", "仿真"]


def load(path):
    b = open(path, "rb").read()
    if b[:2] == b"\xff\xfe":
        txt = b.decode("utf-16-le", errors="replace")
    else:
        txt = b.decode("gb18030", errors="replace")
    return txt.lstrip("\ufeff").replace("\x00", "")


for rel in FILES:
    p = os.path.join(CFG, rel)
    print("\n" + "=" * 24 + " " + rel + " " + "=" * 24)
    if not os.path.exists(p):
        print("不存在")
        continue
    try:
        txt = load(p)
    except Exception:
        print("读取失败:"); traceback.print_exc(); continue

    lines = [s.strip() for s in txt.replace("\r", "\n").split("\n") if s.strip()]
    shown = 0
    for line in lines:
        if any(k in line for k in INTEREST):
            print("*", line)
            shown += 1
        elif shown < 0:
            print(" ", line)
    if shown == 0:
        print("(未命中关键词，前 40 行原文)")
        for line in lines[:40]:
            print(" ", line)
