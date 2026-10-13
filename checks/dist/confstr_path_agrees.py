#!/usr/bin/env python3
"""门禁：libc 的 confstr(_CS_PATH) 必须与 shell 的 DEFAULT_PATH 逐字节一致。

为什么需要它：这是两处真值源（libc 的 confstr 与 shell 的 env.rs），违反 S13 单点定义。
本项初版写的是 /programs:/bin 并声称「与 shell/init 的约定一致」——那句话是假的，值是编的
（项目所有者质疑 ttyname 的同类问题后全面复查时抓出）。与其让两处各自漂移，不如用门禁钉住。

判据：从两侧源码里解析出实际使用的字面量再比对（不解析源码就会变成"照抄期望值"）。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
LIBC = os.path.join(ROOT, "libc", "src", "posix_batch7.rs")
SHELL = os.path.join(ROOT, "shell", "src", "env.rs")


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def main():
    libc = read(LIBC)
    shell = read(SHELL)
    m1 = re.search(r"1 => b\"([^\"]+)\\0\"", libc)
    m2 = re.search(r"DEFAULT_PATH: &\[u8\] = b\"([^\"]+)\";", shell)
    if not m1:
        print("[confstr-path] FAIL: cannot parse _CS_PATH literal from libc/src/posix_batch7.rs")
        return 1
    if not m2:
        print("[confstr-path] FAIL: cannot parse DEFAULT_PATH literal from shell/src/env.rs")
        return 1
    a, b = m1.group(1), m2.group(1)
    if a != b:
        print("[confstr-path] FAIL: the two sources of truth have drifted")
        print("  confstr _CS_PATH  = %r" % a)
        print("  shell DEFAULT_PATH = %r" % b)
        return 1
    print("[confstr-path] OK: _CS_PATH == DEFAULT_PATH == %r" % a)
    return 0


if __name__ == "__main__":
    sys.exit(main())