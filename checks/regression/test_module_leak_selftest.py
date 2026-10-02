#!/usr/bin/env python3
"""离线自检：生产项是否被误放进 `#[cfg(test)]` 模块（PRE-3，**不需要 QEMU / 不需要 Rust**）。

## 为什么需要（真实事故）

`crates/arch/x86_64/src/ap.rs` 的 `global_asm!`、常量与 `stage()` 曾经**整体夹在
`#[cfg(test)] mod tests` 内部** ✗（该模块一直没闭合 ✓）。于是**非测试构建里它们根本不存在** ✗，
而 `cargo test` 与 UEFI 构建**双双退出 0** ✗ —— **绿是因为代码没被编译** ✓。

## 判据（为什么这条判据成立）

`mod tests` 是**私有**模块 ✓ —— 它里面的 `pub` 项**对外毫无意义** ✗。
所以**测试模块里出现 `pub` 项，几乎必然是放错了位置** ✓。
这条判据**只看源码** ✓，不需要反汇编、不需要符号表 ✓（release `.efi` 没有符号表 ✗）。

退出码：0 = 干净；1 = 发现可疑项。
"""

import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CRATES = os.path.join(os.path.dirname(REPO), "liftoff", "crates")

# `#[cfg(test)]`（可能夹着别的属性）后面紧跟 `mod <名字> {`。
CFG_TEST_MOD = re.compile(r"#\[cfg\(test\)\][\s\S]{0,200}?\bmod\s+[A-Za-z_][A-Za-z0-9_]*\s*\{")
# 模块内的**纯 `pub`** 项 —— 在私有测试模块里没有意义。
#
# **只抓纯 `pub`，不抓 `pub(super)` / `pub(crate)`** ✓：后者是测试辅助函数与桩的常见写法 ✓，
# 是**多余的**但**无害** ✓；我第一版把限定形式也抓了，于是报了 4 处**假信号** ✗。
# 纯 `pub` 不同：它声称"对外可见" ✗，而私有模块里**不可能** ✓ —— 那个声明本身就是"放错了位置"的证据 ✓。
PUBLIC_ITEM = re.compile(r"^\s*pub\s+(?:unsafe\s+)?(fn|struct|enum|const|static|trait|mod|type)\b")


def strip_strings_and_comments(text):
    """把字符串与注释换成空格，避免把注释里的 `pub` 当成代码。"""
    out = []
    i = 0
    n = len(text)
    while i < n:
        two = text[i:i + 2]
        if two == "//":
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif two == "/*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(" " * (j - i))
            i = j
        elif text[i] == chr(34):
            j = i + 1
            while j < n and text[j] != chr(34):
                j += 2 if text[j] == chr(92) else 1
            j = min(j + 1, n)
            out.append(" " * (j - i))
            i = j
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def module_extent(text, brace_start):
    """从模块的 `{` 开始做花括号配平，返回其闭合位置。"""
    depth = 0
    for i in range(brace_start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return len(text)


def scan_source(path, text):
    """返回 [(行号, 内容)] —— 测试模块里的 pub 项。"""
    clean = strip_strings_and_comments(text)
    hits = []
    for match in CFG_TEST_MOD.finditer(clean):
        brace = clean.index("{", match.end() - 1)
        end = module_extent(clean, brace)
        for offset, line in enumerate(text[brace:end].splitlines(), start=1):
            if PUBLIC_ITEM.match(line):
                lineno = text[:brace].count("\n") + offset
                hits.append((lineno, line.strip()))
    return hits


def check_teeth() -> list:
    """**验证判据有牙齿**：合成样本必须被抓到，而 `pub(super)` 不得被误报。"""
    problems = []
    leaked = "#[cfg(test)]\nmod tests {\n    pub fn stage() {}\n}\n"
    if not scan_source("synthetic.rs", leaked):
        problems.append("合成样本里的 `pub fn` 没被抓到 —— 判据没有牙齿")
    benign = "#[cfg(test)]\nmod tests {\n    pub(super) fn helper() {}\n}\n"
    if scan_source("synthetic.rs", benign):
        problems.append("`pub(super)` 被误报 —— 判据过宽")
    # 注释里的 pub 不算（要先把字符串与注释剥掉）。
    commented = "#[cfg(test)]\nmod tests {\n    // pub fn fake() {}\n}\n"
    if scan_source("synthetic.rs", commented):
        problems.append("注释里的 `pub` 被当成代码")
    return problems


def main() -> int:
    if not os.path.isdir(CRATES):
        print("FAIL: 找不到 liftoff/crates: " + CRATES)
        return 1
    teeth = check_teeth()
    if teeth:
        print("FAIL: 判据自身有问题：")
        for item in teeth:
            print("  - " + item)
        return 1
    print("判据自检通过（合成样本被抓到、pub(super) 不误报、注释不算）")

    bad = []
    scanned = 0
    for root, _dirs, files in os.walk(CRATES):
        if "target" in root.split(os.sep):
            continue
        for name in files:
            if not name.endswith(".rs"):
                continue
            path = os.path.join(root, name)
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            scanned += 1
            for lineno, line in scan_source(path, text):
                bad.append((os.path.relpath(path, CRATES), lineno, line))

    print("扫描 %d 个 .rs 文件" % scanned)
    if bad:
        print("FAIL: 测试模块里出现对外可见的项 —— 它们在**非测试构建里不存在**：")
        for rel, lineno, line in bad:
            print("  %s:%d  %s" % (rel, lineno, line))
        print("")
        print("这几乎必然是放错了位置（`mod tests` 是私有模块，pub 无意义）。")
        print("上一次这个形状的事故让 UEFI 产物里整段汇编消失，而闸门照样全绿。")
        return 1
    print("PASS: 没有生产项被夹在测试模块里")
    return 0


if __name__ == "__main__":
    sys.exit(main())
