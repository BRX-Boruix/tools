#!/usr/bin/env python3
"""前台 `^C` 回归验收：N 个独立 QEMU 会话的通过率。

为什么必须是「批量 + 独立会话」而不是跑一次：该缺陷的失败率对**宿主负载**
高度敏感（同一镜像实测出现过 6/6、5/6、3/10），单次 3/3 的验收证明力不足，
曾因此被误判为「已修复」。判定口径详见 docs/TODO/terminal-input.md 6.12.7。

用法（在 sdk/ 目录下）：
    python regress_ctrl_c.py            # 12 个会话
    python regress_ctrl_c.py 20         # 自定义会话数

通过判据：登录 alice -> 执行 /programs/spinburn.elf -> 5 次 ^C（间隔 1s）
-> 等 12s -> 回车 -> 出现**新的**提示符。

**关键细节（曾造成 4 次假通过）**：必须用 ctrl-c 之前的偏移量 `m` 切片后再
查提示符。否则会匹配到 ctrl-c 之前回显的旧提示符，无论失败与否都判通过。
"""
import os, socket, subprocess, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QEMU = os.path.join(ROOT, "envfiles", "tools", "qemu-stable", "qemu-9.2.0-win64", "qemu-system-x86_64.exe")
BASE = 45600

def run_once(i):
    port = BASE + i
    ser = os.path.join(ROOT, "ctrl_c_run_%d.txt" % i)
    try: os.remove(ser)
    except OSError: pass
    proc = subprocess.Popen([QEMU, "-cdrom", os.path.join(ROOT, "boruix.iso"), "-boot", "order=d",
        "-m", "256", "-display", "none", "-serial", "file:" + ser,
        "-monitor", "tcp:127.0.0.1:%d,server,nowait" % port, "-no-reboot"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    sock = None
    for _ in range(80):
        try:
            sock = socket.create_connection(("127.0.0.1", port), timeout=2)
            break
        except OSError:
            time.sleep(0.5)
    mon = sock.makefile("rwb")
    def cmd(c, d=0.35):
        mon.write((c + chr(10)).encode()); mon.flush(); time.sleep(d)
        try: return mon.read1(262144) or b""
        except Exception: return b""
    def key(n, d=0.25): cmd("sendkey " + n, d)
    def typ(t2, d=0.25):
        for c in t2: key({" ": "spc", "/": "slash", "-": "minus", ".": "dot"}.get(c, c), d)
    def snap():
        try:
            with open(ser, "rb") as f: return f.read().decode("utf-8", "replace")
        except OSError: return ""
    ok = None
    try:
        dl = time.time() + 300
        while "username:" not in snap() and time.time() < dl: time.sleep(1)
        typ("alice"); key("ret", 2.0)
        time.sleep(1.5); typ("alicepw"); key("ret", 3.0)
        dl = time.time() + 60
        while "alice:/$" not in snap() and time.time() < dl: time.sleep(0.5)
        typ("/programs/spinburn.elf"); key("ret", 1.0); time.sleep(4.0)
        m = len(snap())
        for _ in range(5): key("ctrl-c", 1.0)
        time.sleep(10.0)
        key("ret", 2.0); time.sleep(3.0)
        ok = "alice:/$" in snap()[m:]
    except Exception as e:
        print("[v%d] EXC %s" % (i, e), flush=True)
    proc.kill()
    return ok

res = []
N = int(sys.argv[1]) if len(sys.argv) > 1 else 12
for i in range(N):
    r = run_once(i)
    res.append(r)
    print("[v%d] %s" % (i + 1, r), flush=True)
npass = sum(1 for x in res if x)
print("=== PASS %d / %d ===" % (npass, len(res)))
sys.exit(0 if npass == len(res) else 1)