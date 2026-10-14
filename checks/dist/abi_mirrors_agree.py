#!/usr/bin/env python3
"""门禁：跨边界的**镜像常量**必须两侧一致。

为什么需要它：本项目的常量常以"两侧各写一份 + 注释互指"的方式存在（内核 syscall 号与
libsys 调用号、内核 Error::to_errno 与 libsys 同名字段、C 头 #define 与 Rust pub const、
内核与用户态各拼一次的路径）。**注释互指不是机制**——两侧各自漂移时没有任何东西会报错。
本项把"必须一致"的几类关系变成可执行判据。

覆盖七类镜像：
  1. syscall 号：kernel/crates/kernel/src/syscall.rs  <->  libsys/src/nr.rs
  2. 错误码：kernel/crates/klib/src/error.rs         <->  libsys/src/error.rs
  3. C 头常量：libc/include/**/*.h                   <->  libc/src/**/*.rs
  4. 路径契约：同一系统路径在多个文件里被拼出来时必须逐字节一致
  5. 数值镜像：libc 报出的限制值必须等于内核里那个真值常量（两侧无法共享常量）
  6. 结构体布局：`#[repr(C)]` 结构的字段顺序 <-> C 头（顺序错位 = 静默 ABI 损坏）
  7. 单 token 契约：同一标识（如数据盘卷标）在多处必须整串相等

判据一律是"从两侧源码解析出实际值再比对"，不是照抄期望值（照抄的检查在两侧同时改错时
仍然全绿，等于没有）。解析不出来的常量（符号名、类型转换）跳过并计数——不把"没解析到"
混进"通过"。
"""
import os
import re
import sys

# 控制台是 GBK：无法编码的字符（如 U+21D2）会让检查在**输出阶段**崩掉，
# 从而把"检查逻辑失败"与"打印失败"混为一谈。这里显式降级，宁可打出 `?`。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

KERNEL_SYSCALL = os.path.join("kernel", "crates", "kernel", "src", "syscall.rs")
LIBSYS_NR = os.path.join("libsys", "src", "nr.rs")
KERNEL_ERROR = os.path.join("kernel", "crates", "klib", "src", "error.rs")
LIBSYS_ERROR = os.path.join("libsys", "src", "error.rs")

# 只在单侧存在、且**已判定为有意**的项。判定理由必须写在这里；新增的不对称一律算失败，
# 因为"内核实现了而用户态接不上"（S28）与"用户态引用了不存在的号"都是真缺陷。
# 当前为空：SYS_STREAM_LOCK 的双侧不对称已随 flock() 落地而消解（2026-10-13）。
TRIAGED_ASYMMETRY = {}

KNOWN_INTS = {
    "i32::MAX": 2147483647,
    "i32::MIN": -2147483648,
    "u32::MAX": 4294967295,
    "i64::MAX": 9223372036854775807,
    "isize::MAX": 9223372036854775807,
    "usize::MAX": 18446744073709551615,
}


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def walk(rel, suffix):
    base = os.path.join(ROOT, rel)
    for dp, dns, fns in os.walk(base):
        dns[:] = [d for d in dns if d not in (".git", "target")]
        for fn in fns:
            if fn.endswith(suffix):
                yield os.path.join(dp, fn)


def eval_int(expr):
    """尽最大努力求值一个 C/Rust 整型常量表达式；求不出返回 None。"""
    s = expr.strip()
    if s in KNOWN_INTS:
        return KNOWN_INTS[s]
    s = re.sub(r"/\*.*?\*/", "", s).strip()
    for k, v in KNOWN_INTS.items():
        s = s.replace(k, str(v))
    s = s.replace("(void *)-1", "-1").replace("(void*)-1", "-1")
    s = s.replace("(void *)0", "0").replace("(void*)0", "0")
    s = s.replace("core::ptr::null_mut()", "0").replace("null_mut()", "0")
    s = re.sub(r"\(\s*(?:unsigned\s+|signed\s+)?[A-Za-z_][A-Za-z0-9_ ]*\s*\*?\s*\)", "", s)
    s = re.sub(r"\bas\s+[A-Za-z_][A-Za-z0-9_]*(?:\s*\*\s*(?:mut|const)\s*[A-Za-z_][A-Za-z0-9_]*)?", "", s)
    s = re.sub(r"\b0o([0-7_]+)", lambda m: str(int(m.group(1).replace("_", ""), 8)), s)
    s = re.sub(r"\b0x([0-9A-Fa-f_]+)", lambda m: str(int(m.group(1).replace("_", ""), 16)), s)
    s = re.sub(r"\b0b([01_]+)", lambda m: str(int(m.group(1).replace("_", ""), 2)), s)
    s = re.sub(r"\b(\d[\d_]*)[uUlL]+\b", r"\1", s)
    s = re.sub(r"\b(\d[\d_]*)", lambda m: m.group(1).replace("_", ""), s)
    s = re.sub(r"\b0([0-7]{2,})\b", lambda m: str(int(m.group(1), 8)), s)
    s = s.replace("(", "").replace(")", "").replace("<<", " << ").replace(">>", " >> ")
    if not re.fullmatch(r"[\d\s+\-*/%<>|&^~]+", s):
        return None
    try:
        v = eval(s, {"__builtins__": {}}, {})  # noqa: S307 - 字符集已在上行限死
    except Exception:
        return None
    return v if isinstance(v, int) else None


