#!/usr/bin/env python3
"""PRE-1: ADR-051 的汇编离线核对（进入 QEMU 之前的门禁）。

做法：找到最近的 UEFI 目标汇编产物，用 llvm-objdump 反汇编，核对**语义上必须存在**的
指令与**必须按序出现**的指令序列。

退出码：0 = 全部命中；1 = 有缺失（不得进入 QEMU）。

为什么要检查序列：跳板里两处 64 位续接点必须由参数帧提供绝对地址。曾经写成标签差值
（mov ebx, 6f），LLVM 把它汇编成 RIP 相对**内存读取**，算出来是垃圾，retf 跳到未映射
地址 → #PF → #DF → 三重故障。单看助记符抓不到，只有按序核对才能抓住。
"""

import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3] / "liftoff"
TARGET = REPO / "target" / "x86_64-unknown-uefi"

# 语义上必须存在的指令 -> (最少出现次数, 说明)。
# llvm-objdump 默认 AT&T 语法：串口指令写作 outb/inb，远返回写作 lretq/lretl。
REQUIRED = {
    "hlt": (1, "Platform::halt 的停机循环"),
    "outb": (1, "串口初始化与输出"),
    "inb": (1, "串口发送前状态轮询"),
    "cli": (1, "跳板关中断（common64 第一条）"),
    "lgdtq": (2, "common64 与 spinup32 各加载一次自建 GDT"),
    "lidtq": (1, "common64 加载空 IDT"),
    "lretq": (2, "common64 的两次远返回：切 CS=0x28、切 CS=0x18"),
    "lretl": (1, "spinup32 从 32 位切回 64 位"),
    "lldtw": (1, "go32 清 LDT"),
    "ltrw": (1, "go32 加载空 TR"),
    "wrmsr": (2, "go32 清 EFER、spinup32 设 EFER.LME/NX"),
    "iretq": (1, "构造 iretq 帧进入内核"),
    "rep stosq": (1, "按 base_revision 卸掉低半区"),
    "movq %rax, %cr3": (1, "spinup32 载入内核页表"),
}

# 必须按此顺序出现的指令序列 -> 说明。
SEQUENCES = [
    (
        r"movl\s+0x2c\(%rsp\), %ebx[\s\S]{0,120}?"
        r"pushq\s+\$0x28[\s\S]{0,80}?"
        r"pushq\s+%rbx[\s\S]{0,80}?"
        r"lretl",
        "32->64 过渡：从参数帧槽 11 取绝对地址再 retf（不得用标签差值）",
    ),
    (
        r"pushq\s+\$0x18[\s\S]{0,80}?"
        r"pushq\s+%rdi[\s\S]{0,80}?"
        r"lretq",
        "64->32 过渡：retfq 到低地址 spinup_go32 拷贝",
    ),
    (
        r"pushq\s+\$0x28[\s\S]{0,80}?"
        r"pushq\s+%rbx[\s\S]{0,80}?"
        r"lretq",
        "common64 重载 CS=0x28",
    ),
]

# 允许缺失但需人工留意的指令。
REPORTED = {
    "sti": "Platform::restore_interrupts（跳板全程关中断，故意不出现）",
}


def find_object() -> Path | None:
    """最近的最终 UEFI 映像（.efi）—— 核对真正上线的机器码。"""
    candidates = [p for p in TARGET.glob("**/*.efi") if p.stat().st_size > 0]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def find_objdump() -> str | None:
    """llvm-objdump（随 llvm-tools 组件安装，通常不在 PATH 上）。"""
    from shutil import which
    found = which("llvm-objdump")
    if found:
        return found
    root = Path(os.environ.get("USERPROFILE", "")) / ".rustup" / "toolchains"
    for p in root.rglob("llvm-objdump.exe"):
        return str(p)
    return None


def main() -> int:
    obj = find_object()
    if obj is None:
        print("FAIL: 找不到 .efi 产物，请先 cargo build --target x86_64-unknown-uefi")
        return 1
    objdump = find_objdump()
    if objdump is None:
        print("FAIL: 找不到 llvm-objdump（需要 rustup component add llvm-tools）")
        return 1
    out = subprocess.run([objdump, "-d", "--no-show-raw-insn", str(obj)],
                         capture_output=True, text=True)
    if out.returncode != 0:
        print("FAIL: llvm-objdump 失败: " + out.stderr[:200])
        return 1
    # objdump 用多个制表符分隔助记符与操作数：把连续空白压成一个空格，
    # 否则 "rep stosq"、"movq %rax, %cr3" 这类模式匹配不到。
    disasm = re.sub(r"[ \t]+", " ", out.stdout)
    print("产物: " + str(obj.relative_to(REPO)))

    failed = []
    for mnemonic, (least, why) in REQUIRED.items():
        hits = len(re.findall(r"\b" + re.escape(mnemonic) + r"\b", disasm))
        if hits >= least:
            print("  OK   " + mnemonic.ljust(14) + " x" + str(hits).ljust(4) + " (需 " +
                  str(least) + ")  " + why)
        else:
            print("  MISS " + mnemonic.ljust(14) + " x" + str(hits).ljust(4) + " (需 " +
                  str(least) + ")  " + why)
            failed.append(mnemonic)

    for pattern, why in SEQUENCES:
        if re.search(pattern, disasm):
            print("  OK   [序列] " + why)
        else:
            print("  MISS [序列] " + why)
            failed.append("序列: " + why)

    for mnemonic, why in REPORTED.items():
        hits = len(re.findall(r"\b" + mnemonic + r"\b", disasm))
        print("  note " + mnemonic.ljust(14) + " x" + str(hits).ljust(4) + "  " + why)

    if failed:
        print("FAIL: 缺失必需项: " + "; ".join(failed))
        return 1
    print("PASS: 必需指令 " + str(len(REQUIRED)) + " 项 + 序列 " +
          str(len(SEQUENCES)) + " 项全部命中")
    return 0


if __name__ == "__main__":
    sys.exit(main())
