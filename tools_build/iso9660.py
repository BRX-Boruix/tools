"""最小 ISO9660 读取器：按路径查文件，返回其起始逻辑块与字节长度。

只实现本仓库需要的部分：主卷描述符 -> 根目录 -> 逐级目录项。不实现 Joliet /
Rock Ridge / 多扩展名：内核 ELF 在 ISO 里是纯 ISO9660 的 8.3 名（`KERNEL.;1`），
诊断脚本需要的就是它。需要别的特性时在此扩展，不要在调用方各写一份。

**为什么不写死 LBA。** 诊断脚本一度把「内核在 LBA 33、长 24619400 字节」当成常量，
那是某一次构建的实测值；ISO 内容一变，同一个数字就静默指向错误位置，读出来的还是
「合法」的字节，于是给出错误的符号/重定位结论。按路径查是唯一诚实的做法。
"""

import struct

# ISO9660 逻辑块恒为 2048 字节（ECMA-119 8.1）。
SECTOR_SIZE = 2048
# 卷描述符区从第 16 块开始，第一块是主卷描述符（Primary Volume Descriptor）。
PVD_LBA = 16
# 主卷描述符里根目录记录（34 字节）的固定偏移。
PVD_ROOT_RECORD_OFFSET = 156
# 卷描述符的标识串与类型字节。
VOLUME_ID = b"CD001"
TYPE_PRIMARY = 1
TYPE_TERMINATOR = 255
# 目录项里「这是一个目录」的标志位（ECMA-119 9.1.6，bit 1）。
FLAG_DIRECTORY = 0x02


class IsoError(Exception):
    """ISO 结构不合法或路径不存在。宁可报错，不返回伪数据。"""


def _both_endian_u32(data: bytes, offset: int) -> int:
    """读 ISO 的「双端序」32 位字段：先小端后大端，两半必须一致。"""
    little = struct.unpack_from("<I", data, offset)[0]
    big = struct.unpack_from(">I", data, offset + 4)[0]
    if little != big:
        raise IsoError("双端序字段两半不一致: %d != %d" % (little, big))
    return little


def _read_sector(fh, lba: int) -> bytes:
    fh.seek(lba * SECTOR_SIZE)
    data = fh.read(SECTOR_SIZE)
    if len(data) != SECTOR_SIZE:
        raise IsoError("读取逻辑块 %d 时提前结束" % lba)
    return data


def _root_record(fh) -> bytes:
    """从主卷描述符取出根目录记录（其 extent 与长度）。"""
    pvd = _read_sector(fh, PVD_LBA)
    if pvd[0] != TYPE_PRIMARY or pvd[1:6] != VOLUME_ID:
        raise IsoError("第 %d 块不是 ISO9660 主卷描述符" % PVD_LBA)
    length = pvd[PVD_ROOT_RECORD_OFFSET]
    if length == 0:
        raise IsoError("主卷描述符里的根目录记录长度为 0")
    return pvd[PVD_ROOT_RECORD_OFFSET:PVD_ROOT_RECORD_OFFSET + length]


def _record_extent(record: bytes) -> int:
    return _both_endian_u32(record, 2)


def _record_size(record: bytes) -> int:
    return _both_endian_u32(record, 10)


def _record_name(record: bytes) -> str:
    """目录项名字：去掉 `;N` 版本后缀与结尾的 `.`，统一大写。"""
    name_len = record[32]
    raw = record[33:33 + name_len]
    # ISO9660 目录项名字是 ASCII（d-characters），显式按 ASCII 解，不用系统默认编码。
    name = raw.decode("ascii", errors="strict")
    if ";" in name:
        name = name.split(";", 1)[0]
    return name.rstrip(".").upper()


def _iter_records(fh, extent_lba: int, size: int):
    """遍历一个目录的目录项（跳过 `.` 与 `..`）。"""
    remaining = size
    sector = extent_lba
    data = _read_sector(fh, sector)
    offset = 0
    while remaining > 0:
        if offset >= SECTOR_SIZE:
            sector += 1
            remaining -= SECTOR_SIZE
            if remaining <= 0:
                break
            data = _read_sector(fh, sector)
            offset = 0
            continue
        length = data[offset]
        if length == 0:
            # 记录不会跨块：本块剩余部分填零，跳到下一块。
            sector += 1
            remaining -= SECTOR_SIZE
            if remaining <= 0:
                break
            data = _read_sector(fh, sector)
            offset = 0
            continue
        yield data[offset:offset + length]
        offset += length


def find_file(iso_path: str, components) -> tuple:
    """按路径分量查文件，返回 `(extent_lba, size_bytes)`。

    `components` 形如 `["boot", "kernel"]`；大小写不敏感（ISO9660 名字是大写）。
    路径不存在或某一级不是目录时抛 `IsoError`。
    """
    wanted = [part.upper() for part in components]
    if not wanted:
        raise IsoError("路径分量不能为空")
    with open(iso_path, "rb") as fh:
        record = _root_record(fh)
        extent = _record_extent(record)
        size = _record_size(record)
        for index, part in enumerate(wanted):
            last = index == len(wanted) - 1
            found = None
            for entry in _iter_records(fh, extent, size):
                name = _record_name(entry)
                if name in (".", ".."):
                    continue
                if name != part:
                    continue
                is_dir = bool(entry[25] & FLAG_DIRECTORY)
                if last and is_dir:
                    raise IsoError("%s 是目录，不是文件" % part)
                if not last and not is_dir:
                    raise IsoError("%s 不是目录" % part)
                found = (_record_extent(entry), _record_size(entry))
                break
            if found is None:
                raise IsoError("路径分量未找到: " + part)
            extent, size = found
        return extent, size


def read_file(iso_path: str, components) -> bytes:
    """按路径读出整个文件。长度取自目录项，不做任何猜测。"""
    extent, size = find_file(iso_path, components)
    with open(iso_path, "rb") as fh:
        fh.seek(extent * SECTOR_SIZE)
        data = fh.read(size)
    if len(data) != size:
        raise IsoError("文件被截断: 期望 %d 字节，实得 %d" % (size, len(data)))
    return data
