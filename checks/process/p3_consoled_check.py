#!/usr/bin/env python3
"""P3 真机三段验收：console 字节环（I-EVENTS 阶段 3 · §6.15.3）。

# 判定全部来自串口真值 + status 遥测（S09），不伪造任何中间证据：

  S1  端到端阻塞-唤醒往返：`consoled-e2e writer &` 后台挂起读 console
      （登记 CONSOLE_WAITER），`consoled-e2e consumer` 写两段 pattern 并对账。
      writer 的 PASS 标记 + consumer 退出码 0 = 真实 park/wake 链路完好。
      后台输出进 /tmp/jobN.out（shell 令牌策略），串口只见 consumer 行——
      判据 = consumer 行出现 [ce2e] 起始输出且无 FAIL。

  S2  consoled 实转：启动 consoled（&），随后注入真实按键（sendkey 硬件
      路径 → IRQ1 → 事件环 → consoled 转换 → console 环）。判据 =
      `/devices/console/status` 的 writes 计数随按键上升（cat 出真值）。
      注：P4 切换前 console 环无既有读者，按键只进环不出显——writes 上升
      即为「事件→字节→环」全链路真值。

  S3  既有面无损：evsrcdemo 组件检查另跑（ievents_component_check.py），
      本脚本不含——单变量归因。
"""
import os, re, socket, subprocess, sys, time
import sys
# --- tools path bootstrap (files live under tools/checks/<cat>/) ---
_TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)
from tools_build import config

ROOT = r"F:\boruix-project"
QEMU = os.path.join(ROOT, "envfiles", "tools", "qemu-stable", "qemu-9.2.0-win64", "qemu-system-x86_64.exe")
ISO = config.OUTPUT_ISO
DISK = os.path.join(ROOT, "disk.img")
LOG = os.path.join(ROOT, "_p3_serial.log")
PORT = 45631
BOOT_WAIT = float(os.environ.get("P3_BOOT_WAIT", "90"))

