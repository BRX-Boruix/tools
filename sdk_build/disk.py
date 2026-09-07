"""磁盘镜像创建与 EXT2 格式化管理模块（ADR-016 / Milestone M13）。

提供自动检测、按需创建、MBR 分区写入与 EXT2 文件系统格式化生成器。
本模块同时支撑两种盘：
- 数据盘（disk.img，--disk/--redisk/mkimg）：持久外部存储，卷标 BORUIX_DATA，
  挂载为 /volumes/<label>（ADR-013/016）。
- 系统盘（systemdisk.img，--systemdisk）：可引导盘，含 Limine 引导器、
  /boot/kernel 与 /programs/*.elf，QEMU 从 -hda 启动（ADR-029 安装模式）。
"""

import argparse
import os
import struct
import subprocess
import sys
import uuid

from . import config
from .util import err, info

DISK_IMG_PATH = os.path.join(config.PROJECT_ROOT, "disk.img")
SYSTEM_DISK_IMG_PATH = os.path.join(config.PROJECT_ROOT, "systemdisk.img")

# EXT2 核心常量
EXT2_SUPER_MAGIC = 0xEF53
EXT2_S_IFDIR = 0x4000
EXT2_S_IFREG = 0x8000
EXT2_FT_DIR = 2
EXT2_FT_REG_FILE = 1

# EXT2 布局常量（本模块统一按 1024B 块、128B inode 构建）
_BS = 1024          # 块大小
_INODE_SIZE = 128
_INODES_PER_GROUP = 1024
_BLOCKS_PER_GROUP = 8192
_PER_BLOCK = _BS // 4   # 每间接块指针数 = 256
# 元数据块：super=1, bgdesc=2, blockbitmap=3, inodebitmap=4,
# inode 表占 1024*128/1024=128 块（块 5..132），首个数据块 = 133。
_INODE_TABLE_BLOCKS = (_INODES_PER_GROUP * _INODE_SIZE) // _BS
_FIRST_DATA_BLOCK = 5 + _INODE_TABLE_BLOCKS

# 目录条目使用 d_type（file_type 字节），须在 superblock 声明
# EXT2_FEATURE_INCOMPAT_FILETYPE；否则严格解析器（含 Limine stage2 的 ext2
# 驱动）会把该字节误读为名字首字符，导致找不到文件（实测见 ADR-029 系统盘 boot）。
EXT2_FEATURE_INCOMPAT_FILETYPE = 0x0002

# 系统盘 MBR 磁盘签名（与数据盘一致，供 ADR-029 M2.2 boot 来源判定）。
SYSTEM_DISK_SIGNATURE = 0x424F5255  # "BORU" LE


def _pack_mbr(path, total_sectors, disk_signature=SYSTEM_DISK_SIGNATURE):
    """写入 MBR 分区表：分区 1 Active(0x80)/Linux(0x83)，起始 LBA 2048。
    返回 (part1_start_lba, part1_sectors)。"""
    part1_start_lba = 2048
    part1_sectors = total_sectors - part1_start_lba
    with open(path, "r+b") as f:
        f.seek(0)
        mbr = bytearray(512)
        mbr[510] = 0x55
        mbr[511] = 0xAA
        struct.pack_into("<I", mbr, 0x1B8, disk_signature)
        p1 = 446
        mbr[p1 + 0] = 0x80
        mbr[p1 + 1] = 0x00
        mbr[p1 + 2] = 0x02
        mbr[p1 + 3] = 0x00
        mbr[p1 + 4] = 0x83
        mbr[p1 + 5] = 0xFF
        mbr[p1 + 6] = 0xFF
        mbr[p1 + 7] = 0xFF
        struct.pack_into("<I", mbr, p1 + 8, part1_start_lba)
        struct.pack_into("<I", mbr, p1 + 12, part1_sectors)
        f.write(mbr)
    return part1_start_lba, part1_sectors


def _build_file_tree(files):
    """{绝对路径: bytes} -> 嵌套 dict（目录=dict，文件=(bytes,size)）。"""
    root = {}
    for path, data in files.items():
        parts = [p for p in path.split("/") if p]
        if not parts:
            raise ValueError("empty path: " + repr(path))
        node = root
        for part in parts[:-1]:
            child = node.get(part)
            if child is None:
                child = {}
                node[part] = child
            elif not isinstance(child, dict):
                raise ValueError("path collision at " + repr(part))
            node = child
        name = parts[-1]
        if not isinstance(data, (bytes, bytearray)):
            raise ValueError("file data must be bytes")
        node[name] = (bytes(data), len(data))
    return root


