#!/usr/bin/env python3
"""诊断模块的离线自检：不启动 QEMU 也能验证的部分。

覆盖 `tools_build/qemu_debug.py` 里可以脱离硬件验证的逻辑——RSP 校验和、PPM->PNG
转换、以及**畸形输入必须报错**（S09：宁可报错，绝不返回伪数据）。

需要真实 QEMU 的部分（HMP 命令、RSP 断点/单步、screendump）不在这里假装验证：
它们的证据来自真机运行，写进 docs/TODO/liftoff.md 的排查记录里。

退出码：0 全通过，1 有失败。
"""

import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools_build import qemu_debug


def _check_checksums() -> None:
    cases = [
        (b"", b"00"),
        (b"g", b"67"),
        # 真实用过的断点包：在内核入口 0xffffffff800378d0 下断点。
        (b"Z0,ffffffff800378d0,4", None),
    ]
    for payload, expected in cases:
        got = qemu_debug.rsp_checksum(payload)
        if expected is not None and got != expected:
            raise AssertionError("校验和 %r: 期望 %r 实得 %r" % (payload, expected, got))
        if len(got) != 2 or any(c not in b"0123456789abcdef" for c in got):
            raise AssertionError("校验和不是两位小写十六进制: %r" % got)
    print("  RSP 校验和: %d 例通过" % len(cases))


def _check_ppm_to_png() -> None:
    width, height = 2, 1
    pixels = bytes([10, 20, 30, 40, 50, 60])
    ppm = b"P6\n%d %d\n255\n" % (width, height) + pixels
    png = qemu_debug.ppm_to_png(ppm)
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AssertionError("PNG 签名不对")
    chunks = {}
    pos = 8
    while pos < len(png):
        length = struct.unpack_from(">I", png, pos)[0]
        tag = png[pos + 4:pos + 8]
        body = png[pos + 8:pos + 8 + length]
        crc = struct.unpack_from(">I", png, pos + 8 + length)[0]
        if crc != (zlib.crc32(tag + body) & 0xFFFFFFFF):
            raise AssertionError("chunk %r 的 CRC 不符" % tag)
        chunks[tag] = body
        pos += 12 + length
    got = struct.unpack_from(">IIBB", chunks[b"IHDR"], 0)
    if got != (width, height, 8, 2):
        raise AssertionError("IHDR 不符: %r" % (got,))
    if zlib.decompress(chunks[b"IDAT"]) != b"\x00" + pixels:
        raise AssertionError("IDAT 解出的扫描线与原像素不一致")
    print("  PPM->PNG: %dx%d 往返逐字节相同，chunk CRC 全对" % (width, height))


def _check_malformed_rejected() -> None:
    # 非 P6、非 8 位、像素不足：三种畸形都必须抛错，不得返回「看起来能用」的 PNG。
    bad_inputs = [
        b"P5\n1 1\n255\n\x00",
        b"P6\n2 1\n65535\n\x00\x00",
        b"P6\n2 1\n255\n\x00",
    ]
    for bad in bad_inputs:
        try:
            qemu_debug.ppm_to_png(bad)
        except qemu_debug.QemuDebugError:
            continue
        raise AssertionError("畸形 PPM 未报错: %r" % bad)
    print("  畸形 PPM: %d 例全部报错" % len(bad_inputs))


def main() -> int:
    failures = []
    for name, fn in (("RSP 校验和", _check_checksums),
                     ("PPM->PNG", _check_ppm_to_png),
                     ("畸形输入拒绝", _check_malformed_rejected)):
        try:
            fn()
        except AssertionError as exc:
            failures.append("%s: %s" % (name, exc))
    if failures:
        for item in failures:
            print("FAIL " + item)
        return 1
    print("诊断模块离线自检通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
