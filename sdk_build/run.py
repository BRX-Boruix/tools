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
    # 盘策略三选一（main.py 用 mutually exclusive group 保证至多其一）：
    #   默认 / `--nodisk`  → LiveCD：不挂盘，盘从未创建也不影响（ADR-017）
    #   `--disk`           → 挂现有盘（缺失则自动创建）
    #   `--redisk`         → 无条件重建盘再挂（清旧盘数据，用当前构建产物）
    # 盘是"持久外部存储"模拟（ADR-013/016）：重建会清除盘上数据，故仅通过
    # 显式 `--redisk` 触发，绝不隐式覆盖已有数据。
    nodisk = getattr(args, "nodisk", False)
    redisk = getattr(args, "redisk", False)
    with_disk = getattr(args, "disk", False)
    disk_mode = "redisk" if redisk else ("disk" if with_disk else ("nodisk" if nodisk else "livecd"))

    if disk_mode in ("disk", "redisk"):
        disk.ensure_disk_image_exists(disk_path, force=(disk_mode == "redisk"))

    cmd = [
        qemu,
        "-cdrom", config.OUTPUT_ISO,
    ]
    if disk_mode in ("disk", "redisk"):
        cmd += ["-hda", disk_path]
    cmd += [
        "-boot", "order=d",
        "-m", str(args.mem),
        "-netdev", "user,id=net0",
        "-device", "e1000,netdev=net0",
    ]
    if args.serial:
        cmd += ["-serial", "stdio"]
    info(f"盘策略: {disk_mode}" + (f" (挂载 {os.path.basename(disk_path)})" if disk_mode in ("disk", "redisk") else " (纯 liveCD，不挂外部盘)"))
    info(f"启动 QEMU: {os.path.basename(qemu)}")
    return subprocess.run(cmd).returncode
