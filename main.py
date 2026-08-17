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
    p_build.add_argument(
        "--test",
        action="store_true",
        help="编译带自检测试的内核（启用 kernel-tests feature）；默认不含测试",
    )
    p_build.add_argument(
        "--test-m3.3",
        dest="test_m33",
        action="store_true",
        help="同时启用 M3.3 用户态异常停机验收（kernel-test-m33 feature）；"
        "该测试验收后停机、不返回主流程（不打印版本横幅），默认关闭",
    )
    p_build.add_argument(
        "--test-m4.1",
        dest="test_m41",
        action="store_true",
        help="同时启用 M4.1 syscall 停机验收（kernel-test-m41 feature）；"
        "该测试验收后停机、不返回主流程（不打印版本横幅），默认关闭",
    )
    p_build.add_argument(
        "--test-m4.2",
        dest="test_m42",
        action="store_true",
        help="同时启用 M4.2 调度器停机验收（kernel-test-m42 feature）；"
        "该测试验收后停机、不返回主流程（不打印版本横幅），默认关闭",
    )
    p_build.add_argument(
        "--test-m4.3",
        dest="test_m43",
        action="store_true",
        help="同时启用 M4.3 静态 ELF 加载验收（kernel-test-m43 feature）；"
        "该测试验收后停机、不返回主流程（不打印版本横幅），默认关闭",
    )
    p_build.add_argument(
        "--test-m4.4",
        dest="test_m44",
        action="store_true",
        help="同时启用 M4.4 真实用户程序验收（kernel-test-m44 feature）；"
        "先编译 libsys+init 用户程序再编译内核嵌入，验收后停机，默认关闭",
    )
    p_build.add_argument(
        "--test-m5",
        dest="test_m5",
        action="store_true",
        help="同时启用 M5 写时复制 COW 验收（kernel-test-m5 feature）；"
        "纯内存逻辑，返回主流程继续启动，默认关闭",
    )
    p_build.add_argument(
        "--release",
        action="store_true",
        help="以 release 配置构建内核（验证正式 release 形态）；默认 debug",
    )
    p_build.set_defaults(func=build.cmd)

    # run 子命令
    p_run = sub.add_parser("run", help="用 QEMU 启动 ISO")
    p_run.add_argument("--mem", default="128M", help="内存大小（默认 128M）")
    p_run.add_argument("--serial", action="store_true", help="启用串口输出到终端")
    p_run.set_defaults(func=run.cmd)

    # br 子命令：Build and Run（先构建，后启动）
    p_br = sub.add_parser("br", help="编译生成 ISO 后立即用 QEMU 启动")
    p_br.add_argument(
        "--test",
        action="store_true",
        help="编译带自检测试的内核（启用 kernel-tests feature）；默认不含测试",
    )
    p_br.add_argument(
        "--test-m3.3",
        dest="test_m33",
        action="store_true",
        help="同时启用 M3.3 用户态异常停机验收（kernel-test-m33 feature）；"
        "该测试验收后停机、不返回主流程（不打印版本横幅），默认关闭",
    )
    p_br.add_argument(
        "--test-m4.1",
        dest="test_m41",
        action="store_true",
        help="同时启用 M4.1 syscall 停机验收（kernel-test-m41 feature）；"
        "该测试验收后停机、不返回主流程（不打印版本横幅），默认关闭",
    )
    p_br.add_argument(
        "--test-m4.2",
        dest="test_m42",
        action="store_true",
        help="同时启用 M4.2 调度器停机验收（kernel-test-m42 feature）；"
        "该测试验收后停机、不返回主流程（不打印版本横幅），默认关闭",
    )
    p_br.add_argument(
        "--test-m4.3",
        dest="test_m43",
        action="store_true",
        help="同时启用 M4.3 静态 ELF 加载验收（kernel-test-m43 feature）；"
        "该测试验收后停机、不返回主流程（不打印版本横幅），默认关闭",
    )
    p_br.add_argument(
        "--test-m4.4",
        dest="test_m44",
        action="store_true",
        help="同时启用 M4.4 真实用户程序验收（kernel-test-m44 feature）；"
        "先编译 libsys+init 用户程序再编译内核嵌入，验收后停机，默认关闭",
    )
    p_br.add_argument(
        "--test-m5",
        dest="test_m5",
        action="store_true",
        help="同时启用 M5 写时复制 COW 验收（kernel-test-m5 feature）；"
        "纯内存逻辑，返回主流程继续启动，默认关闭",
    )
    p_br.add_argument(
        "--release",
        action="store_true",
        help="以 release 配置构建内核（验证正式 release 形态）；默认 debug",
    )
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
