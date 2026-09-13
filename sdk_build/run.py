"""run 子命令：用 QEMU 启动 ISO。"""

import argparse
import os
import shutil
import subprocess

from . import config
from .util import err, info


def _find_qemu() -> str:
    """定位 qemu-system-x86_64：优先 .env 的 QEMU_DIR，其次 PATH。"""
    env = config.load_env()
    qemu_dir = env.get("QEMU_DIR")
    exe = config.QEMU + ".exe"
    if qemu_dir:
        candidate = os.path.join(qemu_dir, exe)
        if os.path.isfile(candidate):
            return candidate
    on_path = shutil.which(config.QEMU)
    if on_path:
        return on_path
    return ""


def cmd(args: argparse.Namespace) -> int:
    """用 QEMU 启动 ISO（默认）或系统盘（--systemdisk）。

    --systemdisk 从 build 产出的 systemdisk.img 经 -hda 启动（ADR-029 安装模式）；
    可与 --disk/--redisk 数据盘并存：系统盘挂 -hda、数据盘挂 -hdb，两个盘同时加载。
    """
    qemu = _find_qemu()
    if not qemu:
        err("未找到 " + config.QEMU + "，请在 .env 配置 QEMU_DIR 或加入 PATH")
        return 1

    from . import disk
    systemdisk = getattr(args, "systemdisk", False)
    disk_path = disk.DISK_IMG_PATH
    # 数据盘策略三选一（main.py 用 mutually exclusive group 保证至多其一）：
    #   默认 / `--nodisk`  → 不挂数据盘（纯 liveCD 或纯系统盘）
    #   `--disk`           → 挂现有数据盘（缺失则自动创建）
    #   `--redisk`         → 无条件重建数据盘再挂（清旧盘数据，用当前构建产物）
    nodisk = getattr(args, "nodisk", False)
    redisk = getattr(args, "redisk", False)
    with_disk = getattr(args, "disk", False)
    disk_mode = "redisk" if redisk else ("disk" if with_disk else ("nodisk" if nodisk else "livecd"))

    # SMP 多核：--smp N（默认 4）→ -smp N；--no-smp（None）→ 不传，单核启动。
    # 加 -cpu max 以启用现代 CPU 特性（多核下 APIC 拓扑/LAPIC id 分布更贴近真机）。
    smp_n = getattr(args, "smp", 4)
    smp_args = ["-cpu", "max", "-smp", str(smp_n)] if smp_n is not None else []

    if systemdisk:
        # 系统盘启动：不依赖 ISO（build --systemdisk 产物即系统盘）。
        sys_disk = disk.SYSTEM_DISK_IMG_PATH
        if not os.path.isfile(sys_disk):
            err("未找到系统盘 " + sys_disk + "，请先运行 build --systemdisk")
            return 1
        if disk_mode in ("disk", "redisk"):
            disk.ensure_disk_image_exists(disk_path, force=(disk_mode == "redisk"))
        cmd = [qemu, "-hda", sys_disk]
        if disk_mode in ("disk", "redisk"):
            cmd += ["-hdb", disk_path]
        cmd += ["-boot", "order=c", "-m", str(args.mem),
                "-netdev", "user,id=net0", "-device", "e1000,netdev=net0"]
        cmd += smp_args
        cmd += config.sound_card_args()
    else:
        # ISO 启动（默认/liveCD）：
        if not os.path.isfile(config.OUTPUT_ISO):
            err("未找到 ISO: " + config.OUTPUT_ISO + "，请先运行 build")
            return 1
        if disk_mode in ("disk", "redisk"):
            disk.ensure_disk_image_exists(disk_path, force=(disk_mode == "redisk"))
        cmd = [qemu, "-cdrom", config.OUTPUT_ISO]
        if disk_mode in ("disk", "redisk"):
            cmd += ["-hda", disk_path]
        cmd += ["-boot", "order=d", "-m", str(args.mem),
                "-netdev", "user,id=net0", "-device", "e1000,netdev=net0"]
        cmd += smp_args
        cmd += config.sound_card_args()
    if args.serial:
        cmd += ["-serial", "stdio"]
    extra = (" + 数据盘 " + os.path.basename(disk_path)) if disk_mode in ("disk", "redisk") else ""
    info("盘策略: " + disk_mode + extra)
    smp_desc = ("SMP " + str(smp_n) + " 核") if smp_n is not None else "单核 (no SMP)"
    info("CPU 拓扑: " + smp_desc)
    info("声卡: " + config.SOUND_CARD_CONTROLLER + " + " + config.SOUND_CARD_OUTPUT
         + " -> " + os.path.basename(config.OUTPUT_WAV))
    info("启动 QEMU: " + os.path.basename(qemu) + " (boot=" + ("c" if systemdisk else "d") + ")")
    return subprocess.run(cmd).returncode

