#!/usr/bin/env python3
"""PRE-2 附：把 `tools_build/qemu_debug.py` 的**三条真机通路**各走一遍。

- **HMP**（QEMU monitor over TCP）：发一条 HMP 命令并取回真实输出；
- **RSP**（gdb stub）：读寄存器、**按找到的代码地址**读内存 / 下断点 / 单步；
- **screendump**：HMP 截屏 → ppm → png。

**为什么需要它**：这些能力此前只在**临时脚本**里验证过 ✗，提升成正式模块之后
**没有在真机上跑过** ✓ —— 于是"它到底能不能用"没有证据 ✗。本检查给出真实输出，
逐条 PASS/FAIL，而不是"看起来对" ✓。

**第 135 轮实测得到的两条事实，直接决定了本脚本怎么写** ✓：
1. `RspClient.registers()` 返回**扁平整数列表**（76 项），**没有名字** ✗ ——
   所以**不能**按 `rip` 取，只能**按值的范围**找出代码地址 ✓。
2. `MonitorClient.command()` 的回包**含终端回显与 `[K`/`[D` 噪声** ✗ ——
   必须剥离后再断言，否则判据很脆弱 ✓。
"""
import os
import re
import sys

_TOOLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
from tools_build import config, liftoff, qemu_debug  # noqa: E402

MARKER = b"username:"
GDB_PORT = qemu_debug.DEFAULT_GDB_PORT
MON_PORT = 45454
# 内核代码段的高半区（本会话实测内核入口在 0xffffffff800378d0 附近）✓。
KERNEL_LOW = 0xFFFF_FFFF_8000_0000
KERNEL_HIGH = 0xFFFF_FFFF_FFFF_FFFF

_ECHO = re.compile(r"\[K|\[D|\x1b\[[0-9;]*[A-Za-z]")


def clean_hmp(text: str) -> str:
    """剥掉 HMP 回包里的终端回显与转义噪声（**纯逻辑** ✓）。"""
    return _ECHO.sub("", text)


def find_code_address(regs) -> int:
    """在**没有名字**的扁平寄存器列表里找出一个代码地址（**纯逻辑** ✓）。

    取第一个落在内核高半区的值；找不到就退到索引 16（x86-64 的 g-packet 里 `rip` 的位置）✓。
    两个都拿不到就返回 0，由调用方如实报"找不到"，**不编一个地址** ✗。
    """
    for value in regs:
        if isinstance(value, int) and KERNEL_LOW <= value <= KERNEL_HIGH:
            return value
    if len(regs) > 16 and isinstance(regs[16], int):
        return regs[16]
    return 0


def main() -> int:
    qemu_debug.kill_existing()
    esp = liftoff.ensure_ready()
    cmd = ([liftoff.qemu_exe(), "-m", "1024", "-smp", "1", "-display", "none",
            "-serial", "stdio", "-cdrom", config.OUTPUT_ISO]
           + config.sound_card_args(silent=True)
           + liftoff.uefi_args(esp)
           + ["-s", "-monitor", "tcp:127.0.0.1:%d,server,nowait" % MON_PORT])
    # **用字典记账** ✓ —— 第 135 轮我用列表，异常分支把同一个名字记了两次 ✗，
    # 于是汇总里同一项既 ok 又 FAIL ✗。字典从结构上不可能重复 ✓。
    results = {}
    cap = qemu_debug.SerialCapture(cmd)
    try:
        seen = cap.wait_for(MARKER, 420)
        print("[a1] 串口到达 %s: %s" % (MARKER.decode(), seen))
        results["serial"] = seen

        # --- HMP ---
        try:
            with qemu_debug.MonitorClient(port=MON_PORT) as mon:
                raw = mon.command("info registers", wait_s=2.0)
                out = clean_hmp(raw)
                tail = " | ".join(line.strip() for line in out.splitlines() if line.strip())
                print("[a1] HMP info registers（已剥离噪声）-> " + tail[:400])
                results["hmp"] = "RIP" in out
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
                    print("[a1] screendump -> ppm %d B -> png %d B" % (len(ppm), len(png)))
                    results["screendump"] = len(png) > 0
                else:
                    results["screendump"] = False
        except Exception as exc:  # noqa: BLE001
            print("[a1] HMP 通路异常: %r" % (exc,))
            results.setdefault("hmp", False)
            results.setdefault("screendump", False)

        # --- RSP ---
        try:
            with qemu_debug.RspClient.connect(port=GDB_PORT) as rsp:
                regs = rsp.registers()
                print("[a1] RSP registers 条数=%d" % len(regs))
                results["rsp_registers"] = len(regs) > 0
                pc = find_code_address(regs)
                print("[a1] RSP 按值找到代码地址 = %#x" % pc)
                results["rsp_find_pc"] = pc != 0
                if pc:
                    mem = rsp.read_memory(pc, 16)
                    print("[a1] RSP read_memory(%#x,16) = %s" % (pc, mem.hex()))
                    results["rsp_read_memory"] = len(mem) == 16
                    hit = rsp.set_breakpoint(pc, 4)
                    print("[a1] RSP set_breakpoint(%#x) = %s" % (pc, hit))
                    results["rsp_breakpoint"] = bool(hit)
                    rsp.continue_()
                    stopped = rsp.wait_for_stop(5.0)
                    print("[a1] RSP continue + wait_for_stop(5s) = %s" % stopped)
                    try:
                        rsp.step(timeout=10.0)
                        print("[a1] RSP step 成功")
                        results["rsp_step"] = True
                    except Exception as exc:  # noqa: BLE001
                        print("[a1] RSP step 失败: %r" % (exc,))
                        results["rsp_step"] = False
                else:
                    results["rsp_read_memory"] = False
                    results["rsp_breakpoint"] = False
                    results["rsp_step"] = False
        except Exception as exc:  # noqa: BLE001
            print("[a1] RSP 通路异常: %r" % (exc,))
            for name in ("rsp_registers", "rsp_find_pc", "rsp_read_memory", "rsp_breakpoint", "rsp_step"):
                results.setdefault(name, False)
    finally:
        cap.close()
        qemu_debug.kill_existing()

    print("")
    for name, ok in results.items():
        print("  %-18s %s" % (name, "ok" if ok else "FAIL"))
    bad = [n for n, ok in results.items() if not ok]
    print("")
    print("PASS: debug_path_check" if not bad else "FAIL: debug_path_check -> " + ", ".join(bad))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
