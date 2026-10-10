# -*- coding: utf-8 -*-
"""极星客户端窗口控制与读取工具（供 agent 自动化使用）。

子命令:
    read                置顶 + 截图 + 全窗 OCR（scale 2）
    top                 置顶 + 截图 + 顶栏(0-130px) OCR（scale 3）
    band <t> <b> [scale] 指定水平带 OCR
    maximize / restore  窗口最大化 / 还原
    click <x> <y>       在屏幕绝对坐标点击（默认左键单击）
    dclick <x> <y>      双击
    key <keys>          发送按键（如 alt、esc、f5）

所有 OCR 结果写入 reports/_client_read.txt。
"""
import io
import sys
import time

import win32api
import win32con
import win32gui
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

OUT = r"D:\第九届郑商所杯_2026\reports\_client_read.txt"
TMP = r"D:\第九届郑商所杯_2026\reports\_client_tmp.png"


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
    time.sleep(0.7)


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


def ocr_band(img, origin, t, b, scale, engine):
    region = img.crop((0, t, img.width, b))
    big = region.resize((region.width * scale, region.height * scale), Image.LANCZOS)
    big.save(TMP)
    result, _ = engine(TMP)
    rows = []
    if result:
        for box, text, score in result:
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            x = int(min(xs) / scale) + origin[0]
            y = int(min(ys) / scale) + t + origin[1]
            w = int((max(xs) - min(xs)) / scale)
            rows.append((y, x, w, text, float(score)))
    rows.sort()
    return rows


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "read"
    hwnd = find_window()
    if not hwnd:
        print("未找到极星窗口（class 含 SSLForm）")
        return

    if cmd == "maximize":
        win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
        time.sleep(0.6)
        print("已最大化:", win32gui.GetWindowRect(hwnd))
        return
    if cmd == "restore":
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        time.sleep(0.4)
        print("已还原:", win32gui.GetWindowRect(hwnd))
        return
    if cmd == "click":
        x, y = int(sys.argv[2]), int(sys.argv[3])
        focus(hwnd)
        win32api.SetCursorPos((x, y))
        time.sleep(0.15)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.06)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        print("已单击 (%d,%d)" % (x, y))
        return
    if cmd == "dclick":
        x, y = int(sys.argv[2]), int(sys.argv[3])
        focus(hwnd)
        win32api.SetCursorPos((x, y))
        time.sleep(0.15)
        for _ in range(2):
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            time.sleep(0.06)
        print("已双击 (%d,%d)" % (x, y))
        return
    if cmd == "rclick":
        x, y = int(sys.argv[2]), int(sys.argv[3])
        focus(hwnd)
        win32api.SetCursorPos((x, y))
        time.sleep(0.2)
        win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
        time.sleep(0.08)
        win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
        time.sleep(0.6)
        print("已右键 (%d,%d)" % (x, y))
        return
    if cmd == "move":
        x, y = int(sys.argv[2]), int(sys.argv[3])
        win32api.SetCursorPos((x, y))
        time.sleep(0.2)
        print("已移动鼠标 (%d,%d)" % (x, y))
        return
    if cmd == "screen":
        # 全屏截图 + OCR（用于捕捉右键弹出的菜单，菜单是独立顶层窗口）
        import ctypes
        from PIL import ImageGrab

        scale = int(sys.argv[2]) if len(sys.argv) > 2 else 2
        img = ImageGrab.grab(all_screens=False)
        big = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)
        big.save(TMP)
        result, _ = RapidOCR()(TMP)
        rows = []
        if result:
            for box, text, score in result:
                xs = [p[0] for p in box]
                ys = [p[1] for p in box]
                rows.append((int(min(ys) / scale), int(min(xs) / scale),
                             int((max(xs) - min(xs)) / scale), text, float(score)))
        rows.sort()
        for y, x, w, text, score in rows:
            print("y=%4d x=%4d w=%4d  %.2f  %s" % (y, x, w, score, text))
        print("共 %d 块" % len(rows))
        return
    if cmd == "key":
        name = sys.argv[2].lower()
        vk = {"alt": win32con.VK_MENU, "esc": win32con.VK_ESCAPE, "f5": win32con.VK_F5,
              "enter": win32con.VK_RETURN, "tab": win32con.VK_TAB}.get(name)
        if vk is None:
            print("不支持的按键:", name)
            return
        focus(hwnd)
        win32api.keybd_event(vk, 0, 0, 0)
        time.sleep(0.05)
        win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
        print("已发送按键:", name)
        return

    focus(hwnd)
    img, origin = capture(hwnd)
    engine = RapidOCR()
    print("窗口尺寸 %s 原点 %s" % (img.size, origin))

    if cmd == "top":
        bands = [(0, 130, 3)]
    elif cmd == "band":
        t = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        b = int(sys.argv[3]) if len(sys.argv) > 3 else 130
        s = int(sys.argv[4]) if len(sys.argv) > 4 else 3
        bands = [(t, b, s)]
    else:
        bands = [(0, 130, 3), (130, min(360, img.height), 2), (min(360, img.height), img.height, 2)]

    lines = ["窗口 %s 原点 %s 命令 %s" % (img.size, origin, cmd)]
    for t, b, s in bands:
        lines.append("--- 带 y=%d..%d scale=%d ---" % (t, b, s))
        for y, x, w, text, score in ocr_band(img, origin, t, b, s, engine):
            line = "y=%4d x=%4d w=%3d  %.2f  %s" % (y, x, w, score, text)
            lines.append(line)
            print(line)
    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n已写入 %s" % OUT)


main()
