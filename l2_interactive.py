#!/usr/bin/env python3
"""L-2 真实 QEMU 交互验收：经 login 认证后，向交互 shell 注入真实 PS/2 按键。

# 为何必须这样做（S39 不伪造证据 / ADR-046 §4 条 4）

shell 的 stdin 唯一来源是 PS/2 键盘队列（kernel/src/main.rs:1139 `stdin_source`
只认 `ps2-keyboard`，回退路径也走同一个 arch 队列），**没有**注入 API，
也不能靠 `init --run=` 驱动（`--run=` 直接 exec_path 一条命令行，**不进 REPL**）。
故「交互不回归」只能通过**真实按键**验证。

本脚本走 QEMU monitor 的 `sendkey`：注入的是**真实 PS/2 扫描码**，
经 i8042 → IRQ1 → 内核键盘驱动 → stdin 的完整硬件路径，与人手按键同链路。

# 前置：先过 login

正常启动路径下 init 先 exec login 作认证关口（ADR-041）。种子账户见
kernel/crates/kernel/src/vfs_init.rs:1154：alice/alicepw。
"""
import os
import socket
import subprocess
import sys
import time

ROOT = r"F:\boruix-project"
QEMU = os.path.join(ROOT, "envfiles", "tools", "qemu-stable",
                    "qemu-9.2.0-win64", "qemu-system-x86_64.exe")
ISO = os.path.join(ROOT, "boruix.iso")
DISK = os.path.join(ROOT, "disk.img")
LOG = os.path.join(ROOT, "_l2_serial.log")
PORT = 45461

BOOT_WAIT = float(os.environ.get("L2_BOOT_WAIT", "90"))


