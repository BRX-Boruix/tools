"""run 子命令：用 QEMU 启动 ISO。"""

import argparse
import os
import shutil
import subprocess

from . import config, liftoff
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


def _smp_args(smp_n):
    """把 `--smp N` / `--no-smp` 翻译成 QEMU 参数。**纯函数，可离线测**。

    **为什么提取**：这段决定"给虚拟机几颗核" —— 而 E1/S8 的整个判据就建立在这个数字上
    （`total cpus=N` 必须等于这里给的 N）。它此前**内联在 `cmd()` 里**，因此**不可测**。

    **`-cpu max` 与 `-smp` 必须成对出现**：`-cpu max` 才有多核 APIC 拓扑（LAPIC id 分布更贴近真机）。
    历史上这里出过一个真问题：`-cpu max` 使能了 x2APIC，而当时内核只有 xAPIC 路径，于是崩 ——
    该违规已在 liftoff 侧修正（读请求字段、按内核请求决定），两条链路现在可以对等比较。
    """
    if smp_n is None:
        # `--no-smp`：**不传任何参数** = 单核启动（不是传 1）。
        return []
    return ["-cpu", "max", "-smp", str(smp_n)]


def _ahci_controller_args():
    """AHCI 控制器设备参数（STORAGE-AHCI-2a）。

    QEMU 默认 pc 机器是 i440FX + PIIX4（IDE only），-hda 挂的盘属于 PIIX4
    控制器，AHCI 驱动**看不到**它。故走 AHCI 时必须显式插入 ich9-ahci
    控制器，并把盘挂到它的 ahci.N 总线上。

    为什么用 ich9-ahci 而非切 q35 机器：切机器会改动全部现有启动/存储链路的
    默认行为，回归面过大且与补 AHCI 这件事无关。显式插控制器是能力增量，
    默认路径一字不改。
    """
    return ["-device", "ich9-ahci,id=ahci"]


def _disk_args(buses):
    """按 buses 把盘挂到对应总线（单点定义，杜绝 IDE/AHCI 两路漂移）。

    buses 是 (盘文件路径, 总线后缀) 的有序列表：
      - 后缀 ""         -> 走默认 IDE 控制器（等价既有 -hda/-hdb 位置语义）
      - 后缀 "ahci.N"   -> 独立 drive 后端 + 显式挂到 AHCI 总线 N

    抽出为单函数是为了杜绝漂移：两条路径的差异只在挂到哪条总线，
    盘的存在性与顺序必须完全一致，否则易出 AHCI 下漏挂数据盘这类
    只在特定参数组合下暴露的缺陷。
    """
    ide_flags = ["-hda", "-hdb", "-hdc", "-hdd"]
    out = []
    for idx, item in enumerate(buses):
        path, bus = item
        if bus:
            dev_id = "hd" + str(idx)
            out += ["-drive", "if=none,id=" + dev_id + ",file=" + path + ",format=raw"]
            out += ["-device", "ide-hd,drive=" + dev_id + ",bus=" + bus]
        else:
            # IDE 位置语义与既有一致，保证默认路径零回归。
            out += [ide_flags[idx], path]
    return out


