#!/usr/bin/env python3
"""liftoff 引导下「PID 1 spawn 之后」的冻结诊断：dump 全部 CPU 寄存器。

在串口出现 [kmain] init: spawned pid=1 之后等 5 秒，经 QEMU monitor 执行
info registers -a，把每个 CPU 的 RIP/CR3/CR4 打出来——用于判定系统冻结时
各 CPU 是在内核 idle、已 sysret 进用户态（RIP≈0x400000 附近）、还是卡在
sysret/iret 路径。默认复刻 b2/用户的命令形态（-hda systemdisk + USB ESP）。
"""
import argparse, os, re, socket, subprocess, sys, time

_TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)
from tools_build import config, disk, liftoff  # noqa: E402

LOG = os.path.join(config.PROJECT_ROOT, "_regs_serial.log")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--medium", choices=["systemdisk"], default="systemdisk")
    ap.add_argument("--wait-spawn", type=int, default=480)
    ap.add_argument("--mem", default="256M")
    a = ap.parse_args()
    if os.path.exists(LOG):
        os.remove(LOG)
    fw = liftoff.ovmf_firmware()
    esp = liftoff.ensure_ready()
    # 与 l1_boot_check 的参数集保持一致（-drive 而非 -hda；无 netdev/音频）。
    # 此前用 -hda + netdev + 音频 时，OVMF 在固件阶段挂起（4 CPU 同 RIP，永不进入
    # liftoff）——逐项排查：本参数集已在实测中通过到 spawn。
    qemu = [liftoff.qemu_exe(),
            "-m", a.mem, "-smp", "4",
            "-drive", "format=raw,file=" + disk.SYSTEM_DISK_IMG_PATH,
            "-drive", "if=pflash,format=raw,readonly=on,file=" + fw,
            "-drive", "format=raw,file=fat:rw:" + esp,
            "-serial", "file:" + LOG,
            "-monitor", "tcp:127.0.0.1:45487,server=on,wait=off",
            "-no-reboot", "-display", "none"]
    p = subprocess.Popen(qemu, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def wait_log(pat, timeout):
        dl = time.time() + timeout
        while time.time() < dl:
            try:
                with open(LOG, "rb") as h:
                    if pat.encode() in h.read():
                        return True
            except OSError:
                pass
            time.sleep(1.0)
        return False

    spawned = wait_log("[kmain] init: spawned pid=1", a.wait_spawn)
    print("spawned seen:", spawned)
    if not spawned:
        p.kill()
        print("FAIL: never reached init spawn (see " + LOG + ")")
        return 1
    time.sleep(5.0)
    s = socket.create_connection(("127.0.0.1", 45487), timeout=5)
    time.sleep(1.0)
    try:
        s.recv(65536)
    except OSError:
        pass
    s.sendall(b"info registers -a\n")
    time.sleep(3.0)
    s.settimeout(3.0)
    out = b""
    try:
        while True:
            c = s.recv(65536)
            if not c:
                break
            out += c
    except socket.timeout:
        pass
    p.kill()
    txt = out.decode("utf-8", "replace")
    open(os.path.join(config.PROJECT_ROOT, "_regs_dump.txt"), "w", encoding="utf-8").write(txt)
    regs = re.findall(r"CPU#(\d+)[\s\S]*?RIP=([0-9a-f]{16})[\s\S]*?CR3=([0-9a-f]{16})", txt)
    verdict = []
    for cpu, rip, cr3 in regs:
        tag = "user(0x400000-ish)" if int(rip, 16) < 0x8000000000000000 and int(rip, 16) >= 0x400000 else "kernel/firmware"
        verdict.append("CPU" + cpu + " RIP=" + rip + " CR3=" + cr3 + " -> " + tag)
    print("\n".join(verdict) if verdict else "no regs parsed; raw in _regs_dump.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
