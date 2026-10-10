# -*- coding: utf-8 -*-
"""对极星客户端窗口的指定区域做高倍 OCR，用于精确定位菜单与按钮。

用法:
    python src/trading/_ocr_region.py <left> <top> <right> <bottom> [scale]
坐标相对于客户端窗口左上角（默认窗口由 SSLForm 定位）。

输出: reports/_client_region.txt
"""
import io
import sys
import time

import win32api
import win32con
import win32gui
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

OUT = r"D:\第九届郑商所杯_2026\reports\_client_region.txt"
SHOT = r"D:\第九届郑商所杯_2026\reports\_client_region.png"


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
    if len(args) < 4:
        print(__doc__)
        return
    l, t, r, b = (int(x) for x in args[:4])
    scale = int(args[4]) if len(args) > 4 else 4

    hwnd = find_window()
    if not hwnd:
        print("未找到极星窗口")
        return
    focus(hwnd)
    full, (ox, oy) = capture(hwnd)
    print("窗口 hwnd=%s 尺寸=%s 原点=%s" % (hwnd, full.size, (ox, oy)))

    region = full.crop((l, t, r, b))
    big = region.resize((region.width * scale, region.height * scale), Image.LANCZOS)
    big.save(SHOT)

    result, elapse = RapidOCR()(SHOT)
    rows = []
    if result:
        for box, text, score in result:
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            x = int(min(xs) / scale) + l + ox
            y = int(min(ys) / scale) + t + oy
            w = int((max(xs) - min(xs)) / scale)
            h = int((max(ys) - min(ys)) / scale)
            rows.append((y, x, w, h, text, float(score)))
    rows.sort()

    lines = ["窗口尺寸 %s 原点 %s 区域 (%d,%d,%d,%d) 放大 %dx" % (full.size, (ox, oy), l, t, r, b, scale)]
    for y, x, w, h, text, score in rows:
        line = "y=%4d x=%4d w=%3d h=%2d  %.2f  %s" % (y, x, w, h, score, text)
        lines.append(line)
        print(line)
    lines.append("共 %d 块" % len(rows))
    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n已写入 %s" % OUT)


main()