# ---------- 1. syscall 号 ----------

def parse_syscall_table(rel):
    txt = read(rel)
    simple = {}
    for m in re.finditer(r"pub const ([A-Za-z_][A-Za-z0-9_]*)\s*:\s*u32\s*=\s*(0x[0-9A-Fa-f_]+|[0-9_]+)\s*;", txt):
        simple[m.group(1)] = int(m.group(2).replace("_", ""), 0)
    out, unresolved = {}, []
    for m in re.finditer(r"pub const (SYS_[A-Z0-9_]+)\s*:\s*u32\s*=\s*([^;]+);", txt):
        name, expr = m.group(1), m.group(2).strip()
        mm = re.match(r"nr\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)$", expr)
        try:
            if mm:
                def ev(x):
                    x = x.strip().split("::")[-1]
                    if x in simple:
                        return simple[x]
                    return int(x, 0)
                out[name] = ev(mm.group(1)) | ev(mm.group(2))
            else:
                out[name] = int(expr.split("::")[-1], 0)
        except ValueError:
            unresolved.append(name)
    return out, unresolved


def check_syscall_table():
    k, ku = parse_syscall_table(KERNEL_SYSCALL)
    l, lu = parse_syscall_table(LIBSYS_NR)
    bad = []
    for name in sorted(set(k) & set(l)):
        if k[name] != l[name]:
            bad.append((name, k[name], l[name]))
    only_k = sorted(set(k) - set(l))
    only_l = sorted(set(l) - set(k))
    new_asym = [n for n in only_k + only_l if n not in TRIAGED_ASYMMETRY]
    print("[abi-mirror] syscall 号：kernel %d 项 / libsys %d 项，共同 %d 项" % (len(k), len(l), len(set(k) & set(l))))
    if ku or lu:
        print("  WARN 解析不出的项：%s" % (ku + lu))
    for name, kv, lv in bad:
        print("  FAIL %s：kernel=0x%02X libsys=0x%02X" % (name, kv, lv))
    for name in sorted(set(only_k) & set(TRIAGED_ASYMMETRY)):
        print("  TRIAGED 仅内核侧 %s —— %s" % (name, TRIAGED_ASYMMETRY[name]))
    for name in sorted(set(only_l) & set(TRIAGED_ASYMMETRY)):
        print("  TRIAGED 仅用户态侧 %s —— %s" % (name, TRIAGED_ASYMMETRY[name]))
    for name in new_asym:
        side = "仅内核侧" if name in only_k else "仅用户态侧"
        print("  FAIL 未登记的不对称：%s（%s）" % (name, side))
    return not bad and not new_asym


# ---------- 2. 错误码 ----------

def parse_to_errno(rel):
    txt = read(rel)
    m = re.search(r"fn to_errno\(self\) -> i32 \{(.*?)\n    \}", txt, re.S)
    if not m:
        return None
    out = {}
    for arm in re.finditer(r"Error::([A-Za-z_][A-Za-z0-9_]*)\s*=>\s*(-?\d+)", m.group(1)):
        out[arm.group(1)] = int(arm.group(2))
    return out


def parse_from_errno(rel):
    txt = read(rel)
    m = re.search(r"fn from_errno\(e: i32\) -> Self \{(.*?)\n    \}", txt, re.S)
    if not m:
        return None
    out = {}
    for arm in re.finditer(r"(\d+)\s*=>\s*Error::([A-Za-z_][A-Za-z0-9_]*)", m.group(1)):
        out[int(arm.group(1))] = arm.group(2)
    return out


def check_error_codes():
    k = parse_to_errno(KERNEL_ERROR)
    l = parse_to_errno(LIBSYS_ERROR)
    if not k or not l:
        print("  FAIL 解析 to_errno 失败（kernel=%s libsys=%s）" % (bool(k), bool(l)))
        return False
    ok = True
    print("[abi-mirror] 错误码：kernel %d 项 / libsys %d 项" % (len(k), len(l)))
    for name in sorted(set(k) & set(l)):
        if k[name] != l[name]:
            print("  FAIL %s：kernel=%d libsys=%d" % (name, k[name], l[name]))
            ok = False
    for name in sorted(set(k) ^ set(l)):
        print("  FAIL 单侧存在的错误变体：%s" % name)
        ok = False
    frm = parse_from_errno(LIBSYS_ERROR)
    if frm:
        for name, num in l.items():
            if frm.get(num) != name:
                print("  FAIL libsys from_errno 不是 to_errno 的逆：%s=%d 反查得 %s" % (name, num, frm.get(num)))
                ok = False
    return ok


