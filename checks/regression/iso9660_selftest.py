#!/usr/bin/env python3
"""离线自检：`tools_build/iso9660.py`（PRE-3，**不需要 QEMU**）。

为什么需要：`iso9660.py` 是**纯二进制解析器**，而它此前**没有任何测试**。
解析器的错误不会崩 —— 它会**静默返回错误的字节**，然后被当成合法的符号/重定位结论
（该模块自己的文档里就记着这个教训：曾经把「内核在 LBA 33」写死成常量）。

做法：**合成一张最小 ISO**，走**公开 API**（`find_file` / `read_file`），
不测私有函数 —— 测真实路径。

退出码：0 = 全部通过；1 = 有失败（逐条打印）。
"""

import os
import struct
import sys
import tempfile

TOOLS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, TOOLS_ROOT)

from tools_build import iso9660  # noqa: E402

ROOT_LBA = 20
BOOT_LBA = 21
DATA_LBA = 22
PAYLOAD = b"ELF-ish payload, exact length matters"


def _both_u32(value):
    """ISO 的「双端序」字段：先小端后大端。"""
    return struct.pack("<I", value) + struct.pack(">I", value)


def _record(name, extent, size, is_dir=False):
    """造一个目录项（ECMA-119 9.1）。"""
    # 根目录项的名字是单个 0 字节，所以**两种输入都要收**（我第一次只收 str，撞了）。
    raw = name if isinstance(name, bytes) else name.encode("ascii")
    rec = bytearray(33 + len(raw))
    rec[0] = len(rec)
    rec[1] = 0
    rec[2:10] = _both_u32(extent)
    rec[10:18] = _both_u32(size)
    rec[18:25] = b"\x00" * 7
    rec[25] = 0x02 if is_dir else 0x00
    rec[26] = 0
    rec[27] = 0
    rec[28:32] = struct.pack("<H", 1) + struct.pack(">H", 1)
    rec[32] = len(raw)
    rec[33:] = raw
    return bytes(rec)


def build_iso(path, *, pvd_signature=None, break_dual_endian=False):
    """合成一张最小 ISO：根目录 -> BOOT/ -> KERNEL.;1。"""
    sector = iso9660.SECTOR_SIZE
    img = bytearray(24 * sector)

    pvd = bytearray(sector)
    pvd[0] = iso9660.TYPE_PRIMARY
    pvd[1:6] = pvd_signature if pvd_signature is not None else iso9660.VOLUME_ID
    root = _record(b"\x00", ROOT_LBA, sector, is_dir=True)
    if break_dual_endian:
        # 只改小端那一半 —— 两半不一致必须被拒绝，而不是取其中一半。
        root = bytearray(root)
        root[2:6] = struct.pack("<I", ROOT_LBA + 1)
        root = bytes(root)
    pvd[iso9660.PVD_ROOT_RECORD_OFFSET:iso9660.PVD_ROOT_RECORD_OFFSET + len(root)] = root
    img[iso9660.PVD_LBA * sector:(iso9660.PVD_LBA + 1) * sector] = pvd

    root_dir = bytearray(sector)
    entry = _record("BOOT", BOOT_LBA, sector, is_dir=True)
    root_dir[0:len(entry)] = entry
    img[ROOT_LBA * sector:(ROOT_LBA + 1) * sector] = root_dir

    boot_dir = bytearray(sector)
    entry = _record("KERNEL.;1", DATA_LBA, len(PAYLOAD))
    boot_dir[0:len(entry)] = entry
    img[BOOT_LBA * sector:(BOOT_LBA + 1) * sector] = boot_dir

    img[DATA_LBA * sector:DATA_LBA * sector + len(PAYLOAD)] = PAYLOAD
    with open(path, "wb") as handle:
        handle.write(bytes(img))


def main() -> int:
    failures = []

    def check(label, condition, detail=""):
        if condition:
            print("  ok   " + label)
        else:
            print("  FAIL " + label + ("  " + detail if detail else ""))
            failures.append(label)

    with tempfile.TemporaryDirectory() as tmp:
        good = os.path.join(tmp, "good.iso")
        build_iso(good)

        print("== 正常路径 ==")
        extent, size = iso9660.find_file(good, ["boot", "kernel"])
        check("find_file 返回正确的 extent", extent == DATA_LBA, "实得 %r" % extent)
        check("find_file 返回正确的长度", size == len(PAYLOAD), "实得 %r" % size)
        data = iso9660.read_file(good, ["boot", "kernel"])
        check("read_file 读出的字节完全一致", data == PAYLOAD)
        check("大小写不敏感", iso9660.find_file(good, ["BOOT", "KERNEL"]) == (DATA_LBA, len(PAYLOAD)))

        print("== 拒绝坏数据（不返回伪数据）==")
        def rejects(label, path, components):
            try:
                iso9660.find_file(path, components)
            except iso9660.IsoError:
                check(label, True)
                return
            except Exception as exc:  # noqa: BLE001
                check(label, False, "抛了别的异常: %r" % exc)
                return
            check(label, False, "**没有报错**")

        rejects("路径不存在 -> IsoError", good, ["boot", "nosuch"])
        rejects("把目录当文件 -> IsoError", good, ["boot"])
        rejects("把文件当目录 -> IsoError", good, ["boot", "kernel", "deeper"])
        rejects("空路径分量 -> IsoError", good, [])

        bad_sig = os.path.join(tmp, "badsig.iso")
        build_iso(bad_sig, pvd_signature=b"XXXXX")
        rejects("PVD 签名不符 -> IsoError", bad_sig, ["boot", "kernel"])

        bad_endian = os.path.join(tmp, "badendian.iso")
        build_iso(bad_endian, break_dual_endian=True)
        rejects("双端序两半不一致 -> IsoError", bad_endian, ["boot", "kernel"])

        print("== 截断的映像 ==")
        truncated = os.path.join(tmp, "trunc.iso")
        with open(good, "rb") as src, open(truncated, "wb") as dst:
            dst.write(src.read(iso9660.PVD_LBA * iso9660.SECTOR_SIZE + 10))
        rejects("映像不足一个逻辑块 -> IsoError", truncated, ["boot", "kernel"])

    if failures:
        print("FAIL: %d 项未通过" % len(failures))
        return 1
    print("PASS: iso9660 离线自检全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
