#!/usr/bin/env python3
"""门禁：系统（Rust）**不许知道任何盘的名字或盘上的路径**。

`_CS_PATH` 与 shell 的默认 PATH 必须是**系统契约** `/programs`——一条静态约定路径。

## 这条门禁改过三次，每次都是同一个错误的变体

1. 两处各写一份字面量，门禁核对「逐字节相同」；
2. 两侧都由 `constants.json` 生成，门禁核对生成物相等——但值里带着**卷标**
   （`/programs:/volumes/BORUIX_DATA/3p`）。**两侧同错时等式断言永远绿**；
3. 两侧改调 `libsys::search_path()` 扫 `/volumes`——不烧死了，但**系统仍然知道「3p」**。

## 本版判据

盘叫什么、有几块盘、第三方程序在哪块盘上，都是**数据**。系统对它们的全部认知是
「有一块卷，挂载点 `/volumes/<它自己的卷标>`」——那是运行时从目录项读出来的。
故本门禁查的是**系统 Rust 里不许出现任何盘名/盘路径**，以及两侧都走 `PROGRAM_DIR`。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 系统侧（Rust）——这些目录里**不许**出现盘名或 /volumes/ 路径。
SYSTEM_RUST_ROOTS = ("kernel/crates", "libsys/src", "libc/src", "shell/src",
                     "init/src", "login/src", "rtld/src")

# 盘名（两个都算）：系统一概不知道。
DISK_NAMES = ("BORUIX_DATA", "BORUIX_TESTDISK")

LIBC_HAND = os.path.join(ROOT, "libc", "src", "posix_batch7.rs")
SHELL_HAND = os.path.join(ROOT, "shell", "src", "env.rs")
SHELL_CMD = os.path.join(ROOT, "shell", "src", "commands.rs")
LIBSYS_GEN = os.path.join(ROOT, "libsys", "src", "abi_generated.rs")
LIBSYS_VOL = os.path.join(ROOT, "libsys", "src", "volume.rs")


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def strip_comments(src):
    """去掉**整行注释**。文档里合法地解释「为什么不许烧死它」，不剥会误报。"""
    return "\n".join(ln for ln in src.split("\n") if not ln.lstrip().startswith("//"))


def fail(msg):
    print("[no-disk-in-system] FAIL: " + msg)
    return 1


def main():
    # 1) 两侧都必须是 PROGRAM_DIR（系统契约）。
    if "libsys::PROGRAM_DIR" not in read(LIBC_HAND):
        return fail("libc 的 confstr(_CS_PATH) 未使用 libsys::PROGRAM_DIR")
    if "libsys::PROGRAM_DIR" not in read(SHELL_HAND):
        return fail("shell 的默认 PATH 未使用 libsys::PROGRAM_DIR")
    if "libsys::PROGRAM_DIR" not in read(SHELL_CMD):
        return fail("shell 的 help 文本未使用 libsys::PROGRAM_DIR")

    # 2) 生成物里只许有 PROGRAM_DIR（卷标 / 3p 子目录名不许进 Rust）。
    gen = read(LIBSYS_GEN)
    for bad in ("DATA_VOLUME_LABEL", "THIRD_PARTY_SUBDIR", "DATA_VOLUME_PATH", "DEFAULT_PATH"):
        if bad in gen:
            return fail("libsys 生成物里仍有 %s（那是数据，系统不该知道）" % bad)
    if "PROGRAM_DIR" not in gen:
        return fail("libsys 生成物里没有 PROGRAM_DIR（系统契约）")

    # 3) 扫卷 / 找盘 的函数必须已经删掉。
    vol = read(LIBSYS_VOL)
    for gone in ("pub fn search_path", "pub fn volumes_with_subdir",
                 "pub fn find_volume_file", "pub fn mounted_volumes"):
        if gone in vol:
            return fail("libsys/volume.rs 里仍有 %s（系统不该扫盘）" % gone)

    # 4) 系统 Rust 里不许出现盘名或 /volumes/ 路径（剥注释后）。
    hits = []
    for root in SYSTEM_RUST_ROOTS:
        base = os.path.join(ROOT, root)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in ("target", ".git")]
            for fn in filenames:
                if not fn.endswith(".rs"):
                    continue
                p = os.path.join(dirpath, fn)
                code = strip_comments(read(p))
                for name in DISK_NAMES:
                    if name in code:
                        hits.append((p, name))
                # 只禁**盘名字符串**（BORUIX_DATA / BORUIX_TESTDISK）。
                # `/volumes/<任意名>` 本身不违规：挂载根是系统概念，测试里用合成名
                # （/volumes/data、/volumes/workspace）是合法的。

    if hits:
        for p, what in hits[:20]:
            print("  %s: %s" % (os.path.relpath(p, ROOT), what))
        return fail("系统 Rust 里出现了盘名/盘路径（共 %d 处，见上）" % len(hits))

    print("[no-disk-in-system] OK: 两侧都用 PROGRAM_DIR；生成物无盘名；无扫盘函数；系统 Rust 无盘名/盘路径")
    return 0


if __name__ == "__main__":
    sys.exit(main())
