#!/usr/bin/env python3
"""I-EVENTS 阶段 2 端到端验收：真实按键 -> /devices/input/events -> libsys 转换层 -> 回显。

判据（全部来自串口真值，非构造）：
  1. evdemo 能 open 事件节点并读到记录（`[evdemo] R40` 这类行）；
  2. 真实按键被正确解码：a/e/c/h/o -> `[a]` `[e]` ...；
  3. 大写：Shift+a -> `[A]`（证明修饰键状态机与释放事件生效）；
  4. 回车 -> `[RET]`；退格 -> `[BS]`；
  5. 按 q 正常退出并打印 reads=/waits=。

**已知未决缺陷（见 docs/TODO/terminal-input.md §6.13）**：evdemo 阻塞期间宿主 CPU
约 99%（对照 shell 空闲 ~6%），用 QEMU monitor `stop`/`cont` 证明是 guest 在烧。
evdemo 本身无任何输出增长（真停住），故烧 CPU 的是内核事件阻塞路径本身。
本脚本只验功能正确性，**不**背书 CPU 行为。
"""
import os, socket, subprocess, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
QEMU = os.path.join(ROOT, "envfiles", "tools", "qemu-stable", "qemu-9.2.0-win64", "qemu-system-x86_64.exe")
PORT = 45980
SER = os.path.join(ROOT, "_evdemo_serial.txt")
try: os.remove(SER)
except OSError: pass
proc = subprocess.Popen([QEMU, "-cdrom", os.path.join(ROOT, "boruix.iso"), "-boot", "order=d",
    "-m", "256", "-display", "none", "-serial", "file:" + SER,
    "-monitor", "tcp:127.0.0.1:%d,server,nowait" % PORT, "-no-reboot"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
sock = None
for _ in range(80):
    try:
        sock = socket.create_connection(("127.0.0.1", PORT), timeout=2); break
    except OSError: time.sleep(0.5)
mon = sock.makefile("rwb")
def cmd(c, d=0.35):
    mon.write((c + chr(10)).encode()); mon.flush(); time.sleep(d)
    try: return mon.read1(262144) or b""
    except Exception: return b""
def key(n, d=0.25): cmd("sendkey " + n, d)
def snap():
    try:
        with open(SER, "rb") as f: return f.read().decode("utf-8", "replace")
    except OSError: return ""
dl = time.time() + 300
while "username:" not in snap() and time.time() < dl: time.sleep(1)
print("[ev] login prompt:", "username:" in snap())
for ch in "alice": key(ch, 0.2)
key("ret", 2.5)
for ch in "alicepw": key(ch, 0.2)
key("ret", 3.5)
dl = time.time() + 60
while "alice:/$" not in snap() and time.time() < dl: time.sleep(0.5)
print("[ev] shell ready:", "alice:/$" in snap())
TYPE = {" ": "spc", "/": "slash", ".": "dot", "-": "minus"}
for ch in "/programs/evdemo.elf":
    key(TYPE.get(ch, ch), 0.18)
key("ret", 2.5)
dl = time.time() + 30
while "evdemo] event-stream echo" not in snap() and time.time() < dl: time.sleep(0.5)
print("[ev] evdemo started:", "evdemo] event-stream echo" in snap())
for k in ["a", "e", "c", "h", "o"]:
    key(k, 0.45)
key("shift-a", 0.7)
key("ret", 0.7)
key("backspace", 0.7)
time.sleep(1.0)
# 按 q 退出，验证退出路径与 reads=/waits= 计数
key("q", 1.5)
dl = time.time() + 20
while "[evdemo] PASS" not in snap() and time.time() < dl: time.sleep(0.5)
time.sleep(1.0)
s = snap()
print("[ev] --- 回显序列 ---")
import re
print("   ", " ".join(re.findall(r"\[(RET|BS|ESC|[A-Za-z0-9])\]", s)))
print("[ev] --- 关键行 ---")
for l in s.split(chr(10)):
    if "reads=" in l or "PASS" in l or "FAIL" in l or "waited" in l: print("   ", l.strip()[:110])
print("[ev] evdemo PASS:", "[evdemo] PASS" in s)
proc.kill()