# ---------- 3. C 头 <-> Rust 常量 ----------

def check_header_consts():
    hdr = {}
    for p in walk(os.path.join("libc", "include"), ".h"):
        for i, line in enumerate(open(p, encoding="utf-8").read().splitlines(), 1):
            m = re.match(r"\s*#\s*define\s+([A-Za-z_][A-Za-z0-9_]*)\s+(.+?)\s*$", line)
            if m:
                hdr.setdefault(m.group(1), []).append((m.group(2).strip(), os.path.relpath(p, ROOT), i))
    rs = {}
    for p in walk(os.path.join("libc", "src"), ".rs"):
        txt = open(p, encoding="utf-8").read()
        # **pub 与非 pub 都扫**：同名私有常量同样是"与头文件必须一致"的镜像，
        # 只扫 pub 会让这一类（实测 FP_*/BUFSIZ 共 6 个）完全逃过核对。
        for m in re.finditer(r"(?:pub\s+)?const ([A-Za-z_][A-Za-z0-9_]*)\s*:\s*[^=;]+?=\s*([^;]+);", txt):
            rs.setdefault(m.group(1), []).append((m.group(2).strip(), os.path.relpath(p, ROOT), txt[:m.start()].count("\n") + 1))
    compared, bad, skipped = 0, [], []
    for name in sorted(set(hdr) & set(rs)):
        hv = {eval_int(v) for v, _, _ in hdr[name]} - {None}
        rv = {eval_int(v) for v, _, _ in rs[name]} - {None}
        if not hv or not rv:
            skipped.append(name)
            continue
        compared += 1
        # 指针值常量两侧写法不同（C 的 ((T)-1) 与 Rust 的 usize::MAX）：按 64 位位型比较。
        MASK = (1 << 64) - 1
        if not ({v & MASK for v in hv} & {v & MASK for v in rv}):
            bad.append((name, hdr[name], rs[name]))
    print("[abi-mirror] C 头 <-> Rust 常量：同名 %d 项，可比 %d 项，跳过（含符号名）%d 项"
          % (len(set(hdr) & set(rs)), compared, len(skipped)))
    for name, h, r in bad:
        print("  FAIL %s" % name)
        for v, p, i in h:
            print("        H %-30s %s:%d" % (v[:30], p, i))
        for v, p, i in r:
            print("        R %-30s %s:%d" % (v[:30], p, i))
    return not bad


# ---------- 4. 路径契约 ----------

# 每条 = (概念, [(文件, 抓出路径字面量的正则)])；所有抓出的字面量必须逐字节相同。
PATH_CONTRACTS = (
    ("console 实例节点目录", (
        ("kernel/crates/vfs/src/devfs.rs", r'root\.add_child\("(consoles)"'),
        ("libsys/src/event.rs", r'CONSOLES_DIR_PREFIX: &str = "(/devices/consoles/)"'),
    )),
    # 2026-10-14 补：**单数**的兼容别名 `/devices/console`（实例 0）此前是**无门禁的镜像**——
    # 内核 devfs 逐段拼 add_child("console")，libsys 写整串 CONSOLE_PATH。按本仓的规则
    # 「没有门禁的镜像注释，等于没有」，这一对必须进契约。
    ("console 兼容别名（实例 0）", (
        ("kernel/crates/vfs/src/devfs.rs", r'root\.add_child\("(console)"'),
        ("libsys/src/event.rs", r'CONSOLE_PATH: &str = "(/devices/console)"'),
    )),
    # 2026-10-14：**用户态收成一处**。init/login 原本各写一份字面量（PREFIX / format!），
    # 现都从 libsys::CONSOLES_DIR_PREFIX 派生 ⇒ 上面那条契约只剩「内核建目录」与
    # 「用户态前缀」两个站点。这一条钉住两个引用方**必须**继续引用该常量——
    # 否则有人改回字面量时，上面那条契约仍然"通过"（因为它只看两个站点）。
    ("console 用户态前缀的引用方", (
        ("init/src/main.rs", r'libsys::(CONSOLES_DIR_PREFIX)'),
        ("login/src/main.rs", r'libsys::(CONSOLES_DIR_PREFIX)'),
    )),
    # 2026-10-13：init 里原本三处各写一遍（CONSOLE_REQUESTS_DIR / make_request_path 的
    # PREFIX / drop_bad_name_request 的 DIRP），已收敛为一处常量、其余**派生**；本契约因此
    # 只剩一个站点，另外由下面的「单点字面量」检查钉住"不许再出现第二份"。
    ("console 请求目录", (
        ("init/src/main.rs", r'CONSOLE_REQUESTS_DIR: &str = "(/system/console-requests)"'),
    )),
)


