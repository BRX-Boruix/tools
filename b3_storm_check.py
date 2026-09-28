#!/usr/bin/env python3
"""B3 storm regression: high-frequency typing on a live session.

Reproduces the former flood scenario (rapid repeated line entry that
grew libline history without bound and drove the user heap into
OOM panic). PASS = session survives N flood lines with no
'userspace panic' line in the serial log.
"""
import os, socket, subprocess, sys, time
from sdk_build import config

ROOT = r"F:\boruix-project"
QEMU = os.path.join(ROOT, "envfiles", "tools", "qemu-stable", "qemu-9.2.0-win64", "qemu-system-x86_64.exe")
ISO = config.OUTPUT_ISO
DISK = os.path.join(ROOT, "disk.img")
LOG = os.path.join(ROOT, "_b3_storm_serial.log")
PORT = 45481
FLOOD_LINES = 120

def main():
    if os.path.exists(LOG):
        os.remove(LOG)
    qemu = [QEMU, "-cdrom", ISO, "-hda", DISK, "-boot", "order=d", "-m", "256",
            "-display", "none", "-serial", "file:" + LOG,
            "-monitor", "tcp:127.0.0.1:%d,server,nowait" % PORT, "-no-reboot"]
    print("[storm] starting qemu ...")
    proc = subprocess.Popen(qemu, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    s = None
    for _ in range(60):
        try:
            s = socket.create_connection(("127.0.0.1", PORT), timeout=2)
            break
        except OSError:
            time.sleep(0.5)
    if s is None:
        print("[storm] FAIL: monitor port never came up")
        proc.kill()
        return 1
    f = s.makefile("rwb")

    def key(k, d=0.22):
        f.write(("sendkey " + k + "\n").encode())
        f.flush()
        time.sleep(d)

    def wait_log(pat, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with open(LOG, "rb") as h:
                    data = h.read()
                if pat.encode() in data:
                    return data
            except OSError:
                pass
            time.sleep(0.5)
        return None

    if wait_log("username:", 150) is None:
        print("[storm] FAIL: no login prompt")
        proc.kill()
        return 1
    print("[storm] S1: login as alice")
    for ch in "alice\n":
        key("ret" if ch == "\n" else ch)
    time.sleep(2.0)
    for ch in "alicepw\n":
        key("ret" if ch == "\n" else ch)
    if wait_log("BORUIX shell", 60) is None:
        print("[storm] FAIL: no shell")
        proc.kill()
        return 1
    print("[storm] S2: flooding lines via echo")
    ok = True
    for i in range(FLOOD_LINES):
        txt = "echo flood" + str(i % 10) + "\n"
        for ch in txt:
            key("ret" if ch == "\n" else ch)
        if wait_log("flood" + str(i % 10), 25) is None:
            print("[storm] FAIL: no output for line " + str(i))
            ok = False
            break
    try:
        with open(LOG, "rb") as h:
            data = h.read()
    except OSError:
        data = b""
    if b"panic" in data.lower():
        print("[storm] FAIL: userspace panic under flood")
        ok = False
    if ok:
        print("[storm] PASS: no panic under " + str(FLOOD_LINES) + "-line flood")
    proc.kill()
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())