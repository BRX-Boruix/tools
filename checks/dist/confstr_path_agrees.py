#!/usr/bin/env python3
"""门禁：libc 的 confstr(_CS_PATH) 必须与 shell 的 DEFAULT_PATH 逐字节一致。

为什么需要它：这是两处真值源（libc 的 confstr 与 shell 的 env.rs）。本项初版写的是
/programs:/bin 并声称「与 shell/init 的约定一致」——那句话是假的，值是编的
（项目所有者质疑 ttyname 的同类问题后全面复查时抓出）。

## 2026-10-14 起的判据变化

两侧现在都由 tools/abi/constants.json 的 tokens 节**生成**（tools/abi/generate.py），
故本项不再从手写源码里抠字面量，改为查**接线**：

  1. libc 的 confstr 必须引用 crate::abi_generated::DEFAULT_PATH_C；
  2. shell 的 env.rs 必须引用 crate::abi_generated::DEFAULT_PATH；
  3. 两侧**生成物**里的字节串必须逐字节相同（libc 那份带结尾 NUL）。

第 3 条才是真正的内容核对——第 1、2 条只保证没人绕过生成物。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
LIBC_HAND = os.path.join(ROOT, "libc", "src", "posix_batch7.rs")
SHELL_HAND = os.path.join(ROOT, "shell", "src", "env.rs")
LIBC_GEN = os.path.join(ROOT, "libc", "src", "abi_generated.rs")
SHELL_GEN = os.path.join(ROOT, "shell", "src", "abi_generated.rs")


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def main():
    libc_h, shell_h = read(LIBC_HAND), read(SHELL_HAND)
    if not re.search(r"1 => crate::abi_generated::DEFAULT_PATH_C,", libc_h):
        print("[confstr-path] FAIL: libc 的 confstr 未委托 crate::abi_generated::DEFAULT_PATH_C")
        return 1
    if not re.search(r"DEFAULT_PATH: &\[u8\] = crate::abi_generated::DEFAULT_PATH;", shell_h):
        print("[confstr-path] FAIL: shell 的 DEFAULT_PATH 未委托 crate::abi_generated::DEFAULT_PATH")
        return 1

    libc_g, shell_g = read(LIBC_GEN), read(SHELL_GEN)
    m1 = re.search(r'pub const DEFAULT_PATH_C: &\[u8\] = b"([^"]*)\\0";', libc_g)
    m2 = re.search(r'pub\(crate\) const DEFAULT_PATH: &\[u8\] = b"([^"]*)";', shell_g)
    if not m1 or not m2:
        print("[confstr-path] FAIL: 解析不出两侧生成物里的默认 PATH")
        return 1
    a, b = m1.group(1), m2.group(1)
    if a != b:
        print("[confstr-path] FAIL: 两侧生成物漂移（本不该发生——它们出自同一份 JSON）")
        print("  libc  DEFAULT_PATH_C = %r" % a)
        print("  shell DEFAULT_PATH   = %r" % b)
        return 1
    print("[confstr-path] OK: 两侧生成物一致；confstr(_CS_PATH) == shell PATH == %r" % a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
