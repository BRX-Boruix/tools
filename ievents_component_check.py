#!/usr/bin/env python3
"""I-EVENTS 组件验收：`libline::EventSource` 的真机行为。

## 为什么需要这个脚本

阶段 2 交付了 `libline::EventSource`——行编辑库的事件流输入源。但 `evdemo`
（阶段 2 的验收程序）明确是**诊断形态**：它「绕开 `libline::EventSource`，
直接 open → read → parse_record → feed」。故 `EventSource` **本身**
此前只被**宿主单测**覆盖（libline 的 `test_event_source_*`），
**从未**在真实内核上跑过。

这在阶段 3 变成实际风险：阶段 3 的「最小形态」正是让 `shell`/`login`
改用 `EventSource`。宿主单测**测不到**真机上的阻塞语义、事件环分片、
以及 `read_into` 与内核 `-EAGAIN` 哨兵的配合。

本脚本用 `evsrcdemo`（**组件路径**）补上该缺口。

## **当前状态：0/10 —— 组件有阻塞缺陷（2026-09-25 实测）**

本脚本**故意**保持 0/10 通过率并提交：它记录的是一个**真实缺陷**，
不是测试写错。已确证（详见 docs/TODO/terminal-input.md §6.14.4g）：

  * `EventSource::open()` 成功（`component_opens` 这一条 **PASS**）；
  * **内核**侧事件节点阻塞语义**正常**——探针 drain 到环空后确实阻塞；
  * `refill()` 在环空时**立即返回 false**，违反其「阻塞到有数据」契约，
    导致按键无法唤醒消费者。

**修复后本脚本应转为全绿**；在那之前它是缺陷的**可复现证据**（S09）。

## 判据（全部来自串口真值）

  1. `component_opens`      —— `EventSource::open()` 成功
  2. `letters_decoded`      —— a/e/c/h/o 解出对应 `[CHAR x]`
  3. `shift_uppercase`      —— Shift+a 解出 `[CHAR A]`（修饰键状态机）
  4. `submit`               —— 回车解出 `[SUBMIT]`
  5. `backspace`            —— 退格解出 `[BACKSPACE]`
  6. `blocking_semantics`   —— `wouldblock` 计数为 0（阻塞读生效，非自旋）
  7. `clean_exit`           —— 按 q 后打印 PASS 与统计

## 与 evdemo 的关系（互补，不重复）

  evdemo     : 手搓 open/read/parse/feed —— 测「数据链本身对不对」
  evsrcdemo  : 用 libline::EventSource    —— 测「**组件**封得对不对」

两者都过，才说明阶段 3 可以放心把 shell/login 切到组件路径。
"""
import os, re, socket, subprocess, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QEMU = os.path.join(ROOT, "envfiles", "tools", "qemu-stable", "qemu-9.2.0-win64", "qemu-system-x86_64.exe")
PORT = 46300
SER = os.path.join(ROOT, "_evsrc_serial.txt")


def qk(ch):
    """ASCII -> QEMU QKeyCode 名。

    **陷阱（本项目踩过）**：QEMU `sendkey` **只接受小写 QKeyCode 名**，
    大写字母会被静默拒绝（`invalid parameter: A`），且**错误不会到串口**。
    大写必须用 `shift-a` 形式注入，这也更贴近人手输入。
    """
    if ch == " ": return "spc"
    if ch == "\n": return "ret"
    if ch == "\x7f": return "backspace"
    if ch.isupper(): return "shift-" + ch.lower()
    return ch


