#!/usr/bin/env python3
"""
BORUIX SDK 辅助工具主入口。

用法:
    python sdk.py <子命令> [选项]

子命令:
    limine   下载并部署 Limine bootloader 到 sdk/boot/
    --help   查看帮助
"""

import argparse
import os
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

# Limine GitHub release 二进制下载地址
LIMINE_RELEASES = "https://github.com/Limine-Bootloader/Limine/releases/download"
DEFAULT_LIMINE_VERSION = "12.5.2"


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

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
