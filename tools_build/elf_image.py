"""ELF64 只读解析：头、段、节、符号表，以及「地址 -> 符号+偏移」反解。

诊断为什么需要它：内核 panic / 异常只给出 `RIP` 与 `CR2`。把 `RIP` 反解成
`arch_x86_64::smp::requested_cpu_count+0xc` 才能从「某个地址出错」变成「哪条路径出错」
——L5 的最后一层缺陷就是这样定位的（`smp::requested_cpu_count` 读 `0x3de16680`，
那正是引导器响应容器的裸地址）。没有这一步，排查只能靠猜。

只读、不写、不改：本模块从不修改传入的字节，也从不猜测缺失的数据——解析不了就抛
`ElfError`。**绝不返回看起来合理的假值**：一个错误的符号名比没有符号名危险得多。
"""

import struct
import sys

# ELF 标识（EI_MAG0..EI_NIDENT）。
ELF_MAGIC = b"\x7fELF"
ELFCLASS64 = 2
ELFDATA2LSB = 1

# 节类型。
SHT_SYMTAB = 2
SHT_STRTAB = 3

# 段类型。
PT_LOAD = 1

# 段标志位。
PF_X = 0x1
PF_W = 0x2
PF_R = 0x4

# 文件头各字段偏移（ELF64，小端）。
_EHDR = "<16sHHIQQQIHHHHHH"


class ElfError(Exception):
    """ELF 结构不合法。解析失败一律抛错，不降级。"""


def _cstr(blob: bytes, offset: int) -> str:
    """读一个 NUL 结尾字符串。符号名是 ASCII（Rust 符号名只用 ASCII）。"""
    if offset < 0 or offset >= len(blob):
        raise ElfError("字符串表偏移越界: %d" % offset)
    end = blob.find(b"\x00", offset)
    if end < 0:
        raise ElfError("字符串表在偏移 %d 处没有结尾 NUL" % offset)
    return blob[offset:end].decode("ascii", errors="strict")


class Segment:
    """程序头（`PT_LOAD` 等）。"""

    __slots__ = ("type", "flags", "offset", "vaddr", "filesz", "memsz")

    def __init__(self, type_, flags, offset, vaddr, filesz, memsz):
        self.type = type_
        self.flags = flags
        self.offset = offset
        self.vaddr = vaddr
        self.filesz = filesz
        self.memsz = memsz

    def __repr__(self):
        return "Segment(type=%d flags=%d off=%#x vaddr=%#x filesz=%d memsz=%d)" % (
            self.type, self.flags, self.offset, self.vaddr, self.filesz, self.memsz)


class Symbol:
    """符号表条目。`name` 是原始（Rust 单态化后很长的）名字。"""

    __slots__ = ("name", "value", "size", "section")

    def __init__(self, name, value, size, section):
        self.name = name
        self.value = value
        self.size = size
        self.section = section

    def __repr__(self):
        return "Symbol(%s @ %#x +%d)" % (self.name, self.value, self.size)


