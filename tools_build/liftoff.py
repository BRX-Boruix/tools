"""liftoff（UEFI 引导器）接线：编 EFI、摆 ESP、给 run 出 OVMF 参数。

`--liftoff` 把启动链从「BIOS + brxLimine」换成「UEFI + liftoff」，**介质不变**：
ISO / systemdisk 里已经有 `/boot/kernel` 与 `/programs/*`，liftoff 的 ISO9660 与
EXT2 两条路径都读得懂，缺的只是一个 UEFI ESP（`EFI/BOOT/BOOTX64.EFI`）。

与既有开关正交：`br --systemdisk --redisk --serial --release --liftoff` 等组合
都成立——build 侧只追加「编 liftoff + 摆 ESP」，run 侧只追加「OVMF + ESP」。
"""

import os
import shutil
import subprocess

from . import config
from .util import err, info

# liftoff 源码目录与构建目标（与 liftoff 仓库的 rust-toolchain.toml 一致）。
LIFTOFF_DIR = os.path.join(config.PROJECT_ROOT, "liftoff")
EFI_TARGET = "x86_64-unknown-uefi"
EFI_SRC = os.path.join(LIFTOFF_DIR, "target", EFI_TARGET, "release", "liftoff.efi")
# ESP 落点：工作区根的 esp-liftoff/（与 brxLimine 的产物互不干扰）。
ESP_DIR = os.path.join(config.PROJECT_ROOT, "esp-liftoff")


def _qemu_dir() -> str:
    """从 .env 取 QEMU_DIR（与 boottest 同一真值来源；缺项即硬失败）。"""
    env = {}
    if os.path.isfile(config.ENV_FILE):
        with open(config.ENV_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env[k] = v
    d = env.get("QEMU_DIR")
    if not d:
        err("未在 " + config.ENV_FILE + " 中找到 QEMU_DIR（liftoff 需要 OVMF 固件）")
    return d


def ovmf_firmware() -> str:
    """OVMF 固件路径：<QEMU_DIR>/share/edk2-x86_64-code.fd。"""
    fw = os.path.join(_qemu_dir(), "share", "edk2-x86_64-code.fd")
    if not os.path.isfile(fw):
        err("未找到 OVMF 固件: " + fw + "（liftoff 走 UEFI，需要 edk2-x86_64-code.fd）")
    return fw


def build_efi() -> str:
    """cargo build --release --target x86_64-unknown-uefi；返回 liftoff.efi 路径。"""
    if not os.path.isdir(LIFTOFF_DIR):
        err("未找到 liftoff 源码目录: " + LIFTOFF_DIR)
    info("构建 liftoff（UEFI，" + EFI_TARGET + "）...")
    rc = subprocess.run(
        ["cargo", "build", "--release", "--target", EFI_TARGET], cwd=LIFTOFF_DIR
    ).returncode
    if rc != 0:
        err("liftoff 构建失败：cargo build --release --target " + EFI_TARGET)
    if not os.path.isfile(EFI_SRC):
        err("未找到构建产物: " + EFI_SRC)
    return EFI_SRC


def stage_esp() -> str:
    """把 liftoff.efi 摆成 ESP 的 EFI/BOOT/BOOTX64.EFI（幂等），返回 ESP 目录。"""
    if not os.path.isfile(EFI_SRC):
        err("未找到 " + EFI_SRC + "：先执行 build --liftoff（或 run/br 加 --liftoff 会自动构建）")
    boot_dir = os.path.join(ESP_DIR, "EFI", "BOOT")
    os.makedirs(boot_dir, exist_ok=True)
    shutil.copy(EFI_SRC, os.path.join(boot_dir, "BOOTX64.EFI"))
    return ESP_DIR


def ensure_ready() -> str:
    """确保 liftoff.efi 与 ESP 就绪（build/run 共用），返回 ESP 目录。"""
    if not os.path.isfile(EFI_SRC):
        build_efi()
    return stage_esp()


def uefi_args(esp: str) -> list:
    """OVMF 固件 + ESP 的 QEMU 参数（介质参数由调用方照旧拼接）。

    ESP 走 **USB 可移动介质**：OVMF 没有变量存储（未给 vars pflash）时，只对
    默认可移动路径 EFI/BOOT/BOOTX64.EFI 建引导项；裸 IDE 挂载的 vvfat 盘在
    多盘拓扑下不会被枚举成可引导设备（实测：只出 Boot0001 系统盘 + Boot0003
    Internal Shell，直接掉进 UEFI Shell）。USB 挂载则必然枚举。
    """
    return [
        "-drive", "if=pflash,format=raw,readonly=on,file=" + ovmf_firmware(),
        "-drive", "if=none,id=liftoff-esp,format=raw,file=fat:rw:" + esp,
        "-device", "qemu-xhci",
        "-device", "usb-storage,drive=liftoff-esp",
    ]

def qemu_exe() -> str:
    """qemu-system-x86_64 可执行文件（QEMU_DIR 优先）。"""
    exe = os.path.join(_qemu_dir(), "qemu-system-x86_64.exe")
    if not os.path.isfile(exe):
        err("未找到 QEMU: " + exe)
    return exe