#!/usr/bin/env python3
"""机内 tcc 的运行期资产是否与当前 sysroot **同步**（防「改了 libc 却验了旧库」）。

## 为什么需要（真实教训，不是预防性洁癖）

机内 `tcc` 链接的是 `tools/diskfiles/3p/tcc/libc.a` —— 它由 `tcc-on-boruix/boruix/stage_assets.py`
从 sysroot 铺过去。**改了 libc 却没重铺**时，机内编译链接的仍是旧库：代码明明修好了，
现象却一字不变。2026-10 我在这个问题上白跑了 4 轮（`docs/TODO/3p.md` 有完整记录，
与 `tcc-on-boruix/boruix/CRT-AND-LIBS:71` 的「改了 libc 却没重链 tcc.elf」同族）。

本脚本把「记得重铺」变成一次**可执行的检查**：不一致就**响亮报错**（非 0 退出）。

**覆盖范围（名字是历史遗留，实际是「数据盘上那几个手工拷贝的资产」）**：
  libc.a + 全部头文件 + tcc.elf（机内编译器）+ rtld.elf（动态链接器）+ tccmt.elf（libtcc 能力探针）。
rtld.elf 的构建+铺料在 `tools/tools_build/build_rtld.py`；tcc.elf 与 tccmt.elf 在
`tcc-on-boruix/boruix/build.py` + `stage_assets.py`。

用法:
    set BORUIX_SYSROOT=<install --prefix 的产物>
    python tools/checks/dist/tcc_assets_fresh.py            # 或 --sysroot <dir>
退出码: 0 = 一致；1 = 有漂移（附清单）；2 = 参数/路径问题。
"""
import argparse
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
STAGED = os.path.join(ROOT, "tools", "diskfiles", "3p", "tcc")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sysroot", default=os.environ.get("BORUIX_SYSROOT"))
    a = ap.parse_args()
    if not a.sysroot or not os.path.isdir(a.sysroot):
        print("[FAIL] 需要 --sysroot（或 BORUIX_SYSROOT）指向已安装的 sysroot")
        return 2
    if not os.path.isdir(STAGED):
        print("[FAIL] 未找到机内 tcc 资产目录: " + STAGED)
        return 2

    drift = []

    # 1) libc.a：最重要的一项（符号与实现都从这里来）。
    src_lib = os.path.join(a.sysroot, "lib", "libc.a")
    dst_lib = os.path.join(STAGED, "libc.a")
    if not os.path.isfile(src_lib):
        print("[FAIL] sysroot 里没有 lib/libc.a: " + src_lib)
        return 2
    if not os.path.isfile(dst_lib):
        drift.append("libc.a：铺料缺失（" + dst_lib + "）")
    elif sha256(src_lib) != sha256(dst_lib):
        drift.append("libc.a：与 sysroot 不一致（机内 tcc 会链到旧库）")

    # 2) 头文件：声明漂移同样会让机内编译拿到旧原型（PHANTOM/未声明类缺陷的温床）。
    src_inc = os.path.join(a.sysroot, "include")
    dst_inc = os.path.join(STAGED, "include")
    for dirpath, _dirs, files in os.walk(src_inc):
        for f in files:
            if not f.endswith(".h"):
                continue
            s = os.path.join(dirpath, f)
            rel = os.path.relpath(s, src_inc)
            d = os.path.join(dst_inc, rel)
            if not os.path.isfile(d):
                drift.append("头文件缺失: " + rel)
            elif sha256(s) != sha256(d):
                drift.append("头文件不一致: " + rel)

    # 3) tcc.elf（**编译器本体**）：与 libc.a 同族的「手工拷贝」资产，此前**没有任何
    #    门禁**。2026-10 实测事故：改了 tccelf.c 却没把新 tcc.elf 铺到盘上，一次 A/B
    #    的两臂跑的是同一份旧二进制（仪器标记在两臂里都没出现才发现）。
    src_tcc = os.path.join(ROOT, "tcc-on-boruix", "_build", "tcc.elf")
    dst_tcc = os.path.join(ROOT, "tools", "diskfiles", "3p", "tcc.elf")
    if not os.path.isfile(src_tcc):
        drift.append("tcc.elf：构建产物缺失（" + src_tcc + "）——先跑 boruix/build.py")
    elif not os.path.isfile(dst_tcc):
        drift.append("tcc.elf：铺料缺失（" + dst_tcc + "）")
    elif sha256(src_tcc) != sha256(dst_tcc):
        drift.append("tcc.elf：与 _build 产物不一致（机内跑的是**旧编译器**）")

    # 4) rtld.elf（**动态链接器**）：与 tcc.elf 同族的「手工拷贝」资产。2026-10 已补上
    #    构建+铺料脚本 tools/tools_build/build_rtld.py；这里把「记得重铺」变成门禁。
    #    教训同 3)：改了 rtld 源码却没重铺 ⇒ 机上跑的仍是旧 rtld，测量作废。
    src_rtld = os.path.join(ROOT, "rtld", "target", "x86_64-unknown-boruix", "debug", "rtld")
    dst_rtld = os.path.join(ROOT, "tools", "diskfiles", "3p", "rtld.elf")
    if not os.path.isfile(src_rtld):
        drift.append("rtld.elf：构建产物缺失（" + src_rtld + "）——先跑 tools/tools_build/build_rtld.py")
    elif not os.path.isfile(dst_rtld):
        drift.append("rtld.elf：铺料缺失（" + dst_rtld + "）")
    elif sha256(src_rtld) != sha256(dst_rtld):
        drift.append("rtld.elf：与构建产物不一致（机内跑的是**旧 rtld**）")

    # 5) tccmt.elf（**libtcc 能力探针**）：与 tcc.elf 同一形态的手工拷贝资产。
    #    探针要证明的是「当前这份 libtcc 无互斥」；盘上留旧探针就等于拿旧构建当证据。
    src_probe = os.path.join(ROOT, "tcc-on-boruix", "_build", "tccmt.elf")
    dst_probe = os.path.join(ROOT, "tools", "diskfiles", "3p", "tccmt.elf")
    if not os.path.isfile(src_probe):
        drift.append("tccmt.elf：构建产物缺失（" + src_probe + "）——先跑 boruix/build.py --probe tccmt")
    elif not os.path.isfile(dst_probe):
        drift.append("tccmt.elf：铺料缺失（" + dst_probe + "）")
    elif sha256(src_probe) != sha256(dst_probe):
        drift.append("tccmt.elf：与 _build 产物不一致（机内跑的是**旧探针**）")

    if drift:
        print("[FAIL] 数据盘资产与构建产物不同步（%d 项）——请先重铺:" % len(drift))
        print("       python tcc-on-boruix/boruix/stage_assets.py --sysroot <sysroot>")
        print("       python tools/tools_build/build_rtld.py --sysroot <sysroot>")
        for d in drift[:20]:
            print("       - " + d)
        if len(drift) > 20:
            print("       ...（其余 %d 项省略）" % (len(drift) - 20))
        return 1

    print("[OK] 数据盘资产与构建产物一致（libc.a + 全部头文件 + tcc.elf + rtld.elf + tccmt.elf）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