class ElfImage:
    """一个解析好的 ELF64 小端映像。"""

    def __init__(self, data):
        self.data = data
        (magic, e_type, e_machine, _version, e_entry, e_phoff, e_shoff, _flags,
         _ehsize, e_phentsize, e_phnum, e_shentsize, e_shnum,
         e_shstrndx) = struct.unpack_from(_EHDR, data, 0)
        if magic[:4] != ELF_MAGIC:
            raise ElfError("不是 ELF 文件")
        if magic[4] != ELFCLASS64:
            raise ElfError("只支持 ELF64（EI_CLASS=%d）" % magic[4])
        if magic[5] != ELFDATA2LSB:
            raise ElfError("只支持小端（EI_DATA=%d）" % magic[5])
        self.type = e_type
        self.machine = e_machine
        self.entry = e_entry
        self._phoff = e_phoff
        self._phentsize = e_phentsize
        self._phnum = e_phnum
        self._shoff = e_shoff
        self._shentsize = e_shentsize
        self._shnum = e_shnum
        self._shstrndx = e_shstrndx
        self._segments = None
        self._sections = None
        self._symbols = None

    @classmethod
    def parse(cls, data: bytes):
        if len(data) < struct.calcsize(_EHDR):
            raise ElfError("数据太短，装不下 ELF 文件头")
        return cls(data)

    # ---------- 节 ----------

    def _raw_sections(self):
        if self._sections is None:
            out = []
            for i in range(self._shnum):
                off = self._shoff + i * self._shentsize
                if off + self._shentsize > len(self.data):
                    raise ElfError("节头 %d 越界" % i)
                (name, type_, flags, addr, offset, size, link, info, align,
                 entsize) = struct.unpack_from("<IIQQQQIIQQ", self.data, off)
                out.append({"name": name, "type": type_, "flags": flags,
                            "addr": addr, "offset": offset, "size": size,
                            "link": link, "info": info, "align": align,
                            "entsize": entsize})
            self._sections = out
        return self._sections

    def _shstrtab(self) -> bytes:
        sections = self._raw_sections()
        if self._shstrndx >= len(sections):
            raise ElfError("e_shstrndx 越界: %d" % self._shstrndx)
        section = sections[self._shstrndx]
        return self.data[section["offset"]:section["offset"] + section["size"]]

    def section_names(self):
        """返回全部节名（用于诊断：确认 `.symtab` / `.rela.dyn` 是否存在）。"""
        shstr = self._shstrtab()
        return [_cstr(shstr, s["name"]) for s in self._raw_sections()]

    def section(self, name: str):
        """按名字取节；不存在返回 `None`（调用方必须显式处理缺失）。"""
        shstr = self._shstrtab()
        for s in self._raw_sections():
            if _cstr(shstr, s["name"]) == name:
                return s
        return None

    # ---------- 段 ----------

    def segments(self):
        if self._segments is None:
            out = []
            for i in range(self._phnum):
                off = self._phoff + i * self._phentsize
                if off + self._phentsize > len(self.data):
                    raise ElfError("程序头 %d 越界" % i)
                (type_, flags, offset, vaddr, _paddr, filesz, memsz, _align) = \
                    struct.unpack_from("<IIQQQQQQ", self.data, off)
                out.append(Segment(type_, flags, offset, vaddr, filesz, memsz))
            self._segments = out
        return self._segments

    def vaddr_to_offset(self, vaddr: int):
        """虚拟地址 -> 文件偏移。落在某个 `PT_LOAD` 的文件区间内才返回。"""
        for seg in self.segments():
            if seg.type != PT_LOAD:
                continue
            if seg.vaddr <= vaddr < seg.vaddr + seg.filesz:
                return seg.offset + (vaddr - seg.vaddr)
        return None

    def read_vaddr(self, vaddr: int, length: int) -> bytes:
        """按虚拟地址读一段字节。不可读时抛错（不返回零填充）。"""
        offset = self.vaddr_to_offset(vaddr)
        if offset is None:
            raise ElfError("虚拟地址 %#x 不在任何 PT_LOAD 的文件区间内" % vaddr)
        end = offset + length
        if end > len(self.data):
            raise ElfError("虚拟地址 %#x 处读取 %d 字节越界" % (vaddr, length))
        return self.data[offset:end]

    # ---------- 符号 ----------

    def symbols(self):
        """返回 `.symtab` 里的全部符号。没有 `.symtab` 时抛错。

        **不静默返回空表**：那会让调用方以为「地址解析不出符号是正常的」。
        """
        if self._symbols is None:
            symtab = self.section(".symtab")
            if symtab is None:
                raise ElfError("映像里没有 .symtab（可能被 strip 过）")
            if symtab["entsize"] == 0:
                raise ElfError(".symtab 的 sh_entsize 为 0")
            sections = self._raw_sections()
            if symtab["link"] >= len(sections):
                raise ElfError(".symtab 的 sh_link 越界")
            strtab = sections[symtab["link"]]
            blob = self.data[strtab["offset"]:strtab["offset"] + strtab["size"]]
            out = []
            count = symtab["size"] // symtab["entsize"]
            for i in range(count):
                off = symtab["offset"] + i * symtab["entsize"]
                (st_name, _info, _other, st_shndx, st_value,
                 st_size) = struct.unpack_from("<IBBHQQ", self.data, off)
                if st_name == 0:
                    continue
                out.append(Symbol(_cstr(blob, st_name), st_value, st_size, st_shndx))
            self._symbols = out
        return self._symbols

    def resolve(self, address: int):
        """把地址反解成 `(符号名, 偏移)`；找不到返回 `None`。

        选择规则：取 `value <= address` 中 `value` 最大者。优先取**有大小**的符号
        （`st_size > 0`）且地址落在 `[value, value+size)` 内的精确命中，其次退回
        最近的前驱符号——两者含义不同，所以返回值里同时给出偏移，由调用方判断。
        """
        exact = None
        nearest = None
        for sym in self.symbols():
            if sym.value == 0 or sym.value > address:
                continue
            if nearest is None or sym.value > nearest.value:
                nearest = sym
            if sym.size > 0 and sym.value <= address < sym.value + sym.size:
                if exact is None or sym.value > exact.value:
                    exact = sym
        chosen = exact if exact is not None else nearest
        if chosen is None:
            return None
        return chosen.name, address - chosen.value


