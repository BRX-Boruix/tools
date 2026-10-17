"""BORUIX_TESTDISK：**测试专用**盘，由 Python 侧现场编译夹具生成。

## 它是什么 / 不是什么

- **是**：测试夹具的载体。夹具源码在 `tools/testdisk/`（本模块所在的仓里），
  由本模块用 sysroot 的 `boruix-clang` 编译后写进镜像——测试因此自足。
- **不是**：数据盘的附属。它**不读** `tools/diskfiles/`（那是数据盘的内容），两块盘互不知道。
- **不是**：系统概念。系统不知道这块盘存在、也不知道它叫什么；对它来说这只是
  「一块卷，挂载点 `/volumes/<它自己的卷标>`」。

## 为什么盘名可以出现在这里

盘名是**数据**。它只允许出现在 Python 的构建/测试脚本里；**Rust 系统代码里出现即违规**
（由 `checks/dist/no_disk_in_system.py` 强制）。

## 用法

    python tools/main.py build --testdisk     # 只生成 testdisk.img
    python tools/main.py run   --testdisk     # 只挂载（要求镜像已存在）
    python tools/main.py br    --testdisk     # 生成并挂载
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

#: 夹具源码目录（本仓内，**不是** diskfiles/）。
SRC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testdisk")

#: 要编进镜像的夹具（文件名去掉 .c）。**显式清单**，不扫目录——
#: 扫目录会让「新增一个文件」静默改变镜像内容，且无法表达「这个文件不参与」。
FIXTURES = (
    "cc1-smoke", "ctor_check", "dircount", "dlfcn_hdr_check", "forkmin", "forkrace",
    "fsbench", "fswcmd", "fswrite", "heapstress", "hello_cc1", "jitprobe",
    "mathclass_check", "mkfiles", "mode_umask_check", "readbench", "setvbuf_check",
    "surface7_check", "syscallfuzz", "tiny", "wave2",
)

#: 目录里存在但**不编进镜像**的，以及为什么。
NOT_ON_DISK = {
    # 实测（2026-10-17）：它引用的 dlopen/dlsym/dlclose 由 **rtld** 提供，不在 libc.a 里；
    # 普通 boruix-clang 链接会失败（必须带 --unresolved-symbols 并交给 rtld 装载）。
    "dlclose_check": "dl* 由 rtld 提供，boruix-clang 链不上（需 rtld 装载）",
    "pad_equiv": "宿主侧等价性测试（在宿主上编译运行，与机内无关）",
}


def _clang(sysroot):
    p = os.path.join(sysroot, "bin", "boruix-clang")
    return p if os.path.isfile(p) else None


def generate(sysroot=None):
    """生成 testdisk.img。返回 0 = 成功。

    把 `tools/testdisk/` 的夹具逐个用 sysroot 的 `boruix-clang` 编译，产物放进 staging，
    再交给 disk.create_ext2_disk_image 打成 ext2 镜像。
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
        for name in FIXTURES:
            cpath = os.path.join(SRC_DIR, name + ".c")
            if not os.path.isfile(cpath):
                err("testdisk: 缺夹具源码 " + cpath)
                return 1
            out = os.path.join(stage, name + ".elf")
            # boruix-clang 是 **Python 脚本**（不是原生 exe），必须用当前解释器跑——
            # 直接执行会得到 WinError 193（不是有效的 Win32 应用程序）。
            r = subprocess.run([sys.executable, clang, cpath, "-o", out])
            if r.returncode != 0:
                err("testdisk: 编译失败 " + name)
                return 1
        info("testdisk: 写入 " + IMG_PATH + "（卷标 " + LABEL + "，" + str(len(FIXTURES)) + " 个夹具）")
        if not disk.create_ext2_disk_image(IMG_PATH, label=LABEL, src=stage):
            err("testdisk: 生成镜像失败")
            return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)
    info("testdisk: 完成")
    return 0


def exists():
    return os.path.isfile(IMG_PATH)
