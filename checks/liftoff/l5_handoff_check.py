#!/usr/bin/env python3
"""PRE-2: QEMU/OVMF 端到端验收（ADR-052 第 1 层）—— L5 交接 + 覆盖矩阵。

真实链路：OVMF 固件 -> ESP（USB 可移动介质）里的 BOOTX64.EFI -> liftoff ->
ISO9660 上的 /boot/kernel -> 内核 -> 用户态 init 及其守护进程 -> 登录提示符。

判定标准（量化）：串口上出现 username: 。这是 L5「交接」的验收条件——它要求链路
每一环都真的通了：响应填充（HHDM/内存映射/RSDP/帧缓冲/可执行文件/SMP）、
exit_prepared 取 map_key、覆盖检查、跳板交付的机器状态、以及内核能加载并运行用户态。
任何一环坏了，username: 都不会出现。

串口通道用 -serial stdio，不用 -serial file:。QEMU 的 file 后端不在每次写入时刷新
（checks/interactive/l3_interactive.py 记录了实测：静止 16 秒文件大小不变），落盘时机
取决于内部缓冲——属未定义行为。运行期轮询它，等于把判定的正确性押在一个未文档化的
缓冲策略上：输出多到填满缓冲就恰好能用，输出少就永远读不到。stdio 由本进程实时读走，
时序确定。

到 username: 必须真的挂上 ISO 与声卡：
* ISO 必须以 -cdrom 挂（内核找的是 CD 设备；挂成硬盘时 /programs 为空，init.elf
  加载不了，内核只能进 idle loop）；
* 声卡参数必须给（intel-hda + hda-output），否则用户态 intel-hda 驱动探测不到设备，
  会在它自己的分配器里 panic。
两者都从 config / 既有参数构造器取，不在本文件里另写一份（S15）。

覆盖矩阵（--matrix）：台账 §4.3 要求「单核与 4 核都必须过」「-cpu max 与默认模型都
必须过」。默认（不带 --matrix）跑单格：-smp 1 + 默认 CPU 模型，与历史行为一致，
供快速回归。

退出码：0 = 所跑格子全部通过；1 = 有格子未出现标记（打印每格结果与失败尾部）。
"""

import argparse
import os
import sys

TOOLS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, TOOLS_ROOT)

from tools_build import config, liftoff, qemu_debug  # noqa: E402

MARKER = b"username:"
# 内核映像有 24MB，从 ISO 读进来本身就要两分多钟（真机实测约 140 秒），再加内核与
# 用户态启动。给足余量：宁可等，不要因为超时把真实通过判成失败。
TIMEOUT_S = 600
# 覆盖矩阵（台账 §4.3）：核数 × CPU 模型。cpu_args 为空列表表示 QEMU 默认模型。
MATRIX = [
    (1, [], "单核 + 默认 CPU 模型"),
    (1, ["-cpu", "max"], "单核 + -cpu max"),
    (4, [], "4 核 + 默认 CPU 模型"),
    (4, ["-cpu", "max"], "4 核 + -cpu max"),
]


def run_cell(esp, smp, cpu_args, timeout_s=None):
    """跑一格，返回 (是否到达标记, 串口文本)。"""
    cmd = ([liftoff.qemu_exe(), "-m", "1024", "-smp", str(smp), "-display", "none",
            "-serial", "stdio", "-cdrom", config.OUTPUT_ISO]
           + cpu_args
           + config.sound_card_args(silent=True)
           + liftoff.uefi_args(esp))
    capture = qemu_debug.SerialCapture(cmd)
    try:
        seen = capture.wait_for(MARKER, timeout_s or TIMEOUT_S)
    finally:
        # 必须用 taskkill：Windows 上 QEMU 不随父进程退出，残留进程会占住
        # fat:rw: 的 ESP 目录，让下一次运行失败（实测多次）。
        capture.close()
    return seen, capture.buffer.text()


