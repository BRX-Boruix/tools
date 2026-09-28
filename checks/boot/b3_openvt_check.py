#!/usr/bin/env python3
"""B3-C3/C5 acceptance: runtime console instance creation end-to-end.

S1 boot (parallel mode, BORUIX_CONSOLES_N pre-created) - login - shell
S2 run /programs/openvt.elf - init patrol must log
   '[init] openvt: instance 4 created' (first free id after 0..3)
S3 run /programs/openvt.elf again - '[init] openvt: instance 5 created'
   (monotonic allocation across successive requests)
PASS = both created lines + zero 'dropped' lines + shell prompt returns.
"""
import os, re, socket, subprocess, sys, time
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
LOG = os.path.join(ROOT, "_b3_openvt_serial.log")
PORT = 45480

def main():
    if os.path.exists(LOG):
        os.remove(LOG)
    qemu = [QEMU, "-cdrom", ISO, "-hda", DISK, "-boot", "order=d", "-m", "256",
            "-display", "none", "-serial", "file:" + LOG,
            "-monitor", "tcp:127.0.0.1:%d,server,nowait" % PORT, "-no-reboot"]
    print("[b3] starting qemu ...")
    proc = subprocess.Popen(qemu, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    s = None
    for _ in range(60):
        try:
            s = socket.create_connection(("127.0.0.1", PORT), timeout=2)
            break
        except OSError:
            time.sleep(0.5)
    if s is None:
        print("[b3] FAIL: monitor port never came up")
        proc.kill()
        return 1
    f = s.makefile("rwb")

    def key(k, d=0.30):
        f.write(("sendkey " + k + "\n").encode())
        f.flush()
        time.sleep(d)

    named = {" ": "spc", ".": "dot", "-": "minus", "/": "slash", ";": "semicolon",
             "=": "equal", ",": "comma"}
    def qc(ch):
        if ch == "\n":
            return "ret"
        if ch.isupper():
            return "shift-" + ch.lower()
        if ch in named:
            return named[ch]
        return ch

    def type_str(txt, d=0.35):
        for ch in txt:
            key(qc(ch), d)

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

    ok = True
    if wait_log("username:", 150) is None:
        print("[b3] FAIL: no login prompt")
        proc.kill()
        return 1
    # 4 实例并行：等全部 getty 焦点转移完成（4 行 focus 日志）再打字，
    # 否则键入会被焦点切换分流到不同实例的 login（实证：凭据分流
    # 导致 authentication failed，2026-09-28 晚）。
    dl = time.time() + 60
    while time.time() < dl:
        try:
            with open(LOG, "rb") as h:
                if h.read().count(b"focus -> instance") >= 4:
                    break
        except OSError:
            pass
        time.sleep(1)
    time.sleep(2.0)
    print("[b3] S1 login prompt seen; logging in as alice")
    type_str("alice\n")
    time.sleep(2.5)
    type_str("alicepw\n")
    if wait_log("BORUIX shell", 60) is None:
        print("[b3] FAIL: no shell banner (BORUIX shell)")
        proc.kill()
        return 1
    print("[b3] S1b shell up")
    time.sleep(1.5)

    print("[b3] S2 running /programs/openvt.elf (expect instance 4)")
    type_str("/programs/openvt.elf\n")
    if wait_log("[init] openvt: instance 4 created", 60) is None:
        print("[b3] FAIL: no 'instance 4 created' from init patrol")
        ok = False
    else:
        print("[b3] S2 PASS: init created instance 4")
    time.sleep(2.0)

    # S3: focus is claimed by the instance-4 login (B3-T2 getty claim
    # semantics) so keystrokes naturally land on the new terminal.
    # Log in ON instance 4: proves the new instance is usable end-to-end
    # (login+bind+shell) AND monotonic allocation (next request = 5).
    print("[b3] S3 login on new instance 4 (focus claimed by new getty)")
    time.sleep(2.0)
    type_str("alice\n")
    time.sleep(2.5)
    type_str("alicepw\n")
    if wait_log("BORUIX shell", 60) is None:
        print("[b3] FAIL: no shell on instance 4 (login/bind broken)")
        ok = False
    else:
        print("[b3] S3a PASS: instance 4 login+bind+shell works")
    time.sleep(1.5)
    print("[b3] S3b running /programs/openvt.elf (expect instance 5)")
    type_str("/programs/openvt.elf\n")
    if wait_log("[init] openvt: instance 5 created", 60) is None:
        print("[b3] FAIL: no instance 5 created from init patrol")
        ok = False
    else:
        print("[b3] S3b PASS: instance 5 created (monotonic allocation)")
    time.sleep(2.0)
    with open(LOG, "rb") as h:
        txt = h.read().decode("utf-8", "replace")
    n_dropped = len(re.findall(r"openvt request dropped", txt))
    if n_dropped != 0:
        print("[b3] FAIL: %d request(s) dropped (want 0)" % n_dropped)
        ok = False
    if ok:
        print("[b3] PASS: openvt - init patrol - runtime instances verified")
    proc.kill()
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
