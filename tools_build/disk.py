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
# 每组 inode 表占 1024*128/1024=128 块。
_INODE_TABLE_BLOCKS = (_INODES_PER_GROUP * _INODE_SIZE) // _BS
# 标准多块组 EXT2（1K 块 → s_first_data_block=1，块 0 保留；superblock@1、
# GDT@2 起连续；随后各块组真实铺 block_bitmap/inode_bitmap/inode 表，数据区在
# 所有元数据之后由 _BlockAllocator 跨组全局分配）。每个已用块都在其所属块组
# （blk//_BLOCKS_PER_GROUP）的位图置位，kernel 写路径与数据盘挂载自洽。
# 所有 inode 只放 group 0（ino ≤ _INODES_PER_GROUP），以兼容 brxLimine fork
# stage2 的 ext2 驱动——它用 (ino-1)/blocks_per_group 定组、并从 group0 连续
# inode 表线性读 inode，仅当全部 inode 落在首组表内才正确。
_GROUP_META_BLOCKS = 2 + _INODE_TABLE_BLOCKS  # 每组=block_bitmap(1)+inode_bitmap(1)+inode表

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
    def __init__(self, start=None):
        self.next = start if start is not None else 133
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
    # 块组数：EXT2 规范 s_blocks_per_group 由块大小决定（1K 块 → 8192）。
    num_groups = (total_blocks + _BLOCKS_PER_GROUP - 1) // _BLOCKS_PER_GROUP
    gdt_blocks = (num_groups * 32 + _BS - 1) // _BS  # 组描述符表占块数（每项 32B）
    # 磁盘布局（块号，fdb=1 → 块 0 保留）：
    #   1                 superblock
    #   2 .. 1+gdt_blocks GDT（num_groups 项，连续）
    #   之后每块组 g：block_bitmap_g, inode_bitmap_g, inode_table_g(_GROUP_META_BLOCKS)
    #   数据区从 group_meta_end 起，由 _BlockAllocator 跨组全局分配。
    gdt_start = 2
    group_meta = []  # (block_bitmap_blk, inode_bitmap_blk, inode_table_blk)
    cur = gdt_start + gdt_blocks  # group0 元数据紧随 GDT 之后（superblock@1、GDT@gdt_start）
    for _g in range(num_groups):
        group_meta.append((cur, cur + 1, cur + 2))
        cur += _GROUP_META_BLOCKS
    data_start = cur
    # 元数据块号集合（含块 0 保留区），用于组 0 位图置位（全部 < blocks_per_group）。
    meta_blocks = set(range(0, data_start))

    tree = _build_file_tree(files)
    assigned, inode_count = _assign_inodes(tree)
    alloc = _BlockAllocator(start=data_start)
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
            # 文件权限：全部 0755（可执行）。此前统一 0644，使 /programs 池里的程序 ELF
            # **没有 x 位**——liveCD 启动时 /programs 来自内核内嵌 payload（不走 DAC），
            # 问题被掩盖；系统盘（ADR-029 安装模式）启动时 /programs 即本盘 EXT2 池目录，
            # exec 走真实策略求值，A2-7 起 init 在拉起 login 前已把 caps 收窄为
            # SYSTEM|KILL（不再持 CAP_OWNER 绕过面），对无 x 位文件的 exec 被如实拒绝
            # （EACCES），用户可见症状为「login.elf/shell.elf 无法启动，进不去系统」。
            # 本函数的两个使用方（系统盘 /boot/* + /programs/*、数据盘文档）中，引导
            # 文件与程序本就需要可读可执行，统一 0755 无害；数据盘文档变 0755 亦不
            # 构成安全问题（数据盘无认证边界，见 ADR-041 §1.2.5 R-1 的同源论证）。
            inode_meta[ino] = (EXT2_S_IFREG | 0o755, size, i_block, sectors)
    walk(assigned, 2)

    # 位图必须覆盖 allocator 分发的每一块（含目录/数据/间接块）+ 全部元数据块。
    used_blocks = set(meta_blocks)
    used_blocks.update(alloc.used)
    max_used = max(used_blocks) if used_blocks else 0
    if max_used >= total_blocks:
        raise ValueError("EXT2 块分配超出盘容量: up to " + str(max_used) + ", total " + str(total_blocks))

    # 每块组的块位图：把每个已用块置位到其所属块组（blk//bpg）的位图。
    group_bbitmaps = [bytearray(_BS) for _ in range(num_groups)]
    for blk in used_blocks:
        g = blk // _BLOCKS_PER_GROUP
        if g >= num_groups:
            continue  # 越界块（不应发生，见上面 max_used 检查）
        bit = blk % _BLOCKS_PER_GROUP
        group_bbitmaps[g][bit >> 3] |= (1 << (bit & 7))
    # 每块组的 inode 位图：所有 inode 放 group 0（兼容 fork 驱动 group 换算）。
    group_ibitmaps = [bytearray(_BS) for _ in range(num_groups)]
    for ino in range(1, inode_count + 1):
        if ino > _INODES_PER_GROUP:
            raise ValueError("inode 超出 group0 容量（fork 驱动约束）: " + str(inode_count))
        group_ibitmaps[0][ino >> 3] |= (1 << (ino & 7))

    free_blocks_total = total_blocks - len(used_blocks)
    total_inodes = _INODES_PER_GROUP * num_groups
    free_inodes_total = total_inodes - inode_count
    # 每块组的空闲块/空闲 inode 计数（组 g 覆盖 [g*bpg, (g+1)*bpg) ∩ [0,total_blocks)）。
    grp_free_blocks = []
    for g in range(num_groups):
        lo = g * _BLOCKS_PER_GROUP
        hi = min((g + 1) * _BLOCKS_PER_GROUP, total_blocks)
        span = max(0, hi - lo)
        used_in_group = sum(1 for b in used_blocks if lo <= b < hi)
        grp_free_blocks.append(span - used_in_group)
    grp_free_inodes = [_INODES_PER_GROUP - (inode_count if g == 0 else 0) for g in range(num_groups)]

    with open(path, "r+b") as f:
        f.seek(part_byte_offset + _BS)
        sb = bytearray(1024)
        struct.pack_into("<I", sb, 0, total_inodes)
        struct.pack_into("<I", sb, 4, total_blocks)
        struct.pack_into("<I", sb, 8, total_blocks // 20)
        struct.pack_into("<I", sb, 12, free_blocks_total)
        struct.pack_into("<I", sb, 16, free_inodes_total)
        struct.pack_into("<I", sb, 20, 1)                       # s_first_data_block=1（1K 块规范）
        struct.pack_into("<I", sb, 24, 0)                       # s_log_block_size=0 → 1024
        struct.pack_into("<I", sb, 28, 0)                       # s_log_frag_size=0
        struct.pack_into("<I", sb, 32, _BLOCKS_PER_GROUP)       # s_blocks_per_group
        struct.pack_into("<I", sb, 36, _BLOCKS_PER_GROUP)       # s_frags_per_group
        struct.pack_into("<I", sb, 40, _INODES_PER_GROUP)       # s_inodes_per_group
        struct.pack_into("<H", sb, 56, EXT2_SUPER_MAGIC)
        struct.pack_into("<H", sb, 58, 1)                       # s_state=clean
        struct.pack_into("<H", sb, 62, 0)                       # s_errors
        struct.pack_into("<I", sb, 76, 1)                       # s_rev_level=1 (dynamic)
        struct.pack_into("<I", sb, 84, 11)                      # s_first_ino
        struct.pack_into("<H", sb, 88, _INODE_SIZE)
        struct.pack_into("<I", sb, 96, EXT2_FEATURE_INCOMPAT_FILETYPE)  # 声明 d_type 的 FILETYPE 不兼容特性
        label_bytes = label.encode("utf-8")[:16]
        sb[120:120 + len(label_bytes)] = label_bytes
        sb[104:120] = uuid.uuid4().bytes
        f.write(sb)

        # GDT：从块 gdt_start 起，num_groups 项连续，每项 32B。
        gdt = bytearray(gdt_blocks * _BS)
        for g in range(num_groups):
            bb, ib, it = group_meta[g]
            off = g * 32
            struct.pack_into("<I", gdt, off + 0, bb)
            struct.pack_into("<I", gdt, off + 4, ib)
            struct.pack_into("<I", gdt, off + 8, it)
            struct.pack_into("<H", gdt, off + 12, grp_free_blocks[g])
            struct.pack_into("<H", gdt, off + 14, grp_free_inodes[g])
            dircnt = sum(1 for m, _, _, _ in inode_meta.values() if m & EXT2_S_IFDIR) if g == 0 else 0
            struct.pack_into("<H", gdt, off + 16, dircnt)
        f.seek(part_byte_offset + gdt_start * _BS)
        f.write(gdt)

        # 每块组的 block/inode 位图与 inode 表。
        for g in range(num_groups):
            bb, ib, it = group_meta[g]
            f.seek(part_byte_offset + bb * _BS)
            f.write(group_bbitmaps[g])
            f.seek(part_byte_offset + ib * _BS)
            f.write(group_ibitmaps[g])
            if g != 0:
                continue  # inode 只写 group 0（其它组 inode 表保持全 0）
            itab = part_byte_offset + it * _BS
            for ino, (mode, size, iblocks, sectors) in inode_meta.items():
                inode = bytearray(_INODE_SIZE)
                struct.pack_into("<H", inode, 0, mode)
                struct.pack_into("<I", inode, 4, size)
                struct.pack_into("<I", inode, 28, sectors)
                # i_links_count @26（目录>=2，含 . 与 ..；普通文件=1）；osd1@36 保持 0。
                struct.pack_into("<H", inode, 26, 2 if mode & EXT2_S_IFDIR else 1)
                for j, blk in enumerate(iblocks):
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
        # 统一写 alloc.pending（目录块 + 文件数据 + 间接表，均为已分配的数据区块）
        for blk, buf in alloc.pending.items():
            f.seek(part_byte_offset + blk * _BS)
            f.write(bytes(buf))
    return True


"""
数据盘内容来源：`tools/diskfiles/`。

**为何由构建脚本自带内容**：磁盘镜像的内容原本硬编码为两个内联字符串
（hello.txt / notes.txt），要改内容就得改 Python 源码。改为扫描本目录后，
内容与代码分离——放文件进去即可，无需动构建逻辑。

**只读语义**：本目录只作为**输入**被读取，构建过程绝不写入它。
产出物只有 `disk.img`。这保证重复构建的结果只取决于 diskfiles 的内容，
不受上一次构建影响。
"""

import os

from . import config
from .util import err, info

# 镜像内容根目录：与构建脚本同级（tools/diskfiles）。
DISKFILES_DIR = os.path.join(config.TOOLS_DIR, "diskfiles")

# 数据盘容量下限（MB）。小于此值连 EXT2 元数据都紧张，且没有余量做后续写入。
DISK_MIN_SIZE_MB = 16

# 容量余量：EXT2 元数据、间接块、以及「盘不该被塞满」的预留。
# 元数据开销随盘增大而增大（块组数 x 每组元数据），故按比例留白而非固定值。
DISK_META_OVERHEAD_RATIO = 0.25
# 绝对余量下限（MB）：小盘时比例留白不足以容纳块组元数据。
DISK_META_OVERHEAD_MIN_MB = 4


def scan_diskfiles(src=DISKFILES_DIR):
    """递归扫描 `src`，返回 `{EXT2 绝对路径: bytes}`（保持目录结构）。

    路径分隔统一为 `/`（`_build_file_tree` 依赖该约定）。相对路径
    `a/b/c.txt` 映射为 `/a/b/c.txt`。

    目录不存在或为空时**如实报错**，不静默产出一张空盘——
    一张「成功但没内容」的盘会让调用方以为内容已写入。
    """
    if not os.path.isdir(src):
        err("未找到数据盘内容目录: " + src)
        err("请创建该目录并放入要写入 disk.img 的文件。")
        return None

    files = {}
    for dirpath, dirnames, filenames in os.walk(src):
        # 排序使构建结果确定：同样的输入必须产出同样的盘（可重复构建）。
        dirnames.sort()
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, src).replace(os.sep, "/")
            try:
                with open(full, "rb") as f:
                    files["/" + rel] = f.read()
            except OSError as exc:
                err("读取 " + full + " 失败: " + str(exc))
                return None

    if not files:
        err("数据盘内容目录为空: " + src)
        err("空盘会被误认为「内容已写入」，故此处拒绝构建。")
        return None
    return files