def check_path_contracts():
    ok = True
    print("[abi-mirror] 路径契约：%d 条" % len(PATH_CONTRACTS))
    for concept, sites in PATH_CONTRACTS:
        found = []
        for rel, pattern in sites:
            txt = read(rel)
            m = re.search(pattern, txt)
            if not m:
                print("  FAIL %s：在 %s 里解析不出路径（正则 %s）" % (concept, rel, pattern))
                ok = False
                continue
            found.append((m.group(1), rel))
        # 判据：各处的路径**段序列**必须互为后缀（内核按"目录名 + 子名"逐段拼，
        # 用户态按整串拼，故合法形态本就长短不一；段序列一旦不是后缀关系即为漂移）。
        def segs(s):
            return [x for x in s.split("/") if x]
        vals = [(segs(v), v, rel) for v, rel in found]
        longest = max(vals, key=lambda t: len(t[0]))[0] if vals else []
        drifted = [t for t in vals if longest[len(longest) - len(t[0]):] != t[0]] if vals else []
        if drifted:
            print("  FAIL %s：多处拼法不一致（段序列非后缀关系）" % concept)
            for s, v, rel in vals:
                print("        %-28s %s" % (v, rel))
            ok = False
        elif found:
            print("  OK   %s = %s（%d 处）" % (concept, found[0][1], len(found)))
    return ok


# 跨 crate 的**数值**镜像：两侧不能共享常量（libc 与内核是两棵独立的编译单元），
# 只能各写一份。每条 = (概念, [(文件, 抓出数字的正则)])；抓出的数必须全部相等。
VALUE_MIRRORS = (
    ("页大小 getpagesize()", (
        ("libc/src/unistd.rs", r"fn getpagesize\(\) -> c_int \{\s*(\d+)"),
        ("kernel/crates/vfs/src/page_cache.rs", r"pub const PAGE_SIZE: usize = (\d+);"),
    )),
    ("_PC_PATH_MAX", (
        ("libc/src/unistd.rs", r"_PC_PATH_MAX => (\d+)"),
        ("kernel/crates/kernel/src/syscall.rs", r"const MAX_USER_PATH_BYTES: usize = (\d+);"),
    )),
    ("_PC_NAME_MAX", (
        ("libc/src/unistd.rs", r"_PC_NAME_MAX => (\d+)"),
        ("kernel/crates/vfs/src/mount.rs", r"pub const MAX_NAME_BYTES: usize = (\d+);"),
    )),
    ("_PC_PIPE_BUF", (
        ("libc/src/unistd.rs", r"_PC_PIPE_BUF => (\d+)"),
        ("kernel/crates/ipc/src/lib.rs", r"pub const PIPE_CAPACITY: usize = (\d+);"),
    )),
    ("flock 命令字 SHARED", (
        ("kernel/crates/kernel/src/syscall.rs", r"pub const FLOCK_CMD_SHARED: u64 = (\d+);"),
        ("libsys/src/nr.rs", r"pub const FLOCK_CMD_SHARED: u64 = (\d+);"),
    )),
    ("flock 命令字 EXCLUSIVE", (
        ("kernel/crates/kernel/src/syscall.rs", r"pub const FLOCK_CMD_EXCLUSIVE: u64 = (\d+);"),
        ("libsys/src/nr.rs", r"pub const FLOCK_CMD_EXCLUSIVE: u64 = (\d+);"),
    )),
    ("flock 命令字 UNLOCK", (
        ("kernel/crates/kernel/src/syscall.rs", r"pub const FLOCK_CMD_UNLOCK: u64 = (\d+);"),
        ("libsys/src/nr.rs", r"pub const FLOCK_CMD_UNLOCK: u64 = (\d+);"),
    )),
)


def check_value_mirrors():
    ok = True
    print("[abi-mirror] 跨 crate 数值镜像：%d 条" % len(VALUE_MIRRORS))
    for concept, sites in VALUE_MIRRORS:
        found = []
        for rel, pattern in sites:
            m = re.search(pattern, read(rel))
            if not m:
                print("  FAIL %s：在 %s 里解析不出数值（正则 %s）" % (concept, rel, pattern))
                ok = False
                continue
            found.append((int(m.group(1)), rel))
        if len({v for v, _ in found}) > 1:
            print("  FAIL %s：两侧数值不一致" % concept)
            for v, rel in found:
                print("        %-8d %s" % (v, rel))
            ok = False
        elif found:
            print("  OK   %s = %d（%d 处）" % (concept, found[0][0], len(found)))
    return ok


# ---------- 6. 结构体字段顺序 ----------

