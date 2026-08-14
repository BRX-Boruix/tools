#!/usr/bin/env python3
"""从 qemu-efi-aarch64 .deb 包中提取 QEMU_EFI.fd 固件。

用法: python extract_firmware.py <path_to.deb>
"""
import os
import shutil
import struct
import sys
import tarfile

AR_MAGIC = b"!<arch>\n"


def ar_members(path):
    """解析 ar 归档，yield (name, data_bytes)。"""
    with open(path, "rb") as f:
        assert f.read(8) == AR_MAGIC, "不是 ar 归档"
        while True:
            header = f.read(60)
            if len(header) < 60:
                break
            name = header[0:16].decode().strip()
            size_str = header[48:58].decode().strip()
            size = int(size_str)
            data = f.read(size)
            # ar 成员按 2 字节对齐
            if size % 2 == 1:
                f.read(1)
            yield name, data


def main():
    if len(sys.argv) < 2:
        print("用法: python extract_firmware.py <path_to.deb>")
        return 1
    deb = sys.argv[1]
    workdir = os.path.dirname(os.path.abspath(__file__))
    tmp = os.path.join(workdir, "_deb_tmp")
    os.makedirs(tmp, exist_ok=True)

    data_tar = None
    for name, data in ar_members(deb):
        if name == "data.tar.xz":
            data_tar = os.path.join(tmp, "data.tar.xz")
            with open(data_tar, "wb") as w:
                w.write(data)
            print(f"提取 {name} ({len(data)} bytes)")

    if data_tar is None:
        print("未找到 data.tar.xz")
        return 1

    # 从 data.tar.xz 中提取 QEMU_EFI.fd
    dest = os.path.join(workdir, "firmware")
    os.makedirs(dest, exist_ok=True)
    found = False
    with tarfile.open(data_tar) as t:
        for m in t.getmembers():
            if m.name.endswith("QEMU_EFI.fd"):
                src = t.extractfile(m)
                target = os.path.join(dest, "QEMU_EFI.fd")
                with open(target, "wb") as w:
                    shutil.copyfileobj(src, w)
                print(f"提取固件 -> {target} ({m.size} bytes)")
                found = True

    shutil.rmtree(tmp, ignore_errors=True)
    if not found:
        print("未找到 QEMU_EFI.fd")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