class _BlockAllocator:
    """顺序块分配器：alloc() 返回递增块号；pending={块:bytearray}。

    used 记录 alloc() 已分发（含目录块/数据块/间接表块）的全部块号——即使某块
    最终内容全 0 未经 pending 触碰，也必须在块位图置位，否则文件系统与位图
    不一致会让后续写入方把已占用块当空闲块分配出去、覆写既有数据。
    """
    def __init__(self):
        self.next = _FIRST_DATA_BLOCK
        self.pending = {}
        self.used = set()
    def alloc(self):
        b = self.next
        self.next += 1
        self.used.add(b)
        return b
    def buf(self, block):
        if block not in self.pending:
            self.pending[block] = bytearray(_BS)
        return self.pending[block]


def _alloc_file_blocks(alloc, size):
    """为 size 字节文件分配数据块与间接表块，返回 (i_block[15], sectors)。
    支持 12 直接 + 单/双/三间接；间接表内容写入 alloc.pending。"""
    n = (size + _BS - 1) // _BS
    if n <= 0:
        return [0] * 15, 0
    def sect(k):
        return k * _BS // 512
    i_block = [0] * 15
    data_blocks = [alloc.alloc() for _ in range(n)]
    total_sectors = sect(len(data_blocks))
    for i in range(min(12, n)):
        i_block[i] = data_blocks[i]
    idx = 12
    if n <= 12:
        return i_block, total_sectors
    def make_single(ptrs):
        tbl = alloc.alloc()
        t = alloc.buf(tbl)
        for j, p in enumerate(ptrs):
            struct.pack_into("<I", t, j * 4, p)
        return tbl, len(ptrs) + 1
    si_ptrs = data_blocks[12:12 + _PER_BLOCK]
    si_tbl, si_used = make_single(si_ptrs)
    i_block[12] = si_tbl
    total_sectors += sect(si_used)
    idx += len(si_ptrs)
    if n <= 12 + _PER_BLOCK:
        return i_block, total_sectors
    l1_ptrs = []
    while idx < n:
        take = min(n - idx, _PER_BLOCK)
        sub = data_blocks[idx:idx + take]
        idx += take
        si2, _ = make_single(sub)
        l1_ptrs.append(si2)
        total_sectors += sect(take + 1)
    dbl = alloc.alloc()
    i_block[13] = dbl
    t = alloc.buf(dbl)
    for j, p in enumerate(l1_ptrs):
        struct.pack_into("<I", t, j * 4, p)
    total_sectors += sect(1)
    if n <= 12 + _PER_BLOCK + _PER_BLOCK * _PER_BLOCK:
        return i_block, total_sectors
    l2_ptrs = []
    while idx < n:
        l1_list = []
        for _ in range(_PER_BLOCK):
            if idx >= n:
                break
            take = min(n - idx, _PER_BLOCK)
            sub = data_blocks[idx:idx + take]
            idx += take
            si3, _ = make_single(sub)
            l1_list.append(si3)
            total_sectors += sect(take + 1)
        l1t = alloc.alloc()
        t = alloc.buf(l1t)
        for j, p in enumerate(l1_list):
            struct.pack_into("<I", t, j * 4, p)
        l2_ptrs.append(l1t)
        total_sectors += sect(1)
    tri = alloc.alloc()
    i_block[14] = tri
    t = alloc.buf(tri)
    for j, p in enumerate(l2_ptrs):
        struct.pack_into("<I", t, j * 4, p)
    total_sectors += sect(1)
    return i_block, total_sectors


def _write_dir_block(block, entries):
    """把目录条目编码进一个 1024B 块。条目：[(name, ino, ft)]。
    调用方须把 "." 与 ".." 作为普通条目传入（根目录指向自身）。"""
    cur = 0
    entries = list(entries)
    for i, (name, ino, ft) in enumerate(entries):
        nb = name.encode("utf-8")
        nlen = len(nb)
        actual = 8 + nlen
        rec = (actual + 3) & ~3
        if i == len(entries) - 1:
            rec = _BS - cur
        struct.pack_into("<I", block, cur, ino)
        struct.pack_into("<H", block, cur + 4, rec)
        block[cur + 6] = nlen
        block[cur + 7] = ft
        block[cur + 8:cur + 8 + nlen] = nb
        cur += rec
    return cur


