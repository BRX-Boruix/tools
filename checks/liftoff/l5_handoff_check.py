#!/usr/bin/env python3
"""PRE-2: QEMU/OVMF 端到端验收（ADR-052 第 1 层）—— L5 交接。

真实链路：OVMF 固件 -> ESP（USB 可移动介质）里的 BOOTX64.EFI -> liftoff ->
ISO9660 上的 `/boot/kernel` -> 内核 -> 用户态 `init` 及其守护进程 -> 登录提示符。

判定标准（量化）：串口上出现 `username:`。这是 L5「交接」的验收条件——它要求
链路**每一环都真的通了**：响应填充（HHDM/内存映射/RSDP/帧缓冲/可执行文件/SMP）、
`exit_prepared` 取 `map_key`、覆盖检查、跳板交付的机器状态、以及内核能加载并运行
用户态。任何一环坏了，`username:` 都不会出现。

**串口通道用 `-serial stdio`，不用 `-serial file:`。** QEMU 的 file 后端不在每次写入
时刷新（`checks/interactive/l3_interactive.py` 记录了实测：静止 16 秒文件大小不变），
落盘时机取决于内部缓冲——属未定义行为。运行期轮询它，等于把判定的正确性押在一个
未文档化的缓冲策略上：输出多到填满缓冲就「恰好能用」，输出少就永远读不到。`stdio`
由本进程实时读走，时序确定。

到 `username:` 必须真的挂上 ISO 与声卡：
* ISO 必须以 `-cdrom` 挂（内核找的是 CD 设备；挂成硬盘时 `/programs` 为空，
  `init.elf` 加载不了，内核只能进 idle loop）；
* 声卡参数必须给（`intel-hda` + `hda-output`），否则用户态 `intel-hda` 驱动
  探测不到设备，会在它自己的分配器里 panic。
两者都从 `config` / 既有参数构造器取，不在本文件里另写一份（S15）。

退出码：0 = 判定通过；1 = 未出现（打印串口尾部与常见原因）。
"""

import os
import sys

TOOLS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, TOOLS_ROOT)

from tools_build import config, liftoff, qemu_debug  # noqa: E402

MARKER = b"username:"
# 内核映像有 24MB，从 ISO 读进来本身就要两分多钟（真机实测约 140 秒），再加内核与
# 用户态启动。给足余量：宁可等，不要因为超时把真实通过判成失败。
TIMEOUT_S = 600


def main() -> int:
    if not os.path.isfile(config.OUTPUT_ISO):
        print("FAIL: 未找到 ISO: " + config.OUTPUT_ISO + "（先运行 `main.py build`）")
        return 1
    qemu_debug.kill_existing()
    esp = liftoff.ensure_ready()
    cmd = ([liftoff.qemu_exe(), "-m", "1024", "-smp", "1", "-display", "none",
            "-serial", "stdio", "-cdrom", config.OUTPUT_ISO]
           + config.sound_card_args(silent=True)
           + liftoff.uefi_args(esp))
    print("[pre2-l5] ISO: " + config.OUTPUT_ISO)
    print("[pre2-l5] ESP: " + esp)
    print("[pre2-l5] 等待标记: " + MARKER.decode())
    capture = qemu_debug.SerialCapture(cmd)
    try:
        seen = capture.wait_for(MARKER, TIMEOUT_S)
    finally:
        # 必须用 taskkill：Windows 上 QEMU 不随父进程退出，残留进程会占住
        # `fat:rw:` 的 ESP 目录，让下一次运行失败（实测多次）。
        capture.close()
    text = capture.buffer.text()
    if seen:
        print("PASS: 串口出现 %s（%d 字节）" % (MARKER.decode(), len(capture.buffer)))
        return 0
    print("FAIL: %d 秒内未出现 %s（串口 %d 字节）" % (
        TIMEOUT_S, MARKER.decode(), len(capture.buffer)))
    print("== 常见原因 ==")
    print("  * 内核在 mm::init panic -> 某个响应没送到（查 `Failed to get HHDM response`）")
    print("  * 只到 `reached idle loop` -> ISO 没以 -cdrom 挂，/programs 为空")
    print("  * 用户态分配器 panic -> 声卡参数缺失，intel-hda 探测不到设备")
    print("== serial tail ==")
    print(text[-2000:])
    return 1


if __name__ == "__main__":
    sys.exit(main())
