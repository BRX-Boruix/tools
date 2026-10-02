#!/usr/bin/env python3
"""liftoff 的**统一回归入口**。

**为什么需要它**：liftoff 的离线检查此前**各自独立、靠手工逐个跑**—— 台账 §4.2 只说了
"每个里程碑另加 PRE-2/PRE-3"，**没说谁跑**。于是"某个检查被忘记跑"是常态，
而**忘记跑**在结果上与"通过"无法区分。

用法：
    python checks/run_all.py              # 只跑**离线**检查（秒级）
    python checks/run_all.py --hardware   # 额外跑需要 QEMU 的检查（每次 5–10 分钟）

退出码 0 = 选中的检查**全部**通过；非 0 = 有失败 / 超时 / 文件缺失。
**空集合不算通过**（"一个都没跑"不是"全绿"）。
"""

import argparse
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS_DIR = os.path.dirname(_HERE)

# 需要 QEMU 的检查 —— **显式登记**，不靠文件名猜。默认不跑：单次 5–10 分钟，
# 而 A3 的覆盖矩阵要跑四格。
HARDWARE_CHECKS = (
    "checks/liftoff/l5_handoff_check.py",
)

# 离线检查（宿主、秒级）。**新增检查必须登记在这里** —— 与
# `selftest_registry_check.py` 同一约定：**登记是强制的**，不是"能自动发现就不用登记"。
OFFLINE_CHECKS = (
    "checks/regression/check_catalog.py",
    "checks/regression/selftest_registry_check.py",
    "checks/regression/run_all_selftest.py",
    "checks/regression/config_paths_selftest.py",
    "checks/regression/iso9660_selftest.py",
    "checks/regression/elf_image_selftest.py",
    "checks/regression/symbols_selftest.py",
    "checks/regression/run_smp_selftest.py",
    "checks/regression/test_module_leak_selftest.py",
    "checks/regression/diag_selftest.py",
    # **PRE-3 本体**（ADR-052 第 3 层）：中立层不得依赖具体实现。
    # 它此前**不在**统一入口里 —— 于是"PRE-3 在跑吗"这个问题的答案是"能跑，但没人跑"。
    # （我第一版把注释写成了 C 风格的 `//` —— Python 会当场 SyntaxError，
    #  而"统一入口自己坏了"比"某个检查没过"更坏：它让**所有**检查都不再被执行。）
    "checks/regression/check_arch_isolation.py",
    # **量化验收**（台账 §4.1）：体积上限 = 所有者第 106 轮裁定的 **256 KiB**。
    # 写在文档里的数字不会拦住任何人 —— 变成可执行的检查才会。
    "checks/liftoff/size_check.py",
    "checks/liftoff/asm_check.py",
    "checks/liftoff/mock_impl_check.py",
)

# 单个检查的超时。超时**算失败**（不能当成 0）。
CHECK_TIMEOUT_S = 300


def select(hardware: bool) -> list:
    """选中要跑的检查（相对 `tools/` 的路径）。**纯逻辑、宿主可测**。"""
    chosen = list(OFFLINE_CHECKS)
    if hardware:
        chosen.extend(HARDWARE_CHECKS)
    return chosen


def summarize(results) -> int:
    """把 (路径, 退出码或 None) 汇总成进程退出码。**纯逻辑、宿主可测**。

    **空集合 -> 非 0**：一个都没跑，不能算"全绿"。
    退出码为 `None`（超时或文件缺失）**算失败**。
    """
    if not results:
        return 1
    return 0 if all(code == 0 for _, code in results) else 1


def run_one(relative: str):
    """跑一个检查，返回退出码；**超时或文件缺失返回 None**。"""
    full = os.path.join(_TOOLS_DIR, relative)
    if not os.path.isfile(full):
        return None
    try:
        proc = subprocess.run(
            [sys.executable, full],
            cwd=_TOOLS_DIR,
            timeout=CHECK_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return None
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="liftoff 统一回归入口")
    parser.add_argument("--hardware", action="store_true",
                        help="额外跑需要 QEMU 的检查（每次 5–10 分钟）")
    args = parser.parse_args()

    chosen = select(args.hardware)
    results = []
    for relative in chosen:
        print("== " + relative)
        code = run_one(relative)
        if code is None:
            print("   FAIL: 超时（%d 秒）或文件缺失" % CHECK_TIMEOUT_S)
        else:
            print("   exit=%d" % code)
        results.append((relative, code))

    failed = [p for p, c in results if c != 0]
    print("")
    print("共 %d 项，%d 项未通过" % (len(results), len(failed)))
    for p in failed:
        print("  FAIL: " + p)
    return summarize(results)


if __name__ == "__main__":
    sys.exit(main())