def compute_disk_size_mb(files):
    """按内容大小推算镜像容量（MB，整数，向上取整）。

    **为何要算而不是给个固定值**：固定容量在内容超出时会抛
    「EXT2 块分配超出盘容量」。与其让用户去猜该调多大，不如按实际内容推算。

    估算口径（偏保守，宁可多留不给不够）：
      1. 文件数据块：每文件按 1KB 块向上取整；
      2. 间接块：数据块数每满 256 块多占 1 块（单/双/三间接的指针表）；
      3. inode 表 + 目录块：按文件数 x 每文件 1 块估；
      4. 再乘 1.25 并加 4MB 下限余量。
    这些是**上界估计**：多留的余量是刻意的，因为 EXT2 元数据量随盘大小
    自身增长，精确解需要迭代求解（盘越大、元数据越多、又需要更大）。
    """
    block = 1024
    per_block_ptrs = block // 4

    data_blocks = 0
    indirect_blocks = 0
    for data in files.values():
        n = (len(data) + block - 1) // block
        data_blocks += n
        # 间接块数（仅估算用）：每 256 个数据块需要 1 个指针块。
        indirect_blocks += (n + per_block_ptrs - 1) // per_block_ptrs

    # 每个文件至少 1 个 inode；每个目录至少 1 个数据块。
    n_files = len(files)
    dirs = set()
    for p in files:
        parts = [x for x in p.split("/") if x]
        for i in range(1, len(parts)):
            dirs.add("/".join(parts[:i]))
    inode_and_dir_blocks = n_files + len(dirs) + 2

    need_bytes = (data_blocks + indirect_blocks + inode_and_dir_blocks) * block
    need_mb = need_bytes / (1024 * 1024)

    # 元数据开销 + 余量。
    budget = need_mb * (1 + DISK_META_OVERHEAD_RATIO) + DISK_META_OVERHEAD_MIN_MB
    size_mb = int(budget + 0.999)  # 向上取整
    return max(size_mb, DISK_MIN_SIZE_MB)


