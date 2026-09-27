#!/usr/bin/env python3
"""ADR-048 T5 acceptance: two-instance getty rotation (owner ruling B).

S1 first getty = instance 0: `instance 0` marker + login alice ->
   `[console] pid=P focus -> instance 0` -> shell prompt (single-session path unchanged).
S2 session rotation: shell kills itself (`ps` -> own pid -> `kill -9 PID`,
   SIGKILL self is a first-class kernel path) -> init respawns login with
   `instance 1` -> `[console] ... focus -> instance 1`.
S3 dual consoled: `consoled started (pid N)` exactly 2x.

judgement: S1 + S2 + S3.
"""
import os, socket, subprocess, sys, time, re
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QEMU = os.path.join(ROOT, "envfiles", "tools", "qemu-stable",
                    "qemu-9.2.0-win64", "qemu-system-x86_64.exe")
LOG = os.path.join(ROOT, "_t5_serial.log")
PORT = 45493

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
        print("[t5] FAIL: monitor never up"); proc.kill(); return 1
    f = s.makefile("rwb")

    def key(k, d=0.25):
        f.write(("sendkey " + k + "\n").encode()); f.flush(); time.sleep(d)

    def typ(t2, d=0.12):
        named = {" ": "spc", "/": "slash", ".": "dot", "-": "minus"}
        for c in t2:
            key(named.get(c, c), d)

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
        print("[t5] FAIL: no login prompt"); proc.kill(); return 1
    # S3: dual consoled
    n_con = len(re.findall(r"consoled started \(pid \d+\)", snap()))
    print("[t5] S3 consoled daemons: %d (want 2)" % n_con)
    if n_con != 2: ok = False
    # S1: instance 0 getty + login + focus claim
    if not wait("instance 0", 15):
        print("[t5] S1 FAIL: no `instance 0` rotation marker"); ok = False
    else:
        print("[t5] S1 getty instance-0 marker seen")
    typ("alice"); key("ret", 2.0)
    time.sleep(1.0); typ("alicepw"); key("ret", 3.0)
    if not wait("alice:/$", 60):
        print("[t5] S1 FAIL: no shell on instance 0"); proc.kill(); return 1
    if "focus -> instance 0" not in snap():
        print("[t5] S1 FAIL: focus-0 claim not seen"); ok = False
    else:
        print("[t5] S1 focus -> instance 0 claimed")
    # S2: end session by SIGKILL self, expect rotation to instance 1
    typ("ps --json"); key("ret", 2.5)
    full = snap()
    # ps --json：[{"pid":N,...,"name":"shell.elf",...}]——取 shell.elf 的 pid。
    m = re.findall(r'"pid"\s*:\s*(\d+)[^}]*"name"\s*:\s*"shell\.elf"', full)
    if not m:
        m = re.findall(r'"name"\s*:\s*"shell\.elf"[^}]*"pid"\s*:\s*(\d+)', full)
    if not m:
        print("[t5] S2 FAIL: shell pid not found in ps output"); ok = False
    else:
        pid = m[-1]
        print("[t5] S2 shell pid = " + pid)
        typ("kill -9 " + pid); key("ret", 2.5)
        time.sleep(1.0)
        if not wait("session ended", 30):
            print("[t5] S2 FAIL: session did not end (kill self refused?)")
            ok = False
        elif not wait("instance 1", 30):
            print("[t5] S2 FAIL: no `instance 1` rotation marker")
            ok = False
        elif not wait("focus -> instance 1", 40):
            print("[t5] S2 FAIL: no `focus -> instance 1` claim")
            ok = False
        else:
            print("[t5] S2 rotation to instance 1 + focus claim OK")
    proc.kill()
    print("[t5] ---- " + ("PASS" if ok else "FAIL") + " ----")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