def cmd(args) -> int:
    """`main.py where`：把内核 ELF 里的地址反解成符号（诊断用）。"""
    from . import config, iso9660

    iso = args.iso or config.OUTPUT_ISO
    try:
        data = iso9660.read_file(iso, config.KERNEL_ISO_COMPONENTS)
        image = ElfImage.parse(data)
    except (iso9660.IsoError, ElfError, OSError) as exc:
        print("读取内核 ELF 失败: %s" % exc, file=sys.stderr)
        return 1

    if args.list_sections:
        for name in image.section_names():
            print(name)
        return 0

    print("ISO:      " + iso)
    print("入口:     %#x" % image.entry)
    print("段:       %d   节: %d   符号: %d" % (
        len(image.segments()), len(image.section_names()), len(image.symbols())))
    if not args.addresses:
        return 0
    for address, text in resolve_readable(image, args.addresses):
        print("  %#018x -> %s" % (address, text if text else "(不在任何符号范围内)"))
    return 0


def _is_base62(ch: str) -> bool:
    return ch.isascii() and (ch.isalnum())


def readable_name(mangled: str) -> str:
    """把 Rust v0 符号名**尽力**渲染成 `模块::路径::函数`。

    **这不是 demangler。** 它只提取 v0 名字里长度前缀的标识符段（`6kernel` -> `kernel`）
    并跳过 crate 消歧串（`Cs<base62>_`）与其它编码字符，因此是**有损**的：泛型实参、
    闭包序号、常量参数都不会出现。它只用于让 `RIP` 反解结果一眼可读——
    `Symbol.name` 始终保留原始名，需要精确信息时用它。

    本机没有 `rustfilt` / `c++filt`（已确认），所以不依赖外部工具。
    """
    out = []
    i = 0
    n = len(mangled)
    while i < n:
        ch = mangled[i]
        # crate 消歧串：`C` + 一个字母 + base62 串 + `_`。
        if ch == "C" and i + 1 < n and mangled[i + 1].isalpha():
            j = i + 2
            while j < n and _is_base62(mangled[j]):
                j += 1
            if j < n and mangled[j] == "_":
                i = j + 1
                continue
        if ch.isdigit():
            j = i
            while j < n and mangled[j].isdigit():
                j += 1
            length = int(mangled[i:j])
            if length > 0 and j + length <= n:
                out.append(mangled[j:j + length])
                i = j + length
                continue
        i += 1
    if not out:
        return mangled
    return "::".join(out)


def resolve_addresses(image: ElfImage, addresses):
    """批量反解，返回 `[(address, text)]`；解不出的 text 为 None。"""
    out = []
    for address in addresses:
        hit = image.resolve(address)
        out.append((address, None if hit is None else "%s+0x%x" % hit))
    return out


def resolve_readable(image: ElfImage, addresses):
    """同 `resolve_addresses`，但名字经过 `readable_name` 渲染。"""
    out = []
    for address in addresses:
        hit = image.resolve(address)
        if hit is None:
            out.append((address, None))
        else:
            out.append((address, "%s+0x%x" % (readable_name(hit[0]), hit[1])))
    return out
    return out