def create_ext2_disk_image(path, size_mb=None, label="BORUIX_DATA", src=None):
    """创建数据盘：MBR 分区 1 + EXT2，内容取自 `tools/diskfiles/`。返回 True。

    - `size_mb=None`（默认）：按内容自动推算容量；显式传入则用作覆盖值。
    - `src`：内容目录，默认 `tools/diskfiles`（测试可注入临时目录）。

    内容目录**只读**：本函数只读取它，产出物只有 `path`。
    """
    if src is None:
        src = DISKFILES_DIR
    files = scan_diskfiles(src)
    if files is None:
        return False

    if size_mb is None:
        size_mb = compute_disk_size_mb(files)
        info(
            "数据盘容量按内容推算: "
            + str(size_mb)
            + "MB ("
            + str(len(files))
            + " 个文件)"
        )
    else:
        # 显式覆盖：若内容装不下，如实警告，而不是等往下写时抛异常。
        need = compute_disk_size_mb(files)
        if size_mb < need:
            err(
                "指定容量 "
                + str(size_mb)
                + "MB 小于内容所需约 "
                + str(need)
                + "MB，构建可能失败。"
            )

    total_bytes = size_mb * 1024 * 1024
    total_sectors = total_bytes // 512
    info("正在创建磁盘镜像: " + path + " (" + str(size_mb) + "MB, " + str(total_sectors) + " 扇区)...")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as f:
        f.seek(total_bytes - 1)
        f.write(b"\x00")
    start, sectors = _pack_mbr(path, total_sectors)
    _write_ext2_filesystem(path, start, sectors, files, label)
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


