#!/usr/bin/env python3
"""
BORUIX SDK 辅助工具统一入口。

用法:
    python main.py <子命令> [选项]

子命令:
    limine   下载并部署 Limine bootloader 到 sdk/boot/
    build    编译内核并生成可引导 ISO（x86_64）
    run      用 QEMU 启动 ISO
    br       Build and Run：编译生成 ISO 后立即用 QEMU 启动
    --help   查看帮助

各子命令的实现分散在 sdk_build/ 包中，本文件只负责入口与参数注册。
"""

import argparse
import sys

from sdk_build import br, build, limine, run
from sdk_build.config import DEFAULT_LIMINE_VERSION


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sdk",
        description="BORUIX SDK 辅助工具主入口",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # limine 子命令
    p_limine = sub.add_parser("limine", help="下载并部署 Limine bootloader")
    p_limine.add_argument(
        "--version",
        default=DEFAULT_LIMINE_VERSION,
        help=f"Limine 版本（默认 {DEFAULT_LIMINE_VERSION}）",
    )
    p_limine.add_argument(
        "--skip-existing",
        action="store_true",
        help="若已存在则跳过下载",
    )
    p_limine.add_argument(
        "--force",
        action="store_true",
        help="强制重新下载（删除旧版本）",
    )
    p_limine.set_defaults(func=limine.cmd)

    # build 子命令
    p_build = sub.add_parser("build", help="编译内核并生成可引导 ISO")
    p_build.set_defaults(func=build.cmd)

    # run 子命令
    p_run = sub.add_parser("run", help="用 QEMU 启动 ISO")
    p_run.add_argument("--mem", default="128M", help="内存大小（默认 128M）")
    p_run.add_argument("--serial", action="store_true", help="启用串口输出到终端")
    p_run.set_defaults(func=run.cmd)

    # br 子命令：Build and Run（先构建，后启动）
    p_br = sub.add_parser("br", help="编译生成 ISO 后立即用 QEMU 启动")
    p_br.add_argument("--mem", default="128M", help="内存大小（默认 128M）")
    p_br.add_argument("--serial", action="store_true", help="启用串口输出到终端")
    p_br.set_defaults(func=br.cmd)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
