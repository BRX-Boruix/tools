#!/usr/bin/env python3
"""PRE-3 辅助：确认 `checks/liftoff/` 下每个脚本都被本目录 README 登记。

为什么需要：A4 查证时发现 `l2_frozen_regs_check.py` **存在于目录里却无人登记** ——
没人知道它是什么、该不该跑。**一个没人知道存在的检查，等于不存在。**

这与 `regression/check_arch_isolation.py` 里「强制 workspace 成员显式归类」是同一手法：
**把"忘了登记"从可能变成不可能**。

排除项：`legacy/`（历史实现，按约定不登记）、`__pycache__`、`fixtures/`。

退出码：0 = 全部已登记；1 = 有脚本未登记（逐个列出）。
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKS_ROOT = os.path.dirname(HERE)

# 本轮只覆盖 `liftoff`：它有 README 且刚暴露过漏登记。其余目录留作后续。
TARGET = "liftoff"
EXCLUDE_DIRS = {"legacy", "__pycache__", "fixtures"}


def catalogued_scripts(directory):
    """返回该目录下应被登记的脚本名（不含被排除的子目录）。"""
    found = []
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for name in files:
            if name.endswith(".py"):
                found.append(name)
    return sorted(found)


def main() -> int:
    directory = os.path.join(CHECKS_ROOT, TARGET)
    readme = os.path.join(directory, "README.md")
    if not os.path.isfile(readme):
        print("FAIL: " + TARGET + "/README.md 不存在 —— 无法核对登记情况")
        return 1
    with open(readme, "r", encoding="utf-8") as handle:
        text = handle.read()

    missing = [name for name in catalogued_scripts(directory) if name not in text]
    if missing:
        print("FAIL: " + TARGET + "/ 下有脚本未在 README 登记：")
        for name in missing:
            print("  - " + name)
        print("请登记它（说明用途与是否属门禁），或移入 legacy/。")
        return 1
    print("PASS: " + TARGET + "/ 下全部脚本均已登记")
    return 0


if __name__ == "__main__":
    sys.exit(main())
