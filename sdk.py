#!/usr/bin/env python3
"""
BORUIX SDK 辅助工具主入口。

用法:
    python sdk.py <子命令> [选项]

子命令:
    limine   下载并部署 Limine bootloader 到 sdk/boot/
    build    编译内核并生成可引导 ISO
    run      用 QEMU 启动 ISO
    --help   查看帮助
"""

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

SDK_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SDK_DIR)
BOOT_DIR = os.path.join(SDK_DIR, "boot")
LIMINE_BINARY_DIR = os.path.join(BOOT_DIR, "limine-binary")
KERNEL_DIR = os.path.join(PROJECT_ROOT, "kernel")
KERNEL_ELF = os.path.join(
    KERNEL_DIR, "target", "x86_64-unknown-none", "debug", "boruix-kernel"
)
LIMINE_CONF = os.path.join(SDK_DIR, "limine.conf")
LIMINE_TOOL = os.path.join(LIMINE_BINARY_DIR, "limine-tool-windows-x86", "limine.exe")
OUTPUT_ISO = os.path.join(PROJECT_ROOT, "boruix.iso")
ENV_FILE = os.path.join(PROJECT_ROOT, ".env")

# Limine GitHub release 二进制下载地址
LIMINE_RELEASES = "https://github.com/Limine-Bootloader/Limine/releases/download"
DEFAULT_LIMINE_VERSION = "12.5.2"

TARGET = "x86_64-unknown-none"


# ---------------------------------------------------------------------------
# 环境变量读取（.env）
# ---------------------------------------------------------------------------

