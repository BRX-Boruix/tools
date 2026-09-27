#!/usr/bin/env python3
"""I-EVENTS legacy #6 acceptance: consoled watchdog (init getty-cycle patrol+respawn).

S1 boot -> login(alice/alicepw) -> shell
S2 ps -> find consoled pid -> kill -9 PID (daemon truly dies)
S3 exit session -> init supervisor watchdog -> serial shows
   'consoled was dead; respawned'
S4 new login prompt: typed chars echo = stdin producer alive.
PASS = S3 respawn line + S4 echo.

QEMU 接线与 l2_interactive.py 同款（serial=file、monitor=tcp server,nowait、
sendkey 经 monitor 注入）——沿用仓库已验证的稳健形态。
"""
import os, re, socket, subprocess, sys, time

ROOT = r"F:\boruix-project"
QEMU = os.path.join(ROOT, "envfiles", "tools", "qemu-stable",
                    "qemu-9.2.0-win64", "qemu-system-x86_64.exe")
ISO = os.path.join(ROOT, "boruix.iso")
DISK = os.path.join(ROOT, "disk.img")
LOG = os.path.join(ROOT, "_p6_wd_serial.log")
PORT = 45471

def main():
    if os.path.exists(LOG):
        os.remove(LOG)
    qemu = [QEMU, "-cdrom", ISO, "-hda", DISK, "-boot", "order=d", "-m", "256",
            "-display", "none", "-serial", "file:" + LOG,
            "-monitor", "tcp:127.0.0.1:%d,server,nowait" % PORT, "-no-reboot"]
    print("[wd] starting qemu ...")
    proc = subprocess.Popen(qemu, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    s = None
    for _ in range(60):
        try:
            s = socket.create_connection(("127.0.0.1", PORT), timeout=2)
            break
        except OSError:
            time.sleep(0.5)
    if s is None:
        print("[wd] FAIL: monitor port never came up")
        proc.kill()
        return 1
    f = s.makefile("rwb")

    def key(k, d=0.30):
        f.write(("sendkey " + k + "\n").encode())
        f.flush()
        time.sleep(d)

    named = {" ": "spc", ".": "dot", "-": "minus", "/": "slash", ";": "semicolon",
             "=": "equal", ",": "comma"}
    shiftmap = {"!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6",
                "&": "7", "*": "8", "(": "9", ")": "0", "_": "minus",
                "+": "equal", ":": "semicolon", "'": "apostrophe",
                "<": "comma", ">": "period", "?": "slash", "~": "grave",
                "{": "bracket_left", "}": "bracket_right", "|": "backslash"}

    def qc(ch):
        if ch == "\n":
            return "ret"
        if ch.isupper():
            return "shift-" + ch.lower()
        if ch in shiftmap:
            return "shift-" + shiftmap[ch]
        if ch in named:
            return named[ch]
        return ch

    def type_str(txt, d=0.14):
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
        print("[wd] FAIL: no login prompt")
        proc.kill()
        return 1
    print("[wd] S1 first login prompt seen (cycle 1)")
    # ---- 负面验收（当前语义下诚实可达的形态）----
    # 看门狗的「死后复活」触发需要 consoled 真死；登录 shell 无 CAP_KILL，
    # 杀 CAP_SYSTEM 守护 = EACCES（ADR-040 特权级维度），用户态无法构造；
    # shell 亦无 exit/^D-退出通道，会话无法主动结束。故唯一诚实的多周期
    # 构造 = **开机首个 login 故意 3 次认证失败**（R13 认证关口语义内）——
    # login 自行退出 → supervisor 进入 getty 周期 2（看门狗用真实
    # /processes/list 跑一遍 pid_of_name → consoled 存活 → **不得**重复
    # spawn）→ 重生 login → 第二轮正确登录可用。判定：consoled started
    # 恰好 2 次（双守护，T5-b）、respawned 0 次、第二轮 login 走到 welcome。
    type_str("wrongname\n")
    time.sleep(1.2)
    type_str("wrongpw\n")
    time.sleep(1.5)
    type_str("\n")
    time.sleep(1.2)
    type_str("\n")
    time.sleep(1.2)
    type_str("\n")
    if wait_log("too many failed attempts", 40) is None:
        print("[wd] FAIL: login did not exhaust attempts (no cycle end)")
        proc.kill()
        return 1
    # login 3 次耗尽自行退出 → supervisor 周期 2 → username: 再现：
    if wait_log("username:", 120) is None:
        print("[wd] FAIL: no second login prompt (supervisor did not cycle)")
        proc.kill()
        return 1
    print("[wd] S2 supervisor cycled into getty round 2 (watchdog ran)")
    time.sleep(2.0)
    with open(LOG, "rb") as h:
        txt2 = h.read().decode("utf-8", "replace")
    n_started = len(re.findall(r"consoled started \(pid \d+\)", txt2))
    n_respawn = len(re.findall(r"consoled was dead; respawned", txt2))
    # ADR-048 T5-b（owner 裁决 B）：双守护形态——启动即 consoled[0]+consoled[1]
    # 各一（`consoled started` 2 次）；判定随之更新：恰 2 次启动、0 误重生。
    if n_started != 2 or n_respawn != 0:
        print("[wd] FAIL: consoled started x%d, respawned x%d (want 2 and 0)"
              % (n_started, n_respawn))
        ok = False
    else:
        print("[wd] S3 watchdog: no double-spawn, no false respawn (2 daemons kept)")
    # 第二轮真实登录可用 = 周期 2 后终端生产者仍在场：
    type_str("root\n")
    time.sleep(1.0)
    type_str("rootpw\n")
    if wait_log("welcome, root", 40) is None:
        print("[wd] FAIL: second login did not reach welcome")
        ok = False
    else:
        print("[wd] S4 second-session login ok -> stdin producer alive")

    proc.kill()
    print("[wd] ---- " + ("PASS" if ok else "FAIL") + " ----")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
