"""BORUIX_TESTDISK：**测试专用**盘，由 Python 侧现场生成。

## 它是什么 / 不是什么

- **是**：测试夹具的载体。夹具源码**写在本文件里**，编译后写进镜像——测试因此自足，
  不依赖 `tools/diskfiles/`（那是给人类维护的**数据盘**内容，两块盘互不知道）。
- **不是**：系统概念。系统不知道这块盘存在、也不知道它叫什么；对它来说这只是
  「一块卷，挂载点 `/volumes/<它自己的卷标>`」。

## 为什么盘名可以出现在这里

盘名是**数据**。它只允许出现在 Python 的构建/测试脚本里；**Rust 系统代码里出现即违规**
（由 `checks/dist/no_disk_in_system.py` 强制）。

## 用法

    python tools/main.py build --testdisk     # 只生成 testdisk.img
    python tools/main.py run   --testdisk     # 只挂载（要求镜像已存在）
    python tools/main.py br    --testdisk     # 生成并挂载

镜像里**只有本文件里写的夹具**，与 `disk.img` 无任何交集。
"""

import os
import shutil
import subprocess
import sys
import tempfile

from . import config, disk
from .util import err, info

#: 测试盘的卷标。**只在本文件（Python）里使用**——Rust 侧不许出现。
LABEL = "BORUIX_TESTDISK"

#: 镜像路径（与数据盘 `disk.img` 并列、互不覆盖）。
IMG_PATH = os.path.join(config.PROJECT_ROOT, "testdisk.img")

#: 夹具源码。**写在这里**而不是从 `diskfiles/` 读——测试盘必须自足，
#: 且不能与人类维护的数据盘内容耦合。键是产物名，值是 C 源码。
FIXTURES = {
    "tdhello": r"""
#include <stdio.h>
int main(void)
{
    puts("hello from the test disk");
    return 0;
}
""",
    "tdexit": r"""
/* 退出码夹具：让测试能断言「盘上的程序确实被执行了」，而不只是挂上了。 */
int main(void)
{
    return 42;
}
""",
}


def _clang(sysroot):
    p = os.path.join(sysroot, "bin", "boruix-clang")
    if not os.path.isfile(p):
        return None
    return p


def generate(sysroot=None):
    """生成 testdisk.img。返回 0 = 成功。

    步骤：把 FIXTURES 的源码写到临时目录 → 用 sysroot 的 `boruix-clang` 逐个编译 →
    把产物放进 staging 目录 → 交给 disk.create_ext2_disk_image 打成 ext2 镜像。

    盘里**不放** `diskfiles/` 的任何内容：两块盘互不知道。
    """
    sysroot = sysroot or os.environ.get("BORUIX_SYSROOT")
    if not sysroot:
        err("testdisk 需要 sysroot：传 --sysroot <prefix> 或设 BORUIX_SYSROOT（先 install）")
        return 1
    clang = _clang(sysroot)
    if not clang:
        err("sysroot 里没有 bin/boruix-clang：" + sysroot)
        return 1

    work = tempfile.mkdtemp(prefix="boruix-testdisk-")
    stage = os.path.join(work, "stage")
    os.makedirs(stage)
    try:
        for name, src in FIXTURES.items():
            cpath = os.path.join(work, name + ".c")
            with open(cpath, "w", encoding="utf-8", newline="\n") as f:
                f.write(src.lstrip("\n"))
            out = os.path.join(stage, name + ".elf")
            info("testdisk: 编译 " + name + ".c")
            # boruix-clang 是 **Python 脚本**（不是原生 exe），必须用当前解释器跑——
            # 直接执行会得到 WinError 193（不是有效的 Win32 应用程序）。
            r = subprocess.run([sys.executable, clang, cpath, "-o", out])
            if r.returncode != 0:
                err("testdisk: 编译失败 " + name)
                return 1
        info("testdisk: 写入 " + IMG_PATH + "（卷标 " + LABEL + "）")
        if not disk.create_ext2_disk_image(IMG_PATH, label=LABEL, src=stage):
            err("testdisk: 生成镜像失败")
            return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)
    info("testdisk: 完成（" + str(len(FIXTURES)) + " 个夹具）")
    return 0


def exists():
    return os.path.isfile(IMG_PATH)
