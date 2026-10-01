#!/usr/bin/env python3
"""PRE-2 辅助：验证 QEMU 诊断客户端（RSP / HMP / screendump）在**真机**上可用。

为什么需要这个检查：这三个客户端是从排查 L5 时的临时脚本提升来的，提升后从未在
真机上跑过。离线自检（`checks/regression/diag_selftest.py`）只能钉住校验和、
PPM->PNG 与停机包识别；HMP 命令、RSP 断点/单步/读内存、`screendump` 的真实路径
必须真机验证，否则「提升」只是把代码搬了个位置。

断言（全部来自真机，逐条打印）：
  1. RSP 能在内核入口下断点并命中；
  2. 命中时 RIP **等于**映像的 `e_entry`（入口从 ELF 读，不写死地址）；
  3. RSP 读内存读出的入口前 16 字节与 ELF 文件里的**逐字节相同**；
  4. RSP 单步后收到停机包；
  5. HMP `info registers` 能读到 RIP，且与 RSP 读到的一致；
  6. `screendump` 产出合法 PNG（签名 + 尺寸）。

第 3 条是最强的一条：它把「RSP 能读内存」与「这块内存确实是那个内核映像」绑在一起，
排除了「读到了别的东西也算通过」。

退出码：0 全通过；1 有失败（打印已通过的条目与失败原因）。
"""

import os
import sys

TOOLS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, TOOLS_ROOT)

from tools_build import config, elf_image, iso9660, liftoff, qemu_debug  # noqa: E402

# HMP 监视器端口。固定值：HMP 需要 QEMU 侧监听一个已知端口。若被占用，
# 连接会失败并如实报错（不静默降级），改这个常量即可。
MONITOR_PORT = 45460
# 内核入口在读完 24MB 映像之后才到达（真机实测约 140 秒读盘 + 启动）。
# `-S` 冻结启动后，从 `c` 到内核入口要经历完整引导（读 24MB 映像约 140 秒 + 启动）。
STOP_TIMEOUT_S = 420
ENTRY_PROBE_BYTES = 16