def _write_file_data(alloc, i_block, data):
    """把文件数据写入其数据块（经直接/单/双/三间接链定位物理块）。"""
    per = _PER_BLOCK
    def map_logical(i_block, logical):
        if logical < 12:
            return i_block[logical]
        if logical < 12 + per:
            l1 = i_block[12]
            t = alloc.pending[l1]
            return struct.unpack_from("<I", t, (logical - 12) * 4)[0]
        if logical < 12 + per + per * per:
            rem = logical - 12 - per
            l1_idx = rem // per
            l1_off = rem % per
            l1 = struct.unpack_from("<I", alloc.pending[i_block[13]], l1_idx * 4)[0]
            t = alloc.pending[l1]
            return struct.unpack_from("<I", t, l1_off * 4)[0]
        rem = logical - 12 - per - per * per
        t2_idx = rem // (per * per)
        rem2 = rem % (per * per)
        l1_idx = rem2 // per
        l1_off = rem2 % per
        t2 = struct.unpack_from("<I", alloc.pending[i_block[14]], t2_idx * 4)[0]
        l1 = struct.unpack_from("<I", alloc.pending[t2], l1_idx * 4)[0]
        t = alloc.pending[l1]
        return struct.unpack_from("<I", t, l1_off * 4)[0]
    n = (len(data) + _BS - 1) // _BS
    for l in range(n):
        phys = map_logical(i_block, l)
        buf = alloc.buf(phys)
        chunk = data[l * _BS:(l + 1) * _BS]
        buf[:len(chunk)] = chunk
    return n


def _assign_inodes(tree):
    """为文件树分配 inode：root=2，其余自 3 起 BFS 递增。
    返回 (带 inode 的树, inode_count)。节点变为 (ino, payload)。"""
    counter = [2]
    def walk(node):
        if isinstance(node, dict):
            ino = counter[0]
            counter[0] += 1
            newdir = {}
            for name, child in node.items():
                newdir[name] = walk(child)
            return (ino, ("dir", newdir))
        else:
            data, size = node
            ino = counter[0]
            counter[0] += 1
            return (ino, ("file", data, size))
    assigned = walk(tree)
    return assigned, counter[0] - 1


