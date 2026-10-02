#!/usr/bin/env python3
"""tools 的**统一回归入口**。

**为什么需要它**：离线检查此前**各自独立、靠手工逐个跑**—— "每个里程碑另加检查"，
**没说谁跑**。于是"某个检查被忘记跑"是常态，而**忘记跑**在结果上与"通过"无法区分。

用法：
    python checks/run_all.py              # 跑**离线**检查（秒级）
    python checks/run_all.py --hardware   # 额外跑需要 QEMU 的检查（当前登记表为空）

退出码 0 = 选中的检查**全部**通过；非 0 = 有失败 / 超时 / 文件缺失。
**空集合不算通过**（"一个都没跑"不是"全绿"）。
"""

import argparse
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS_DIR = os.path.dirname(_HERE)

# 需要 QEMU 的检查 —— **显式登记**，不靠文件名猜。当前为空（原登记项已随其子系统归档）。
HARDWARE_CHECKS = ()

# 离线检查（宿主、秒级）。**新增检查必须登记在这里** —— 登记是强制的，
# 不靠"自动发现"：自动发现会让"改名后静默少跑"无法察觉。
OFFLINE_CHECKS = (
    "checks/regression/run_all_selftest.py",
    "checks/regression/config_paths_selftest.py",
    "checks/regression/iso9660_selftest.py",
    "checks/regression/elf_image_selftest.py",
    "checks/regression/symbols_selftest.py",
    "checks/regression/run_smp_selftest.py",
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
    parser = argparse.ArgumentParser(description="tools 统一回归入口")
    parser.add_argument("--hardware", action="store_true",
                        help="额外跑需要 QEMU 的检查（当前登记表为空）")
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
