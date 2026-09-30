#!/usr/bin/env python3
"""PRE-1: ADR-051 的汇编离线核对（进入 QEMU 之前的门禁）。

做法：找到最近的 UEFI 目标汇编产物（dev profile 才含机器码），用 llvm-objdump 反汇编，
核对**语义上必须存在**的指令，并打印实际出现的相关指令供人工复核。

退出码：0 = 必需指令全部命中；1 = 有缺失（不得进入 QEMU）。
"""

import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3] / 'liftoff'
TARGET = REPO / 'target' / 'x86_64-unknown-uefi'

# 语义上必须存在的指令：平台停机、中断开关、串口读写。
REQUIRED = {
    'hlt': 'Platform::halt 的停机循环',
    'cli': 'Platform::disable_interrupts',
    'sti': 'Platform::restore_interrupts',
    'out': '串口输出 outb',
    'in': '串口状态读取 inb',
}


def find_object() -> Path | None:
    """最近的**最终** UEFI 映像（`.efi`）——核对真正上线的机器码，而非中间目标文件。"""
    candidates = [p for p in TARGET.glob('**/*.efi') if p.stat().st_size > 0]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def find_objdump() -> str | None:
    """llvm-objdump（随 llvm-tools 组件安装，通常不在 PATH 上）。"""
    from shutil import which
    found = which('llvm-objdump')
    if found:
        return found
    root = Path(os.environ.get('USERPROFILE', '')) / '.rustup' / 'toolchains'
    for p in root.rglob('llvm-objdump.exe'):
        return str(p)
    return None


def main() -> int:
    obj = find_object()
    if obj is None:
        print('FAIL: 找不到 .efi 产物，请先 cargo build --target x86_64-unknown-uefi')
        return 1
    objdump = find_objdump()
    if objdump is None:
        print('FAIL: 找不到 llvm-objdump（需要 rustup component add llvm-tools）')
        return 1
    out = subprocess.run([objdump, '-d', '--no-show-raw-insn', str(obj)],
                         capture_output=True, text=True)
    if out.returncode != 0:
        print('FAIL: llvm-objdump 失败: ' + out.stderr[:200])
        return 1
    disasm = out.stdout
    print('产物: ' + str(obj.relative_to(REPO)))
    missing = []
    for mnemonic, why in REQUIRED.items():
        hits = re.findall(r'\b' + mnemonic + r'\b', disasm)
        if hits:
            print('  OK   ' + mnemonic.ljust(4) + ' x' + str(len(hits)).ljust(3) + '  ' + why)
        else:
            print('  MISS ' + mnemonic.ljust(4) + '      ' + why)
            missing.append(mnemonic)
    if missing:
        print('FAIL: 缺失必需指令: ' + ', '.join(missing))
        return 1
    print('PASS: 必需指令全部命中（' + str(len(REQUIRED)) + ' 项）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