def diagnose(text):
    """按串口内容给出最可能的原因。这只是提示，判定只看标记。"""
    print("== 常见原因 ==")
    if "KERNEL PANIC" in text:
        msg = [l.split("message:", 1)[1].strip() for l in text.splitlines()
               if "message:" in l]
        print("  * 内核 panic -> " + (msg[0] if msg else "(未读到 message)"))
    elif "reached idle loop" in text:
        print("  * 只到 idle loop -> ISO 没以 -cdrom 挂，/programs 为空")
    elif "userspace panic" in text:
        print("  * 用户态 panic -> 声卡参数缺失，intel-hda 探测不到设备")
    else:
        print("  * 串口过短 -> 引导早期失败，先查 PRE-1/PRE-2 前置检查")
    print("== serial tail ==")
    print(text[-1500:])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--matrix", action="store_true",
                        help="跑全部 4 格覆盖矩阵；默认只跑单格（约 4 分钟/格）")
    parser.add_argument("--smp", type=int, default=1, choices=(1, 4),
                        help="单格模式的核数（默认 1）")
    parser.add_argument("--cpu", default=None, choices=("max",),
                        help="单格模式的 CPU 模型（缺省即 QEMU 默认模型）")
    parser.add_argument("--dump-serial", default=None, metavar="PATH",
                        help="把每格的串口输出写到该文件（留证；多格时追加并标注格子）")
    parser.add_argument("--expect-cpus", type=int, default=None, metavar="N",
                        help="断言串口出现 `total cpus=N`。**这是 S8 的判据**：`--smp 4` 时 N 必须是 4。"
                             "默认不检查 —— 因为当前实现只报 1 核（那是待实现的功能），"
                             "把默认设成检查会让现有 PASS 全变红。")
    parser.add_argument("--timeout", type=float, default=None, metavar="SECONDS",
                        help="覆盖等待标记的秒数（默认 %d）。用于**有界诊断**：已知会早期"
                             "失败时不必等满默认时长" % TIMEOUT_S)
    args = parser.parse_args()

    if not os.path.isfile(config.OUTPUT_ISO):
        print("FAIL: 未找到 ISO: " + config.OUTPUT_ISO + "（先运行 main.py build）")
        return 1

    if args.matrix:
        cells = MATRIX
    else:
        cpu = ["-cpu", args.cpu] if args.cpu else []
        cells = [(args.smp, cpu, "%d 核 + %s" % (args.smp, args.cpu or "默认 CPU 模型"))]

    qemu_debug.kill_existing()
    esp = liftoff.ensure_ready()
    print("[pre2-l5] ISO: " + config.OUTPUT_ISO)
    print("[pre2-l5] ESP: " + esp)
    print("[pre2-l5] 等待标记: " + MARKER.decode())

    failures = []
    for smp, cpu_args, desc in cells:
        print("-- 格子: " + desc + " --")
        seen, text = run_cell(esp, smp, cpu_args, args.timeout)
        if args.dump_serial:
            with open(args.dump_serial, "a", encoding="utf-8") as handle:
                handle.write("\n===== %s =====\n" % desc)
                handle.write(text)
        if seen:
            # **S8 判据**：到了 `username:` 还不够 —— 还要看 SMP 是否真的起来了。
            # 只报 1 核而请求了 4 核时，这一格必须 FAIL，否则检查会"看起来通过"。
            if args.expect_cpus is not None:
                needle = "total cpus=%d" % args.expect_cpus
                if needle not in text:
                    print("  FAIL: " + desc + "（到了 username:，但串口没有 `" + needle + "`）")
                    failures.append((desc + " [SMP]", text))
                    continue
            print("  PASS: " + desc + "（%d 字节）" % len(text))
            continue
        failures.append((desc, text))
        waited = args.timeout or TIMEOUT_S
        print("  FAIL: " + desc + "（%d 秒内未出现标记，串口 %d 字节）" % (waited, len(text)))

    if not failures:
        print("PASS: %d/%d 格全部到达 username:" % (len(cells), len(cells)))
        return 0
    print("FAIL: %d/%d 格未到达 username:" % (len(failures), len(cells)))
    for desc, text in failures:
        print("===== " + desc + " =====")
        diagnose(text)
    return 1


if __name__ == "__main__":
    sys.exit(main())
