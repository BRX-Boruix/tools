#!/usr/bin/env python3
"""ADR-048 T1 acceptance: /devices/consoles/N instance family mounted.

judgement: login alice -> `ls /devices/consoles` shows 0 1 2 3 ->
`cat /devices/consoles/0/status` works (same ring family as console).
Single-session behaviour unchanged (l2 9/9 covers).
"""
import os, socket, subprocess, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QEMU = os.path.join(ROOT, "envfiles", "tools", "qemu-stable",
                    "qemu-9.2.0-win64", "qemu-system-x86_64.exe")
LOG = os.path.join(ROOT, "_t1_serial.log")
PORT = 45491

def main():
    if os.path.exists(LOG):
        os.remove(LOG)
    proc = subprocess.Popen([QEMU, "-cdrom", os.path.join(ROOT, "boruix.iso"),
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
        print("[t1] FAIL: monitor never up"); proc.kill(); return 1
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
        print("[t1] FAIL: no login prompt"); proc.kill(); return 1
    typ("alice"); key("ret", 2.0)
    time.sleep(1.0); typ("alicepw"); key("ret", 3.0)
    if not wait("alice:/$", 60):
        print("[t1] FAIL: no shell"); proc.kill(); return 1
    print("[t1] login ok")
    typ("ls /devices/consoles"); key("ret", 2.0)
    time.sleep(1.5)
    full = snap()
    tail = full[full.rfind("ls /devices/consoles"):] if "ls /devices/consoles" in full else ""
    have = [d for d in "0123" if d in tail]
    print("[t1] ls output digits present: " + ",".join(have))
    if have != ["0", "1", "2", "3"]:
        print("[t1] FAIL: instance family incomplete"); ok = False
    typ("cat /devices/consoles/0/status"); key("ret", 2.0)
    time.sleep(1.0)
    full = snap()
    if "write_pos" not in full:
        print("[t1] FAIL: instance 0 status unreadable"); ok = False
    else:
        print("[t1] instance-0 status JSON readable (ring family alive)")
    proc.kill()
    print("[t1] ---- " + ("PASS" if ok else "FAIL") + " ----")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