def load_env() -> dict:
    """读取项目根目录 .env 文件为 dict。"""
    env = {}
    if os.path.isfile(ENV_FILE):
        with open(ENV_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip().strip('"').strip("'")
    return env


# ---------------------------------------------------------------------------
# 公共工具
# ---------------------------------------------------------------------------

def info(msg: str) -> None:
    print(f"[sdk] {msg}")


def err(msg: str) -> None:
    print(f"[sdk] 错误: {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# limine 子命令
# ---------------------------------------------------------------------------

def _download(url: str, dest: str) -> None:
    info(f"下载 {url}")
    urllib.request.urlretrieve(url, dest)


def _extract_zip(zip_path: str, dest: str) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)


def _extract_tar(tar_path: str, dest: str) -> None:
    with tarfile.open(tar_path) as tf:
        tf.extractall(dest)


def cmd_limine(args: argparse.Namespace) -> int:
    """下载并部署 Limine bootloader 到 sdk/boot/limine-binary/"""
    version = args.version
    if args.skip_existing and os.path.isdir(LIMINE_BINARY_DIR):
        info(f"Limine 已存在: {LIMINE_BINARY_DIR} (跳过下载)")
        return 0

    if args.force and os.path.isdir(LIMINE_BINARY_DIR):
        import shutil
        info(f"删除旧版本: {LIMINE_BINARY_DIR}")
        shutil.rmtree(LIMINE_BINARY_DIR)

    os.makedirs(BOOT_DIR, exist_ok=True)

    # 优先用 zip（Windows 友好）
    zip_url = f"{LIMINE_RELEASES}/v{version}/limine-binary.zip"
    archive_url = zip_url
    is_zip = True

    with tempfile.TemporaryDirectory() as tmp:
        archive_path = os.path.join(tmp, "limine-binary.archive")
        try:
            _download(archive_url, archive_path)
        except Exception as e:
            err(f"下载失败: {e}")
            return 1

        try:
            if is_zip:
                _extract_zip(archive_path, BOOT_DIR)
            else:
                _extract_tar(archive_path, BOOT_DIR)
        except Exception as e:
            err(f"解压失败: {e}")
            return 1

    if not os.path.isdir(LIMINE_BINARY_DIR):
        # zip 解压后应产生 limine-binary/ 目录
        err("解压后未找到 limine-binary/ 目录，部署可能不完整")
        return 1

    info(f"Limine v{version} 已部署到 {LIMINE_BINARY_DIR}")
    return 0


# ---------------------------------------------------------------------------
# build 子命令
# ---------------------------------------------------------------------------

def _cargo_build_kernel() -> int:
    """编译内核为 ELF"""
    info(f"编译内核 (target={TARGET})")
    cmd = ["cargo", "build", "--target", TARGET]
    r = subprocess.run(cmd, cwd=KERNEL_DIR)
    if r.returncode != 0:
        err("内核编译失败")
        return r.returncode
    if not os.path.isfile(KERNEL_ELF):
        err(f"未找到内核 ELF: {KERNEL_ELF}")
        return 1
    info(f"内核 ELF: {KERNEL_ELF}")
    return 0


def _make_iso() -> int:
    """用 xorriso 生成 BIOS+UEFI 混合引导 ISO"""
    iso_root = os.path.join(SDK_DIR, "iso_root")
    if os.path.isdir(iso_root):
        shutil.rmtree(iso_root)
    os.makedirs(os.path.join(iso_root, "boot", "limine"), exist_ok=True)
    os.makedirs(os.path.join(iso_root, "EFI", "BOOT"), exist_ok=True)

    # 拷贝内核
    shutil.copy(KERNEL_ELF, os.path.join(iso_root, "boot", "kernel"))
    # 拷贝 limine.conf
    shutil.copy(LIMINE_CONF, os.path.join(iso_root, "boot", "limine", "limine.conf"))

    lb = LIMINE_BINARY_DIR
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
        "iso_root", "-o", OUTPUT_ISO,
    ]
    r = subprocess.run(cmd, cwd=SDK_DIR)
    if r.returncode != 0:
        err("xorriso 生成 ISO 失败")
        return r.returncode

    # BIOS 引导安装
    if not os.path.isfile(LIMINE_TOOL):
        err(f"未找到 limine 工具: {LIMINE_TOOL}")
        return 1
    info("运行 limine bios-install ...")
    r = subprocess.run([LIMINE_TOOL, "bios-install", OUTPUT_ISO])
    if r.returncode != 0:
        err("limine bios-install 失败")
        return r.returncode

    shutil.rmtree(iso_root)
    info(f"ISO 已生成: {OUTPUT_ISO}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    """编译内核并生成可引导 ISO"""
    rc = _cargo_build_kernel()
    if rc != 0:
        return rc
    return _make_iso()


# ---------------------------------------------------------------------------
# run 子命令
# ---------------------------------------------------------------------------

def _find_qemu() -> str:
    """定位 qemu-system-x86_64：优先 .env 的 QEMU_DIR，其次 PATH。"""
    env = load_env()
    qemu_dir = env.get("QEMU_DIR")
    if qemu_dir:
        candidate = os.path.join(qemu_dir, "qemu-system-x86_64.exe")
        if os.path.isfile(candidate):
            return candidate
    on_path = shutil.which("qemu-system-x86_64")
    if on_path:
        return on_path
    return ""


def cmd_run(args: argparse.Namespace) -> int:
    """用 QEMU 启动 ISO"""
    if not os.path.isfile(OUTPUT_ISO):
        err(f"未找到 ISO: {OUTPUT_ISO}，请先运行 build")
        return 1

    qemu = _find_qemu()
    if not qemu:
        err("未找到 QEMU，请在 .env 配置 QEMU_DIR 或加入 PATH")
        return 1

    cmd = [qemu, "-cdrom", OUTPUT_ISO, "-m", str(args.mem)]
    if args.serial:
        cmd += ["-serial", "stdio"]
    info(f"启动 QEMU: {os.path.basename(qemu)}")
    return subprocess.run(cmd).returncode


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main() -> int:
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
    p_limine.set_defaults(func=cmd_limine)

    # build 子命令
    p_build = sub.add_parser("build", help="编译内核并生成可引导 ISO")
    p_build.set_defaults(func=cmd_build)

    # run 子命令
    p_run = sub.add_parser("run", help="用 QEMU 启动 ISO")
    p_run.add_argument("--mem", default="128M", help="内存大小（默认 128M）")
    p_run.add_argument("--serial", action="store_true", help="启用串口输出到终端")
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
