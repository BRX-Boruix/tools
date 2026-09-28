#!/usr/bin/env python3
"""defect #2 batch boot: run N boots, capture any 'attempted to kill init' panic with the new vector/rip/error_code fields."""
import os, re, subprocess, sys, time, socket
import sys
# --- tools path bootstrap (files live under tools/checks/<cat>/) ---
_TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)
from tools_build import config

ROOT = r"F:\boruix-project"
QEMU = os.path.join(ROOT, "envfiles", "tools", "qemu-stable",
                    "qemu-9.2.0-win64", "qemu-system-x86_64.exe")
ISO = config.OUTPUT_ISO
DISK = os.path.join(ROOT, "disk.img")
PORT = 45481
N = int(sys.argv[1]) if len(sys.argv) > 1 else 10
TIMEOUT = 150

def one_boot(i):
    log = os.path.join(ROOT, "_p2_boot_%02d.log" % i)
    if os.path.exists(log):
        os.remove(log)
    qemu = [QEMU, "-cdrom", ISO, "-hda", DISK, "-boot", "order=d", "-m", "256",
            "-display", "none", "-serial", "file:" + log,
            "-monitor", "tcp:127.0.0.1:%d,server,nowait" % (PORT + i), "-no-reboot"]
    proc = subprocess.Popen(qemu, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + TIMEOUT
    hit = False
    try:
        while time.time() < deadline:
            try:
                with open(log, "rb") as h:
                    data = h.read()
                if b"attempted to kill init" in data:
                    hit = True
                    break
                if b"username:" in data:
                    # 登录提示符出现 = 本次 boot 完整走过 panic 窗口
                    break
            except OSError:
                pass
            time.sleep(1.0)
    finally:
        proc.kill()
    return hit, log

def main():
    hits = []
    for i in range(N):
        hit, log = one_boot(i)
        print("[p2] boot %02d: %s" % (i, "PANIC-CAPTURED" if hit else "clean"))
        if hit:
            hits.append(log)
    print("[p2] ---- %d/%d boots panicked ----" % (len(hits), N))
    for h in hits:
        with open(h, "rb") as f:
            data = f.read().decode("utf-8", "replace")
        m = re.search(r"KERNEL PANIC[^\x00]*", data)
        if m:
            print("[p2] " + data[m.start():m.start() + 400].replace("\n", " | "))
    return 0

if __name__ == "__main__":
    sys.exit(main())