#!/usr/bin/env python3
"""`checks/run_all.py` 的自检 —— 宿主、离线、**不碰 QEMU**。

测的是**发现 / 筛选 / 汇总**这三件纯逻辑 ✓，不是"被跑的那些检查能不能过" ✗
（那是它们自己的事）。

**为什么必须有它**：一个"统一入口"如果自己没被测，它可能"一个检查都没跑"
却退出 0 —— 那就把"忘记跑"变成了"看起来通过" ✗，比没有入口更坏。
"""

import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS_DIR = os.path.dirname(os.path.dirname(_HERE))
RUN_ALL = os.path.join(_TOOLS_DIR, "checks", "run_all.py")

_failures = []


def check(name, cond, detail=""):
    if cond:
        print("  ok   " + name)
    else:
        print("  FAIL " + name + (" :: " + detail if detail else ""))
        _failures.append(name)


def load():
    spec = importlib.util.spec_from_file_location("run_all", RUN_ALL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    if not os.path.isfile(RUN_ALL):
        print("FAIL: 找不到 " + RUN_ALL)
        return 1
    m = load()

    # 1) 默认**不带**硬件检查；`--hardware` 才带上。
    offline = m.select(False)
    with_hw = m.select(True)
    check("默认选择里没有需要 QEMU 的检查", not (set(offline) & set(m.HARDWARE_CHECKS)),
          str(set(offline) & set(m.HARDWARE_CHECKS)))
    check("--hardware 会带上硬件检查",
          set(with_hw) == set(offline) | set(m.HARDWARE_CHECKS))
    check("默认选择非空", len(offline) > 0, "空 = 一个都不跑，等于没有入口")

    # 2) 登记表里的每个路径**都必须真实存在** —— 改名/删文件后不能静默少跑 ✗。
    missing = [p for p in with_hw if not os.path.isfile(os.path.join(_TOOLS_DIR, p))]
    check("登记表里每个检查文件都存在", not missing, "缺失: " + str(missing))

    # 3) 汇总：**空集合不能算通过** ✗。
    check("空结果集 -> 非 0", m.summarize([]) != 0)
    check("全通过 -> 0", m.summarize([("a", 0), ("b", 0)]) == 0)
    check("有一个失败 -> 非 0", m.summarize([("a", 0), ("b", 1)]) != 0)
    # 4) 超时/缺失用 None 表示 —— 也必须算失败 ✗（不能当成 0）。
    check("超时/缺失(None) -> 非 0", m.summarize([("a", 0), ("b", None)]) != 0)

    print("")
    if _failures:
        print("FAIL: " + str(len(_failures)) + " 项: " + ", ".join(_failures))
        return 1
    print("PASS: run_all 自检")
    return 0


if __name__ == "__main__":
    sys.exit(main())
