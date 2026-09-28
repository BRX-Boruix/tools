"""L-5 验收：`login` 口令回显抑制已启用，且**认证正确性不变**。

L-5 的目标（terminal-input.md §4.8）：
  * `login` 口令输入不回显；
  * **认证正确性不变**；
  * 真实 QEMU 交互验收。

与 L-3 脚本的分工（避免重复而且各自不足）：
  L-3 只证明「**正确**口令不回显且能登录**」。
  但「不回显」有一个平凡的假通过：**压根不读口令**（比如读空串）
  也不会回显。故本脚本补上反向对照：
  **错误口令必须被拒绝**，**正确口令必须被接受**——
  两者在**同一次运行、同一个 login 进程**里完成。

为何只试一次错误口令：`MAX_ATTEMPTS = 3`，而用完会触发
已登记的 **§6.6**（login 退出后 supervisor 重拉实例在首次堆分配时 panic）。
本脚本只用 1 次失败就转入正确口令，**故意避开那条路径**，
以免把两个缺陷混在一起而无法归因。§6.6 单独记账，不在本点修。
"""
import os
import socket
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
QEMU = os.path.join(ROOT, "envfiles", "tools", "qemu-stable",
                    "qemu-9.2.0-win64", "qemu-system-x86_64.exe")
PORT = int(os.environ.get("L5_MON_PORT", "45530"))
BOOT_WAIT = int(os.environ.get("L5_BOOT_WAIT", "420"))

USER_NAME = "alice"
GOOD_PW = "alicepw"
BAD_PW = "wrongpw"


def main():
    qemu = [
        QEMU,
        "-cdrom", os.path.join(ROOT, "boruix.iso"),
        "-hda", os.path.join(ROOT, "disk.img"),
        "-boot", "order=d",
        "-m", "256",
        "-display", "none",
        "-serial", "stdio",
        "-monitor", "tcp:127.0.0.1:%d,server,nowait" % PORT,
        "-no-reboot",
    ]
    proc = subprocess.Popen(qemu, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)
    buf = bytearray()

    def reader():
        while True:
            chunk = proc.stdout.read(1)
            if not chunk:
                return
            buf.extend(chunk)

    threading.Thread(target=reader, daemon=True).start()

    sock = None
    for _ in range(60):
        try:
            sock = socket.create_connection(("127.0.0.1", PORT), timeout=2)
            break
        except OSError:
            time.sleep(0.5)
    if sock is None:
        print("[l5] FAIL cannot reach QEMU monitor")
        proc.kill()
        return 1
    mon = sock.makefile("rwb")

    def key(name, delay=0.35):
        mon.write(("sendkey " + name + "\n").encode())
        mon.flush()
        time.sleep(delay)

    def type_str(text, delay=0.35):
        for ch in text:
            key({" ": "spc"}.get(ch, ch), delay)

    def snap():
        return bytes(buf).decode("utf-8", "replace")

    def wait_for(needle, timeout):
        deadline = time.time() + timeout
        while needle not in snap() and time.time() < deadline:
            time.sleep(0.5)
        return snap()

    checks = []

    def check(name, cond, detail=""):
        checks.append((name, bool(cond)))
        print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, detail))

    # 等到真的出现登录提示符，**而不是固定秒数**。
    # 内核开机会跑一次**自检**（selftest），耗时约 300s；
    # 固定 88s 会在自检还没跑完时就开始敲键，
    # 键入内容落进了自检输出里，登录流程根本没开始。
    # 故按「出现提示符」同步，并给足余量。
    print("[l5] waiting up to %ds for the login prompt ..." % BOOT_WAIT)
    deadline = time.time() + BOOT_WAIT
    while "username:" not in snap() and time.time() < deadline:
        time.sleep(1.0)

    wait_for("username:", 30.0)
    check("login_prompt_seen", "username:" in snap())

    # ---- 第一次：刻意输错口令 ----
    print("[l5] attempt 1: WRONG password (must be rejected, must not echo) ...")
    type_str(USER_NAME)
    key("ret", 1.5)
    wait_for("password:", 25.0)
    check("password_prompt_seen", "password:" in snap())

    before_bad = snap()
    bad_start = len(before_bad)
    type_str(BAD_PW)
    time.sleep(2.0)
    typed_bad = snap()[bad_start:]
    check("bad_password_not_echoed", BAD_PW not in typed_bad,
          "(wrong password was echoed while typing)")

    key("ret", 3.0)
    after_bad = wait_for("authentication failed", 30.0)
    check("wrong_password_rejected", "authentication failed" in after_bad,
          "(wrong password was ACCEPTED -> auth is broken)")
    check("wrong_password_never_echoed", BAD_PW not in after_bad,
          "(wrong password leaked to the screen)")

    # ---- 第二次：正确口令（同一个 login 进程）----
    # ---- 第二次：正确口令（同一 login 进程）----
    #
    # 注意：login 的失败重试回到的是 **username:** 提示符，不是 password:
    # （见 login/src/main.rs 的 while 循环——每轮从头开始）。
    # 若这里仍去等 "password:"，会命中**上一轮残留**的那一个，
    # 于是把口令当成用户名敲进去。本脚本第一版正是这么错的。
    print("[l5] attempt 2: CORRECT credentials ...")
    wait_for("username:", 25.0)
    type_str(USER_NAME)
    key("ret", 1.5)
    wait_for("password:", 25.0)
    good_start = len(snap())
    type_str(GOOD_PW)
    time.sleep(2.0)
    typed_good = snap()[good_start:]
    check("good_password_not_echoed", GOOD_PW not in typed_good,
          "(correct password was echoed while typing)")
    key("ret", 3.0)
    final = wait_for("welcome, alice", 40.0)
    check("correct_password_accepted", "login: welcome, alice" in final,
          "(correct password was REJECTED -> suppression broke auth)")
    check("shell_reached", "alice:/$" in final,
          "(did not land in the shell)")
    check("no_password_ever_leaked", GOOD_PW not in final and BAD_PW not in final,
          "(a password appeared somewhere in the serial stream)")

    print("[l5] serial bytes: %d" % len(final))
    failed = [c for c in checks if not c[1]]
    print("[l5] ---- %d/%d checks passed ----" % (len(checks) - len(failed),
                                                   len(checks)))
    proc.kill()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())