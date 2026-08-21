import subprocess, sys, time
argv = [sys.executable, "-c", "import time; time.sleep(400)"]
t0 = time.monotonic()
try:
    subprocess.run(argv, timeout=300, capture_output=True, text=True, encoding="utf-8", errors="replace")
except subprocess.TimeoutExpired as exc:
    print("EXC STR:", str(exc))
    print("EXC TIMEOUT:", exc.timeout)
print("elapsed:", round(time.monotonic() - t0, 2))
