import sys
p = r"D:\股票分析项目\2.0版\.quality-state\daily_morning.log"
with open(p, "rb") as f:
    data = f.read()

# 找到 L19962 的字节偏移：搜索 "[2026-08-19 09:31:24] fetch_data"
marker = b"[2026-08-19 09:31:24] fetch_data"
idx = data.find(marker)
print("fetch 退出码行偏移:", idx)
if idx > 0:
    # 打印之前 4000 字节，尝试 UTF-16LE 解码
    chunk = data[idx-4000:idx+2000]
    try:
        dec = chunk.decode('utf-16-le', errors='replace')
        print("=== UTF-16LE 解码（fetch 结束前后）===")
        print(dec[-2500:])
    except Exception as e:
        print("decode err:", e)