def _disk_topology(args, disk_mode, disk_path, sys_disk):
    """裁决挂哪些盘与各挂到哪条总线，产出完整 QEMU 盘参数。

    控制器选择（IDE vs AHCI）与挂哪些盘正交，统一在此裁决，
    避免在每个分支重复写盘参数。
    """
    ahci = bool(getattr(args, "ahci", False))
    systemdisk = bool(getattr(args, "systemdisk", False))
    with_disk = disk_mode in ("disk", "redisk")

    # 盘序列：系统盘在前（与既有系统盘 -hda 语义一致），数据盘在后。
    planned = []
    if systemdisk:
        planned.append(sys_disk)
    if with_disk:
        planned.append(disk_path)

    if ahci:
        buses = [(p, "ahci." + str(i)) for i, p in enumerate(planned)]
    else:
        buses = [(p, "") for p in planned]
    return _disk_args(buses)
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
    silent = getattr(args, "silent", False)
    nodisk = getattr(args, "nodisk", False)
    redisk = getattr(args, "redisk", False)
    with_disk = getattr(args, "disk", False)
    disk_mode = "redisk" if redisk else ("disk" if with_disk else ("nodisk" if nodisk else "livecd"))

    # --liftoff：UEFI 链路（OVMF + ESP），介质与其它开关照旧。
    liftoff_mode = bool(getattr(args, "liftoff", False))

    # SMP 多核：--smp N（默认 4）→ -smp N；--no-smp（None）→ 不传，单核启动。
    # 加 -cpu max 以启用现代 CPU 特性（多核下 APIC 拓扑/LAPIC id 分布更贴近真机）。
    smp_n = getattr(args, "smp", 4)
    # --liftoff 与 BIOS 路径使用同一 CPU 模型：此前 liftoff 会无视 SmpRequest.flags
    # 无条件使能 x2APIC（-cpu max 支持 → 内核只有 xAPIC 路径而崩）。该违规已在
    # liftoff 侧修正（读请求字段、按内核请求决定），故两条链路现在可以对等比较。
    smp_args = _smp_args(smp_n)

    ahci = bool(getattr(args, "ahci", False))
    if systemdisk:
        # 系统盘启动：不依赖 ISO（build --systemdisk 产物即系统盘）。
        sys_disk = disk.SYSTEM_DISK_IMG_PATH
        if not os.path.isfile(sys_disk):
            err("未找到系统盘 " + sys_disk + "，请先运行 build --systemdisk")
            return 1
        if disk_mode in ("disk", "redisk"):
            disk.ensure_disk_image_exists(disk_path, force=(disk_mode == "redisk"))
        boot_order = "c"
    else:
        # ISO 启动（默认/liveCD）：
        sys_disk = ""
        if not os.path.isfile(config.OUTPUT_ISO):
            err("未找到 ISO: " + config.OUTPUT_ISO + "，请先运行 build")
            return 1
        if disk_mode in ("disk", "redisk"):
            disk.ensure_disk_image_exists(disk_path, force=(disk_mode == "redisk"))
        boot_order = "d"

    # 盘挂载：控制器（IDE/AHCI）与"挂哪些盘"在此统一裁决（单点定义）。
    disk_args = _disk_topology(args, disk_mode, disk_path, sys_disk)

    # 顺序关键：QEMU 按序解析设备，AHCI 控制器须在引用其总线的盘**之前**出现。
    if systemdisk:
        cmd = [qemu]
    else:
        cmd = [qemu, "-cdrom", config.OUTPUT_ISO]
    if ahci:
        cmd += _ahci_controller_args()
    cmd += disk_args
    if liftoff_mode:
        # UEFI：**不传 -boot**。没有 OVMF 变量存储时，OVMF 按默认可移动路径
        # \EFI\BOOT\BOOTX64.EFI 起 ESP；强加 boot order 会让它找不到引导项，
        # 直接掉进内置 UEFI Shell（实测症状）。
        boot_args = []
    else:
        boot_args = ["-boot", "order=" + boot_order]
    cmd += boot_args + ["-m", str(args.mem),
            "-netdev", "user,id=net0", "-device", "e1000,netdev=net0"]
    cmd += smp_args
    cmd += config.sound_card_args(silent=silent)
    if liftoff_mode:
        # UEFI：OVMF 固件 + ESP（liftoff.efi 摆成 EFI/BOOT/BOOTX64.EFI）。
        # 介质参数照旧：liveCD 走 -cdrom ISO，--systemdisk 走上面的盘拓扑。
        esp = liftoff.ensure_ready()
        cmd += liftoff.uefi_args(esp)
        info("引导器: liftoff (UEFI/OVMF), ESP=" + esp)
    if args.serial:
        cmd += ["-serial", "stdio"]
    extra = (" + 数据盘 " + os.path.basename(disk_path)) if disk_mode in ("disk", "redisk") else ""
    info("盘策略: " + disk_mode + extra)
    smp_desc = ("SMP " + str(smp_n) + " 核") if smp_n is not None else "单核 (no SMP)"
    info("CPU 拓扑: " + smp_desc)
    info("声卡: " + config.audiodev_desc(silent=silent))
    info("存储控制器: " + ("AHCI (ich9-ahci, 显式)" if ahci else "PIIX4 IDE (默认)"))
    info("启动 QEMU: " + os.path.basename(qemu) + " (boot=" + ("c" if systemdisk else "d") + ")")
    return subprocess.run(cmd).returncode