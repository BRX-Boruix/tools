#!/usr/bin/env python3
"""PRE-2 附：把 `tools_build/qemu_debug.py` 的**三条真机通路**各走一遍。

- **HMP**（QEMU monitor over TCP）：发一条 HMP 命令并取回真实输出；
- **RSP**（gdb stub）：读寄存器、下断点、单步、读内存；
- **screendump**：HMP 截屏 → ppm → png。

**为什么需要它**：这些能力此前只在**临时脚本**里验证过 ✗，提升成正式模块之后
**没有在真机上跑过** ✓ —— 于是"它到底能不能用"没有证据 ✗。本检查给出真实输出，
逐条 PASS/FAIL，而不是"看起来对" ✓。
"""
import os
import sys

_TOOLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
from tools_build import config, liftoff, qemu_debug  # noqa: E402

MARKER = b"username:"
GDB_PORT = qemu_debug.DEFAULT_GDB_PORT
MON_PORT = 45454


def main() -> int:
    qemu_debug.kill_existing()
    esp = liftoff.ensure_ready()
    cmd = ([liftoff.qemu_exe(), "-m", "1024", "-smp", "1", "-display", "none",
            "-serial", "stdio", "-cdrom", config.OUTPUT_ISO]
           + config.sound_card_args(silent=True)
           + liftoff.uefi_args(esp)
           # 调试通路：gdb stub（RSP）+ HMP monitor over TCP
           + ["-s", "-monitor", "tcp:127.0.0.1:%d,server,nowait" % MON_PORT])
    results = []
    cap = qemu_debug.SerialCapture(cmd)
    try:
        seen = cap.wait_for(MARKER, 420)
        print("[a1] 串口到达 %s: %s" % (MARKER.decode(), seen))
        results.append(("serial", seen))

        # --- HMP ---
        try:
            with qemu_debug.MonitorClient(port=MON_PORT) as mon:
                out = mon.command("info registers", wait_s=2.0)
                print("[a1] HMP info registers -> " + out.strip().replace("\n", " | ")[:400])
                results.append(("hmp", "RIP=" in out or "RIP" in out))
                shot_ppm = os.path.join(_TOOLS, "_a1_shot.ppm")
                if os.path.isfile(shot_ppm):
                    os.remove(shot_ppm)
                mon.command("screendump " + shot_ppm, wait_s=4.0)
                if os.path.isfile(shot_ppm) and os.path.getsize(shot_ppm) > 0:
                    with open(shot_ppm, "rb") as h:
                        ppm = h.read()
                    png = qemu_debug.ppm_to_png(ppm)
                    out_png = os.path.join(_TOOLS, "_a1_shot.png")
                    with open(out_png, "wb") as h:
                        h.write(png)
                    print("[a1] screendump -> ppm %d B -> png %d B (%s)" % (len(ppm), len(png), out_png))
                    results.append(("screendump", len(png) > 0))
                else:
                    print("[a1] screendump 未落盘")
                    results.append(("screendump", False))
        except Exception as exc:  # noqa: BLE001
            print("[a1] HMP 通路异常: %r" % (exc,))
            results.append(("hmp", False))
            results.append(("screendump", False))

        # --- RSP ---
        try:
            with qemu_debug.RspClient.connect(port=GDB_PORT) as rsp:
                regs = rsp.registers()
                print("[a1] RSP registers 条数=%d 样例=%r" % (len(regs), regs[:2]))
                results.append(("rsp_registers", len(regs) > 0))
                mem = rsp.read_memory(0x1000, 16)
                print("[a1] RSP read_memory(0x1000,16)=%s" % mem.hex())
                results.append(("rsp_read_memory", len(mem) == 16))
                hit = rsp.set_breakpoint(0x1000, 4)
                print("[a1] RSP set_breakpoint(0x1000)=%s" % hit)
                results.append(("rsp_breakpoint", bool(hit)))
                rsp.continue_()
                stopped = rsp.wait_for_stop(5.0)
                print("[a1] RSP wait_for_stop(5s)=%s" % stopped)
                try:
                    rsp.step(timeout=10.0)
                    print("[a1] RSP step 成功")
                    results.append(("rsp_step", True))
                except Exception as exc:  # noqa: BLE001
                    print("[a1] RSP step 失败: %r" % (exc,))
                    results.append(("rsp_step", False))
        except Exception as exc:  # noqa: BLE001
            print("[a1] RSP 通路异常: %r" % (exc,))
            results.append(("rsp_registers", False))
            results.append(("rsp_read_memory", False))
            results.append(("rsp_breakpoint", False))
            results.append(("rsp_step", False))
    finally:
        cap.close()
        qemu_debug.kill_existing()

    print("")
    for name, ok in results:
        print("  %-16s %s" % (name, "ok" if ok else "FAIL"))
    bad = [n for n, ok in results if not ok]
    print("")
    print("PASS: debug_path_check" if not bad else "FAIL: debug_path_check -> " + ", ".join(bad))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
