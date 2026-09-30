#!/usr/bin/env python3
"""PRE-2: QEMU/OVMF 端到端验收（ADR-052 第 1 层）。

真实链路：OVMF 固件 → ESP（USB 可移动介质）里的 BOOTX64.EFI → 运行 liftoff。
判定标准：串口上出现 liftoff 的启动诊断行 `[liftoff] gen2 up`。

退出码：0 = 判定通过；1 = 未出现（打印串口尾部与常见原因）。
"""

import os
import subprocess
import sys
import time

TOOLS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, TOOLS_ROOT)

from tools_build import liftoff  # noqa: E402

MARKER = b"[liftoff] gen2 up"
TIMEOUT_S = 60


def main() -> int:
    esp = liftoff.ensure_ready()
    log = os.path.join(TOOLS_ROOT, '_pre2_serial.log')
    if os.path.exists(log):
        os.remove(log)
    cmd = [liftoff.qemu_exe(), '-m', '512', '-smp', '1',
           '-display', 'none', '-serial', 'file:' + log] + liftoff.uefi_args(esp)
    print('[pre2] qemu: ' + ' '.join(cmd[:3]) + ' ... esp=' + esp)
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + TIMEOUT_S
    seen = False
    while time.time() < deadline:
        if os.path.exists(log):
            with open(log, 'rb') as handle:
                if MARKER in handle.read():
                    seen = True
                    break
        if proc.poll() is not None:
            break
        time.sleep(1)
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    tail = b''
    if os.path.exists(log):
        with open(log, 'rb') as handle:
            tail = handle.read()[-400:]
    if seen:
        print('PASS: 串口出现 ' + MARKER.decode())
        return 0
    print('FAIL: ' + str(TIMEOUT_S) + ' 秒内未出现 ' + MARKER.decode())
    print('== serial tail ==')
    print(tail.decode('utf-8', 'replace'))
    return 1


if __name__ == '__main__':
    sys.exit(main())
