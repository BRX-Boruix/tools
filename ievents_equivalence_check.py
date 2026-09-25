#!/usr/bin/env python3
"""I-EVENTS **两路等价性基线**：字节路径（现状 stdin）与事件路径（libsys keymap）
对**同一按键序列**是否产出相同字节。

## 为什么需要这个脚本

ADR-045 §3 阶段 3 的验收标准含「键盘字符流经用户态转换后**与现行为等价**」。
"等价"必须有**可判定**的锚——本脚本就是那个锚：

    IRQ1 ─┬─ 轨道A(字节) ─> stdin_source ─> StdinNode ─> fd0 ─> shell 回显
          └─ 轨道B(事件) ─> /devices/input/events ─> libsys keymap ─> evdemo 回显

两侧喂**同一组按键**（含需 Shift 的大写），断言产出的字节**逐字节相同**。
阶段 3 落地后重跑本脚本：**三条判据仍须全绿**（那时轨道 A 已退役，
判据 A 改为对 console 对象读取），否则就是**行为回归**。

## 判据（全部来自串口真值，非构造数据）

  1. byte_path_matches_expected  —— 路径 A 产出 `aZ7 `
  2. event_path_matches_expected —— 路径 B 产出 `aZ7 ` + RET
  3. two_paths_equivalent        —— 两路一致（这才是「等价」本身）

## 实测（2026-09-25，两路一致）

    路径A: 'aZ7 '        路径B: 'aZ7 ' + RET        判定 3/3

## 踩过的坑（S09，留档）

首版路径 A 的解析**漏去 ANSI 转义**（`\x1b[K`），导致正则匹配不到重绘序列，
把「收到了 aZ7 」误报为**空字符串**。当时看似是「两路不一致」的**重大发现**，
实为**脚本缺陷**。修正解析后两路一致。
留档原因：与 §6.10.2 同类——**惊讶的结果先怀疑测量工具**，再怀疑被测系统。
"""
import os, socket, subprocess, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QEMU = os.path.join(ROOT, "envfiles", "tools", "qemu-stable", "qemu-9.2.0-win64", "qemu-system-x86_64.exe")

# 按键序列 -> QEMU 键名 (大写走 shift-x, 与人手同链路)
def qk(ch):
    if ch == " ": return "spc"
    if ch == "\n": return "ret"
    if ch.isupper(): return "shift-" + ch.lower()
    return ch

KEYS = ["a", "Z", "7", " ", "\n"]

