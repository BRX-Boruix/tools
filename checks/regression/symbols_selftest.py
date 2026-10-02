#!/usr/bin/env python3
"""离线自检：`tools_build/symbols.py` 的 `parse_nm`（PRE-3，**不需要 QEMU**）。

为什么需要：这个函数把**寄存器里的地址**翻译成符号 ✓ —— 真机失败时它就是诊断的入口 ✗。
它错了**不会崩**，只会**指向错误的函数** ✗，把排查引到错的方向 ✓。

**只测纯函数 `parse_nm`** ✓（`find_nm` 依赖本机工具链 ✗，`gen` 要写文件 ✓，都不在此断言）。

退出码：0 = 全部通过；1 = 有失败。
"""

import os
import sys

TOOLS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, TOOLS_ROOT)

from tools_build import symbols  # noqa: E402

BASE = symbols._TEXT_BASE
IN_RANGE = BASE + 0x1000
HIGHER = BASE + 0x2000


def main() -> int:
    failures = []

    def check(label, condition, detail=""):
        if condition:
            print("  ok   " + label)
        else:
            print("  FAIL " + label + ("  " + detail if detail else ""))
            failures.append(label)

    print("== 保留文本段符号 ==")
    got = symbols.parse_nm([
        "%x T global_fn\n" % IN_RANGE,
        "%x t local_fn\n" % HIGHER,
    ])
    check("T 与 t 都保留", got == [(IN_RANGE, "global_fn"), (HIGHER, "local_fn")], "实得 %r" % (got,))

    print("== 丢弃非文本段 ==")
    got = symbols.parse_nm([
        "%x D data_symbol\n" % IN_RANGE,
        "%x B bss_symbol\n" % IN_RANGE,
        "%x U undefined\n" % IN_RANGE,
        "%x r rodata_local\n" % IN_RANGE,
        "%x T kept\n" % IN_RANGE,
    ])
    check("只留下 T/t", got == [(IN_RANGE, "kept")], "实得 %r" % (got,))

    print("== 丢弃低地址（保守过滤）==")
    got = symbols.parse_nm([
        "%x T below_base\n" % (BASE - 1),
        "%x T exactly_base\n" % BASE,
        "%x T above\n" % (BASE + 1),
    ])
    check("**边界含等号**：BASE 保留、BASE-1 丢弃",
          got == [(BASE, "exactly_base"), (BASE + 1, "above")], "实得 %r" % (got,))

    print("== 丢弃畸形行 ==")
    got = symbols.parse_nm([
        "\n",
        "onlyone\n",
        "%x T\n" % IN_RANGE,          # 缺名字
        "zzzz T not_hex\n",           # 地址不是十六进制
        "%x T ok\n" % IN_RANGE,
    ])
    check("畸形行一律丢弃、不抛异常", got == [(IN_RANGE, "ok")], "实得 %r" % (got,))

    print("== 排序与同地址决胜 ==")
    got = symbols.parse_nm([
        "%x T zzzzzzzzzz\n" % HIGHER,
        "%x T short\n" % HIGHER,
        "%x T lowest\n" % IN_RANGE,
    ])
    check("按地址升序", [a for a, _ in got] == [IN_RANGE, HIGHER, HIGHER], "实得 %r" % (got,))
    check("**同地址短名优先**", got[1][1] == "short", "实得 %r" % (got[1],))

    print("== 空输入 ==")
    check("空输入返回空列表", symbols.parse_nm([]) == [])

    if failures:
        print("FAIL: %d 项未通过" % len(failures))
        return 1
    print("PASS: symbols.parse_nm 离线自检全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
