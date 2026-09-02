"""Limine BIOS stage2 交叉编译逻辑（用 i686-elf-gcc 交叉工具链）。

职责：把 brxLimine（Limine fork）源码按 Limine 官方 BIOS 目标的编译参数
交叉编译为 stage2 目标文件/链接为 ELF。编译参数逐项取自 Limine 12.5.2
源码 common/common.mk 的 BIOS (TARGET=bios) 分支，保证与官方构建一致。

真实链路（S06/S09）：本模块只驱动真实编译器，绝不伪造/拼接产物。
若工具链缺失或源码依赖头文件（freestanding-c-hdrs / limine-protocol /
flanterm / libfdt 等子模块）未就位，如实报错并量化失败，拒绝产出假结果。
"""

import os
import shutil
import subprocess

import argparse

from . import config
from .util import err, info


# Limine BIOS 目标（common.mk TARGET=bios 分支）的编译/链接参数。
# 仅保留 BIOS 目标所需项；UEFI 目标不在本模块范围。
BIOS_CFLAGS = [
    "-g", "-Wall", "-Wextra", "-Wshadow", "-Wvla",
    "-std=gnu11",
    "-nostdinc",
    "-ffreestanding",
    "-ffunction-sections", "-fdata-sections",
    "-fno-stack-protector", "-fno-stack-check",
    "-fno-omit-frame-pointer", "-fno-strict-aliasing", "-fno-lto",
    # S2CFLAGS（仅 .s2.c）
    "-Os",
    # BIOS 专属
    "-fno-PIC", "-m32", "-march=i686", "-mabi=sysv",
    "-mno-80387", "-mno-mmx",
]

# BIOS 目标的预处理宏（common.mk CPPFLAGS_FOR_TARGET 的 BIOS 增量）。
BIOS_CPPFLAGS = [
    "-DBIOS",
    "-DCOM_OUTPUT=0",
    "-DE9_OUTPUT=0",
    "-DFLANTERM_IN_FLANTERM",
]

# BIOS 目标的链接参数（common.mk LDFLAGS_FOR_TARGET 的 BIOS 增量）。
BIOS_LDFLAGS = [
    "-nostdlib",
    "-z", "max-page-size=0x1000",
    "--gc-sections",
    "-m", "elf_i386",
    "-static",
    "--build-id=sha1",
]

# stage2 汇编（.s2.c）的额外编译参数。
S2CFLAGS = ["-Os"]


def _tool(name: str) -> str:
    """解析 i686-elf 交叉工具链下的可执行文件绝对路径。"""
    return os.path.join(config.I686_ELF_GCC_DIR, "bin", name)


def check_toolchain() -> int:
    """校验 i686-elf 交叉工具链与 nasm 是否可用；缺失即如实报错。

    返回 0 表示就绪；非 0 表示缺失（量化列出缺什么）。
    """
    missing = []
    for name, path in [
        ("i686-elf-gcc", config.I686_ELF_GCC),
        ("i686-elf-ld", _tool("i686-elf-ld.exe")),
        ("i686-elf-objcopy", _tool("i686-elf-objcopy.exe")),
        ("nasm", shutil.which("nasm") or ""),
    ]:
        if not path or not os.path.isfile(path):
            missing.append(name)
    if missing:
        err(f"缺少交叉编译工具: {missing}")
        info("请先下载解压 i686-elf 工具链到 envfiles/ 并在 .env 配置 I686_ELF_GCC_DIR")
        return 1
    info(f"交叉工具链就绪: {config.I686_ELF_GCC} (i686-elf-gcc)")
    return 0


def _compile_cmd(src: str, obj: str, s2: bool = False, inc_dirs: tuple = ()) -> list:
    """构造一条 i686-elf-gcc 编译命令（参数取自 common.mk BIOS 分支）。"""
    cmd = [config.I686_ELF_GCC] + BIOS_CFLAGS[:]
    if s2:
        cmd += S2CFLAGS
    for inc in inc_dirs:
        cmd += ["-I", inc]
    cmd += BIOS_CPPFLAGS
    cmd += ["-c", src, "-o", obj]
    return cmd


