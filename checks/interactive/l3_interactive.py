"""L-3 验收：login 回显抑制（ADR-046 决策 3）。

为何必须真实按键：login 的 stdin 唯一来源是 PS/2 键盘队列，
无注入 API；且「口令回显是否关闭」本质上是一个「屏幕上能
看到什么」的问题，构造数据根本无法回答。

为何用 -serial stdio 而不是 -serial file：
  QEMU 的 -serial file: 在运行期**不刷新**（实测：静止 16s 文件大小
  一字不变），只有进程退出时才整块落盘。任何「输入后立即看屏幕」
  的断言都会读到陈旧内容而误判。-serial stdio 把串口接到
  QEMU 自身 stdout，由本脚本实时收集，才能做到「发一键、看一屏」。

判据：
  1. 用户名 alice 必须逐字回显（证明回显机制本身是开的）；
  2. 口令 alicepw 的明文必须**不出现**在口令提示符之后的快照里；
  3. 登录必须真的成功（welcome + shell 启动）。
  3 是关键：若只测 1+2，一个「压根没读到口令」的坏实现
  也能通过——它只是什么都没做而已。
"""
import os
import sys
# --- tools path bootstrap (files live under tools/checks/<cat>/) ---
_TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)
from tools_build import config
import socket
import subprocess
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
QEMU = os.path.join(ROOT, "envfiles", "tools", "qemu-stable",
                    "qemu-9.2.0-win64", "qemu-system-x86_64.exe")
PORT = int(os.environ.get("L3_MON_PORT", "45510"))
BOOT_WAIT = int(os.environ.get("L3_BOOT_WAIT", "300"))

USER_NAME = "alice"
PASSWORD = "alicepw"


def main():
    qemu = [
        QEMU,
        "-cdrom", config.OUTPUT_ISO,
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
        print("[l3] FAIL cannot reach QEMU monitor")
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

    # 等到真的出现登录提示符，而不是固定秒数（§6.10）。
    # selftest.py 会把 boruix.iso 换成自检镜像（开机跑约 300s 自检、永远不进 login），
    # 固定秒数会让键敲进自检输出里——症状像「代码坏了」，实为测试环境被上一步改坏了。
    print("[l3] waiting up to %ds for the login prompt ..." % BOOT_WAIT)
    _deadline = time.time() + BOOT_WAIT
    while "username:" not in snap() and time.time() < _deadline:
        time.sleep(1.0)

    checks = []

    def check(name, cond, detail=""):
        checks.append((name, bool(cond)))
        print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, detail))

    print("[l3] typing username (echo SHOULD be visible) ...")
    type_str(USER_NAME)
    time.sleep(1.0)
    after_name = snap()
    check("username_prompt_seen", "username:" in after_name)
    check("username_is_echoed", "alic" in after_name,
          "(no echoed text -> username echo broken too)")

    key("ret", 1.0)
    deadline = time.time() + 30.0
    after_ret = snap()
    while "password:" not in after_ret and time.time() < deadline:
        time.sleep(0.5)
        after_ret = snap()
    check("password_prompt_seen", "password:" in after_ret,
          "(Enter did not advance to the password prompt)")

    print("[l3] typing password (echo MUST be suppressed) ...")
    type_str(PASSWORD)
    time.sleep(2.0)
    during_pw = snap()
    prompt_end = during_pw.rfind("password:") + len("password:")
    check("password_not_echoed", PASSWORD not in during_pw[prompt_end:],
          "(password echoed while typing)")
    # 按字母单字符搜是无意义的（'a' 在 'password:' 里就有）。
    # 有意义的是「提示符之后的新增文本里有没有口令连续子串」。
    added = during_pw[prompt_end:]
    check("no_output_while_typing_pw", PASSWORD not in added,
          "(added while typing: %r)" % (added[:60],))

    print("[l3] submitting password ...")
    key("ret", 3.0)
    deadline = time.time() + 40.0
    final = snap()
    while "welcome, alice" not in final and time.time() < deadline:
        time.sleep(0.5)
        final = snap()
    check("login_succeeded", "login: welcome, alice" in final,
          "(authentication did not pass -> suppression may be fake)")
    check("shell_started", "BORUIX shell (PID 2)" in final)
    check("shell_prompt_seen", "alice:/$" in final)
    check("password_never_leaked", PASSWORD not in final,
          "(password found somewhere in the serial stream)")

    print("[l3] serial bytes: %d" % len(final))
    failed = [c for c in checks if not c[1]]
    print("[l3] ---- %d/%d checks passed ----" % (len(checks) - len(failed),
                                                   len(checks)))
    proc.kill()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())