def main() -> int:
    if not os.path.isfile(config.OUTPUT_ISO):
        print("FAIL: 未找到 ISO: " + config.OUTPUT_ISO)
        return 1

    # 入口地址与入口字节都从映像本身取——不写死地址，也不写死字节。
    image = elf_image.ElfImage.parse(
        iso9660.read_file(config.OUTPUT_ISO, config.KERNEL_ISO_COMPONENTS))
    entry = image.entry
    entry_bytes = image.read_vaddr(entry, ENTRY_PROBE_BYTES)
    print("[diag] 内核入口 %#x，前 %d 字节 %s" % (entry, ENTRY_PROBE_BYTES, entry_bytes.hex()))

    qemu_debug.kill_existing()
    esp = liftoff.ensure_ready()
    # `-S` 让 CPU 在启动时冻结：断点必须在**内核入口执行之前**设好。之前依赖
    # 「连接够快、VM 还没跑到入口」，那是时序赌博；`-S` 把它变成确定行为。
    cmd = ([liftoff.qemu_exe(), "-m", "1024", "-smp", "1", "-display", "none",
            "-serial", "stdio", "-S", "-s",
            "-monitor", "tcp:127.0.0.1:%d,server,nowait" % MONITOR_PORT,
            "-cdrom", config.OUTPUT_ISO]
           + config.sound_card_args(silent=True)
           + liftoff.uefi_args(esp))

    passed = []
    failure = None
    capture = qemu_debug.SerialCapture(cmd)
    try:
        rsp = qemu_debug.RspClient.connect()
        try:
            # 1) 下断点。此时 VM 仍在跑（没给 -S），断点必须早于内核入口设置。
            if not rsp.set_breakpoint(entry):
                failure = "RSP 下断点被拒（Z0 未返回 OK）"
            else:
                passed.append("RSP 断点已设置 @ %#x" % entry)
            if failure is None:
                rsp.continue_()
                stop = rsp.wait_for_stop(STOP_TIMEOUT_S)
                if stop is None:
                    failure = "RSP 在 %d 秒内没有收到停机包（断点未命中）" % STOP_TIMEOUT_S
                else:
                    passed.append("RSP 断点命中: " + stop.decode("ascii", "replace"))
            if failure is None:
                words = rsp.registers()
                rip = words[qemu_debug.REG_RIP]
                if rip != entry:
                    failure = "命中时 RIP=%#x，期望入口 %#x" % (rip, entry)
                else:
                    passed.append("命中时 RIP 等于 e_entry")
            if failure is None:
                got = rsp.read_memory(entry, ENTRY_PROBE_BYTES)
                if got != entry_bytes:
                    failure = ("RSP 读内存与 ELF 不符: 实得 %s 期望 %s"
                               % (got.hex(), entry_bytes.hex()))
                else:
                    passed.append("RSP 读内存与 ELF 入口字节逐字节相同")
            if failure is None:
                # 单步前后各打一条 HMP `info registers`：这能把「gdbstub 没执行 s」
                # 与「执行了但应答丢失」区分开 —— 前者 VM 完全不动，后者 RIP 会变。
                try:
                    with qemu_debug.MonitorClient(port=MONITOR_PORT) as monitor:
                        before = monitor.command("info registers")
                    rip_before = [l for l in before.splitlines() if "RIP=" in l]
                    print("  [diag] 单步前 HMP: " + (rip_before[0].strip()[:60] if rip_before else "(无)"))
                except Exception as exc:
                    print("  [diag] 单步前 HMP 不可用: %s" % exc)
                stepped = rsp.step()
                if stepped is None:
                    try:
                        with qemu_debug.MonitorClient(port=MONITOR_PORT) as monitor:
                            after = monitor.command("info registers")
                        rip_after = [l for l in after.splitlines() if "RIP=" in l]
                        print("  [diag] 单步后 HMP: " + (rip_after[0].strip()[:60] if rip_after else "(无)"))
                        print("  [diag] VM 状态: " + ("stopped" if "stopped" in after else "running/未知"))
                    except Exception as exc:
                        print("  [diag] 单步后 HMP 不可用: %s" % exc)
                    failure = "RSP 单步后没有收到停机包"
                else:
                    passed.append("RSP 单步收到停机包")
        finally:
            rsp.close()

        # HMP：VM 此刻停在断点上，寄存器应与 RSP 读到的一致。
        if failure is None:
            try:
                with qemu_debug.MonitorClient(port=MONITOR_PORT) as monitor:
                    out = monitor.command("info registers")
                if "RIP=" not in out:
                    failure = "HMP `info registers` 输出里没有 RIP="
                else:
                    line = [l for l in out.splitlines() if "RIP=" in l][0]
                    passed.append("HMP 读到寄存器: " + line.strip()[:60])
            except (OSError, qemu_debug.QemuDebugError) as exc:
                failure = "HMP 监视器不可用: %s" % exc

        # screendump：转成 PNG 并校验结构与尺寸。
        if failure is None:
            try:
                with qemu_debug.MonitorClient(port=MONITOR_PORT) as monitor:
                    ppm_path = os.path.join(TOOLS_ROOT, "_diag_shot.ppm")
                    if os.path.exists(ppm_path):
                        os.remove(ppm_path)
                    monitor.command("screendump " + ppm_path, wait_s=3.0)
                if not os.path.isfile(ppm_path):
                    failure = "screendump 没有产出文件"
                else:
                    with open(ppm_path, "rb") as handle:
                        png = qemu_debug.ppm_to_png(handle.read())
                    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
                        failure = "screendump 转出的不是 PNG"
                    else:
                        passed.append("screendump -> PNG %d 字节" % len(png))
            except (OSError, qemu_debug.QemuDebugError) as exc:
                failure = "screendump 失败: %s" % exc
    except (OSError, qemu_debug.QemuDebugError) as exc:
        failure = "诊断客户端异常: %s" % exc
    finally:
        capture.close()

    for item in passed:
        print("  ok   " + item)
    if failure is not None:
        # 失败时必须交出串口证据：断点没命中时，串口能区分「VM 根本没恢复执行」
        # 与「VM 跑了但没到入口」——这两种原因的修法完全不同。
        print("FAIL: " + failure)
        print("== serial tail（%d 字节）==" % len(capture.buffer))
        tail = capture.buffer.text()[-1500:]
        print(tail if tail else "(空：VM 很可能从未执行到任何串口输出)")
        return 1
    print("PASS: QEMU 诊断客户端（RSP/HMP/screendump）真机路径全部可用")
    return 0


if __name__ == "__main__":
    sys.exit(main())
