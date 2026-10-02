#!/usr/bin/env python3
"""PRE-1 附：引导器体积上限检查（台账 §4.1；**所有者第 106 轮裁定 = 256 KiB**）。

**为什么要有它**：体积上限只有变成**可执行的检查**才算量化验收 ——
写在文档里的数字，超标时**不会拦住任何人**。

用法：
    python checks/liftoff/size_check.py                 # 按上限检查 release 产物
    python checks/liftoff/size_check.py --limit-kib 1   # 故意用很小的上限，验证它**真的会拒绝**python checks/liftoff/size_check.py --self-test     # 牙齿自检（阈值判断必须双向成立）
"""
import argparse
import os
import sys

_TOOLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EFI = os.path.join(
    os.path.dirname(_TOOLS), "liftoff", "target", "x86_64-unknown-uefi", "release", "liftoff.efi"
)
# 所有者第 106 轮的裁定（选 B）。**不是**我拍的数。
DEFAULT_LIMIT_KIB = 256


def within(size: int, limit_kib: int) -> bool:
    """体积是否在限内（**纯逻辑**）。边界取**闭区间**：正好等于上限算通过。"""
    return size <= limit_kib * 1024


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-kib", type=int, default=DEFAULT_LIMIT_KIB)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        # **牙齿自检**：阈值判断必须**双向**成立 —— 正好等于上限要过，多一字节要拒。
        # 只测"过"的一侧等于没有阈值。
        limit = args.limit_kib * 1024
        ok = within(limit, args.limit_kib) and not within(limit + 1, args.limit_kib) and within(0, args.limit_kib)
        print("PASS: size_check 牙齿自检" if ok else "FAIL: size_check 牙齿自检")
        return 0 if ok else 1

    if not os.path.isfile(EFI):
        print("FAIL: 找不到产物 " + EFI + "（先 cargo build --release --target x86_64-unknown-uefi）")
        return 1
    size = os.path.getsize(EFI)
    limit = args.limit_kib * 1024
    print("release 产物 %d 字节（%.1f KiB）；上限 %d KiB；余量 %.1f KiB"
          % (size, size / 1024.0, args.limit_kib, (limit - size) / 1024.0))
    if within(size, args.limit_kib):
        print("PASS: size_check")
        return 0
    print("FAIL: size_check —— 超出上限 %d 字节" % (size - limit))
    return 1


if __name__ == "__main__":
    sys.exit(main())
