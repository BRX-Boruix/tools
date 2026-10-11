#!/usr/bin/env python3
"""离线自检：`tools_build/abi_exports.py`（**不需要 QEMU、不需要工具链**）。

为什么需要：版本脚本此前直接用「头文件声明集」，而 `-shared` 要求每个 global 都被本库定义，
`dlopen`/`dlclose`/`dlsym`/`dlerror` 由 rtld 提供、libc 不定义 ⇒ `ld.lld` 直接拒绝（实测）。
本检查锁住「导出面 = 声明集 ∩ 定义集」这条语义与「剔除必须如实报告」。

退出码：0 = 全部通过；1 = 有失败。
"""
import os
import sys

# 显式指定输出编码（S01）：控制台默认编码可能是 GBK，而本文件与其它检查一样会打印非 GBK
# 字符（如 ⇒）；不显式指定就会以 UnicodeEncodeError 崩在「打印」这一步。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TOOLS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, TOOLS_ROOT)

from tools_build import abi_exports  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print("[ok]   %s" % name)
    else:
        print("[FAIL] %s %s" % (name, detail))
        FAILS.append(name)


def main():
    # 真实形状：声明集里有 dlopen 族，而 libc 的 .a 里没有它们。
    declared = ["printf", "malloc", "dlopen", "dlclose", "dlsym", "dlerror", "sqrt"]
    defined = {"printf", "malloc", "sqrt", "exit"}
    kept, removed = abi_exports.intersect_exports(declared, defined)
    check("保留的是两边都有的", kept == ["printf", "malloc", "sqrt"], "kept=%r" % (kept,))
    check("剔除的是本库不定义的",
          sorted(removed) == ["dlclose", "dlerror", "dlopen", "dlsym"], "removed=%r" % (removed,))
    check("顺序沿用声明集", kept == [n for n in declared if n in set(kept)], "kept=%r" % (kept,))

    # 渲染：必须是合法的 version script（global 段 + local: *;）。
    text = abi_exports.render_version_script(kept)
    check("渲染出 global 段", "global:" in text)
    check("渲染出 local: *;", "local:" in text and "*;" in text)
    check("渲染后能被解析回来", abi_exports.parse_version_script(text) == kept,
          "roundtrip=%r" % (abi_exports.parse_version_script(text),))

    # 解析：去重 + 只认 global 段。
    sample = "{\n  global:\n    a;\n    b;\n    a;\n  local:\n    *;\n};\n"
    check("解析去重", abi_exports.parse_version_script(sample) == ["a", "b"])

    # 空声明集不是「合法地没有导出」，而是生成器坏了——调用方必须能分辨。
    kept2, removed2 = abi_exports.intersect_exports([], defined)
    check("空声明集 ⇒ 空保留", kept2 == [] and removed2 == [])

    if FAILS:
        print("[abi_exports] FAILED: %d" % len(FAILS))
        return 1
    print("[abi_exports] PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())