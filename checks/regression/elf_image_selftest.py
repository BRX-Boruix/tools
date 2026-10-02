#!/usr/bin/env python3
"""离线自检：`tools_build/elf_image.py`（PRE-3，**不需要 QEMU**）。

为什么需要：与 `iso9660.py` 同类 —— **纯二进制解析器**，此前没有任何测试。
解析器错了不会崩，会**静默返回错误的符号/地址结论**。

做法：合成最小 ELF64 走**公开 API**（`parse` / `section_names` / `section` / `segments`），
重点覆盖**拒绝路径**—— 与 `iso9660_selftest.py` 同一套路。

**范围声明**：只测本文件已核实的行为。`read_vaddr` / `symbols` / `resolve` 的语义
我没有逐行读过，**因此不在此断言**—— 不猜语义、不写"看起来对"的测试。

退出码：0 = 全部通过；1 = 有失败。
"""

import os
import struct
import sys

TOOLS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, TOOLS_ROOT)

from tools_build import elf_image  # noqa: E402

ELF64_HEADER = "<16sHHIQQQIHHHHHH"
PT_LOAD = 1
SHT_NULL = 0
SHT_STRTAB = 3


def build_elf(*, magic_class=2, data_encoding=1, phnum=1, shnum=2, truncate=0,
              bad_phoff=False, bad_shoff=False):
    """合成最小 ELF64：1 个 PT_LOAD 程序头 + NULL/`.shstrtab` 两个节头。"""
    ident = bytearray(16)
    ident[0:4] = elf_image.ELF_MAGIC
    ident[4] = magic_class
    ident[5] = data_encoding
    ident[6] = 1  # EI_VERSION

    shstr = b"\x00.shstrtab\x00"
    shstr_off = 0x100
    phoff = 64
    shoff = 64 + 56 * phnum
    shstr_index = 1 if shnum > 1 else 0

    header = struct.pack(
        ELF64_HEADER,
        bytes(ident),
        2,      # ET_EXEC
        62,     # EM_X86_64
        1,
        0x400000,   # e_entry
        # **越界必须是"无歧义地超出映像"**：我第一次把 `e_phoff` 设成 0 ——
        # 那不是越界，只是从头开始读，于是断言"没报错"。用远超映像的值。
        0x1_0000 if bad_phoff else phoff,
        0x1_0000 if bad_shoff else shoff,
        0, 64, 56, phnum, 64, shnum, shstr_index,
    )
    assert len(header) == 64, len(header)

    blob = bytearray(header)
    for _ in range(phnum):
        blob += struct.pack("<IIQQQQQQ", PT_LOAD, 5, 0x200, 0x400000, 0x400000, 8, 8, 0x1000)
    for index in range(shnum):
        if index == 0:
            blob += struct.pack("<IIQQQQIIQQ", 0, SHT_NULL, 0, 0, 0, 0, 0, 0, 0, 0)
        else:
            blob += struct.pack("<IIQQQQIIQQ", 1, SHT_STRTAB, 0, 0, shstr_off, len(shstr), 0, 0, 1, 0)
    if len(blob) < shstr_off:
        blob += bytes(shstr_off - len(blob))
    blob += shstr
    if truncate:
        blob = blob[:len(blob) - truncate]
    return bytes(blob)


def main() -> int:
    failures = []

    def check(label, condition, detail=""):
        if condition:
            print("  ok   " + label)
        else:
            print("  FAIL " + label + ("  " + detail if detail else ""))
            failures.append(label)

    def rejects(label, action):
        # **`parse` 是惰性的**：它只校验 ELF 文件头，节头/程序头的越界要到
        # `section_names()` / `segments()` 被**访问**时才检查。
        # 我第一次写这个测试时以为 `parse` 校验一切，于是三项都"没报错" ——
        # **那是我的断言错，不是实现错**。所以这里收一个**动作**而不是数据。
        try:
            action()
        except elf_image.ElfError:
            check(label, True)
            return
        except Exception as exc:  # noqa: BLE001
            check(label, False, "抛了别的异常: %r" % exc)
            return
        check(label, False, "**没有报错**")

    print("== 正常解析 ==")
    image = elf_image.ElfImage.parse(build_elf())
    check("e_entry 解析正确", image.entry == 0x400000, "实得 %#x" % image.entry)
    check("e_machine 解析正确", image.machine == 62, "实得 %r" % image.machine)
    check("节名可读", ".shstrtab" in image.section_names(), "实得 %r" % (image.section_names(),))
    check("按名取节成功", image.section(".shstrtab") is not None)
    check("**取不存在的节返回 None**（不是异常）", image.section(".nosuch") is None)
    segs = image.segments()
    check("段数量正确", len(segs) == 1, "实得 %d" % len(segs))
    check("段类型是 PT_LOAD", segs[0].type == PT_LOAD, "实得 %r" % segs[0].type)

    print("== 拒绝坏数据 ==")
    # 「太短」= 短于 ELF 文件头本身（64 字节），`parse` 立刻拒绝。
    rejects("数据短于文件头 -> ElfError", lambda: elf_image.ElfImage.parse(build_elf()[:40]))
    rejects("魔数不对 -> ElfError", lambda: elf_image.ElfImage.parse(b"NOTELF" + build_elf()[6:]))
    rejects("ELFCLASS32 -> ElfError", lambda: elf_image.ElfImage.parse(build_elf(magic_class=1)))
    rejects("大端 -> ElfError", lambda: elf_image.ElfImage.parse(build_elf(data_encoding=2)))
    # 程序头偏移指向映像之外 —— **只有访问 `segments()` 才会发现**。
    rejects("程序头偏移越界 -> ElfError（访问时发现）",
            lambda: elf_image.ElfImage.parse(build_elf(bad_phoff=True)).segments())

    print("== 边界：节头越界 ==")
    # 声明 4 个节头，但映像里只放了 2 个 —— 必须报错，不能返回部分结果。
    rejects("节头偏移越界 -> ElfError（访问时发现）",
            lambda: elf_image.ElfImage.parse(build_elf(bad_shoff=True)).section_names())

    if failures:
        print("FAIL: %d 项未通过" % len(failures))
        return 1
    print("PASS: elf_image 离线自检全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
