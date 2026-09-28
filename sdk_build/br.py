"""br 子命令：Build and Run —— 编译内核并生成 ISO，然后立即用 QEMU 启动。"""

import argparse

from . import b3p, build, run
from .util import err, info


def cmd(args: argparse.Namespace) -> int:
    """先构建第三方程序，再构建内核 + 生成 ISO，成功后启动 QEMU"""
    # b3p 自动前置：第三方程序是数据盘 /3p/ 的内容来源，而数据盘由 build/run
    # 侧（--redisk / mkimg）消费。放在 build 之前，保证本次 br 用到的盘里
    # 装的是刚编出来的 ELF，而不是上一次的残留。
    #
    # 放在 build 之前而非之后：build 会重编内核并可能经 _build_userspace
    # 触碰 crates/kernel/，两者无共享产物，但早编译能让「第三方编译失败」
    # 在昂贵的整核构建**之前**暴露，失败得更快也更便宜。
    info("br: 先构建第三方程序 (b3p)")
    rc = b3p.build_all()
    if rc != 0:
        err("第三方程序构建失败，停止 br")
        return rc
    rc = build.cmd(args)
    if rc != 0:
        err("build 失败，停止 br（不启动 QEMU）")
        return rc
    return run.cmd(args)
