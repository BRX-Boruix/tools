"""build 子命令：编译内核并生成可引导 ISO。"""

import argparse
import os
import shutil
import subprocess

from . import config
from .util import err, info


def _kernel_elf() -> str:
    return os.path.join(config.KERNEL_DIR, "target", config.TARGET, "debug", "kernel")


def _cargo_build_kernel() -> int:
    """编译内核为 ELF"""
    info(f"编译内核 (target={config.TARGET})")
    cmd = ["cargo", "build", "--target", config.TARGET]
    r = subprocess.run(cmd, cwd=config.KERNEL_DIR)
    if r.returncode != 0:
        err("内核编译失败")
        return r.returncode
    elf = _kernel_elf()
    if not os.path.isfile(elf):
        err(f"未找到内核 ELF: {elf}")
        return 1
    info(f"内核 ELF: {elf}")
    return 0


def _make_iso() -> int:
    """用 xorriso 生成 BIOS+UEFI 混合引导 ISO"""
    iso_root = os.path.join(config.SDK_DIR, "iso_root")
    if os.path.isdir(iso_root):
        shutil.rmtree(iso_root)
    os.makedirs(os.path.join(iso_root, "boot", "limine"), exist_ok=True)
    os.makedirs(os.path.join(iso_root, "EFI", "BOOT"), exist_ok=True)

    # 拷贝内核
    shutil.copy(_kernel_elf(), os.path.join(iso_root, "boot", "kernel"))
    # 拷贝 limine.conf
    shutil.copy(config.LIMINE_CONF, os.path.join(iso_root, "boot", "limine", "limine.conf"))

    lb = config.LIMINE_BINARY_DIR
    # BIOS
    shutil.copy(os.path.join(lb, "limine-bios-cd.bin"), os.path.join(iso_root, "boot", "limine", "limine-bios-cd.bin"))
    shutil.copy(os.path.join(lb, "limine-bios.sys"), os.path.join(iso_root, "boot", "limine", "limine-bios.sys"))
    # UEFI
    shutil.copy(os.path.join(lb, "limine-uefi-cd.bin"), os.path.join(iso_root, "boot", "limine", "limine-uefi-cd.bin"))
    shutil.copy(os.path.join(lb, "BOOTX64.EFI"), os.path.join(iso_root, "EFI", "BOOT", "BOOTX64.EFI"))

    xorriso = shutil.which("xorriso") or r"C:\ffmpeg\bin\xorriso.exe"
    if not os.path.isfile(xorriso):
        err("未找到 xorriso，无法生成 ISO")
        return 1

    info("用 xorriso 生成 ISO ...")
    # 用相对路径并指定 cwd=SDK_DIR，避免 xorriso 在 Windows 上处理绝对路径出错
    cmd = [
        xorriso, "-as", "mkisofs",
        "-b", "boot/limine/limine-bios-cd.bin",
        "-no-emul-boot", "-boot-load-size", "4", "-boot-info-table",
        "--efi-boot", "boot/limine/limine-uefi-cd.bin",
        "-efi-boot-part", "--efi-boot-image", "--protective-msdos-label",
        "iso_root", "-o", config.OUTPUT_ISO,
    ]
    r = subprocess.run(cmd, cwd=config.SDK_DIR)
    if r.returncode != 0:
        err("xorriso 生成 ISO 失败")
        return r.returncode

    # BIOS 引导安装
    if not os.path.isfile(config.LIMINE_TOOL):
        err(f"未找到 limine 工具: {config.LIMINE_TOOL}")
        return 1
    info("运行 limine bios-install ...")
    r = subprocess.run([config.LIMINE_TOOL, "bios-install", config.OUTPUT_ISO])
    if r.returncode != 0:
        err("limine bios-install 失败")
        return r.returncode

    shutil.rmtree(iso_root)
    info(f"ISO 已生成: {config.OUTPUT_ISO}")
    return 0


def cmd(args: argparse.Namespace) -> int:
    """编译内核并生成可引导 ISO"""
    rc = _cargo_build_kernel()
    if rc != 0:
        return rc
    return _make_iso()
