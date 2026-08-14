"""limine 子命令：下载并部署 Limine bootloader。"""

import argparse
import os
import shutil
import tarfile
import tempfile
import urllib.request
import zipfile

from . import config
from .util import err, info


def _download(url: str, dest: str) -> None:
    info(f"下载 {url}")
    urllib.request.urlretrieve(url, dest)


def _extract_zip(zip_path: str, dest: str) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)


def _extract_tar(tar_path: str, dest: str) -> None:
    with tarfile.open(tar_path) as tf:
        tf.extractall(dest)


def cmd(args: argparse.Namespace) -> int:
    """下载并部署 Limine bootloader 到 sdk/boot/limine-binary/"""
    version = args.version
    binary_dir = config.LIMINE_BINARY_DIR
    boot_dir = config.BOOT_DIR

    if args.skip_existing and os.path.isdir(binary_dir):
        info(f"Limine 已存在: {binary_dir} (跳过下载)")
        return 0

    if args.force and os.path.isdir(binary_dir):
        info(f"删除旧版本: {binary_dir}")
        shutil.rmtree(binary_dir)

    os.makedirs(boot_dir, exist_ok=True)

    # 优先用 zip（Windows 友好）
    zip_url = f"{config.LIMINE_RELEASES}/v{version}/limine-binary.zip"

    with tempfile.TemporaryDirectory() as tmp:
        archive_path = os.path.join(tmp, "limine-binary.zip")
        try:
            _download(zip_url, archive_path)
        except Exception as e:
            err(f"下载失败: {e}")
            return 1

        try:
            _extract_zip(archive_path, boot_dir)
        except Exception as e:
            err(f"解压失败: {e}")
            return 1

    if not os.path.isdir(binary_dir):
        err("解压后未找到 limine-binary/ 目录，部署可能不完整")
        return 1

    info(f"Limine v{version} 已部署到 {binary_dir}")
    return 0