def main():
    try: os.remove(SER)
    except OSError: pass
    proc = subprocess.Popen([QEMU, "-cdrom", os.path.join(ROOT, "boruix.iso"),
        "-boot", "order=d", "-m", "256", "-display", "none",
        "-serial", "file:" + SER,
        "-monitor", "tcp:127.0.0.1:%d,server,nowait" % PORT, "-no-reboot"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    sock = None
    for _ in range(80):
        try:
            sock = socket.create_connection(("127.0.0.1", PORT), timeout=2); break
        except OSError: time.sleep(0.5)
    if sock is None:
        print("[evsrc] FAIL: QEMU monitor 未就绪"); proc.kill(); return 1
    mon = sock.makefile("rwb")

    def cmd(c, d=0.3):
        mon.write((c + chr(10)).encode()); mon.flush(); time.sleep(d)
        try: return mon.read1(1 << 20) or b""
        except Exception: return b""

    def key(n, d=0.3): cmd("sendkey " + n, d)

    def snap():
        try:
            with open(SER, "rb") as f: return f.read().decode("utf-8", "replace")
        except OSError: return ""

    def wait_for(pat, timeout):
        dl = time.time() + timeout
        while time.time() < dl:
            if pat in snap(): return True
            time.sleep(0.5)
        return False

    try:
        # 登录
        if not wait_for("username:", 300):
            print("[evsrc] FAIL: 未到 login"); return 1
        for ch in "alice": key(qk(ch), 0.2)
        key("ret", 2.5)
        for ch in "alicepw": key(qk(ch), 0.2)
        key("ret", 3.5)
        if not wait_for("alice:/$", 60):
            print("[evsrc] FAIL: 未到 shell"); return 1

        # 启动组件路径程序。
        # **先发 ^C 清空 shell 行缓冲**：上一轮若残留字符（实测踩过：
        # evdemo 退出后遗留 "abq"），后续路径会被拼成 "abq/programs/..." 而 ENOENT。
        # 这是**测试脚本**纪律，不是被测系统问题。
        key("ctrl-c", 0.5)
        key("ret", 0.5)
        for ch in "/programs/evsrcdemo.elf":
            key({" ": "spc", "/": "slash", ".": "dot"}.get(ch, qk(ch)), 0.16)
        key("ret", 3.0)
        if not wait_for("[evsrcdemo] open ok", 30):
            print("[evsrc] FAIL: evsrcdemo 未启动或 open 失败")
            print(snap()[-800:]); return 1
        print("  [PASS] component_opens")

        # **等程序真正阻塞下来**再按键（时序纪律，非组件缺陷）。
        # 理由：启动程序的路径字符（"/programs/evsrcdemo.elf"）**也进了事件环**，
        # 组件首次读取会先消费这段积压。若此刻就判定判据，会误报「按键无效」。
        # 这是**测试时序**问题，不是组件问题——故此处等待而非改判据。
        time.sleep(2.5)

        # 打按键: a e c h o, Shift+A, 回车, 退格, q
        mark = len(snap())
        for ch in "aecho":
            key(qk(ch), 0.35)
        key("shift-a", 0.4)
        key("ret", 0.4)
        key("backspace", 0.4)
        time.sleep(1.0)
        seg = snap()[mark:]
        key("q", 1.0)
        time.sleep(1.5)
        full = snap()[mark:]

        # 逐条判据
        checks = []
        for ch in "aecho":
            checks.append(("char_" + ch, ("[CHAR %s]" % ch) in seg))
        checks.append(("shift_uppercase_A", "[CHAR A]" in seg))
        checks.append(("submit", "[SUBMIT]" in seg))
        checks.append(("backspace", "[BACKSPACE]" in seg))

        m = re.search(r"chars=(\d+) wouldblock=(\d+)", full)
        if m:
            chars, wb = int(m.group(1)), int(m.group(2))
            checks.append(("blocking_semantics", wb == 0))
        else:
            chars, wb = -1, -1
            checks.append(("blocking_semantics", False))
        checks.append(("clean_exit", "[evsrcdemo] PASS" in full))

        print("")
        for name, ok in checks:
            print("  [%s] %s" % ("PASS" if ok else "FAIL", name))
        npass = sum(1 for _, ok in checks if ok)
        print("")
        print("[evsrc] ---- %d/%d ----" % (npass, len(checks)))
        if chars >= 0:
            print("[evsrc] chars=%d wouldblock=%d" % (chars, wb))
        return 0 if npass == len(checks) else 1
    finally:
        try: proc.kill()
        except Exception: pass
        time.sleep(0.8)
        if os.environ.get("KEEP_SER"):
            print("[evsrc] serial kept at " + SER)
        else:
            try: os.remove(SER)
            except OSError: pass


if __name__ == "__main__":
    raise SystemExit(main())