# Rust 名 -> C 头里的 tag/typedef 名（两侧命名风格不同，但必须是同一个 ABI 结构）。
STRUCT_ALIASES = {
    "Timespec": "timespec",
    "Timeval": "timeval",
    "Tm": "tm",
    "DivT": "div_t",
    "LDivT": "ldiv_t",
    "ImaxdivT": "imaxdiv_t",
}

# 有 #[repr(C)] 但**故意**不参与比对的结构，理由必须写清（不比对 ≠ 没问题，而是
# 它不跨 C ABI，或 C 侧按设计就是不透明类型）。
STRUCT_EXEMPT = {
    "FILE": "C 侧按设计是不透明类型（typedef struct DIR DIR 同款），字段不跨 ABI",
    "spawn_action": "posix_spawn 的内部动作表，只在 libc 内部使用，不跨 ABI",
}

_RUST_STRUCT = re.compile(r"pub struct ([A-Za-z_][A-Za-z0-9_]*)\s*\{")
_C_NAMED = re.compile(r"^\s*(?:typedef\s+)?struct\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{")
_C_ANON = re.compile(r"^\s*typedef\s+struct\s*\{")


def _struct_body(lines, i):
    """lines[i] 含开括号；返回 (花括号内的文本, 闭括号所在行号)。一行式 typedef 也适用。"""
    depth, parts, j, started = 0, [], i, False
    while j < len(lines):
        for ch in lines[j]:
            if ch == "{":
                depth += 1
                started = True
                continue
            if ch == "}":
                depth -= 1
                if depth == 0:
                    return "".join(parts), j
                continue
            if started and depth >= 1:
                parts.append(ch)
        parts.append("\n")
        j += 1
    return "".join(parts), len(lines) - 1


def _rust_repr_c_structs():
    out = {}
    for p in walk(os.path.join("libc", "src"), ".rs"):
        lines = open(p, encoding="utf-8").read().splitlines()
        for i, line in enumerate(lines):
            m = _RUST_STRUCT.match(line.strip())
            if not m:
                continue
            if "repr(C)" not in "\n".join(lines[max(0, i - 4):i + 1]):
                continue
            body, _end = _struct_body(lines, i)
            fields = re.findall(r"pub\s+([A-Za-z_][A-Za-z0-9_]*)\s*:", body)
            out[m.group(1)] = (fields, "%s:%d" % (os.path.relpath(p, ROOT), i + 1))
    return out


def _c_fields(body):
    # 注释必须**整块删除**而不是"从注释起点截断"：字段行的注释在行尾，截断会把
    # **下一条**字段的名字一起吃掉（本检查初版就这么错过了一半字段）。
    body = re.sub(r"/\*.*?\*/", " ", body, flags=re.S)
    body = re.sub(r"//[^\n]*", " ", body)
    out = []
    for part in body.split(";"):
        s = part.strip()
        if not s or s.startswith("#"):
            continue
        m = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:\[[^\]]*\])?\s*(?::\s*\d+)?$", s)
        if m:
            out.append(m.group(1))
    return out


def _c_structs():
    out = {}
    for p in walk(os.path.join("libc", "include"), ".h"):
        lines = open(p, encoding="utf-8").read().splitlines()
        i = 0
        while i < len(lines):
            named, anon = _C_NAMED.match(lines[i]), _C_ANON.match(lines[i])
            if not named and not anon:
                i += 1
                continue
            body, end = _struct_body(lines, i)
            loc = "%s:%d" % (os.path.relpath(p, ROOT), i + 1)
            fields = _c_fields(body)
            # 名字取两处：结构 tag（`struct bx_sem`）与 typedef 名（`} bx_sem_t;`）——
            # Rust 侧用的是 typedef 名，只登记 tag 会漏配（sem_t 一族正是这样）。
            tm = re.search(r"\}\s*([A-Za-z_][A-Za-z0-9_]*)\s*;", lines[end] if end < len(lines) else "")
            names = []
            if named:
                names.append(named.group(1))
            if tm and tm.group(1) not in names:
                names.append(tm.group(1))
            for name in names:
                out.setdefault(name, []).append((fields, loc))
            i = end + 1
    return out


def check_struct_layouts():
    """逐字段比对 #[repr(C)] 结构的**字段顺序**。

    为什么只比顺序不比类型：顺序错位就是静默的 ABI 损坏（读到隔壁字段的字节），
    而类型宽度差异在两侧的定长断言/实际使用里另有暴露。顺序是零成本就能钉死的那一半。
    """
    rust, c = _rust_repr_c_structs(), _c_structs()
    ok = True
    compared, skipped = 0, []
    for rname, (rfields, rloc) in sorted(rust.items()):
        if rname in STRUCT_EXEMPT:
            skipped.append((rname, STRUCT_EXEMPT[rname]))
            continue
        cname = STRUCT_ALIASES.get(rname, rname)
        if cname not in c:
            print("  FAIL %s（%s）：C 头里找不到对应结构 %s" % (rname, rloc, cname))
            ok = False
            continue
        for cfields, cloc in c[cname]:
            compared += 1
            if rfields != cfields:
                print("  FAIL %s：字段顺序不一致" % rname)
                print("        R %s  %s" % (rfields, rloc))
                print("        C %s  %s" % (cfields, cloc))
                ok = False
    print("[abi-mirror] 结构体字段顺序：比对 %d 个，豁免 %d 个" % (compared, len(skipped)))
    for name, why in skipped:
        print("  EXEMPT %s —— %s" % (name, why))
    return ok


