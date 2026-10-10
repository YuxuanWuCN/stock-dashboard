# -*- coding: utf-8 -*-
"""把客户端窗口的一条水平带切成窄片逐片 OCR，避免文字被合并成一个大块。

用法:
    python src/trading/_ocr_slices.py <top> <bottom> [slice_w] [overlap] [scale]
top/bottom 为相对客户端窗口的 y 坐标。

输出: reports/_client_slices.txt
"""
import io
import sys
import time

import win32api
import win32con
import win32gui
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

OUT = r"D:\第九届郑商所杯_2026\reports\_client_slices.txt"
TMP = r"D:\第九届郑商所杯_2026\reports\_slice_tmp.png"


def find_window():
    found = []

    def cb(h, _):
        if win32gui.IsWindowVisible(h) and "SSLForm" in win32gui.GetClassName(h):
            found.append(h)
        return True

    win32gui.EnumWindows(cb, found)
    return found[0] if found else None


def focus(hwnd):
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
        win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)
    except Exception as exc:
        print("置顶失败: %s" % exc)
    time.sleep(0.8)


def capture(hwnd):
    import ctypes
    import win32ui

    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    w, h = right - left, bottom - top
    hdc = win32gui.GetWindowDC(hwnd)
    mfc = win32ui.CreateDCFromHandle(hdc)
    save = mfc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(mfc, w, h)
    save.SelectObject(bmp)
    ctypes.windll.user32.PrintWindow(hwnd, save.GetSafeHdc(), 2)
    info = bmp.GetInfo()
    bits = bmp.GetBitmapBits(True)
    img = Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]), bits, "raw", "BGRX", 0, 1)
    save.DeleteDC()
    mfc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hdc)
    win32gui.DeleteObject(bmp.GetHandle())
    return img, (left, top)


def main():
    args = sys.argv[1:]
    top = int(args[0]) if args else 8
    bottom = int(args[1]) if len(args) > 1 else 52
    sw = int(args[2]) if len(args) > 2 else 70
    ov = int(args[3]) if len(args) > 3 else 35
    scale = int(args[4]) if len(args) > 4 else 6

    hwnd = find_window()
    if not hwnd:
        print("未找到极星窗口")
        return
    focus(hwnd)
    full, (ox, oy) = capture(hwnd)
    W = full.width
    print("窗口 %s 原点 %s 扫描带 y=%d..%d" % (full.size, (ox, oy), top, bottom))

    engine = RapidOCR()
    hits = []
    x = 0
    while x < W:
        x2 = min(W, x + sw)
        region = full.crop((x, top, x2, bottom))
        big = region.resize((region.width * scale, region.height * scale), Image.LANCZOS)
        big.save(TMP)
        result, _ = engine(TMP)
        if result:
            for box, text, score in result:
                xs = [p[0] for p in box]
                cx = int(min(xs) / scale) + x + ox
                cy = int(min([p[1] for p in box]) / scale) + top + oy
                hits.append((cx, cy, text, float(score)))
        x += sw - ov

    # 去重（同一文本可能落入相邻两片）
    seen = {}
    for cx, cy, text, score in hits:
        key = (text, round(cx / 12))
        if key not in seen or score > seen[key][3]:
            seen[key] = (cx, cy, text, score)

    lines = []
    for cx, cy, text, score in sorted(seen.values()):
        line = "x=%4d y=%4d  %.2f  %s" % (cx, cy, score, text)
        lines.append(line)
        print(line)
    lines.append("共 %d 项" % len(seen))
    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n已写入 %s" % OUT)


main()
