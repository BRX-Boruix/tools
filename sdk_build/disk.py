"""磁盘镜像创建与 EXT2 格式化管理模块（ADR-016 / Milestone M13）。

提供自动检测、按需创建、MBR 分区写入与 EXT2 文件系统格式化生成器。
"""

import argparse
import os
import struct
import sys
import uuid

from . import config
from .util import err, info

DISK_IMG_PATH = os.path.join(config.PROJECT_ROOT, "disk.img")

# EXT2 核心常量
EXT2_SUPER_MAGIC = 0xEF53
EXT2_S_IFDIR = 0x4000
EXT2_S_IFREG = 0x8000
EXT2_FT_DIR = 2
EXT2_FT_REG_FILE = 1


def create_ext2_disk_image(path: str, size_mb: int = 64, label: str = "BORUIX_DATA") -> bool:
    """在指定路径创建一个包含 MBR 主分区和标准 EXT2 文件系统的 raw 磁盘镜像。"""
    total_bytes = size_mb * 1024 * 1024
    total_sectors = total_bytes // 512

    info(f"正在创建磁盘镜像: {path} ({size_mb}MB, {total_sectors} 扇区)...")

    # 1. 初始化空文件
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as f:
        # 分配全 0 磁盘
        f.seek(total_bytes - 1)
        f.write(b"\x00")

    with open(path, "r+b") as f:
        # 2. 写入 LBA 0 的 MBR 分区表
        # 分区 1: Active (0x80), Linux (0x83), Start LBA = 2048 (1MB offset), 扇区数 = total_sectors - 2048
        part1_start_lba = 2048
        part1_sectors = total_sectors - part1_start_lba

        f.seek(0)
        mbr = bytearray(512)
        # 引导签名
        mbr[510] = 0x55
        mbr[511] = 0xAA
        # MBR 磁盘签名 @0x1B8（4 字节 LE，非 0）——Limine `File.mbr_disk_id`
        # 的来源，boot 来源判定（ADR-029 M2.2）据此定位本位盘。取确定性的
        # 常量签名，使 disk.img 每次重建都稳定可比对。
        struct.pack_into("<I", mbr, 0x1B8, 0x424F5255)  # "BORU" as LE disk sig

        # 主分区 1 表项 (偏移 0x1BE = 446)
        p1 = 446
        mbr[p1 + 0] = 0x80  # Bootable
        mbr[p1 + 1] = 0x00  # Start Head
        mbr[p1 + 2] = 0x02  # Start Sector
        mbr[p1 + 3] = 0x00  # Start Cylinder
        mbr[p1 + 4] = 0x83  # Partition Type: Linux Native
        mbr[p1 + 5] = 0xFF  # End Head
        mbr[p1 + 6] = 0xFF  # End Sector
        mbr[p1 + 7] = 0xFF  # End Cylinder
        struct.pack_into("<I", mbr, p1 + 8, part1_start_lba)
        struct.pack_into("<I", mbr, p1 + 12, part1_sectors)

        f.write(mbr)

        # 3. 写入分区 1 内的 EXT2 文件系统（以 1024 字节块大小为基准）
        part_byte_offset = part1_start_lba * 512
        block_size = 1024
        total_blocks = (part1_sectors * 512) // block_size
        blocks_per_group = 8192
        inodes_per_group = 1024

        # 超级块 (Superblock，位于分区偏移 1024 字节处)
        f.seek(part_byte_offset + 1024)
        sb = bytearray(1024)
        struct.pack_into("<I", sb, 0, inodes_per_group)     # s_inodes_count
        struct.pack_into("<I", sb, 4, total_blocks)         # s_blocks_count
        struct.pack_into("<I", sb, 8, total_blocks // 20)   # s_r_blocks_count
        struct.pack_into("<I", sb, 12, total_blocks - 50)   # s_free_blocks_count
        struct.pack_into("<I", sb, 16, inodes_per_group - 15) # s_free_inodes_count
        struct.pack_into("<I", sb, 20, 1)                   # s_first_data_block = 1 (1024B blocks)
        struct.pack_into("<I", sb, 24, 0)                   # s_log_block_size = 0 (1024B)
        struct.pack_into("<I", sb, 28, 0)                   # s_log_frag_size
        struct.pack_into("<I", sb, 32, blocks_per_group)    # s_blocks_per_group
        struct.pack_into("<I", sb, 36, blocks_per_group)    # s_frags_per_group
        struct.pack_into("<I", sb, 40, inodes_per_group)    # s_inodes_per_group
        struct.pack_into("<H", sb, 56, EXT2_SUPER_MAGIC)    # s_magic = 0xEF53
        struct.pack_into("<H", sb, 58, 1)                   # s_state = 1 (Cleanly unmounted)
        struct.pack_into("<H", sb, 62, 0)                   # s_minor_rev_level
        struct.pack_into("<I", sb, 76, 1)                   # s_rev_level = 1 (Dynamic rev)
        struct.pack_into("<I", sb, 84, 11)                  # s_first_ino = 11
        struct.pack_into("<H", sb, 88, 128)                 # s_inode_size = 128
        # 卷名
        label_bytes = label.encode("utf-8")[:16]
        sb[120:120 + len(label_bytes)] = label_bytes
        # FS UUID @104（16 字节）——EXT2 rev1 起存在；无卷标降级命名
        # （storage-{ShortUUID}）的数据源。取**随机 v4 UUID**（真实 v4，版本/
        # 变体位按 RFC 4122 设置），与主流 mke2fs 行为一致：UUID 是内容元数据
        # 而非布局结构，随机生成不破坏镜像的可复现性与可引导性（boot 来源判定
        # 用 MBR 磁盘签名，见上），反而保证每块盘 UUID 唯一（避免多盘 storage-
        # ShortUUID 冲突）。
        fs_uuid = uuid.uuid4().bytes
        sb[104:120] = fs_uuid
        f.write(sb)

        # 块组描述符 (Block Group 0 Descriptor, 位于块 2)
        f.seek(part_byte_offset + 2 * block_size)
        bg = bytearray(1024)
        struct.pack_into("<I", bg, 0, 3)                   # bg_block_bitmap = block 3
        struct.pack_into("<I", bg, 4, 4)                   # bg_inode_bitmap = block 4
        struct.pack_into("<I", bg, 8, 5)                   # bg_inode_table = block 5
        struct.pack_into("<H", bg, 12, total_blocks - 50)  # bg_free_blocks_count
        struct.pack_into("<H", bg, 14, inodes_per_group - 15) # bg_free_inodes_count
        struct.pack_into("<H", bg, 16, 2)                  # bg_used_dirs_count
        f.write(bg)

        # 位图块 (Block Bitmap = 3, Inode Bitmap = 4)
        f.seek(part_byte_offset + 3 * block_size)
        f.write(b"\xFF\xFF\xFF\x03" + b"\x00" * (block_size - 4)) # 占用前 26 个块
        f.seek(part_byte_offset + 4 * block_size)
        f.write(b"\xFF\x07" + b"\x00" * (block_size - 2))         # 占用前 11 个 Inode

        # Inode 表 (Block 5 起始，每个 Inode 128 字节)
        # 写入根目录 Inode 2 (偏移 (2-1)*128 = 128 字节)
        inode_table_offset = part_byte_offset + 5 * block_size
        f.seek(inode_table_offset + 128)
        root_inode = bytearray(128)
        struct.pack_into("<H", root_inode, 0, EXT2_S_IFDIR | 0o755) # i_mode
        struct.pack_into("<I", root_inode, 4, 1024)                 # i_size = 1024
        struct.pack_into("<H", root_inode, 26, 3)                   # i_links_count
        struct.pack_into("<I", root_inode, 28, 2)                   # i_blocks (512B sectors)
        struct.pack_into("<I", root_inode, 40, 20)                  # i_block[0] = block 20
        f.write(root_inode)

        # 写入预置文件 Inode 11 (/hello.txt, 偏移 (11-1)*128 = 1280 字节)
        f.seek(inode_table_offset + 1280)
        hello_content = b"Welcome to BORUIX Real Ext2 Filesystem!\n"
        hello_inode = bytearray(128)
        struct.pack_into("<H", hello_inode, 0, EXT2_S_IFREG | 0o644)
        struct.pack_into("<I", hello_inode, 4, len(hello_content))
        struct.pack_into("<H", hello_inode, 26, 1)
        struct.pack_into("<I", hello_inode, 28, 2)
        struct.pack_into("<I", hello_inode, 40, 25)                 # i_block[0] = block 25
        f.write(hello_inode)

        # 写入预置文件 Inode 12 (/notes.txt, 偏移 (12-1)*128 = 1408 字节)
        f.seek(inode_table_offset + 1408)
        notes_content = b"System storage initialized with real MBR & EXT2.\n"
        notes_inode = bytearray(128)
        struct.pack_into("<H", notes_inode, 0, EXT2_S_IFREG | 0o644)
        struct.pack_into("<I", notes_inode, 4, len(notes_content))
        struct.pack_into("<H", notes_inode, 26, 1)
        struct.pack_into("<I", notes_inode, 28, 2)
        struct.pack_into("<I", notes_inode, 40, 26)                 # i_block[0] = block 26
        f.write(notes_inode)

        # 写入根目录数据块 (Block 20)
        f.seek(part_byte_offset + 20 * block_size)
        dir_data = bytearray(1024)
        cur = 0

        def append_dir_entry(data, offset, ino, name, ft, rec_len=0):
            name_bytes = name.encode("utf-8")
            nlen = len(name_bytes)
            if rec_len == 0:
                actual_len = 8 + nlen
                rec_len = (actual_len + 3) & ~3
            struct.pack_into("<I", data, offset, ino)
            struct.pack_into("<H", data, offset + 4, rec_len)
            data[offset + 6] = nlen
            data[offset + 7] = ft
            data[offset + 8:offset + 8 + nlen] = name_bytes
            return offset + rec_len

        # 1. "."
        cur = append_dir_entry(dir_data, cur, 2, ".", EXT2_FT_DIR, 12)
        # 2. ".."
        cur = append_dir_entry(dir_data, cur, 2, "..", EXT2_FT_DIR, 12)
        # 3. "hello.txt"
        cur = append_dir_entry(dir_data, cur, 11, "hello.txt", EXT2_FT_REG_FILE, 20)
        # 4. "notes.txt" (填满剩余块空间)
        append_dir_entry(dir_data, cur, 12, "notes.txt", EXT2_FT_REG_FILE, 1024 - cur)
        f.write(dir_data)

        # 写入文件数据块 (Block 25 & 26)
        f.seek(part_byte_offset + 25 * block_size)
        f.write(hello_content.ljust(block_size, b"\x00"))

        f.seek(part_byte_offset + 26 * block_size)
        f.write(notes_content.ljust(block_size, b"\x00"))

    info(f"磁盘镜像创建成功: {path} (MBR Partition 1 -> EXT2 FS OK)")
    return True


def ensure_disk_image_exists(path: str = DISK_IMG_PATH, size_mb: int = 64, force: bool = False) -> str:
    """确保磁盘镜像存在。

    `force=False`（默认）：仅缺失时自动创建，已存在则沿用（盘 = 持久外部
    存储，数据需保留——ADR-013 语义）。`force=True`（--redisk）：无条件
    重新格式化，盘内旧二进制会被清除重建为当前构建产物——用于开发期盘上
    init/shell 落后于当前内核导致行为被旧盘带偏的场景。
    """
    if force:
        info(f"强制重建磁盘镜像: {path} (清除旧盘数据)")
        create_ext2_disk_image(path, size_mb=size_mb)
    elif not os.path.isfile(path):
        info(f"未检测到物理磁盘镜像 {path}，正在自动创建...")
        create_ext2_disk_image(path, size_mb=size_mb)
    else:
        info(f"检测到已有物理磁盘镜像: {path} (沿用现有数据)")
    return path


def cmd_mkimg(args: argparse.Namespace) -> int:
    """mkimg 子命令交互式执行函数。"""
    path = getattr(args, "output", DISK_IMG_PATH)
    size_mb = getattr(args, "size", 64)
    label = getattr(args, "label", "BORUIX_DATA")
    force = getattr(args, "force", False)

    if os.path.isfile(path) and not force:
        # 提示用户确认覆盖
        print(f"\n[警告] 磁盘镜像文件 '{path}' 已经存在。")
        try:
            choice = input("是否确认覆盖重新格式化？所有已有数据将被清除！[y/N]: ").strip().lower()
        except EOFError:
            choice = "n"

        if choice not in ("y", "yes"):
            info("操作已取消，保留现有磁盘镜像。")
            return 0

    success = create_ext2_disk_image(path, size_mb=size_mb, label=label)
    return 0 if success else 1