def ensure_disk_image_exists(path=DISK_IMG_PATH, size_mb=None, force=False):
    """确保数据盘存在。force=False 仅缺失时创建；force=True 无条件重建。

    `size_mb=None`（默认）表示按 `tools/diskfiles/` 的内容自动推算容量；
    这样往 diskfiles 里加文件后重建的盘会自动变大，无需改调用点。
    """
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
    """mkimg 子命令：由 `tools/diskfiles/` 创建/重格式化数据盘。

    容量默认由内容推算；`--size` 显式给出时作为覆盖值。
    """
    path = getattr(args, "output", DISK_IMG_PATH)
    size_mb = getattr(args, "size", None)
    label = getattr(args, "label", "BORUIX_DATA")
    force = getattr(args, "force", False)
    if os.path.isfile(path) and not force:
        # 非交互环境**绝不阻塞**：stdin 不是终端时 `input()` 可能永远读不到 EOF（管道不关闭），
        # 表现为构建**静默挂起**——本项在阶段 1 的验收里连踩三次。此处如实报错并给出两条出路，
        # 而不是等待一个永远不会到来的回车。
        if not sys.stdin.isatty():
            err("磁盘镜像已存在，且无法确认覆盖（stdin 不是终端）: " + path)
            err("出路：先删除该文件，或传 --force 显式覆盖，或用 `run --redisk` 重建后再挂载。")
            return 1
        print("\n[警告] 磁盘镜像文件 " + repr(path) + " 已经存在。")
        try:
            choice = input("是否确认覆盖重新格式化？所有已有数据将被清除！[y/N]: ").strip().lower()
        except EOFError:
            choice = "n"
        if choice not in ("y", "yes"):
            info("操作已取消，保留现有磁盘镜像。")
            return 0
    success = create_ext2_disk_image(path, size_mb=size_mb, label=label)
    if success:
        info("内容来源: " + DISKFILES_DIR)
    return 0 if success else 1