def _write_ext2_filesystem(path, part_start_lba, part_sectors, files, label):
    """在已建盘的分区 1 内写 EXT2 文件系统，内容 = files 字典。
    files: {绝对路径: bytes}。构建文件树 -> 分配 inode/数据块（含间接表）
    -> 写 superblock/bgdesc/位图/inode 表/目录块/数据块。返回 True。"""
    part_byte_offset = part_start_lba * 512
    total_blocks = (part_sectors * 512) // _BS
    tree = _build_file_tree(files)
    assigned, inode_count = _assign_inodes(tree)
    alloc = _BlockAllocator()
    inode_meta = {}
    dir_entries = {}
    dir_parent = {}
    file_data = {}

    def walk(node, parent_ino):
        ino, payload = node
        kind = payload[0]
        dir_parent[ino] = parent_ino
        if kind == "dir":
            val = payload[1]
            dblock = alloc.alloc()
            children = []
            for name, child in val.items():
                child_ino, child_payload = child
                ckind = child_payload[0]
                ft = EXT2_FT_DIR if ckind == "dir" else EXT2_FT_REG_FILE
                children.append((name, child_ino, ft))
            dir_entries[ino] = children
            inode_meta[ino] = (EXT2_S_IFDIR | 0o755, _BS, [dblock] + [0] * 14, 2)
            for name, child in val.items():
                walk(child, ino)
        else:
            _, data, size = payload
            i_block, sectors = _alloc_file_blocks(alloc, size)
            file_data[ino] = (i_block, data)
            inode_meta[ino] = (EXT2_S_IFREG | 0o644, size, i_block, sectors)
    walk(assigned, 2)

    used_blocks = set(range(0, _FIRST_DATA_BLOCK))
    # 位图必须覆盖 allocator 分发的每一块（含目录/数据/间接块），而非仅 pending
    # 里有过非空内容的块——漏标会使后续写入方复用已占用块、覆写既有数据。
    used_blocks.update(alloc.used)
    max_used = max(used_blocks) if used_blocks else 0
    if max_used >= total_blocks:
        raise ValueError("EXT2 块分配超出盘容量: up to " + str(max_used) + ", total " + str(total_blocks))
    block_bitmap = bytearray(_BS)
    for blk in used_blocks:
        block_bitmap[blk >> 3] |= (1 << (blk & 7))
    inode_bitmap = bytearray(_BS)
    for ino in range(1, inode_count + 1):
        inode_bitmap[ino >> 3] |= (1 << (ino & 7))
    free_blocks = total_blocks - len(used_blocks)
    free_inodes = _INODES_PER_GROUP - inode_count

    with open(path, "r+b") as f:
        f.seek(part_byte_offset + _BS)
        sb = bytearray(1024)
        struct.pack_into("<I", sb, 0, _INODES_PER_GROUP)
        struct.pack_into("<I", sb, 4, total_blocks)
        struct.pack_into("<I", sb, 8, total_blocks // 20)
        struct.pack_into("<I", sb, 12, free_blocks)
        struct.pack_into("<I", sb, 16, free_inodes)
        struct.pack_into("<I", sb, 20, 1)
        struct.pack_into("<I", sb, 24, 0)
        struct.pack_into("<I", sb, 28, 0)
        struct.pack_into("<I", sb, 32, _BLOCKS_PER_GROUP)
        struct.pack_into("<I", sb, 36, _BLOCKS_PER_GROUP)
        struct.pack_into("<I", sb, 40, _INODES_PER_GROUP)
        struct.pack_into("<H", sb, 56, EXT2_SUPER_MAGIC)
        struct.pack_into("<H", sb, 58, 1)
        struct.pack_into("<H", sb, 62, 0)
        struct.pack_into("<I", sb, 76, 1)
        struct.pack_into("<I", sb, 84, 11)
        struct.pack_into("<H", sb, 88, _INODE_SIZE)
        struct.pack_into("<I", sb, 96, EXT2_FEATURE_INCOMPAT_FILETYPE)  # 声明 d_type 的 FILETYPE 不兼容特性
        label_bytes = label.encode("utf-8")[:16]
        sb[120:120 + len(label_bytes)] = label_bytes
        sb[104:120] = uuid.uuid4().bytes
        f.write(sb)

        f.seek(part_byte_offset + 2 * _BS)
        bg = bytearray(1024)
        struct.pack_into("<I", bg, 0, 3)
        struct.pack_into("<I", bg, 4, 4)
        struct.pack_into("<I", bg, 8, 5)
        struct.pack_into("<H", bg, 12, free_blocks)
        struct.pack_into("<H", bg, 14, free_inodes)
        struct.pack_into("<H", bg, 16, sum(1 for mode, _, _, _ in inode_meta.values() if mode & EXT2_S_IFDIR))
        f.write(bg)

        f.seek(part_byte_offset + 3 * _BS)
        f.write(block_bitmap)
        f.seek(part_byte_offset + 4 * _BS)
        f.write(inode_bitmap)

        itab = part_byte_offset + 5 * _BS
        for ino, (mode, size, ib, sectors) in inode_meta.items():
            inode = bytearray(_INODE_SIZE)
            struct.pack_into("<H", inode, 0, mode)
            struct.pack_into("<I", inode, 4, size)
            struct.pack_into("<I", inode, 28, sectors)
            # i_links_count @26（目录>=2，含 . 与 ..；普通文件=1）；osd1@36 保持 0。
            struct.pack_into("<H", inode, 26, 2 if mode & EXT2_S_IFDIR else 1)
            for j, blk in enumerate(ib):
                if blk:
                    struct.pack_into("<I", inode, 40 + j * 4, blk)
            f.seek(itab + (ino - 1) * _INODE_SIZE)
            f.write(inode)

        # 目录块内容：加 . 与 ..
        for ino, (mode, size, ib, sectors) in inode_meta.items():
            if mode & EXT2_S_IFDIR:
                dblock = ib[0]
                d = alloc.pending.get(dblock, bytearray(_BS))
                entries = [(".", ino, EXT2_FT_DIR), ("..", dir_parent[ino], EXT2_FT_DIR)]
                entries.extend(dir_entries[ino])
                _write_dir_block(d, entries)
                alloc.pending[dblock] = d
        # 文件数据
        for ino, (i_block, data) in file_data.items():
            _write_file_data(alloc, i_block, data)
        # 统一写 alloc.pending
        for blk, buf in alloc.pending.items():
            f.seek(part_byte_offset + blk * _BS)
            f.write(bytes(buf))
    return True


def create_ext2_disk_image(path, size_mb=64, label="BORUIX_DATA"):
    """创建数据盘：MBR 分区 1 + EXT2，预置 hello.txt / notes.txt。返回 True。"""
    total_bytes = size_mb * 1024 * 1024
    total_sectors = total_bytes // 512
    info("正在创建磁盘镜像: " + path + " (" + str(size_mb) + "MB, " + str(total_sectors) + " 扇区)...")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as f:
        f.seek(total_bytes - 1)
        f.write(b"\x00")
    start, sectors = _pack_mbr(path, total_sectors)
    hello = b"Welcome to BORUIX Real Ext2 Filesystem!\n"
    notes = b"System storage initialized with real MBR & EXT2.\n"
    _write_ext2_filesystem(path, start, sectors, {"/hello.txt": hello, "/notes.txt": notes}, label)
    info("磁盘镜像创建成功: " + path + " (MBR Partition 1 -> EXT2 FS OK)")
    return True


def create_system_disk_image(path, kernel_elf, programs, limine_conf, limine_bios_sys, size_mb=64):
    """创建可引导系统盘（ADR-029 安装模式）。
    - /boot/kernel                     = kernel_elf
    - /boot/limine/limine.conf         = limine_conf
    - /boot/limine/limine-bios.sys     = limine_bios_sys（Limine stage2）
    - /programs/<name>.elf             = programs 字典 {name: bytes}
    （Limine 引导器安装另由 install_fork_limine_bios 完成）
    返回 True。"""
    total_bytes = size_mb * 1024 * 1024
    total_sectors = total_bytes // 512
    info("正在创建系统盘: " + path + " (" + str(size_mb) + "MB, " + str(total_sectors) + " 扇区)...")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as f:
        f.seek(total_bytes - 1)
        f.write(b"\x00")
    start, sectors = _pack_mbr(path, total_sectors, SYSTEM_DISK_SIGNATURE)
    files = {
        "/boot/kernel": kernel_elf,
        "/boot/limine/limine.conf": limine_conf,
        "/boot/limine/limine-bios.sys": limine_bios_sys,
    }
    for name, data in programs.items():
        files["/programs/" + name + ".elf"] = data
    _write_ext2_filesystem(path, start, sectors, files, "BORUIX_SYS")
    info("系统盘 EXT2 已写入: " + path)
    return True


def install_fork_limine_bios(disk_path, fork_hdd_bin):
    """把 brxLimine fork 的 Limine BIOS stage1+2（含 EXT2 驱动）装进 MBR 盘。

    等效于 `limine bios-install` 对 MBR 盘的写入，但 stage1 引导器数据来自
    fork 的 `limine-bios-hdd.bin`（隐藏区 stage2 内含 ext2 文件系统驱动，能
    读取 ext2 分区上的 `limine-bios.sys`），而非 stock 的 stage1 loader——
    stock 引导器不识别 EXT2，会在 "Stage 3 file not found" 处停住。

    写入模型（与 bios-install 一致）：
    - [0:512]              -> MBR bootsect（stage1）
    - [512:]（stage2_loc）  -> 隐藏区（分区前间隙），bootsect @0x1a4 硬编码其位置
    返回 0 成功，非 0 失败（不改动已传入的分区表/时间戳字段）。
    """
    if not os.path.isfile(disk_path):
        err("系统盘不存在: " + disk_path)
        return 1
    if len(fork_hdd_bin) < 512 or (len(fork_hdd_bin) - 512) > (2048 * 512 - 512):
        err("fork limine-bios-hdd.bin 尺寸异常或超出分区前间隙: %d 字节" % len(fork_hdd_bin))
        return 1
    info("安装 brxLimine fork BIOS 引导到 " + os.path.basename(disk_path) + " ...")
    with open(disk_path, "rb") as f:
        img = bytearray(f.read())
    # 备份并恢复：MBR 分区表（440..510）与 BIOS 时间戳（218..224）。
    orig_mbr = bytes(img[440:440 + 70])
    ts = bytes(img[218:218 + 6])
    img[0:512] = fork_hdd_bin[0:512]
    stage2_loc = 0x200  # 分区自 LBA 2048 起（前 1MB 为 MBR/隐藏区间隙），stage2 放此处
    img[stage2_loc:stage2_loc + len(fork_hdd_bin) - 512] = fork_hdd_bin[512:]
    img[0x1A4:0x1AC] = struct.pack("<Q", stage2_loc)
    img[218:224] = ts
    img[440:510] = orig_mbr
    with open(disk_path, "wb") as f:
        f.write(bytes(img))
    info("brxLimine fork BIOS 引导安装完成（MBR + 隐藏区 stage2 含 EXT2）。")
    return 0

def install_fork_limine_iso(iso_path, fork_cd_bin):
    """把 brxLimine fork 的 Limine BIOS stage1+2 写进 isohybrid ISO（等价于 `limine bios-install`）。

    xorriso 用 --protective-msdos-label 产生的 ISO 已具有 MBR 保护分区（
    El Torito 启动影像为 boot/limine/limine-bios-cd.bin）。此函数把 stage1
    启动区（[0:512]）写到 MBR、stage2（[512:]）写到 0x200，并在 0x1a4
    硬编码 stage2 位置，与官方 bios-install 对 MBR 的写入模型一致。
    不改动已传入的保护分区表/时间戳字段。返回 0 成功，非 0 失败。
    """
    if not os.path.isfile(iso_path):
        err("ISO 不存在: " + iso_path)
        return 1
    if len(fork_cd_bin) < 512:
        err("fork limine-bios-cd.bin 尺寸异常: %d 字节" % len(fork_cd_bin))
        return 1
    info("写入 brxLimine fork BIOS 引导到 ISO (isohybrid MBR + stage2@0x200) ...")
    with open(iso_path, "rb") as f:
        img = bytearray(f.read())
    if len(img) < 0x200 + (len(fork_cd_bin) - 512):
        err("ISO 太小，无法写入 stage2")
        return 1
    # 保备并恢复：保护分区表(440..510) 与 BIOS 时间戳(218..224)。
    orig_mbr = bytes(img[440:440 + 70])
    ts = bytes(img[218:218 + 6])
    img[0:512] = fork_cd_bin[0:512]
    stage2_loc = 0x200
    img[stage2_loc:stage2_loc + len(fork_cd_bin) - 512] = fork_cd_bin[512:]
    img[0x1A4:0x1AC] = struct.pack("<Q", stage2_loc)
    img[218:224] = ts
    img[440:510] = orig_mbr
    with open(iso_path, "wb") as f:
        f.write(bytes(img))
    info("brxLimine fork BIOS 引导安装到 ISO 完成。")
    return 0


def ensure_disk_image_exists(path=DISK_IMG_PATH, size_mb=64, force=False):
    """确保数据盘存在。force=False 仅缺失时创建；force=True 无条件重建。"""
    if force:
        info("强制重建磁盘镜像: " + path + " (清除旧盘数据)")
        create_ext2_disk_image(path, size_mb=size_mb)
    elif not os.path.isfile(path):
        info("未检测到物理磁盘镜像 " + path + "，正在自动创建...")
        create_ext2_disk_image(path, size_mb=size_mb)
    else:
        info("检测到已有物理磁盘镜像: " + path + " (沿用现有数据)")
    return path


def cmd_mkimg(args):
    """mkimg 子命令：创建/重格式化数据盘。"""
    path = getattr(args, "output", DISK_IMG_PATH)
    size_mb = getattr(args, "size", 64)
    label = getattr(args, "label", "BORUIX_DATA")
    force = getattr(args, "force", False)
    if os.path.isfile(path) and not force:
        print("\n[警告] 磁盘镜像文件 " + repr(path) + " 已经存在。")
        try:
            choice = input("是否确认覆盖重新格式化？所有已有数据将被清除！[y/N]: ").strip().lower()
        except EOFError:
            choice = "n"
        if choice not in ("y", "yes"):
            info("操作已取消，保留现有磁盘镜像。")
            return 0
    success = create_ext2_disk_image(path, size_mb=size_mb, label=label)
    return 0 if success else 1

