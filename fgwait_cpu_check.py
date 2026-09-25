"""§6.13 归属判定实验：前台子进程阻塞时谁在烧 CPU。

三个场景，唯一变量是「前台子进程阻塞在什么上」：
  * shell idle                —— 无子进程（基线，应 ~6%）
  * blkdemo 阻塞读 stdin      —— 旧字节路径（KBD_WAITER）
  * evdemo  阻塞读事件节点     —— 事件路径（IN_EVENT_WAITER）

判据：若 blkdemo 与 evdemo **同为 ~100%**，则缺陷与事件流无关，
而属 `shell` 的前台等待循环（见 docs/TODO/terminal-input.md §6.13.3）。

**注意**：不要用 `spinburn` 做对照——它本身设计即忙等，是伪对照（§6.13.8）。

已知结论（2026-09-25）：shell 6.4% / blkdemo 100.0% / evdemo 99.6%。
**本脚本只测量、不修复**；§6.13 尚未修复。
"""
import os, socket, subprocess, time, re
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QEMU = os.path.join(ROOT, "envfiles", "tools", "qemu-stable", "qemu-9.2.0-win64", "qemu-system-x86_64.exe")
def run(port, ser, launch, label, waitfor, secs=10):
    try: os.remove(ser)
    except OSError: pass
    proc = subprocess.Popen([QEMU, "-cdrom", os.path.join(ROOT, "boruix.iso"), "-boot", "order=d",
        "-m", "256", "-display", "none", "-serial", "file:" + ser,
        "-monitor", "tcp:127.0.0.1:%d,server,nowait" % port, "-no-reboot"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    sock = None
    for _ in range(80):
        try:
            sock = socket.create_connection(("127.0.0.1", port), timeout=2); break
        except OSError: time.sleep(0.5)
    mon = sock.makefile("rwb")
    def cmd(c, d=0.30):
        mon.write((c + chr(10)).encode()); mon.flush(); time.sleep(d)
        try: return mon.read1(1 << 20) or b""
        except Exception: return b""
    def key(n, d=0.22): cmd("sendkey " + n, d)
    def snap():
        try:
            with open(ser, "rb") as f: return f.read().decode("utf-8", "replace")
        except OSError: return ""
    def cpu():
        p = subprocess.run(["powershell", "-NoProfile", "-Command",
            "(Get-Process -Id %d).TotalProcessorTime.TotalSeconds" % proc.pid],
            capture_output=True, text=True)
        try: return float(p.stdout.strip())
        except Exception: return -1.0
    dl = time.time() + 300
    while "username:" not in snap() and time.time() < dl: time.sleep(1)
    for ch in "alice": key(ch, 0.2)
    key("ret", 2.5)
    for ch in "alicepw": key(ch, 0.2)
    key("ret", 3.5)
    dl = time.time() + 60
    while "alice:/$" not in snap() and time.time() < dl: time.sleep(0.5)
    TYPE = {" ": "spc", "/": "slash", ".": "dot"}
    for ch in launch: key(TYPE.get(ch, ch), 0.16)
    key("ret", 3.0)
    if waitfor:
        dl = time.time() + 45
        while waitfor not in snap() and time.time() < dl: time.sleep(0.5)
    prev=-1
    for _ in range(25):
        cur=len(snap())
        if cur==prev: break
        prev=cur; time.sleep(1.0)
    c0=cpu(); t0=time.time(); time.sleep(secs); c1=cpu(); el=time.time()-t0
    print("[own] %-34s util=%.1f%%" % (label, 100.0*(c1-c0)/el))
    proc.kill(); time.sleep(1.5)
run(46040, os.path.join(ROOT,"_own_shell.txt"),   "",                    "shell idle (baseline)",        None)
run(46042, os.path.join(ROOT,"_own_blk.txt"),     "/programs/blkdemo.elf", "blkdemo fg: blocks on STDIN",  "[blkdemo] blocking")
run(46044, os.path.join(ROOT,"_own_ev.txt"),      "/programs/evdemo.elf",  "evdemo fg: blocks on EVENTS",  "[evdemo] R")