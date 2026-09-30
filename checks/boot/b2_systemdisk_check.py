#!/usr/bin/env python3
"""B2 系统盘验收：EXT2 系统盘 → 登录 → BORUIX shell → 从盘上 exec 程序（S1/S2/S3）。

默认走 BIOS + brxLimine（-hda）；--liftoff 走 UEFI + liftoff（OVMF + ESP + 同一张盘），
断言完全相同——这正是「liftoff 下 OS 是否完整可用」的验收。
"""
import argparse, os, socket, subprocess, sys, time
# --- tools path bootstrap (files live under tools/checks/<cat>/) ---
_TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)
from tools_build import config, liftoff

ROOT = r"F:\boruix-project"
QEMU = os.path.join(ROOT, "envfiles", "tools", "qemu-stable", "qemu-9.2.0-win64", "qemu-system-x86_64.exe")
SDISK = os.path.join(ROOT, "systemdisk.img")
LOG = os.path.join(ROOT, "_b2_sysdisk_serial.log")
PORT = 45482

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--liftoff", action="store_true",
                    help="用 liftoff(UEFI/OVMF) 引导而非 brxLimine(BIOS)")
    # UEFI 路径多一层 OVMF 固件初始化，且 24.6MB 内核的读取/装载在 TCG 下更慢——
    # S1（登录提示）超时按链路可调，BIOS 路径沿用 150s。
    ap.add_argument("--s1-timeout", type=int, default=150)
    args = ap.parse_args()
    if os.path.exists(LOG):
        os.remove(LOG)
    common = ["-m", "256", "-display", "none", "-serial", "file:" + LOG,
              "-monitor", "tcp:127.0.0.1:%d,server,nowait" % PORT, "-no-reboot"]
    if args.liftoff:
        esp = liftoff.ensure_ready()
        qemu = [liftoff.qemu_exe()] + common + [
            "-drive", "format=raw,file=" + SDISK] + liftoff.uefi_args(esp)
        print("[sysdisk] boot from EXT2 systemdisk via liftoff (UEFI/OVMF), esp=" + esp)
    else:
        qemu = [QEMU, "-hda", SDISK, "-boot", "order=c"] + common
        print("[sysdisk] boot from EXT2 systemdisk (no ISO, no data disk)")
    proc = subprocess.Popen(qemu, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    s = None
    for _ in range(60):
        try:
            s = socket.create_connection(("127.0.0.1", PORT), timeout=2)
            break
        except OSError:
            time.sleep(0.5)
    if s is None:
        print("[sysdisk] FAIL: monitor port never came up")
        proc.kill()
        return 1
    f = s.makefile("rwb")

    named = {" ": "spc", ".": "dot", "-": "minus", "/": "slash"}

    def key(k, d=0.30):
        f.write(("sendkey " + k + "\n").encode())
        f.flush()
        time.sleep(d)

    def type_str(txt, d=0.30):
        for ch in txt:
            if ch == "\n":
                key("ret", d)
            else:
                key(named.get(ch, ch), d)

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
    if wait_log("username:", args.s1_timeout) is None:
        print("[sysdisk] FAIL: no login prompt")
        proc.kill()
        return 1
    print("[sysdisk] S1 PASS: kernel booted from EXT2 system disk, login up")
    # parallel getty: wait for 4 focus claims before typing (same
    # discipline as the B3 main e2e - keystrokes otherwise tear across
    # instances).
    deadline = time.time() + 60
    seen = 0
    while time.time() < deadline and seen < 4:
        try:
            with open(LOG, "rb") as h:
                seen = h.read().count(b"focus -> instance")
        except OSError:
            pass
        if seen < 4:
            time.sleep(1.0)
    print("[sysdisk] focus claims seen:", seen)
    type_str("alice\n")
    time.sleep(2.0)
    type_str("alicepw\n")
    if wait_log("BORUIX shell", 60) is None:
        print("[sysdisk] FAIL: no shell")
        proc.kill()
        return 1
    print("[sysdisk] S2 PASS: shell running (ELF served from EXT2 /programs)")
    time.sleep(1.5)
    type_str("/programs/openvt.elf\n")
    if wait_log("[init] openvt: instance 4 created", 60) is None:
        print("[sysdisk] FAIL: openvt exec failed from EXT2 /programs")
        ok = False
    else:
        print("[sysdisk] S3 PASS: openvt exec from EXT2 /programs, runtime instance created")
    proc.kill()
    print("[sysdisk] " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
