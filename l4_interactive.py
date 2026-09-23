"""L-4 / T-CTRL-C 验收：`^C` 投递 `SIGINT` 给**shell 自己 spawn 的 child**。

验收要求（ADR-046 §1.2、terminal-input.md §4.7）：
  * QEMU 中 shell 前台任务可被 `^C` 中断并**回到提示符**；
  * 内核侧**零改动**（无新增 syscall、无模式开关）。

为何必须真实按键：验收定义的就是「人手按 Ctrl-C」这一动作。
用 QEMU monitor 的 `sendkey ctrl-c` 注入**真实 PS/2 扫描码**，
经 i8042 → IRQ1 → 内核键盘驱动 → stdin，与真人按键同一条硬件路径。

用例：
  1. `spinburn` 是一个**真实 ELF**（永不自行退出的空转+睡眠循环），
     经 `exec_path` 派生为**前台子进程**；
  2. 等它真正跑起来（看到 `[spinburn] start`）；
  3. 按 `^C`；
  4. **断言它被中断、回到 `alice:/$` 提示符**。

  反向对照（同一次运行）：在按 `^C` **之前**，必须先确认
  子进程**还在跑**（提示符尚未回来）——否则「它自己结束了」会被
  误认为「Ctrl-C 生效了」。
"""
import os
import socket
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QEMU = os.path.join(ROOT, "envfiles", "tools", "qemu-stable",
                    "qemu-9.2.0-win64", "qemu-system-x86_64.exe")
PORT = int(os.environ.get("L4_MON_PORT", "45520"))
BOOT_WAIT = int(os.environ.get("L4_BOOT_WAIT", "300"))


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
        print("[l4] FAIL cannot reach QEMU monitor")
        proc.kill()
        return 1
    mon = sock.makefile("rwb")

    def key(name, delay=0.35):
        mon.write(("sendkey " + name + "\n").encode())
        mon.flush()
        time.sleep(delay)

    def type_str(text, delay=0.35):
        for ch in text:
            # 注意：QEMU `sendkey` 用的是键**名**，不是字符**面值**。
            # `.` `-` `/` 等符号键必须映射，否则 sendkey 会被拒而字符丢失——
            # 本脚本曾因未映射 `.` 而把 `/programs/spinburn.elf` 打成
            # `/programs/spinburnelf`，误报 ENOENT。
            key({" ": "spc", "/": "slash", "-": "minus", ".": "dot",
                 "_": "shift-minus"}.get(ch, ch), delay)

    def snap():
        return bytes(buf).decode("utf-8", "replace")

    checks = []

    def check(name, cond, detail=""):
        checks.append((name, bool(cond)))
        print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, detail))

    # 等到真的出现登录提示符，而不是固定秒数（§6.10）。
    # selftest.py 会把 boruix.iso 换成自检镜像（开机跑约 300s 自检、永远不进 login），
    # 固定秒数会让键敲进自检输出里——症状像「代码坏了」，实为测试环境被上一步改坏了。
    print("[l4] waiting up to %ds for the login prompt ..." % BOOT_WAIT)
    _deadline = time.time() + BOOT_WAIT
    while "username:" not in snap() and time.time() < _deadline:
        time.sleep(1.0)

    # --- 登录（L-3 已验证的路径） ---
    deadline = time.time() + 30.0
    while "username:" not in snap() and time.time() < deadline:
        time.sleep(0.5)
    check("login_prompt_seen", "username:" in snap())
    type_str("alice")
    key("ret", 1.5)
    deadline = time.time() + 25.0
    while "password:" not in snap() and time.time() < deadline:
        time.sleep(0.5)
    check("password_prompt_seen", "password:" in snap())
    type_str("alicepw")
    key("ret", 3.0)
    deadline = time.time() + 40.0
    while "alice:/$" not in snap() and time.time() < deadline:
        time.sleep(0.5)
    check("shell_ready", "alice:/$" in snap(), "(could not reach the shell)")

    # --- 前置校验：spinburn 存在 ---
    print("[l4] checking that spinburn exists ...")
    type_str("ls /programs", 0.25)
    key("ret", 3.0)
    listing = snap()
    if os.environ.get("L4_DUMP"):
        print("[l4][dump-after-ls]")
        print(repr(listing[-600:]))
    check("spinburn_available", "spinburn.elf" in listing,
          "(no spinburn ELF -> cannot test a real foreground child)")

    # --- 启动真实前台子进程 ---
    print("[l4] starting spinburn as a FOREGROUND child ...")
    # 必须写完整路径：不含 `/` 的词被 `classify_command` 判为 Builtin，
    # 压根不会走 VFS 路径装载。编译期产物就叫 `spinburn.elf`（带扩展名），
    # 所以必须写全路径。
    type_str("/programs/spinburn.elf", 0.3)
    key("ret", 3.0)
    deadline = time.time() + 25.0
    while "[spinburn] start" not in snap() and time.time() < deadline:
        time.sleep(0.5)
    started = snap()
    if os.environ.get("L4_DUMP"):
        print("[l4][dump-after-spinburn]")
        print(repr(started[-700:]))
    check("child_started", "[spinburn] start" in started,
          "(foreground child did not start)")

    # --- 反向对照：此刻它必须**还在跑** ---
    tail_before = started[started.rfind("[spinburn] start"):]
    check("child_still_running_before_ctrl_c",
          "alice:/$" not in tail_before,
          "(prompt already back -> the child ended on its own; a later Ctrl-C "
          "would prove nothing)")

    # --- 真实 Ctrl-C ---
    print("[l4] sending REAL Ctrl-C ...")
    key("ctrl-c", 3.0)
    deadline = time.time() + 30.0
    final = snap()
    while "alice:/$" not in final[final.rfind("[spinburn] start"):] \
            and time.time() < deadline:
        time.sleep(0.5)
        final = snap()
    after = final[final.rfind("[spinburn] start"):]
    check("prompt_back_after_ctrl_c", "alice:/$" in after,
          "(Ctrl-C did not bring the prompt back)")

    # --- 信号真的到了子进程：应有 SIGINT 记录 ---
    check("sigint_reported", "SIGINT" in after or "signal" in after.lower(),
          "(no SIGINT mention in the kernel/shell output)")

    # --- shell 自己没被杀（目标必须是 child，不是自己） ---
    print("[l4] verifying the shell survived and still works ...")
    type_str("echo alive", 0.3)
    key("ret", 3.0)
    tail = snap()[snap().rfind("[spinburn] start"):]
    check("shell_survived_and_works", "alive" in tail,
          "(shell did not run the follow-up command)")

    print("[l4] serial bytes: %d" % len(final))
    # 诊断增强：把完整串口落盘（此前只有脚本自身的 [l4] 行，
    # 真出问题时无法回看内核/用户态到底输出了什么）。环境变量
    # L4_DUMP 指定路径；未设则默认写到当前目录 l4_serial.txt。
    dump_path = os.environ.get("L4_DUMP", "l4_serial.txt")
    try:
        with open(dump_path, "wb") as f:
            f.write(final.encode("utf-8", "replace"))
        print("[l4] serial dumped to %s" % dump_path)
    except OSError as e:
        print("[l4] WARN cannot dump serial: %s" % e)
    failed = [c for c in checks if not c[1]]
    print("[l4] ---- %d/%d checks passed ----" % (len(checks) - len(failed),
                                                   len(checks)))
    proc.kill()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())