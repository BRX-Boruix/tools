#!/usr/bin/env python3
"""liftoff（UEFI/OVMF）端到端验收。

真实链路：OVMF 固件 → ESP 里的 liftoff.efi → 介质（ISO / systemdisk）上的
/boot/kernel → 内核 → /programs/init.elf（PID 1）。断言全部取自串口实际输出，
缺一即失败——「看到 booting user init」不算数，成功分界行是 `init: loaded`。

用法：
  python checks/liftoff/l1_boot_check.py                      # liveCD（ISO）
  python checks/liftoff/l1_boot_check.py --medium systemdisk   # 安装模式
"""
import argparse
import os
import subprocess
import sys
import time

_TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)
from tools_build import config, disk, liftoff  # noqa: E402

LOG = os.path.join(config.PROJECT_ROOT, "_liftoff_serial.log")

# 每个介质各自的引导方式锚点（其余锚点两者相同）。
MODE_ANCHOR = {
    "iso": "[boot] liveCD mode",
    "systemdisk": "[boot] install mode root =",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--medium", choices=sorted(MODE_ANCHOR), default="iso")
    ap.add_argument("--timeout", type=int, default=600, help="等串口命中的上限（秒）")
    ap.add_argument("--mem", default="256M")
    a = ap.parse_args()

    if a.medium == "iso":
        if not os.path.isfile(config.OUTPUT_ISO):
            print("FAIL: 未找到 ISO " + config.OUTPUT_ISO + "（先 python main.py build --liftoff）")
            return 2
        medium_args = ["-cdrom", config.OUTPUT_ISO]
    else:
        if not os.path.isfile(disk.SYSTEM_DISK_IMG_PATH):
            print("FAIL: 未找到系统盘 " + disk.SYSTEM_DISK_IMG_PATH + "（先 build --systemdisk）")
            return 2
        medium_args = ["-drive", "format=raw,file=" + disk.SYSTEM_DISK_IMG_PATH]

    anchors = [
        "[liftoff] M2b entry",                     # 固件真的装载并进入 liftoff
        "Hello, BORUIX!",                          # 交接成功、内核在跑
        MODE_ANCHOR[a.medium],                     # 内核认了启动方式
        "[kmain] booting user init (PID 1) ...",   # 进入 init 启动流程
        "[kmain] init: loaded",                    # init.elf 真读到了（成功分界行）
        "[kmain] init: spawned pid=1 from init.elf",  # PID 1 真的起来了
    ]

    if os.path.exists(LOG):
        os.remove(LOG)
    esp = liftoff.ensure_ready()
    qemu = [liftoff.qemu_exe(), "-m", a.mem, "-smp", "4",
            "-display", "none", "-no-reboot",
            "-serial", "file:" + LOG] + medium_args + liftoff.uefi_args(esp)
    print("[liftoff] medium=" + a.medium + " esp=" + esp)
    proc = subprocess.Popen(qemu, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + a.timeout
    content = ""
    try:
        while time.time() < deadline:
            time.sleep(1.0)
            if os.path.exists(LOG):
                with open(LOG, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                if all(x in content for x in anchors):
                    break
            if proc.poll() is not None:
                break
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    failed = False
    for x in anchors:
        if x in content:
            print("PASS: contains " + x)
        else:
            print("FAIL: missing " + x)
            failed = True
    if failed:
        print("== serial tail ==")
        print(content[-4000:])
        return 1
    print("LIFTOFF E2E PASS (" + a.medium + ")")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
