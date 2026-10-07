#!/usr/bin/env python3
"""
BORUIX 系统工具统一入口（系统集成、构建与验收）。

用法:
    python main.py <子命令> [选项]

子命令:
    build    编译内核并生成可引导 ISO（x86_64）（Limine 引导完全走 brxLimine fork）
    install  产出第三方 sysroot（3P1-2）
    run      用 QEMU 启动 ISO
    br       Build and Run：编译生成 ISO 后立即用 QEMU 启动
    --help   查看帮助

各子命令的实现分散在 tools_build/ 包中，本文件只负责入口与参数注册。
"""

import argparse
import sys

from tools_build import b3p, br, build, config, disk, elf_image, install, limine_build, run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tools",
        description="BORUIX 系统工具主入口（构建/运行/验收；第三方 SDK 内容在 ../sdk）",
    )
    sub = parser.add_subparsers(dest="command", required=True)


    # limine-build 子命令：用 i686-elf 交叉编译器编译 Limine BIOS stage2
    p_lb = sub.add_parser("limine-build", help="用 i686-elf 交叉编译器交叉编译 Limine BIOS stage2")
    p_lb.add_argument(
        "--check",
        action="store_true",
        help="仅校验交叉编译工具链是否就绪，不实际编译",
    )
    p_lb.add_argument(
        "--source",
        default=None,
        help="待编译的 Limine 源文件（brxLimine 相对路径，如 common/fs/fat32.s2.c）；默认按缺省源清单",
    )
    p_lb.add_argument(
        "--brx-dir",
        default=None,
        help="brxLimine 源码根目录（默认项目根下 brxLimine）",
    )
    p_lb.add_argument(
        "--build-dir",
        default=None,
        help="编译输出目录（默认 envfiles/_limine_build）",
    )
    p_lb.set_defaults(func=limine_build.cmd)

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
        "--test-pre2",
        dest="test_pre2",
        action="store_true",
        help="同时启用 ADR-034 PRE-2 用户态 #PF CR2 透传验收（kernel-test-pre2 "
        "feature）；该测试验收后停机、不返回主流程，默认关闭",
    )
    p_build.add_argument(
        "--test-signal",
        dest="test_signal",
        action="store_true",
        help="同时启用 ADR-034 S1-13 信号 handler/sigreturn 停机验收（kernel-test-signal "
        "feature）；该测试验收后停机、不返回主流程，默认关闭",
    )
    p_build.add_argument(
        "--signal-halt",
        dest="signal_halt",
        default="nested",
        choices=["nested", "handler", "fault"],
        help="停机验收选择跑哪个 halt 测试：nested（默认）/ handler / fault（须与 --test-signal 同用）",
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
        "--test-waitpid",
        dest="test_waitpid",
        action="store_true",
        help="同时启用 C7.1/#7 waitpid 父子链停机验收（kernel-test-waitpid feature）；"
        "该测试验收后停机、不返回主流程，默认关闭",
    )
    p_build.add_argument(
        "--release",
        action="store_true",
        help="以 release 配置构建内核（验证正式 release 形态）；默认 debug",
    )
    p_build.add_argument(
        "--systemdisk",
        action="store_true",
        help="产系统盘 systemdisk.img（--systemdisk；可与 --disk/--redisk 并存，系统盘与数据盘同时挂载）",
    )
    p_build.add_argument(
        "--brxlimine",
        action="store_true",
        help="（已废除，恒走 brxLimine fork，保留以兼容旧脚本）",
    )
    p_build.set_defaults(func=build.cmd)

    # run 子命令
    p_run = sub.add_parser("run", help="用 QEMU 启动 ISO")
    p_run.add_argument("--mem", default=config.DEFAULT_MEM, help="内存大小（默认见 config.DEFAULT_MEM）")
    p_run.add_argument("--serial", action="store_true", help="启用串口输出到终端")
    p_run.add_argument(
        "--silent",
        action="store_true",
        help="音频改为落盘到 audio-out.wav 而不是本机喇叭（无声卡环境/留档用）",
    )
    # 盘策略三选一：默认即 LiveCD（不挂盘）；--disk 挂现有盘（缺失自动建）；
    # --redisk 重建盘再挂。均为互斥，绝不静默覆盖盘数据。
    p_run_disk_grp = p_run.add_mutually_exclusive_group()
    p_run_disk_grp.add_argument(
        "--disk",
        action="store_true",
        help="挂载外部盘（disk.img，缺失自动创建）——非 LiveCD",
    )
    p_run_disk_grp.add_argument(
        "--redisk",
        action="store_true",
        help="无条件重建外部盘再挂载（清旧盘数据，用当前构建产物）",
    )
    p_run_disk_grp.add_argument(
        "--nodisk",
        action="store_true",
        help="显式声明纯 LiveCD 启动（默认即此，仅供消除歧义）",
    )
    p_run.add_argument(
        "--ahci",
        action="store_true",
        help="把盘挂到显式插入的 ich9-ahci 控制器（而非默认 PIIX4 IDE），"
        "供 AHCI 驱动验收；默认关闭，现有链路行为不变",
    )
    p_run.add_argument(
        "--systemdisk",
        action="store_true",
        help="从 build 产出的系统盘 systemdisk.img 启动（-hda；可与 --disk/--redisk 并存，系统盘 -hda + 数据盘 -hdb）",
    )
    # SMP 多核：默认 4 核；--no-smp 显式禁用（单核）。--smp N 与 --no-smp 互斥。
    p_run_smp_grp = p_run.add_mutually_exclusive_group()
    p_run_smp_grp.add_argument(
        "--smp",
        type=int,
        default=4,
        metavar="N",
        help="启用 SMP 多核，N = CPU 核数（默认 4）",
    )
    p_run_smp_grp.add_argument(
        "--no-smp",
        dest="smp",
        action="store_const",
        const=None,
        help="禁用 SMP（单核启动，不传 -smp 给 QEMU）",
    )
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
        "--test-pre2",
        dest="test_pre2",
        action="store_true",
        help="同时启用 ADR-034 PRE-2 用户态 #PF CR2 透传验收（kernel-test-pre2 "
        "feature）；该测试验收后停机、不返回主流程，默认关闭",
    )
    p_br.add_argument(
        "--test-signal",
        dest="test_signal",
        action="store_true",
        help="同时启用 ADR-034 S1-13 信号 handler/sigreturn 停机验收（kernel-test-signal "
        "feature）；该测试验收后停机、不返回主流程，默认关闭",
    )
    p_br.add_argument(
        "--signal-halt",
        dest="signal_halt",
        default="nested",
        choices=["nested", "handler", "fault"],
        help="停机验收选择跑哪个 halt 测试：nested（默认）/ handler / fault（须与 --test-signal 同用）",
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
        "--test-waitpid",
        dest="test_waitpid",
        action="store_true",
        help="同时启用 C7.1/#7 waitpid 父子链停机验收（kernel-test-waitpid feature）；"
        "该测试验收后停机、不返回主流程，默认关闭",
    )
    p_br.add_argument(
        "--release",
        action="store_true",
        help="以 release 配置构建内核（验证正式 release 形态）；默认 debug",
    )
    p_br.add_argument("--mem", default=config.DEFAULT_MEM, help="内存大小（默认见 config.DEFAULT_MEM）")
    p_br.add_argument("--serial", action="store_true", help="启用串口输出到终端")
    p_br.add_argument(
        "--silent",
        action="store_true",
        help="音频改为落盘到 audio-out.wav 而不是本机喇叭（无声卡环境/留档用）",
    )
    # 盘策略三选一（同 run）：默认即 LiveCD；--disk 挂盘；--redisk 重建盘再挂。
    p_br_disk_grp = p_br.add_mutually_exclusive_group()
    p_br_disk_grp.add_argument(
        "--disk",
        action="store_true",
        help="挂载外部盘（disk.img，缺失自动创建）——非 LiveCD",
    )
    p_br_disk_grp.add_argument(
        "--redisk",
        action="store_true",
        help="无条件重建外部盘再挂载（清旧盘数据，用当前构建产物）",
    )
    p_br_disk_grp.add_argument(
        "--nodisk",
        action="store_true",
        help="显式声明纯 LiveCD 启动（默认即此，仅供消除歧义）",
    )
    p_br.add_argument(
        "--ahci",
        action="store_true",
        help="把盘挂到显式插入的 ich9-ahci 控制器（而非默认 PIIX4 IDE），"
        "供 AHCI 驱动验收；默认关闭，现有链路行为不变",
    )
    p_br.add_argument(
        "--systemdisk",
        action="store_true",
        help="从 build 产出的系统盘 systemdisk.img 启动（-hda；可与 --disk/--redisk 并存，系统盘 -hda + 数据盘 -hdb）",
    )
    # SMP 多核：默认 4 核；--no-smp 显式禁用（单核）。--smp N 与 --no-smp 互斥。
    p_br_smp_grp = p_br.add_mutually_exclusive_group()
    p_br_smp_grp.add_argument(
        "--smp",
        type=int,
        default=4,
        metavar="N",
        help="启用 SMP 多核，N = CPU 核数（默认 4）",
    )
    p_br_smp_grp.add_argument(
        "--no-smp",
        dest="smp",
        action="store_const",
        const=None,
        help="禁用 SMP（单核启动，不传 -smp 给 QEMU）",
    )
    p_br.set_defaults(func=br.cmd)

    # mkimg 子命令：创建/格式化物理磁盘镜像
    p_mkimg = sub.add_parser(
        "mkimg",
        help="由 tools/diskfiles/ 创建或重新格式化数据盘镜像 (EXT2)",
    )
    p_mkimg.add_argument(
        "--size",
        type=int,
        default=None,
        help="磁盘大小 (MB)。默认按 diskfiles 内容自动推算；显式给出则作为覆盖值",
    )
    p_mkimg.add_argument("--label", default="BORUIX_DATA", help="EXT2 卷标名 (默认 BORUIX_DATA)")
    p_mkimg.add_argument("--force", "-f", action="store_true", help="强制覆盖已有磁盘镜像无需确认")
    p_mkimg.set_defaults(func=disk.cmd_mkimg)

    # b3p 子命令：构建第三方程序并落到 tools/diskfiles/3p/（数据盘 /3p/ 下）。
    #
    # 与 build 的 USER_PROGRAMS 是两条独立通道：第三方程序不进 liveCD payload、
    # 不重编内核，只经数据盘在 /volumes/<label>/3p/<name>.elf 被 exec。
    p_b3p = sub.add_parser(
        "b3p",
        help="构建第三方程序（清单见 tools_build/b3p.py）并放入 tools/diskfiles/3p/",
    )
    p_b3p.add_argument(
        "--debug",
        action="store_true",
        help="以 debug 配置构建（默认 release：交付物体积/加载时间更优）",
    )
    p_b3p.add_argument(
        "--prog",
        action="append",
        default=None,
        metavar="NAME",
        help="只构建指定程序（可重复）；名字须在清单中，拼错即报错",
    )
    p_b3p.add_argument(
        "--list",
        action="store_true",
        help="只列出第三方程序与源码包清单，不构建",
    )
    # --src：走"源码包"通道（3P6-5）——只把源码铺到 3p/src/<name>/，**不编译**；
    # 编译由系统内编译器在 BORUIX 机内按包里的 BUILD 配方完成。
    p_b3p.add_argument(
        "--src",
        action="store_true",
        help="分发源码包（只铺源码到 3p/src/<name>/，编译在机内做；清单见 b3p.py 的 SOURCE_PACKAGES）",
    )
    # --new：生成最小可编译骨架（3P1-6）。生成**现代形态**——无 build.rs、无 linker.ld，
    # 目标定义/链接脚本/TLS 模型全部来自 sysroot 的 cargo 配置。
    p_b3p.add_argument(
        "--new",
        metavar="NAME",
        default=None,
        help="生成最小可编译工程骨架（需 --sysroot 或 BORUIX_SYSROOT）",
    )
    p_b3p.add_argument(
        "--sysroot",
        default=None,
        metavar="DIR",
        help="sysroot 目录（python main.py install --prefix <DIR> 的产物）",
    )
    p_b3p.add_argument(
        "--dir",
        default=None,
        metavar="PARENT",
        help="骨架生成到哪个父目录下（默认当前目录）",
    )
    p_b3p.set_defaults(func=b3p.cmd)

    # where 子命令：把内核 ELF 里的地址反解成 `模块::路径::函数+偏移`（诊断用）。
    #
    # 存在的理由：内核 panic / 异常只给出 RIP 与 CR2，没有符号反解就只能靠猜。
    # L5 的最后一层缺陷正是靠它从「某个地址出错」变成「哪条路径出错」
    # （`arch_x86_64::smp::requested_cpu_count` 读 `0x3de16680`——引导器响应容器的裸地址）。
    p_where = sub.add_parser(
        "where",
        help="把内核 ELF 里的地址反解成符号（诊断）",
    )
    p_where.add_argument(
        "addresses",
        nargs="*",
        type=lambda text: int(text, 0),
        metavar="ADDR",
        help="待反解的地址（接受 0x 前缀）；不给出则只打印映像概况",
    )
    p_where.add_argument(
        "--iso",
        default=None,
        help="ISO 路径（默认 config.OUTPUT_ISO，即构建产物）",
    )
    p_where.add_argument(
        "--sections",
        action="store_true",
        dest="list_sections",
        help="改为列出全部节名",
    )
    p_where.set_defaults(func=elf_image.cmd)

    # install 子命令：产出可交付给第三方的 sysroot（3P1-2）。
    #
    # 这是「分发解耦」的交付面：第三方拿到 <prefix> 后，C 程序一条 boruix-clang 即可
    # 编出可运行 ELF，Rust 工程用 <prefix>/cargo-config.toml 即可，**无需克隆系统源码**。
    p_install = sub.add_parser(
        "install",
        help="产出第三方 sysroot（头文件 + libc.a + 链接脚本 + C 驱动 + 目标定义）",
    )
    p_install.add_argument(
        "--prefix",
        required=True,
        help="安装根目录（可不存在；已存在则就地更新，不删除无关文件）",
    )
    p_install.add_argument(
        "--debug",
        action="store_true",
        help="以 debug 配置构建 libc.a（默认 release：交付物形态）",
    )
    p_install.set_defaults(func=install.cmd)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