def main():
    if os.path.exists(LOG):
        os.remove(LOG)
    qemu = [QEMU, "-cdrom", ISO, "-hda", DISK, "-boot", "order=d", "-m", "256",
            "-display", "none", "-serial", "file:" + LOG,
            "-monitor", "tcp:127.0.0.1:%d,server,nowait" % PORT, "-no-reboot"]
    print("[l2] starting qemu ...")
    proc = subprocess.Popen(qemu, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    s = None
    for _ in range(60):
        try:
            s = socket.create_connection(("127.0.0.1", PORT), timeout=2)
            break
        except OSError:
            time.sleep(0.5)
    if s is None:
        print("[l2] FAIL: monitor port never came up")
        proc.kill()
        return 1
    f = s.makefile("rwb")

    def key(k, d=0.30):
        f.write(("sendkey " + k + "\n").encode())
        f.flush()
        time.sleep(d)

    def type_str(txt, d=0.14):
        for ch in txt:
            key({" ": "spc", "|": "backslash"}.get(ch, ch), d)

    def snap():
        try:
            return open(LOG, "rb").read().decode("utf-8", "replace")
        except OSError:
            return ""

    # 等到真的出现登录提示符，而不是固定秒数（§6.10）。
    # selftest.py 会把 boruix.iso 换成自检镜像（开机跑约 300s 自检、永远不进 login），
    # 固定秒数会让键敲进自检输出里——症状像「代码坏了」，实为测试环境被上一步改坏了。
    # 轮询下若镜像被换过，会在 BOOT_WAIT 后**如实失败**，而不是把键喂给自检输出。
    print("[l2] waiting up to %ds for the login prompt ..." % BOOT_WAIT)
    _deadline = time.time() + BOOT_WAIT
    while "username:" not in snap() and time.time() < _deadline:
        time.sleep(1.0)
    if "username:" not in snap():
        print("[l2] FAIL: login prompt never appeared in %ds" % BOOT_WAIT)
        print("[l2]        (did you run selftest.py? it replaces boruix.iso with the")
        print("[l2]         selftest image, which boots straight into ~300s of tests)")
        print("[l2]        rebuild the normal image first:  python main.py build")
        proc.kill()
        return 1

    # ---- 先过 login：username / password ----
    print("[l2] authenticating as alice ...")
    type_str("alice")
    key("ret")
    time.sleep(0.6)
    type_str("alicepw")
    key("ret")
    time.sleep(3.0)

    results = {}
    marks = {}

    # ---- 场景 1：输入 + 回车执行 ----
    print("[l2] scenario 1: 'echo hi' + Enter")
    type_str("echo hi")
    key("ret")
    time.sleep(2.0)
    marks["s1"] = snap()

    # ---- 场景 2：上翻历史（CSI 编辑路径） ----
    print("[l2] scenario 2: Up arrow then Enter")
    key("up")
    time.sleep(0.8)
    key("ret")
    time.sleep(2.0)
    marks["s2"] = snap()

    # ---- 场景 3：Tab 补全 ----
    print("[l2] scenario 3: 'ec' + Tab")
    type_str("ec")
    key("tab")
    time.sleep(1.0)
    # Tab 已把 'ec' 补成 'echo '（**带尾空格**，命令位契约），故这里不再加空格。
    # 旧脚本多打一个空格得到 'echo  tabtest'，那是**脚本**的错，不是 Tab 没生效。
    type_str("tabtest")
    key("ret")
    time.sleep(2.0)
    marks["s3"] = snap()

    # ---- 场景 4：退格 ----
    print("[l2] scenario 4: 'echoZ' + Backspace + 'X' + Enter")
    type_str("echoZ")
    key("backspace")
    time.sleep(0.5)
    # 退格后再输一个可观察字符：若退格生效，Z 应消失。
    # （不断言精确长度——monitor 的 sendkey 可能自动重复，那是注入工具的行为，不是 shell 的。）
    type_str("end")
    key("ret")
    time.sleep(2.5)
    marks["s4"] = snap()

    proc.kill()
    try:
        proc.wait(timeout=10)
    except Exception:
        pass

    full = snap()
    print("[l2] serial bytes: %d" % len(full))

    checks = []

    def check(name, cond, detail=""):
        checks.append((name, bool(cond)))
        print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, detail))

    # login 必须真的成功。判据要能**区分**成败：
    #   成功 -> login 打印 "welcome, alice" 且 shell 打印 "BORUIX shell"
    #   失败 -> login 打印 "authentication failed" 并回到 "username:"
    # 只查 "alice" 是不够的（用户名本身回显里就有 alice），故必须查欢迎语。
    check("login_succeeded", "login: welcome, alice" in full,
          "(no 'welcome' line -> authentication did not pass)")
    check("shell_started", "BORUIX shell (PID 2)" in full,
          "(login passed but shell never started)")
    check("shell_prompt_seen", "alice:/$" in full,
          "(shell prompt 'user:cwd$' not on serial)")

    s1 = marks.get("s1", "")
    s2 = marks.get("s2", "")
    s3 = marks.get("s3", "")
    s4 = marks.get("s4", "")

    # 场景 1：命令行被回显，且执行后 shell 打印了新提示符
    check("s1_line_echoed", "echo hi" in s1)
    # 执行后应回到新提示符：'$ ' 出现次数比"仅回显"时更多
    check("s1_new_prompt_after", s1.count("alice:/$") >= 2,
          "(prompt count=%d, need >=2: one before, one after)" % s1.count("alice:/$"))

    # 场景 2：上翻后命令再次出现在屏幕上（证明历史被召回）
    check("s2_history_recall", s2.count("echo hi") >= 2,
          "(echo hi count=%d, need >=2)" % s2.count("echo hi"))

    # 场景 3：Tab 把 'ec' 补成 'echo'，故最终命令是 'echo tabtest'
    check("s3_tab_completed", "echo tabtest" in s3,
          "(no literal 'echo tabtest' -> Tab did not expand 'ec')")

    # 场景 4：退格删掉 Z，故是 'echo ok' 而非 'echoZ ok'
    # 退格后缓冲区应为 'echo'，故执行的是 echo。关键证据：Z 不在最终命令里。
    check("s4_backspace_removed_Z", "echoZ" not in s4, "(stray Z still present -> backspace broken)")

    failed = [c for c in checks if not c[1]]
    print("[l2] ---- %d/%d checks passed ----" % (len(checks) - len(failed), len(checks)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
