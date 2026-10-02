#!/usr/bin/env python3
"""离线自检：`tools_build/run.py` 的 `_smp_args`（PRE-3，**不需要 QEMU**）。

为什么需要：这个函数决定"给虚拟机几颗核" ✓ —— 而 **E1/S8 的判据就是
`total cpus=N` 必须等于这里给的 N** ✓。它此前内联在 `cmd()` 里、不可测 ✗。

退出码：0 = 全部通过；1 = 有失败。
"""

import os
import sys

TOOLS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, TOOLS_ROOT)

from tools_build import run  # noqa: E402


def main() -> int:
    failures = []

    def check(label, condition, detail=""):
        if condition:
            print("  ok   " + label)
        else:
            print("  FAIL " + label + ("  " + detail if detail else ""))
            failures.append(label)

    print("== --no-smp：不传参数（单核）==")
    check("None -> 空参数（不是 -smp 1）", run._smp_args(None) == [], "实得 %r" % (run._smp_args(None),))

    print("== 指定核数 ==")
    for n in (1, 4, 8):
        got = run._smp_args(n)
        check("--smp %d -> [-cpu max, -smp %d]" % (n, n),
              got == ["-cpu", "max", "-smp", str(n)], "实得 %r" % (got,))

    print("== -cpu max 与 -smp 必须成对 ==")
    for n in (1, 4):
        got = run._smp_args(n)
        check("--smp %d 同时给了 -cpu max" % n,
              got[:2] == ["-cpu", "max"], "实得 %r" % (got,))

    print("== 默认值 ==")
    # 默认由 `cmd()` 的 `getattr(args, "smp", 4)` 给出 —— 这里断言那个数字本身，
    # 因为 S8 要跑 4 核；默认值悄悄变了会让检查在错误的核数上"通过" ✗。
    import inspect
    source = inspect.getsource(run.cmd)
    check("cmd() 的默认 --smp 是 4", 'getattr(args, "smp", 4)' in source,
          "未在 cmd() 里找到默认 4")

    if failures:
        print("FAIL: %d 项未通过" % len(failures))
        return 1
    print("PASS: run._smp_args 离线自检全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