def run_byte_path():
    """路径A: shell 从 fd0 读字节并回显 -> 取回显的最终命令行."""
    ser = os.path.join(ROOT, "_eq_byte.txt")
    try: os.remove(ser)
    except OSError: pass
    proc = subprocess.Popen([QEMU, "-cdrom", os.path.join(ROOT, "boruix.iso"), "-boot", "order=d",
        "-m", "256", "-display", "none", "-serial", "file:" + ser,
        "-monitor", "tcp:127.0.0.1:46200,server,nowait", "-no-reboot"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    sock = None
    for _ in range(80):
        try:
            sock = socket.create_connection(("127.0.0.1", 46200), timeout=2); break
        except OSError: time.sleep(0.5)
    mon = sock.makefile("rwb")
    def cmd(c, d=0.3):
        mon.write((c + chr(10)).encode()); mon.flush(); time.sleep(d)
        try: return mon.read1(1 << 20) or b""
        except Exception: return b""
    def key(n, d=0.3): cmd("sendkey " + n, d)
    def snap():
        try:
            with open(ser, "rb") as f: return f.read().decode("utf-8", "replace")
        except OSError: return ""
    dl = time.time() + 300
    while "username:" not in snap() and time.time() < dl: time.sleep(1)
    for ch in "alice": key(ch, 0.2)
    key("ret", 2.5)
    for ch in "alicepw": key(ch, 0.2)
    key("ret", 3.5)
    dl = time.time() + 60
    while "alice:/$" not in snap() and time.time() < dl: time.sleep(0.5)
    mark = len(snap())
    for ch in KEYS: key(qk(ch), 0.35)
    time.sleep(1.5)
    seg = snap()[mark:]
    proc.kill(); time.sleep(1.0)
    # 逐次重绘取**累积输入**: 每次击键 libline 都重绘 "alice:/$ <buf>\r".
    # 必须先去 ANSI 转义, 否则匹配不到(实测踩过: 漏去转义导致误判为"空")。
    clean = seg.replace("\x1b[K", "")
    seq = [m.group(1) for m in __import__("re").finditer(r"alice:/\$ ([a-zA-Z0-9 ]*)\r", clean)]
    seq = [x for x in seq if x != ""]
    return seq[-1] if seq else ""

def run_event_path():
    """路径B: evdemo 经 libsys keymap 转字节并回显 ([a] [A] ...)。"""
    ser = os.path.join(ROOT, "_eq_ev.txt")
    try: os.remove(ser)
    except OSError: pass
    proc = subprocess.Popen([QEMU, "-cdrom", os.path.join(ROOT, "boruix.iso"), "-boot", "order=d",
        "-m", "256", "-display", "none", "-serial", "file:" + ser,
        "-monitor", "tcp:127.0.0.1:46202,server,nowait", "-no-reboot"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    sock = None
    for _ in range(80):
        try:
            sock = socket.create_connection(("127.0.0.1", 46202), timeout=2); break
        except OSError: time.sleep(0.5)
    mon = sock.makefile("rwb")
    def cmd(c, d=0.3):
        mon.write((c + chr(10)).encode()); mon.flush(); time.sleep(d)
        try: return mon.read1(1 << 20) or b""
        except Exception: return b""
    def key(n, d=0.3): cmd("sendkey " + n, d)
    def snap():
        try:
            with open(ser, "rb") as f: return f.read().decode("utf-8", "replace")
        except OSError: return ""
    dl = time.time() + 300
    while "username:" not in snap() and time.time() < dl: time.sleep(1)
    for ch in "alice": key(ch, 0.2)
    key("ret", 2.5)
    for ch in "alicepw": key(ch, 0.2)
    key("ret", 3.5)
    dl = time.time() + 60
    while "alice:/$" not in snap() and time.time() < dl: time.sleep(0.5)
    for ch in "/programs/evdemo.elf": key({" ": "spc", "/": "slash", ".": "dot"}.get(ch, ch), 0.18)
    key("ret", 3.0)
    dl = time.time() + 30
    while "[evdemo]" not in snap() and time.time() < dl: time.sleep(0.5)
    mark = len(snap())
    for ch in KEYS: key(qk(ch), 0.35)
    time.sleep(1.5)
    seg = snap()[mark:]
    key("q", 1.0)
    proc.kill(); time.sleep(1.0)
    import re
    toks = re.findall(r"\[([^\]]*)\]", seg)
    # 串口里混有其它组件的 [xxx] 行, 只保留 evdemo 的键回显
    NOISE = {"audio", "init", "vfs", "evdemo", "driver_hub", "pci", "uio", "syscall", "terminal", "kdbg-peek"}
    toks = [x for x in toks if x not in NOISE and not x.startswith("audio") and not x.startswith("init")]
    return toks

print("=== 两路等价性对照 ===")
print("按键序列: %r" % "".join(KEYS))
a = run_byte_path()
print("路径A 字节路径(现状 stdin) 回显: %r" % a)
b = run_event_path()
print("路径B 事件路径(libsys keymap) tokens: %r" % b)
print("")
# 判据: 两路对同一按键序列产出**相同字节**
expected = "aZ7 "
a_bytes = a
b_bytes = "".join("<RET>" if x == "RET" else x for x in b)
print("路径A 字节: %r" % a_bytes)
print("路径B 字节: %r" % b_bytes)
ok_a = (a_bytes == expected)
ok_b = (b_bytes == expected + "<RET>")
print("")
print("  [%s] byte_path_matches_expected" % ("PASS" if ok_a else "FAIL"))
print("  [%s] event_path_matches_expected" % ("PASS" if ok_b else "FAIL"))
print("  [%s] two_paths_equivalent" % ("PASS" if ok_a and ok_b else "FAIL"))
print("")
print("[eq] ---- %d/3 ----" % (int(ok_a) + int(ok_b) + int(ok_a and ok_b)))