# 单 token 契约：同一标识在多处必须**逐字节相同**（不是路径段后缀关系，故单列一类）。
# 例：卷标 BORUIX_DATA —— 磁盘镜像用它命名，内核据此挂到 /volumes/<label>，
# 而用户态把 /volumes/BORUIX_DATA/... 写死在多处。改一处而不改另一处，
# 表现为"数据盘在，但 /volumes/BORUIX_DATA 不存在"，且没有任何东西会报错。
TOKEN_CONTRACTS = (
    ("3p 子目录名（tcc 安装目录 ↔ 宿主 staging）", (
        ("tcc-on-boruix/boruix/config.h", r'CONFIG_TCCDIR "/volumes/BORUIX_DATA/([A-Za-z0-9_]+)/tcc"'),
        ("tools/tools_build/b3p.py", r'THIRD_PARTY_SUBDIR = "([A-Za-z0-9_]+)"'),
    )),
    ("数据盘卷标", (
        ("tools/main.py", r'--label",\s*default="([A-Za-z0-9_]+)"'),
        ("tools/tools_build/disk.py", r'def create_ext2_disk_image\([^)]*label="([A-Za-z0-9_]+)"'),
        ("shell/src/env.rs", r'DEFAULT_PATH: &\[u8\] = b"[^"]*/volumes/([A-Za-z0-9_]+)/'),
        ("init/src/main.rs", r'let probe = "/volumes/([A-Za-z0-9_]+)/welcome\.txt"'),
    )),
)


def check_token_contracts():
    ok = True
    print("[abi-mirror] 单 token 契约：%d 条" % len(TOKEN_CONTRACTS))
    for concept, sites in TOKEN_CONTRACTS:
        found = []
        for rel, pattern in sites:
            m = re.search(pattern, read(rel))
            if not m:
                print("  FAIL %s：在 %s 里解析不出（正则 %s）" % (concept, rel, pattern))
                ok = False
                continue
            found.append((m.group(1), rel))
        if len({v for v, _ in found}) > 1:
            print("  FAIL %s：多处取值不一致" % concept)
            for v, rel in found:
                print("        %-24s %s" % (v, rel))
            ok = False
        elif found:
            print("  OK   %s = %s（%d 处）" % (concept, found[0][0], len(found)))
    return ok


# 「同一字面量只许出现一次」：S13 单点化的机械判据。
# 只数**代码行**里的出现次数（以 // 开头的注释行不计）——注释里提一句不算第二份事实。
SINGLE_LITERAL = (
    ("console 请求目录（init 内）", "init/src/main.rs", "/system/console-requests"),
    # 用户态单一事实源已从 init 移到 libsys（init/login 改为派生）。
    ("console 实例节点目录（用户态单一事实源）", "libsys/src/event.rs", "/devices/consoles/"),
)


def check_single_literal():
    ok = True
    print("[abi-mirror] 单点字面量：%d 条" % len(SINGLE_LITERAL))
    for label, rel, lit in SINGLE_LITERAL:
        count = 0
        for line in read(rel).splitlines():
            if line.strip().startswith("//"):
                continue
            count += line.count(lit)
        if count != 1:
            print("  FAIL %s：%s 在代码里出现 %d 次（应为 1 次）" % (label, repr(lit), count))
            ok = False
        else:
            print("  OK   %s = %s（唯一）" % (label, repr(lit)))
    return ok


# ---------- 9. 结构体字段宽度（类型） ----------

