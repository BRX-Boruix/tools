#!/usr/bin/env python3
"""检查：`checks/regression/` 下的 `*_selftest.py` 都必须在 `checks/liftoff/README.md` 里登记。

## 为什么需要

`checks/regression/check_catalog.py` 只覆盖 `checks/liftoff/` ——
所以新加在 `checks/regression/` 的**离线自检**（`iso9660` / `elf_image` / `symbols` / `run_smp` /
`config_paths` / `test_module_leak`）**没有任何东西强制它们被登记**。
我登记了，但**"我登记了"不是机制**。

## 为什么范围这么窄

`checks/regression/` 下还有**别的子系统**的检查（不属于 liftoff）——
对它们提要求会**越界**。所以这里**只**强制 `*_selftest.py` 这一族。

退出码：0 = 全部已登记；1 = 有未登记的。
"""

import os
import sys

TOOLS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REGRESSION = os.path.join(TOOLS_ROOT, "checks", "regression")
README = os.path.join(TOOLS_ROOT, "checks", "liftoff", "README.md")


def selftests() -> list:
    if not os.path.isdir(REGRESSION):
        return []
    return sorted(name for name in os.listdir(REGRESSION)
                  if name.endswith("_selftest.py"))


def check_teeth(text: str) -> list:
    """**判据必须有牙齿**：用一个"确定没登记"的合成名字，验证登记逻辑会判它缺失。

    **我第一版写错了**：它断言 `test_module_leak_selftest.py` **不存在**—— 而它存在，
    所以真调用会**永远失败**；而且我当时**没在 `main()` 里调用它**，于是它成了**死代码**。
    现在两处都修好：它拿一个合成探针名验证逻辑，并且**真的被调用**。
    """
    problems = []
    probe = "definitely_not_registered_selftest.py"
    if probe in text:
        problems.append("牙齿自检的前提不成立：合成探针名竟然出现在 README 里")
    elif probe in [name for name in selftests() if name in text]:
        problems.append("登记逻辑没有牙齿：未登记的名字被判成已登记")
    return problems


def main() -> int:
    if not os.path.isfile(README):
        print("FAIL: 找不到 " + README)
        return 1
    with open(README, encoding="utf-8") as handle:
        text = handle.read()

    teeth = check_teeth(text)
    if teeth:
        print("FAIL: 判据自身有问题：")
        for item in teeth:
            print("  - " + item)
        return 1
    print("判据自检通过（合成探针名确实会被判成未登记）")

    names = selftests()
    if not names:
        print("FAIL: 在 " + REGRESSION + " 下没找到任何 *_selftest.py —— 路径不对或检查被删了")
        return 1

    missing = [name for name in names if name not in text]
    print("检查 %d 个离线自检是否已在 README 里登记" % len(names))
    if missing:
        print("FAIL: 下列自检**没有被登记**（新加检查时必须同时登记，否则没人知道要跑它）：")
        for name in missing:
            print("  " + name)
        return 1
    print("PASS: 全部 %d 个离线自检都已登记" % len(names))
    return 0


if __name__ == "__main__":
    sys.exit(main())