def compile_sources(
    brx_dir: str,
    build_dir: str,
    sources: list,
    extra_inc: tuple = (),
) -> int:
    """把给定 Limine 源码文件交叉编译为 ELF32 目标文件。

    参数:
        brx_dir:   brxLimine 源码根目录。
        build_dir: 编译输出目录（.o 按源码相对路径镜像）。
        sources:   待编译源文件列表（brx_dir 相对路径，如 "common/fs/fat32.s2.c"）。
        extra_inc: 额外 -I 头文件搜索路径。

    返回 0=全部成功；否则如实返回第一个失败文件的返回值。
    """
    rc = check_toolchain()
    if rc != 0:
        return rc
    if not os.path.isdir(brx_dir):
        err(f"brxLimine 源码目录不存在: {brx_dir}")
        return 1
    os.makedirs(build_dir, exist_ok=True)

    ok = 0
    for rel in sources:
        src = os.path.join(brx_dir, rel)
        obj = os.path.join(build_dir, os.path.splitext(rel)[0] + ".o")
        os.makedirs(os.path.dirname(obj), exist_ok=True)
        is_s2 = rel.endswith(".s2.c")
        # 头文件搜索路径：与 Limine 官方 common.mk CPPFLAGS_FOR_TARGET 一致。
        # 包括源码 common、libc-compat、子模块依赖（freestanding-c-hdrs /
        # limine-protocol / flanterm / libfdt），以及调用方补充的依赖头。
        inc = [
            os.path.join(brx_dir, "common"),
            os.path.join(brx_dir, "common", "libc-compat"),
            os.path.join(brx_dir, "limine-protocol", "include"),
            os.path.join(brx_dir, "flanterm", "src"),
            os.path.join(brx_dir, "libfdt", "src"),
            os.path.join(brx_dir, "freestanding-c-hdrs", "include"),
        ]
        inc = [d for d in inc if os.path.isdir(d)] + list(extra_inc)
        cmd = _compile_cmd(src, obj, s2=is_s2, inc_dirs=inc)
        info(f"编译 {rel}")
        r = subprocess.run(cmd)
        if r.returncode != 0:
            err(f"编译失败: {rel}")
            return r.returncode
        if not os.path.isfile(obj):
            err(f"编译未产出目标文件: {obj}")
            return 1
        ok += 1
    info(f"交叉编译完成: {ok}/{len(sources)} 个源文件 -> {build_dir}")
    return 0


def verify_object(obj: str) -> int:
    """校验目标文件为 ELF32 / Intel 80386（BIOS 目标应如此）。"""
    readelf = _tool("i686-elf-readelf.exe")
    if not os.path.isfile(readelf):
        err(f"缺少 i686-elf-readelf: {readelf}")
        return 1
    r = subprocess.run(
        [readelf, "-h", obj], capture_output=True, text=True
    )
    out = r.stdout or ""
    if "Intel 80386" not in out or "ELF32" not in out:
        err(f"目标文件架构异常（应 ELF32/Intel 80386）: {obj}")
        return 1
    info(f"目标文件架构校验通过 (ELF32/Intel 80386): {obj}")
    return 0


def link_bios_stage2(build_dir: str, objects: list, out_elf: str, ld_script: str) -> int:
    """用 i686-elf-ld 按 BIOS 链接脚本链接 stage2 为 ELF。

    参数:
        build_dir: 链接/中间产物目录。
        objects:   目标文件绝对路径列表。
        out_elf:   输出 ELF 路径。
        ld_script: 链接脚本路径（由 linker_bios.ld.in 预处理得到）。
    """
    rc = check_toolchain()
    if rc != 0:
        return rc
    ld = _tool("i686-elf-ld.exe")
    if not os.path.isfile(ld):
        err(f"缺少 i686-elf-ld: {ld}")
        return 1
    cmd = [ld] + BIOS_LDFLAGS + objects + ["-T", ld_script, "-o", out_elf]
    info(f"链接 stage2: {os.path.basename(out_elf)}")
    r = subprocess.run(cmd)
    if r.returncode != 0:
        err(f"链接失败: {out_elf}")
        return r.returncode
    if not os.path.isfile(out_elf):
        err(f"链接未产出 ELF: {out_elf}")
        return 1
    info(f"链接完成: {out_elf}")
    return 0


# limine-build 子命令的缺省源清单：BIOS 目标下 common/fs 的文件系统驱动
# （后续可按需扩为完整 stage2 源清单）。
DEFAULT_SOURCES = [
    "common/fs/fat32.s2.c",
]


def cmd(args: argparse.Namespace) -> int:
    """limine-build 子命令入口：校验工具链并按需交叉编译。"""
    brx_dir = args.brx_dir or config.BRXLIMINE_DIR
    build_dir = args.build_dir or os.path.join(config.ENVFILES_DIR, "_limine_build")

    # --check：仅校验工具链
    if getattr(args, "check", False):
        return check_toolchain()

    # 依赖头文件由 compile_sources 自动从 brxLimine 子模块目录解析；
    # 这里校验关键依赖头是否就位（freestanding-c-hdrs 提供 -nostdinc 下的标准头）。
    fhdr_real = os.path.join(brx_dir, "freestanding-c-hdrs", "include", "stdint.h")
    if not os.path.isfile(fhdr_real):
        err("缺少 freestanding-c-hdrs 依赖头（先运行 bootstrap 初始化子模块）")
        err(f"未找到: {fhdr_real}")
        return 1

    src = args.source
    sources = [src] if src else DEFAULT_SOURCES

    rc = compile_sources(brx_dir, build_dir, sources)
    if rc != 0:
        return rc

    # 校验每个目标文件架构
    for rel in sources:
        obj = os.path.join(build_dir, os.path.splitext(rel)[0] + ".o")
        rc = verify_object(obj)
        if rc != 0:
            return rc
    return 0