# 字段**宽度类**表：只比宽度，不比精确类型——宽度错位（C 的 long vs Rust 的 i32）
# 才是静默 ABI 损坏；同宽度的不同写法（unsigned long vs u64）不是缺陷。
_C_SCALAR = {
    "char": 1, "signed char": 1, "unsigned char": 1, "_Bool": 1, "bool": 1,
    "short": 2, "short int": 2, "unsigned short": 2, "unsigned short int": 2,
    "int": 4, "signed int": 4, "unsigned": 4, "unsigned int": 4, "float": 4,
    "long": 8, "long int": 8, "unsigned long": 8, "unsigned long int": 8,
    "long long": 8, "unsigned long long": 8, "double": 8, "long double": 8,
    # <stdint.h> 由**编译器内置**提供（本仓的 inttypes.h 只是 include 它），
    # 故这些名字不在我们的 typedef 表里；LP64 下宽度如下。
    "int8_t": 1, "uint8_t": 1, "int16_t": 2, "uint16_t": 2,
    "int32_t": 4, "uint32_t": 4, "int64_t": 8, "uint64_t": 8,
    "intmax_t": 8, "uintmax_t": 8, "intptr_t": 8, "uintptr_t": 8, "ptrdiff_t": 8,
}
_RUST_SCALAR = {
    "i8": 1, "u8": 1, "c_char": 1, "c_uchar": 1, "bool": 1,
    "i16": 2, "u16": 2, "c_ushort": 2,
    "i32": 4, "u32": 4, "c_int": 4, "c_uint": 4, "f32": 4, "AtomicI32": 4,
    "i64": 8, "u64": 8, "c_long": 8, "c_ulong": 8, "usize": 8, "isize": 8,
    "f64": 8, "AtomicU64": 8, "c_longlong": 8, "c_ulonglong": 8,
}


def _c_typedefs():
    out = {}
    for p in walk(os.path.join("libc", "include"), ".h"):
        txt = re.sub(r"/\*.*?\*/", " ", open(p, encoding="utf-8").read(), flags=re.S)
        txt = re.sub(r"//[^\n]*", " ", txt)
        for m in re.finditer(r"typedef\s+([^;{}]+?)\s+([A-Za-z_][A-Za-z0-9_]*)\s*;", txt):
            out[m.group(2)] = m.group(1).strip()
        # 函数指针 typedef：上面的正则取不到名字，但它就是指针。
        for m in re.finditer(r"typedef\s+[^;{}]*?\(\s*\*\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)", txt):
            out[m.group(1)] = "void *"
    return out


def _rust_typedefs():
    """扫**全部** libc/src（不只 ctypes.rs）：sighandler_t/sigset_t 定义在 signal.rs。"""
    out = {}
    for p in walk(os.path.join("libc", "src"), ".rs"):
        txt = open(p, encoding="utf-8").read()
        for m in re.finditer(r"pub type ([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^;]+);", txt):
            out.setdefault(m.group(1), m.group(2).strip())
    return out


def _rust_consts():
    """Rust 整数常量表：数组长度写成常量名（`[spawn_action; SPAWN_MAX_ACTIONS]`）时要能求值。"""
    out = {}
    for p in walk(os.path.join("libc", "src"), ".rs"):
        txt = open(p, encoding="utf-8").read()
        for m in re.finditer(r"pub const ([A-Za-z_][A-Za-z0-9_]*)\s*:\s*[A-Za-z0-9_]+\s*=\s*(\d+)\s*;", txt):
            out[m.group(1)] = int(m.group(2))
    return out


_RUST_CONSTS = {}


def _shape_of(parts):
    """把子形状列表折成一个形状；任一项建模不了则整体建模不了。"""
    return None if any(x is None for x in parts) else tuple(parts)


def _c_shape(t, typedefs, structs, depth=0):
    """返回字段的**形状**：标量=字节数、数组=(arr,N,内层)、嵌套结构=子形状元组、指针=8。
    None 表示建模不了（调用方跳过该结构，而不是猜）。"""
    t = " ".join(t.split())
    t = t.replace("volatile ", "").replace("const ", "").replace("register ", "").strip()
    if t.endswith("*"):
        return 8
    m = re.match(r"(.+?)\s*\[\s*(\d+)\s*\]$", t)
    if m:
        inner = _c_shape(m.group(1), typedefs, structs, depth + 1)
        return None if inner is None else ("arr", int(m.group(2)), inner)
    if t in _C_SCALAR:
        return _C_SCALAR[t]
    if t.startswith("struct ") or t.startswith("union "):
        name = t.split(None, 1)[1].strip()
        if depth < 6 and name in structs:
            return _shape_of([_c_shape(x, typedefs, structs, depth + 1) for x in structs[name]])
        return None
    if depth < 8 and t in typedefs:
        return _c_shape(typedefs[t], typedefs, structs, depth + 1)
    return None


def _rust_shape(t, typedefs, structs, depth=0):
    t = " ".join(t.split())
    if "::" in t and "[" not in t and "(" not in t:
        t = t.split("::")[-1].strip()
    if "*mut" in t or "*const" in t or t.startswith("&"):
        return 8
    m = re.match(r"\[(.+?);\s*([A-Za-z_][A-Za-z0-9_]*|\d+)\]$", t)
    if m:
        inner = _rust_shape(m.group(1), typedefs, structs, depth + 1)
        n = m.group(2)
        n = int(n) if n.isdigit() else _RUST_CONSTS.get(n)
        return None if inner is None or n is None else ("arr", n, inner)
    if t in _RUST_SCALAR:
        return _RUST_SCALAR[t]
    if depth < 6 and t in structs:
        return _shape_of([_rust_shape(x, typedefs, structs, depth + 1) for x in structs[t]])
    if depth < 8 and t in typedefs:
        return _rust_shape(typedefs[t], typedefs, structs, depth + 1)
    return None


