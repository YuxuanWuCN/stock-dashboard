# -*- coding: utf-8 -*-
"""把极星客户端窗口切到前台并 OCR 读取其界面文本。

极星主窗口类名为 SSLForm，界面为自绘（无原生子窗口、UIA 控件数为 0），
因此只能用「窗口置顶 + 截图 + OCR」的方式把界面转成文本与坐标。

用法: python src/trading/_read_client.py [关键词...]
输出: reports/_client_ocr.txt
"""
import io
import sys
import time

import win32api
import win32con
import win32gui
from PIL import Image

from rapidocr_onnxruntime import RapidOCR

OUT = r"D:\第九届郑商所杯_2026\reports\_client_ocr.txt"
SCRATCH = r"D:\第九届郑商所杯_2026\reports\_client_shot.png"
WINDOW_CLASS = "SSLForm"


def find_client_window():
    """极星窗口类名实际为 'class SSLForm'（含前缀），因此用子串匹配。"""
    found = []

    def cb(h, _):
        if win32gui.IsWindowVisible(h) and WINDOW_CLASS in win32gui.GetClassName(h):
            found.append(h)
        return True

    win32gui.EnumWindows(cb, found)
    return found[0] if found else None


def focus(hwnd):
    """置顶窗口。用 ALT 键骗过 Windows 的前台锁定策略。"""
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
        win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)
    except Exception as exc:
        print("置顶失败: %s" % exc)
    time.sleep(0.9)


def grab(hwnd, pad=6):
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    left, top = max(0, left - pad), max(0, top - pad)
    import win32ui
    import win32con as wc
    import ctypes

    hdc = win32gui.GetWindowDC(hwnd)
    mfc = win32ui.CreateDCFromHandle(hdc)
    save = mfc.CreateCompatibleDC()
    w, h = right - left, bottom - top
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
    img.save(SCRATCH)
    return img, (left, top)


def main():
    hwnd = find_client_window()
    if not hwnd:
        print("未找到极星窗口（class=SSLForm）")
        return
    title = win32gui.GetWindowText(hwnd)
    focus(hwnd)
    img, origin = grab(hwnd)
    print("窗口 hwnd=%s 标题=%r 尺寸=%s 原点=%s" % (hwnd, title, img.size, origin))

    scale = 2
    big = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)
    big_path = r"D:\第九届郑商所杯_2026\reports\_client_shot_big.png"
    big.save(big_path)
    engine = RapidOCR()
    result, elapse = engine(big_path)

    rows = []
    if result:
        for box, text, score in result:
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            x = int(min(xs) / scale) + origin[0]
            y = int(min(ys) / scale) + origin[1]
            rows.append((y, x, text, float(score)))
    rows.sort()

    lines = ["窗口: %r  hwnd=%s  size=%s  耗时=%s" % (title, hwnd, img.size, elapse)]
    for y, x, text, score in rows:
        line = "y=%4d x=%4d  %.2f  %s" % (y, x, score, text)
        lines.append(line)
        print(line)
    lines.append("共 %d 个文本块" % len(rows))
    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n已写入 %s" % OUT)


main()
