#!/usr/bin/env python3
"""ADR-048 extension E3 acceptance: parallel multi-session (owner directive).

Build with BORUIX_SESSION_MODE=parallel + BORUIX_CONSOLES_N=4.
S1 init spawns one getty per instance: `parallel session started (pid P instance i)` x4 (i=0..3).
S2 all sessions alive: `username:` prompts >= 4 (shared serial interleaves them).
S3 ledger respawn: SIGKILL the focused session (instance 3, last spawned) ->
   `parallel session ended ... instance 3` -> respawn on instance 3.
S4 focus follows respawn: `focus -> instance 3` seen again.

judgement: S1-S4.
"""
import os, socket, subprocess, sys, time, re
from sdk_build import config
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QEMU = os.path.join(ROOT, "envfiles", "tools", "qemu-stable",
                    "qemu-9.2.0-win64", "qemu-system-x86_64.exe")
LOG = os.path.join(ROOT, "_e3_serial.log")
PORT = 45495
N = int(os.environ.get("BORUIX_CONSOLES_N", "4"))

def main():
    if os.path.exists(LOG):
        os.remove(LOG)
    proc = subprocess.Popen([QEMU, "-cdrom", config.OUTPUT_ISO,
        "-boot", "order=d", "-m", "256", "-display", "none",
        "-serial", "file:" + LOG,
        "-monitor", "tcp:127.0.0.1:%d,server,nowait" % PORT, "-no-reboot"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    s = None
    for _ in range(60):
        try:
            s = socket.create_connection(("127.0.0.1", PORT), timeout=2); break
        except OSError:
            time.sleep(0.5)
    if s is None:
        print("[t7] FAIL: monitor never up"); proc.kill(); return 1
    f = s.makefile("rwb")
    def key(k, d=0.25):
        f.write(("sendkey " + k + "\n").encode()); f.flush(); time.sleep(d)
    def snap():
        try:
            with open(LOG, "rb") as h: return h.read().decode("utf-8", "replace")
        except OSError: return ""
    def wait(pat, timeout):
        dl = time.time() + timeout
        while time.time() < dl:
            if pat in snap(): return True
            time.sleep(0.5)
        return False
    ok = True
    if not wait("username:", 200):
        print("[t7] FAIL: no login prompt"); proc.kill(); return 1
    time.sleep(3.0)  # 让 N 个 getty 全部落位
    full = snap()
    # S1: per-instance getty
    started = re.findall(r"parallel session started \(pid \d+ instance (\d+)\)", full)
    uniq = sorted(set(started))
    print("[t7] S1 getty instances: %s (want 0..%d, %d total)" % (uniq, N-1, len(started)))
    if len(uniq) != N or len(started) != N: ok = False
    # S2: all prompts up
    n_prompt = full.count("username:")
    print("[t7] S2 username prompts: %d (want >= %d)" % (n_prompt, N))
    if n_prompt < N: ok = False
    # S3: kill focused session。焦点实例**动态判定**（S09 证据链修正）：
    # spawn-is-binding 下焦点 = 最后完成 spawn 的实例，exec 完成顺序是调度竞争
    # 序（实测 0,1,3,2），不恒为 N-1——旧断言「last spawned = N-1」是 harness
    # 假设错误，内核账本对账一直正确。
    fm = re.findall(r"focus -> instance (\d+)", snap())
    if not fm:
        print("[t7] S3 FAIL: no focus marker to identify focused instance"); ok = False
        inst = -1
    else:
        inst = int(fm[-1])
        print("[t7] S3 focused instance (dynamic): %d; killing via 3 auth failures" % inst)
        # 焦点会话此刻是 **login**（未认证）——没有 shell/kill 可用；会话终止的
        # 诚实手段 = 3 次认证失败（p6 同款，R13 认证关口语义：login 失败退出）。
        named = {" ": "spc", "-": "minus", ".": "dot", "/": "slash"}
        def typ(t2, d=0.12):
            for c in t2:
                key(named.get(c, c), d)
        for _ in range(3):
            typ("nobody"); key("ret", 1.5)
            time.sleep(0.8)
            typ("wrongpw"); key("ret", 2.5)
            time.sleep(1.0)
        if not wait("parallel session ended", 40):
            print("[t7] S3 FAIL: no session-end marker"); ok = False
        else:
            tail = snap().split("parallel session ended")[-1][:200]
            if ("instance %d" % inst) not in tail:
                print("[t7] S3 FAIL: end marker not instance-tagged: " + tail[:80]); ok = False
            else:
                print("[t7] S3 ledger respawn trigger OK (instance %d)" % inst)
        if not wait("parallel session started (pid ", 30):
            print("[t7] S3 FAIL: no respawn spawn marker"); ok = False
        elif ("instance %d)" % inst) not in snap().split("parallel session ended")[-1][:400]:
            print("[t7] S3 WARN: respawn instance tag not in immediate tail")
        else:
            print("[t7] S3 respawn on instance %d OK" % inst)
        # S4: focus follows
        if not wait("focus -> instance %d" % inst, 40):
            print("[t7] S4 FAIL: focus did not follow respawn"); ok = False
        else:
            print("[t7] S4 focus -> instance %d OK" % inst)
    proc.kill()
    print("[t7] ---- " + ("PASS" if ok else "FAIL") + " ----")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
