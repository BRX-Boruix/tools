"""br 子命令：Build and Run —— 编译内核并生成 ISO，然后立即用 QEMU 启动。"""

import argparse

from . import build, run
from .util import err


def cmd(args: argparse.Namespace) -> int:
    """先构建内核 + 生成 ISO，成功后启动 QEMU"""
    rc = build.cmd(args)
    if rc != 0:
        err("build 失败，停止 br（不启动 QEMU）")
        return rc
    return run.cmd(args)
