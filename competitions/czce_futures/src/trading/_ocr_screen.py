# -*- coding: utf-8 -*-
"""对极星客户端窗口截图做 OCR，以文本形式"读"出界面内容。

本模型不支持读图，因此用 OCR 把界面转成带坐标的文本。
用法: python src/trading/_ocr_screen.py <png> [left top right bottom]
"""
import io
import sys

from PIL import Image
from rapidocr_onnxruntime import RapidOCR

OUT = r"D:\第九届郑商所杯_2026\reports\_ocr_result.txt"

png = sys.argv[1] if len(sys.argv) > 1 else r"D:\第九届郑商所杯_2026\reports\_screen_now.png"
crop = None
if len(sys.argv) >= 6:
    crop = tuple(int(x) for x in sys.argv[2:6])

img = Image.open(png).convert("RGB")
offset = (0, 0)
if crop:
    img = img.crop(crop)
    offset = (crop[0], crop[1])

# 放大有助于小字号识别
scale = 2
img = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)
tmp = r"D:\第九届郑商所杯_2026\reports\_ocr_input.png"
img.save(tmp)

engine = RapidOCR()
result, elapse = engine(tmp)

lines = ["原图: %s  裁剪: %s  放大: %dx  耗时: %s" % (png, crop, scale, elapse)]
rows = []
if result:
    for box, text, score in result:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        x = int(min(xs) / scale) + offset[0]
        y = int(min(ys) / scale) + offset[1]
        rows.append((y, x, text, float(score)))

rows.sort()
for y, x, text, score in rows:
    line = "y=%4d x=%4d  %.2f  %s" % (y, x, score, text)
    lines.append(line)
    print(line)

lines.append("")
lines.append("共识别 %d 个文本块" % len(rows))
with io.open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("\n已写入 %s" % OUT)
