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
    """用 QEMU 启动 ISO"""
    if not os.path.isfile(config.OUTPUT_ISO):
        err(f"未找到 ISO: {config.OUTPUT_ISO}，请先运行 build")
        return 1

    qemu = _find_qemu()
    if not qemu:
        err(f"未找到 {config.QEMU}，请在 .env 配置 QEMU_DIR 或加入 PATH")
        return 1

    disk_path = config.PROJECT_ROOT + os.sep + "disk.img"
    from . import disk
    disk.ensure_disk_image_exists(disk_path)

    cmd = [
        qemu,
        "-cdrom", config.OUTPUT_ISO,
        "-hda", disk_path,
        "-m", str(args.mem),
        "-netdev", "user,id=net0",
        "-device", "e1000,netdev=net0",
    ]
    if args.serial:
        cmd += ["-serial", "stdio"]
    info(f"启动 QEMU: {os.path.basename(qemu)}")
    return subprocess.run(cmd).returncode
