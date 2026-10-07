#!/usr/bin/env python3
"""头文件语法门：每个公开头文件**单独**过一遍宿主 clang 的 `-fsyntax-only`。

## 为什么需要（真实教训，5 秒 vs 7 分钟）

2026-10：`wordexp.h` 里我把 `wordexp_t` 打成了 `worddexp_t`。这个错**只在系统内 tcc 编译时**
才暴露（`wordexp.h:36: error: ',' expected (got '*')`），而我为此跑了整整一轮 QEMU（构建 + 启动
≈ 7 分钟）才发现。用宿主 clang 做一次纯语法检查**只要 5 秒**——同一个错立刻现形。

## 做法

对 sysroot 里每个 `*.h`，生成一个只 `#include` 它的临时 TU，用宿主 clang
`--target=x86_64-unknown-none -ffreestanding -nostdinc -I <sysroot>/include -fsyntax-only` 过一遍。
**每个头单独一个 TU**：这样测的是「该头能否独立被包含」，而不是头与头之间的偶然组合。

**不加 `-nostdinc`**：有些头**合法依赖编译器内置头**（`inttypes.h` 就 `#include <stdint.h>`，
由编译器提供）。首版加了 `-nostdinc`，于是把 `inttypes.h` 误报成失败——门自己先要正确。
`-I <sysroot>/include` 仍排在搜索序最前，故我们 libc 的头优先于内置同名头（与真实构建一致）。

**诚实边界**：语法正确 ≠ 与 Rust 侧的 `#[repr(C)]` 布局一致，也 ≠ 行为正确。
本门只挡「拼写/缺类型/自相矛盾的声明」这一类——它们恰好是最容易犯、又最贵的错。

**本门查不出的（如实声明，2026-10 实测）**：
  - **缺宏**：我给 `errno.rs` 加了 `ENOSYS` 却忘了同步 `include/errno.h`——头文件本身语法完好，
    本门全绿，直到 `libcc1.c` 用 tcc 编译时才报 `'ENOSYS' undeclared`。
    这类「C 程序用到的宏没定义」只能靠**真实 C 程序**（`tools/3psrc/libcc1`）挡。
  - **Rust/C 两侧布局不一致**（两边各自都能编译）。
故本门与「系统内运行时验收」是**互补**的两道，不是替代关系。

用法:
    set BORUIX_SYSROOT=<install --prefix 的产物>
    python tools/checks/dist/headers_syntax.py [--sysroot <dir>] [--clang <exe>]
退出码: 0 = 全部通过；1 = 有头文件过不了；2 = 参数/工具问题。
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sysroot", default=os.environ.get("BORUIX_SYSROOT"))
    ap.add_argument("--clang", default=os.environ.get("BORUIX_CLANG") or shutil.which("clang"))
    a = ap.parse_args()
    if not a.sysroot or not os.path.isdir(a.sysroot):
        print("[FAIL] 需要 --sysroot（或 BORUIX_SYSROOT）指向已安装的 sysroot")
        return 2
    if not a.clang:
        print("[FAIL] 找不到 clang（可用 --clang / BORUIX_CLANG 指定）")
        return 2
    inc = os.path.join(a.sysroot, "include")
    if not os.path.isdir(inc):
        print("[FAIL] sysroot 里没有 include/: " + inc)
        return 2

    headers = []
    for root, _dirs, files in os.walk(inc):
        for f in files:
            if f.endswith(".h"):
                rel = os.path.relpath(os.path.join(root, f), inc).replace(os.sep, "/")
                headers.append(rel)
    headers.sort()

    bad = []
    with tempfile.TemporaryDirectory(prefix="boruix-hdr-") as work:
        for rel in headers:
            src = os.path.join(work, "probe.c")
            with open(src, "w", encoding="utf-8", newline="\n") as f:
                f.write("#include <%s>\nint boruix_probe_%s;\n" % (rel, rel.replace("/", "_").replace(".", "_")))
            r = subprocess.run(
                [a.clang, "--target=x86_64-unknown-none", "-ffreestanding",
                 "-I", inc, "-fsyntax-only", src],
                capture_output=True, text=True, errors="replace",
            )
            if r.returncode != 0:
                bad.append((rel, r.stderr.strip().splitlines()[:3]))

    print("[headers] 检查 %d 个头文件（各一个 TU）" % len(headers))
    if not bad:
        print("[OK] 全部通过")
        return 0
    print("[FAIL] %d 个头文件过不了：" % len(bad))
    for rel, lines in bad:
        print("    " + rel)
        for ln in lines:
            print("        " + ln)
    return 1


if __name__ == "__main__":
    sys.exit(main())