def _field_types(body, lang):
    """从结构体正文里取每个字段的**类型文本**（按出现顺序）。

    C 侧取「声明里最后一个标识符」当字段名，其**前面**的部分即类型；数组维度跟在
    字段名之后，要并回类型里（否则宽度会漏乘）。指针声明（`char **p`）也必须能取到名字。
    """
    out = []
    if lang == "c":
        body = re.sub(r"/\*.*?\*/", " ", body, flags=re.S)
        body = re.sub(r"//[^\n]*", " ", body)
        for part in body.split(";"):
            s = part.strip()
            if not s or s.startswith("#"):
                continue
            m = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*(\[[^\]]*\])?\s*(?::\s*\d+)?$", s)
            if not m:
                continue
            type_text = s[: m.start()].strip()
            if m.group(2):
                type_text = (type_text + " " + m.group(2)).strip()
            if type_text:
                out.append(type_text)
    else:
        for m in re.finditer(r"pub\s+[A-Za-z_][A-Za-z0-9_]*\s*:\s*([^,]+?)\s*,", body):
            out.append(m.group(1).strip())
    return out


def _rust_field_types():
    """Rust 侧：结构名 -> 字段类型列表（与 _rust_repr_c_structs 同源同序）。"""
    out = {}
    for p in walk(os.path.join("libc", "src"), ".rs"):
        lines = open(p, encoding="utf-8").read().splitlines()
        for i, line in enumerate(lines):
            m = _RUST_STRUCT.match(line.strip())
            if not m:
                continue
            if "repr(C)" not in "\n".join(lines[max(0, i - 4):i + 1]):
                continue
            body, _ = _struct_body(lines, i)
            out[m.group(1)] = _field_types(body, "rust")
    return out


def check_struct_widths():
    global _RUST_CONSTS
    ctd, rtd = _c_typedefs(), _rust_typedefs()
    _RUST_CONSTS = _rust_consts()
    rust = _rust_field_types()
    cstructs = {}
    for p in walk(os.path.join("libc", "include"), ".h"):
        lines = open(p, encoding="utf-8").read().splitlines()
        i = 0
        while i < len(lines):
            named, anon = _C_NAMED.match(lines[i]), _C_ANON.match(lines[i])
            if not named and not anon:
                i += 1
                continue
            body, end = _struct_body(lines, i)
            tm = re.search(r"\}\s*([A-Za-z_][A-Za-z0-9_]*)\s*;", lines[end] if end < len(lines) else "")
            for nm in ([named.group(1)] if named else []) + ([tm.group(1)] if tm else []):
                cstructs.setdefault(nm, _field_types(body, "c"))
            i = end + 1
    ok = True
    compared, skipped = 0, []
    for rname, rfields in sorted(rust.items()):
        if rname in STRUCT_EXEMPT:
            continue
        cname = STRUCT_ALIASES.get(rname, rname)
        if cname not in cstructs:
            continue
        ctypes = cstructs[cname]
        if len(ctypes) != len(rfields):
            continue  # 字段数不同：顺序检查已报
        widths = []
        for ct, rt in zip(ctypes, rfields):
            cw = _c_shape(ct, ctd, cstructs)
            rw = _rust_shape(rt, rtd, rust)
            if cw is None or rw is None:
                widths = None
                break
            widths.append((ct, rt, cw, rw))
        if widths is None:
            skipped.append(rname)
            continue
        compared += 1
        for ct, rt, cw, rw in widths:
            if cw != rw:
                print("  FAIL %s：字段形状不一致  C(%s)=%s  Rust(%s)=%s" % (rname, ct, cw, rt, rw))
                ok = False
    print("[abi-mirror] 结构体字段形状：比对 %d 个，跳过（含未建模类型）%d 个" % (compared, len(skipped)))
    if skipped:
        print("       跳过：%s" % ", ".join(sorted(skipped)))
    return ok


def main():
    results = [
        ("syscall 号", check_syscall_table()),
        ("错误码", check_error_codes()),
        ("C 头常量", check_header_consts()),
        ("路径契约", check_path_contracts()),
        ("数值镜像", check_value_mirrors()),
        ("结构体布局", check_struct_layouts()),
        ("单 token 契约", check_token_contracts()),
        ("单点字面量", check_single_literal()),
        ("结构体字段宽度", check_struct_widths()),
    ]
    failed = [n for n, ok in results if not ok]
    if failed:
        print("[abi-mirror] FAIL：%s" % "、".join(failed))
        return 1
    print("[abi-mirror] OK：七类镜像全部一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