def main():
    if os.path.exists(LOG):
        os.remove(LOG)
    qemu = [QEMU, "-cdrom", ISO, "-hda", DISK, "-boot", "order=d", "-m", "256",
            "-display", "none", "-serial", "file:" + LOG,
            "-monitor", "tcp:127.0.0.1:%d,server,nowait" % PORT, "-no-reboot"]
    proc = subprocess.Popen(qemu, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    s = None
    for _ in range(60):
        try:
            s = socket.create_connection(("127.0.0.1", PORT), timeout=2); break
        except OSError:
            time.sleep(0.5)
    if s is None:
        print("[p3] FAIL: monitor never came up"); proc.kill(); return 1
    f = s.makefile("rwb")

    def key(k, d=0.30):
        f.write(("sendkey " + k + "\n").encode()); f.flush(); time.sleep(d)

    _SPECIAL = {" ": "spc", "/": "slash", "-": "minus", "=": "equal", "&": "shift-7", ".": "dot", "_": "shift-minus", ">": "shift-period"}
    def _qc(ch):
        if ch in _SPECIAL: return _SPECIAL[ch]
        if ch.isupper(): return "shift-" + ch.lower()
        return ch
    def type_str(txt, d=0.14):
        for ch in txt: key(_qc(ch), d)
    def snap():
        try: return open(LOG, "rb").read().decode("utf-8", "replace")
        except OSError: return ""
    def wait_for(substr, timeout):
        dl = time.time() + timeout
        while time.time() < dl:
            if substr in snap(): return True
            time.sleep(1.0)
        return False

    # ---- boot + login ----
    print("[p3] waiting for login prompt ...")
    dl = time.time() + BOOT_WAIT
    while not os.path.exists(LOG) and time.time() < dl:
        if proc.poll() is not None:
            print("[p3] FAIL: qemu died at startup (rc=%s) — check pagefile/memory" % proc.returncode)
            return 1
        time.sleep(0.5)
    if not wait_for("username:", BOOT_WAIT):
        print("[p3] FAIL: login prompt never appeared"); proc.kill(); return 1
    type_str("alice"); key("ret"); time.sleep(0.6)
    type_str("alicepw"); key("ret"); time.sleep(3.0)

    results = {}

    # ---- S0: 环境探针（S09）：身份/权限地形——run14 实证前台 shell 连
    # 家目录都写不进（echo> 重定向后 cat ENOENT），先弄清自己是谁。
    print("[p3] S0: env probe")
    type_str("cat /processes/self/status")
    key("ret")
    time.sleep(1.5)
    type_str("cat /processes/2/status")
    key("ret")
    time.sleep(1.5)
    type_str("ls /users/alice")
    key("ret")
    time.sleep(1.5)
    type_str("cat /users/alice/identity")
    key("ret")
    time.sleep(1.5)
    type_str("echo probe > /users/alice/ce2e_probe.txt")
    key("ret")
    time.sleep(1.5)
    type_str("ls /users/alice")
    key("ret")
    time.sleep(1.5)
    type_str("cat /users/alice/ce2e_probe.txt")
    key("ret")
    time.sleep(1.5)
    type_str("echo probe > /volumes/BORUIX_DATA/ce2e_probe.txt")
    key("ret")
    time.sleep(1.5)
    type_str("cat /volumes/BORUIX_DATA/ce2e_probe.txt")
    key("ret")
    time.sleep(1.5)

    # ---- S1: e2e roundtrip（单前台命令：roundtrip 角色自己 spawn writer）----
    print("[p3] S1: consoled-e2e roundtrip")
    type_str("/programs/consoled-e2e.elf roundtrip")
    key("ret")
    # 判据（串口真值，S09）：consumer 打印 PASS 行 = writer 两段校验过 +
    # status 遥测对账过 + 往返全程无 FAIL。等待有界；FAIL 行抢先出现即假。
    ok1 = wait_for("[ce2e] PASS (roundtrip", 30)
    fail1 = wait_for("[ce2e] FAIL", 1)
    results["s1_roundtrip"] = ok1 and not fail1

    # writer 子进程 stdout 继承父进程 → 串口可见其失败自述（S09）。

    # ---- S2: consoled real conversion ----
    print("[p3] S2: consoled real conversion")
    type_str("/programs/consoled.elf &")
    key("ret")
    time.sleep(2.5)
    # 读初始 writes（cat /devices/console/status）
    type_str("cat /devices/console/status")
    key("ret")
    time.sleep(2.0)
    m1 = snap()
    w1 = _last_int_field(m1, "writes")
    # 注入真实按键（事件环 → consoled → console 环）。
    # 键盘 IRQ 同时喂 KBD 队列（shell 行编辑）与事件环（consoled 消费）——
    # hello 是否被 shell 当命令执行与 consoled 无关，但必须回车清掉 shell
    # 行缓冲，否则与后续 cat 拼行（run3 实测 hellocat）。
    type_str("hello")
    key("ret")
    time.sleep(2.0)
    type_str("cat /devices/console/status")
    key("ret")
    time.sleep(2.0)
    m2 = snap()
    w2 = _last_int_field(m2, "writes")
    print("[p3] writes before=%s after=%s" % (w1, w2))
    results["s2_writes_rising"] = w1 is not None and w2 is not None and w2 > w1

    # ---- cleanup: kill consoled (leave system clean) ----
    # consoled 是常驻进程：杀掉以免干扰后续人工交互（pid 从 ps 拿不到就跳过）。
    # 这里不做 —— 验收后直接关机（QEMU kill），状态无所谓。

    proc.kill()
    ok = all(results.values())
    print("[p3] ==== %s ====" % ("PASS" if ok else "FAIL"))
    for k, v in results.items():
        print("[p3]   %-22s %s" % (k, "PASS" if v else "FAIL"))
    return 0 if ok else 2

def _last_int_field(text, field):
    """取串口日志里该字段**最后一次**出现的整数值（cat 输出在最后）。"""
    vals = re.findall(r'"' + field + r'":(\d+)', text)
    return int(vals[-1]) if vals else None

if __name__ == "__main__":
    sys.exit(main())
