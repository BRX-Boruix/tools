#!/usr/bin/env python3
"""ADR-048 T3 acceptance: focus gate (SYS_STREAM_FOCUS_SET, owner ruling alpha).

S1 login alice (login claims focus for instance 0 idempotently) -> shell ok
   => single-session behaviour unchanged (hard criterion).
S2 run focusdemo as unprivileged shell child -> FOCUS_SET(1) must be
   denied with EACCES (CAP_SYSTEM gate holds; no terminal hijack face).

judgement: S1 shell prompt + S2 [focusdemo] PASS line.
"""
import os, socket, subprocess, sys, time
import sys
# --- tools path bootstrap (files live under tools/checks/<cat>/) ---
_TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)
from tools_build import config
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
QEMU = os.path.join(ROOT, "envfiles", "tools", "qemu-stable",
                    "qemu-9.2.0-win64", "qemu-system-x86_64.exe")
LOG = os.path.join(ROOT, "_t3_serial.log")
PORT = 45492

def main():
    if os.path.exists(LOG):
        os.remove(LOG)
    proc = subprocess.Popen([QEMU, "-cdrom", config.OUTPUT_ISO,
        "-boot", "order=d", "-m", "256", "-display", "none",
        "-serial", "file:" + LOG,
        "-monitor", "tcp:127.0.0.1:%d,server,nowait" % PORT, "-no-reboot"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    s = None
    for _ in range(60):
        try:
            s = socket.create_connection(("127.0.0.1", PORT), timeout=2); break
        except OSError:
            time.sleep(0.5)
    if s is None:
        print("[t3] FAIL: monitor never up"); proc.kill(); return 1
    f = s.makefile("rwb")

    def key(k, d=0.3):
        f.write(("sendkey " + k + "\n").encode()); f.flush(); time.sleep(d)

    def typ(t2, d=0.15):
        for c in t2:
            key({" ": "spc", "/": "slash", ".": "dot"}.get(c, c), d)

    def snap():
        try:
            with open(LOG, "rb") as h: return h.read().decode("utf-8", "replace")
        except OSError: return ""

    def wait(pat, timeout):
        dl = time.time() + timeout
        while time.time() < dl:
            if pat in snap(): return True
            time.sleep(0.5)
        return False

    ok = True
    if not wait("username:", 200):
        print("[t3] FAIL: no login prompt"); proc.kill(); return 1
    typ("alice"); key("ret", 2.0)
    time.sleep(1.0); typ("alicepw"); key("ret", 3.0)
    if not wait("alice:/$", 60):
        print("[t3] FAIL: no shell (login focus-claim path may have broken session)")
        proc.kill(); return 1
    print("[t3] S1 login+focus-claim: single session unchanged")
    typ("/programs/focusdemo.elf"); key("ret", 2.0)
    time.sleep(1.5)
    if "[focusdemo] PASS: denied with EACCES" not in snap():
        print("[t3] FAIL: focusdemo gate verdict not seen")
        print(snap()[-600:])
        ok = False
    else:
        print("[t3] S2 adversarial FOCUS_SET denied with EACCES (gate holds)")
    proc.kill()
    print("[t3] ---- " + ("PASS" if ok else "FAIL") + " ----")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
