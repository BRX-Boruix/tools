#!/usr/bin/env python3
"""阶段 1（分发解耦）的端到端检查：3P1-2/3/4/5/6。

在**工作区之外的空目录**里验证三件事：
  1. `install --prefix` 产出完整 sysroot；
  2. C：一条 `boruix-clang hello.c` 编出可运行 ELF；
  3. Rust：`b3p --new` 生成骨架，`cargo build` 编过。

并对两条路径的产物断言**加载器硬约束**：PT_LOAD 段**页级不重叠**。
（曾因 `ld.lld` 默认 `-z relro` 把 RW 段拆成两个共享同一页的 PT_LOAD，内核按页映射两次
返回 AlreadyExists(17)，表现为大程序无法装载——小数据程序不生成 RELRO，故长期未暴露。）

用法: python tools/checks/dist/sysroot_e2e.py [--keep]
退出码 0 = 通过。不启动 QEMU（运行时验收另由 BORUIX_INIT_RUN 通道覆盖）。
"""
import argparse
import os
import shutil
import struct
import subprocess
import sys
import tempfile

# 本文件位于 <root>/tools/checks/dist/ —— 由自身位置推导项目根，与 cwd 无关。
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))

HELLO_C = """#include <stdio.h>

int main(void) {
    printf("hello from sysroot\\n");
    return 0;
}
"""


def run(cmd, cwd, label):
    r = subprocess.run(cmd, cwd=cwd)
    if r.returncode != 0:
        print("[FAIL] " + label + "（退出码 %d）" % r.returncode)
        sys.exit(1)


def page_overlap_ok(path):
    """返回 (段数, 页级不重叠?)。ELF64 little-endian 的最小解析，只读程序头。"""
    d = open(path, "rb").read()
    e_phoff, = struct.unpack_from("<Q", d, 32)
    e_phentsize, e_phnum = struct.unpack_from("<HH", d, 54)
    segs = []
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        p_type, _p_flags = struct.unpack_from("<II", d, off)
        _po, p_vaddr, _pa, _pf, p_memsz, _al = struct.unpack_from("<QQQQQQ", d, off + 8)
        if p_type == 1:  # PT_LOAD
            segs.append((p_vaddr & ~0xFFF, (p_vaddr + p_memsz + 0xFFF) & ~0xFFF))
    ok = all(segs[i][1] <= segs[i + 1][0] for i in range(len(segs) - 1))
    return len(segs), ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="保留临时目录（排查用）")
    args = ap.parse_args()

    work = tempfile.mkdtemp(prefix="boruix-sysroot-e2e-")
    prefix = os.path.join(work, "sysroot")
    try:
        print("[1/3] install --prefix ...")
        run([sys.executable, os.path.join(ROOT, "tools", "main.py"),
             "install", "--prefix", prefix], ROOT, "install")
        for rel in ("cargo-config.toml", "boruix.json", os.path.join("lib", "libc.a"),
                    os.path.join("lib", "linker.ld"), os.path.join("lib", "user_main.o"),
                    os.path.join("bin", "boruix-clang")):
            if not os.path.isfile(os.path.join(prefix, rel)):
                print("[FAIL] sysroot 缺少 " + rel)
                return 1

        print("[2/3] C: boruix-clang hello.c ...")
        cdir = os.path.join(work, "cproj")
        os.makedirs(cdir)
        with open(os.path.join(cdir, "hello.c"), "w", encoding="utf-8") as f:
            f.write(HELLO_C)
        run([sys.executable, os.path.join(prefix, "bin", "boruix-clang"), "hello.c"],
            cdir, "C 编译")
        n, ok = page_overlap_ok(os.path.join(cdir, "hello.elf"))
        if not ok:
            print("[FAIL] C 产物 PT_LOAD 页级重叠（%d 段）——加载器会 AlreadyExists(17)" % n)
            return 1
        print("      C ELF: %d 个 LOAD 段，页级不重叠 OK" % n)

        print("[3/3] Rust: b3p --new + cargo build ...")
        rdir = os.path.join(work, "rproj")
        os.makedirs(rdir)
        run([sys.executable, os.path.join(ROOT, "tools", "main.py"), "b3p",
             "--new", "e2eprobe", "--sysroot", prefix, "--dir", rdir], ROOT, "b3p --new")
        proj = os.path.join(rdir, "e2eprobe")
        for rel in ("Cargo.toml", os.path.join("src", "main.rs"),
                    os.path.join(".cargo", "config.toml")):
            if not os.path.isfile(os.path.join(proj, rel)):
                print("[FAIL] 骨架缺少 " + rel)
                return 1
        if os.path.isfile(os.path.join(proj, "build.rs")) or \
           os.path.isfile(os.path.join(proj, "linker.ld")):
            print("[FAIL] 骨架不该包含 build.rs / linker.ld")
            return 1
        run(["cargo", "build"], proj, "Rust 编译")
        elf = os.path.join(proj, "target", "boruix", "debug", "e2eprobe")
        if not os.path.isfile(elf):
            print("[FAIL] 未找到 Rust 产物: " + elf)
            return 1
        n, ok = page_overlap_ok(elf)
        if not ok:
            print("[FAIL] Rust 产物 PT_LOAD 页级重叠（%d 段）" % n)
            return 1
        print("      Rust ELF: %d 个 LOAD 段，页级不重叠 OK" % n)

        print("[OK] 阶段 1 分发解耦检查通过")
        return 0
    finally:
        if args.keep:
            print("（保留临时目录: " + work + "）")
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())