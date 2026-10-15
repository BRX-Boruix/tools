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
#
# **2026-10-14 起改为「生成 + 接线检查」**。此前两侧各手写一份、本类比对数值；
# 现在数值的唯一事实源是 tools/abi/constants.json，两侧由 tools/abi/generate.py 生成。
# 故本类不再比数值（那是 generate.py --check 的职责），改查**接线**：
#   - 两侧手写文件里不得再有写死的 SYS_* 数值（必须引用 crate::abi_generated::*）；
#   - 引用的目标名必须与常量名一致；
#   - 两侧的 SYS_* 名字集合必须与 JSON 完全一致（不多不少）。

ABI_JSON = os.path.join("tools", "abi", "constants.json")


def parse_abi_json():
    import json as _json
    with open(os.path.join(ROOT, ABI_JSON), encoding="utf-8") as fh:
        doc = _json.load(fh)
    doms, ops = doc["syscall_domains"], doc["syscall_ops"]
    out = {}
    for name, e in doc["syscalls"].items():
        o = e["op"]
        out[name] = doms[e["domain"]] | (ops[o] if isinstance(o, str) else int(o))
    return out


def parse_generated_refs(rel):
    """手写文件里的 SYS_* 定义现在必须是 crate::abi_generated::SYS_X 的引用。"""
    txt = read(rel)
    refs = {}
    for m in re.finditer(
        r"pub const (SYS_[A-Z0-9_]+): u32 = crate::abi_generated::([A-Za-z0-9_]+);", txt
    ):
        refs[m.group(1)] = m.group(2)
    hard = [m.group(1) for m in re.finditer(
        r"pub const (SYS_[A-Z0-9_]+): u32 = (?!crate::abi_generated::)[^;]+;", txt
    )]
    return refs, hard


def check_syscall_table():
    ref = parse_abi_json()
    ok = True
    print("[abi-mirror] syscall 号：单一事实源 %s，%d 项" % (ABI_JSON, len(ref)))
    for rel in (KERNEL_SYSCALL, LIBSYS_NR):
        refs, hard = parse_generated_refs(rel)
        if hard:
            print("  FAIL %s 里仍有写死的 SYS_* 数值：%s" % (rel, hard[:5]))
            ok = False
        wrong = sorted(n for n, tgt in refs.items() if n != tgt)
        if wrong:
            print("  FAIL %s 引用的目标名与常量名不一致：%s" % (rel, wrong[:5]))
            ok = False
        missing = sorted(set(ref) - set(refs))
        extra = sorted(set(refs) - set(ref))
        if missing:
            print("  FAIL %s 缺少 %d 项：%s" % (rel, len(missing), missing[:5]))
            ok = False
        if extra:
            print("  FAIL %s 多出 %d 项：%s" % (rel, len(extra), extra[:5]))
            ok = False
        if not (hard or wrong or missing or extra):
            print("  OK   %s：%d 项全部引用生成物" % (rel, len(refs)))
    return ok


# ---------- 2. 错误码 ----------
#
# **2026-10-14 起改为「生成 + 接线检查」**（与第 1 类同一改法）。此前两侧各手写
# to_errno/from_errno、本类比对数值与互逆性；现在数值的唯一事实源是
# tools/abi/constants.json，两侧由 tools/abi/generate.py 生成。故本类改查**接线**：
#   - 两侧的 to_errno（以及 libsys 的 from_errno）必须**委托** crate::abi_generated；
#   - 两侧不得残留裸映射臂（Error::X => N）。
# 数值一致、以及 libsys 的 from_errno 是 to_errno 的逆，由生成器从**同一份** JSON
# 同时产出两侧而结构性成立；libc 的 errno.h/errno.rs 与 JSON 同值也由生成器核对。

ERRNO_SIDES = (
    (KERNEL_ERROR, ("to_errno",)),
    (LIBSYS_ERROR, ("to_errno", "from_errno")),
)


def check_error_codes():
    ok = True
    print("[abi-mirror] 错误码：单一事实源 %s" % ABI_JSON)
    for rel, fns in ERRNO_SIDES:
        txt = read(rel)
        for fn in fns:
            body = re.search(r"fn " + fn + r"\([^)]*\)[^{]*\{(.*?)\n    \}", txt, re.S)
            if body is None:
                print("  FAIL %s：找不到 %s" % (rel, fn))
                ok = False
                continue
            if "crate::abi_generated::" + fn not in body.group(1):
                print("  FAIL %s：%s 未委托 crate::abi_generated::%s" % (rel, fn, fn))
                ok = False
        arms = re.findall(r"Error::[A-Za-z_][A-Za-z0-9_]*\s*=>\s*-?\d+\s*,", txt)
        if arms:
            print("  FAIL %s：残留 %d 条裸映射臂 %s" % (rel, len(arms), arms[:3]))
            ok = False
    if ok:
        print("  OK   kernel/libsys 的 errno 映射全部委托生成物，无裸映射臂")
    return ok


# ---------- 3. C 头 <-> Rust 常量 ----------
#
# **2026-10-14 起全部改为生成**。这一族共 279 项（libc 的 C 头 #define 与 Rust 常量同名），
# 此前是"两侧各手写一份 + 本类比对"。现在：
#   · 134 项 errno  -> tools/abi/constants.json 的 errno_table；
#   · 144 项其它常量 -> 同文件的 c_consts；
#   · **1 项 NULL 仍手写**——它是**条件定义**（`#ifdef __cplusplus` 两个分支值不同），
#     单一值表达不了。如实保留并在此说明。
#
# 本类的职责因此变成两件：
#   1. **内容核对**：C 头里的值与生成物里的值必须一致（防头文件被改而不重新生成）；
#   2. **接线核对**：手写 libc 源里**不得**再定义这些常量（只能 use 生成物），
#      并**显式报数**（名字从一侧消失会让交集变小、类仍然"通过"——那是静默流失）。

GENERATED_STILL_HANDWRITTEN = {
    "NULL": "条件定义（#ifdef __cplusplus 两分支值不同），单一值表达不了",
}


def _libc_const_defs(exclude_generated):
    out = {}
    for p in walk(os.path.join("libc", "src"), ".rs"):
        rel = os.path.relpath(p, ROOT)
        if exclude_generated and rel.endswith("abi_generated.rs"):
            continue
        txt = open(p, encoding="utf-8").read()
        for m in re.finditer(r"(?:pub\s+)?const ([A-Za-z_][A-Za-z0-9_]*)\s*:\s*[^=;]+?=\s*([^;]+);", txt):
            pre = txt[:m.start()]
            if pre.rfind("#[cfg(test)]") > pre.rfind("\n}"):
                continue  # 测试模块里的同名常量不算（如 ctype.rs 的局部 EOF）
            out.setdefault(m.group(1), []).append((m.group(2).strip(), rel, pre.count("\n") + 1))
    return out


def check_header_consts():
    import json as _json
    with open(os.path.join(ROOT, ABI_JSON), encoding="utf-8") as fh:
        _doc = _json.load(fh)
    errno_tbl, c_consts = _doc["errno_table"], _doc["c_consts"]
    generated = set(errno_tbl) | set(c_consts)

    hdr = {}
    for p in walk(os.path.join("libc", "include"), ".h"):
        for i, line in enumerate(open(p, encoding="utf-8").read().splitlines(), 1):
            m = re.match(r"\s*#\s*define\s+([A-Za-z_][A-Za-z0-9_]*)\s+(.+?)\s*$", line)
            if m:
                hdr.setdefault(m.group(1), []).append((m.group(2).strip(), os.path.relpath(p, ROOT), i))
    all_defs = _libc_const_defs(exclude_generated=False)
    gen_defs = {k: v for k, v in all_defs.items()
                if any(r.endswith("abi_generated.rs") for _, r, _ in v)}
    hand_defs = _libc_const_defs(exclude_generated=True)

    ok = True
    missing = sorted(generated - set(gen_defs))
    if missing:
        print("  FAIL 生成物里缺少 %d 项：%s" % (len(missing), missing[:6]))
        ok = False
    leaked = sorted(n for n in generated if n in hand_defs)
    if leaked:
        print("  FAIL 手写 libc 源里仍在定义已生成的常量 %d 项：%s" % (len(leaked), leaked[:6]))
        ok = False
    print("[abi-mirror] C 头 <-> Rust 常量：**已生成 %d 项**（errno %d + 其它 %d），仍手写 %d 项 %s"
          % (len(generated), len(errno_tbl), len(c_consts),
             len(GENERATED_STILL_HANDWRITTEN), list(GENERATED_STILL_HANDWRITTEN)))

    compared, bad, skipped = 0, [], []
    for name in sorted(set(hdr) & set(gen_defs)):
        hv = {eval_int(v) for v, _, _ in hdr[name]} - {None}
        rv = {eval_int(v) for v, _, _ in gen_defs[name]} - {None}
        if not hv or not rv:
            skipped.append(name)
            continue
        compared += 1
        MASK = (1 << 64) - 1
        if not ({v & MASK for v in hv} & {v & MASK for v in rv}):
            bad.append((name, hdr[name], gen_defs[name]))
    print("  C 头 <-> 生成物：可比 %d 项，跳过（含符号名/表达式）%d 项" % (compared, len(skipped)))
    for name, h, r in bad:
        print("  FAIL %s" % name)
        for v, p, i in h:
            print("        H %-30s %s:%d" % (v[:30], p, i))
        for v, p, i in r:
            print("        R %-30s %s:%d" % (v[:30], p, i))
    return ok and not bad


# ---------- 4. 系统路径 ----------
#
# **2026-10-14 起改为「生成 + 接线检查」**（与 1/2/5 类同一改法）。完整路径的唯一事实源
# 是 tools/abi/constants.json 的 paths 节：用户态取整串，内核 devfs 取**末段**
# （段名是完整路径的派生量，写第二遍就多一个可漂移处）。故本类改查**接线**。

PATH_WIRING = (
    ("console 实例节点目录（内核段名）", "kernel/crates/vfs/src/devfs.rs",
     r"root\.add_child\(crate::abi_generated::CONSOLES_DIR_NAME, "),
    ("console 兼容别名（内核段名）", "kernel/crates/vfs/src/devfs.rs",
     r"root\.add_child\(crate::abi_generated::CONSOLE_NODE_NAME, "),
    ("console 兼容别名（用户态整串）", "libsys/src/event.rs",
     r"pub const CONSOLE_PATH: &str = crate::abi_generated::CONSOLE_PATH;"),
    ("console 实例节点目录（用户态整串）", "libsys/src/event.rs",
     r"pub const CONSOLES_DIR_PREFIX: &str = crate::abi_generated::CONSOLES_DIR_PREFIX;"),
    # 引用方契约（保留）：init/login 必须继续引用 libsys 的前缀，不许改回字面量。
    ("console 用户态前缀的引用方", "init/src/main.rs", r"libsys::CONSOLES_DIR_PREFIX"),
    ("console 用户态前缀的引用方", "login/src/main.rs", r"libsys::CONSOLES_DIR_PREFIX"),
)

# 这些文件里**不得**再写死路径（测试里的硬编码不算——那是独立核对，故意不跟随生成物）。
PATH_HARDCODED = (
    ("kernel/crates/vfs/src/devfs.rs", r'root\.add_child\("(?:console|consoles)"'),
    ("libsys/src/event.rs", r'pub const (?:CONSOLE_PATH|CONSOLES_DIR_PREFIX): &str = "'),
)


def check_path_contracts():
    ok = True
    print("[abi-mirror] 系统路径：单一事实源 %s，%d 个站点" % (ABI_JSON, len(PATH_WIRING)))
    for concept, rel, pat in PATH_WIRING:
        if not re.search(pat, read(rel)):
            print("  FAIL %s：%s 里没有引用生成物（应匹配 %s）" % (concept, rel, pat))
            ok = False
    for rel, pat in PATH_HARDCODED:
        m = re.search(pat, read(rel))
        if m:
            print("  FAIL %s 里仍有写死的路径：%s" % (rel, m.group(0)))
            ok = False
    if ok:
        print("  OK   %d 个站点全部引用生成物，且无写死路径" % len(PATH_WIRING))
    return ok


# ---------- 5. 跨 crate 数值 ----------
#
# **2026-10-14 起改为「生成 + 接线检查」**（与第 1、2 类同一改法）。此前这些数值在
# 三四个仓库各写一份、本类比对；现在唯一事实源是 tools/abi/constants.json，
# 各侧由 tools/abi/generate.py 生成。故本类改查**接线**：每个站点必须引用
# crate::abi_generated::*，且不得再写死数字。
#
# 覆盖面：页大小、路径上限、名字上限、管道块、flock 三个命令字（kernel 与 libsys 两侧）、
# 以及 libc 的 getpagesize/pathconf 四个出口。

VALUE_WIRING = (
    ("页大小", "kernel/crates/vfs/src/page_cache.rs",
     r"pub const PAGE_SIZE: usize = crate::abi_generated::PAGE_SIZE;"),
    ("路径上限", "kernel/crates/kernel/src/syscall.rs",
     r"const MAX_USER_PATH_BYTES: usize = crate::abi_generated::PATH_MAX;"),
    ("名字上限", "kernel/crates/vfs/src/mount.rs",
     r"pub const MAX_NAME_BYTES: usize = crate::abi_generated::NAME_MAX;"),
    ("管道块", "kernel/crates/ipc/src/lib.rs",
     r"pub const PIPE_CAPACITY: usize = crate::abi_generated::PIPE_BUF;"),
    ("flock SHARED（内核）", "kernel/crates/kernel/src/syscall.rs",
     r"pub const FLOCK_CMD_SHARED: u64 = crate::abi_generated::FLOCK_CMD_SHARED;"),
    ("flock EXCLUSIVE（内核）", "kernel/crates/kernel/src/syscall.rs",
     r"pub const FLOCK_CMD_EXCLUSIVE: u64 = crate::abi_generated::FLOCK_CMD_EXCLUSIVE;"),
    ("flock UNLOCK（内核）", "kernel/crates/kernel/src/syscall.rs",
     r"pub const FLOCK_CMD_UNLOCK: u64 = crate::abi_generated::FLOCK_CMD_UNLOCK;"),
    ("flock SHARED（用户态）", "libsys/src/nr.rs",
     r"pub const FLOCK_CMD_SHARED: u64 = crate::abi_generated::FLOCK_CMD_SHARED;"),
    ("flock EXCLUSIVE（用户态）", "libsys/src/nr.rs",
     r"pub const FLOCK_CMD_EXCLUSIVE: u64 = crate::abi_generated::FLOCK_CMD_EXCLUSIVE;"),
    ("flock UNLOCK（用户态）", "libsys/src/nr.rs",
     r"pub const FLOCK_CMD_UNLOCK: u64 = crate::abi_generated::FLOCK_CMD_UNLOCK;"),
    ("getpagesize", "libc/src/unistd.rs", r"crate::abi_generated::PAGE_SIZE"),
    ("_PC_PATH_MAX", "libc/src/unistd.rs", r"_PC_PATH_MAX => crate::abi_generated::PATH_MAX,"),
    ("_PC_NAME_MAX", "libc/src/unistd.rs", r"_PC_NAME_MAX => crate::abi_generated::NAME_MAX,"),
    ("_PC_PIPE_BUF", "libc/src/unistd.rs", r"_PC_PIPE_BUF => crate::abi_generated::PIPE_BUF,"),
)

# 这些常量**不得**再写死数字（写死即绕过生成物）。
VALUE_HARDCODED = (
    ("kernel/crates/kernel/src/syscall.rs", r"const MAX_USER_PATH_BYTES: usize = \d+;"),
    ("kernel/crates/vfs/src/page_cache.rs", r"pub const PAGE_SIZE: usize = \d+;"),
    ("kernel/crates/vfs/src/mount.rs", r"pub const MAX_NAME_BYTES: usize = \d+;"),
    ("kernel/crates/ipc/src/lib.rs", r"pub const PIPE_CAPACITY: usize = \d+;"),
    ("kernel/crates/kernel/src/syscall.rs", r"pub const FLOCK_CMD_[A-Z]+: u64 = \d+;"),
    ("libsys/src/nr.rs", r"pub const FLOCK_CMD_[A-Z]+: u64 = \d+;"),
    ("libc/src/unistd.rs", r"_PC_(?:PATH_MAX|NAME_MAX|PIPE_BUF) => -?\d+,"),
)


def check_value_mirrors():
    ok = True
    print("[abi-mirror] 跨 crate 数值：单一事实源 %s，%d 个站点" % (ABI_JSON, len(VALUE_WIRING)))
    for concept, rel, pat in VALUE_WIRING:
        if not re.search(pat, read(rel)):
            print("  FAIL %s：%s 里没有引用生成物（应匹配 %s）" % (concept, rel, pat))
            ok = False
    for rel, pat in VALUE_HARDCODED:
        m = re.search(pat, read(rel))
        if m:
            print("  FAIL %s 里仍有写死的数值：%s" % (rel, m.group(0)))
            ok = False
    if ok:
        print("  OK   %d 个站点全部引用生成物，且无写死数值" % len(VALUE_WIRING))
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


# ---------- 7. 单 token 契约 ----------
#
# **2026-10-14 起改为「生成 + 接线检查」**（与 1/2/4/5 类同一改法）。卷标 BORUIX_DATA
# 与 3p 子目录名此前在 tools（2 个文件）/ shell / init / tcc 各写一份，由本类比对；
# 现在唯一事实源是 tools/abi/constants.json 的 tokens 节，各侧由 generate.py 生成。
# 故本类改查**接线**：各站点必须引用生成物，且不得再写死。

TOKEN_WIRING = (
    ("数据盘卷标（argparse 默认）", "tools/main.py",
     r"default=generated\.DATA_VOLUME_LABEL"),
    ("数据盘卷标（disk.py 签名）", "tools/tools_build/disk.py",
     r"label=generated\.DATA_VOLUME_LABEL"),
    ("数据盘卷标（disk.py getattr）", "tools/tools_build/disk.py",
     r'getattr\(args, "label", generated\.DATA_VOLUME_LABEL\)'),
    ("3p 子目录名", "tools/tools_build/b3p.py",
     r"THIRD_PARTY_SUBDIR = generated\.THIRD_PARTY_SUBDIR"),
    ("默认 PATH", "shell/src/env.rs",
     r"pub\(crate\) const DEFAULT_PATH: &\[u8\] = crate::abi_generated::DEFAULT_PATH;"),
    ("数据盘探针", "init/src/main.rs", r"let probe = libsys::WELCOME_PROBE;"),
)

TOKEN_HARDCODED = (
    ("tools/main.py", r'default="BORUIX_DATA"'),
    ("tools/tools_build/disk.py", r'label="BORUIX_DATA"'),
    ("tools/tools_build/b3p.py", r'THIRD_PARTY_SUBDIR = "3p"'),
    ("shell/src/env.rs", r'b"/programs:/volumes/BORUIX_DATA/3p"'),
    ("init/src/main.rs", r'"/volumes/BORUIX_DATA/welcome\.txt"'),
)


def check_token_contracts():
    import json as _json
    ok = True
    with open(os.path.join(ROOT, ABI_JSON), encoding="utf-8") as fh:
        tk = _json.load(fh)["tokens"]
    third = "/volumes/%s/%s" % (tk["DATA_VOLUME_LABEL"], tk["THIRD_PARTY_SUBDIR"])
    print("[abi-mirror] 单 token 契约：单一事实源 %s（卷标 %s / 3p 子目录 %s）"
          % (ABI_JSON, tk["DATA_VOLUME_LABEL"], tk["THIRD_PARTY_SUBDIR"]))
    for concept, rel, pat in TOKEN_WIRING:
        if not re.search(pat, read(rel)):
            print("  FAIL %s：%s 里没有引用生成物（应匹配 %s）" % (concept, rel, pat))
            ok = False
    # tcc 的 config.h 是**整行生成**（前后还有大量手写说明）：直接核对它等于 JSON 派生的值。
    m = re.search(r'#define CONFIG_TCCDIR "([^"]*)"', read("tcc-on-boruix/boruix/config.h"))
    if not m or m.group(1) != third + "/tcc":
        print("  FAIL tcc 的 CONFIG_TCCDIR 与 JSON 不一致：实为 %s，应为 %s/tcc"
              % (m.group(1) if m else "缺失", third))
        ok = False
    for rel, pat in TOKEN_HARDCODED:
        mm = re.search(pat, read(rel))
        if mm:
            print("  FAIL %s 里仍有写死的 token：%s" % (rel, mm.group(0)))
            ok = False
    if ok:
        print("  OK   %d 个站点全部引用生成物；C 头的整行与 JSON 同值" % len(TOKEN_WIRING))
    return ok


# 「同一字面量只许出现一次」：S13 单点化的机械判据。
# 只数**代码行**里的出现次数（以 // 开头的注释行不计）——注释里提一句不算第二份事实。
SINGLE_LITERAL = (
    ("console 请求目录（init 内）", "init/src/main.rs", "/system/console-requests"),
    # /devices/consoles/ 的「单点字面量」检查**已撤销**：它现在由 tools/abi/constants.json
    # 生成（见第 4 类），字面量根本不该出现在手写文件里——那是 PATH_HARDCODED 的职责。
    # /system/console-requests 保留：内核只在注释里提到它，**不是**跨边界契约，
    # 它是 init 内部的单点，仍由本检查钉住"不许出现第二份"。
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


# ---------- 10. 跨边界 wire 常量（内核 <-> libsys） ----------
#
# 54 项：信号号 / `PROT_*` / `AT_*` / `EVENT_*` / `ACE_*` / syscall 动词 / 限制值。
# 此前是"两侧各手写一份 + 注释互指（S13）"。**实测 2026-10-15**：把 libsys 的
# `SIGINT` 从 2 改成 3、`EVENT_RECORD_SIZE` 从 16 改成 17、`NICE_BIAS` 从 20 改成 21，
# `generate.py` 与 `abi_mirrors_agree` **两个工具都不报** —— 注释互指不是机制。
#
# 现在值由 JSON 的 wire 段生成，本类做**接线核对**：
#   (a) 两侧生成物里必须有这个名字；
#   (b) 手写站点必须引用生成物，不得再出现字面量。

K_WIRE_GEN = os.path.join("kernel", "crates", "klib", "src", "abi_generated.rs")
L_WIRE_GEN = os.path.join("libsys", "src", "abi_generated.rs")


def check_wire_consts():
    import json as _json
    with open(os.path.join(ROOT, ABI_JSON), encoding="utf-8") as fh:
        wire = _json.load(fh)["wire"]
    names = {k: v for k, v in wire.items() if not k.startswith("_")}
    ok = True
    for rel in (K_WIRE_GEN, L_WIRE_GEN):
        txt = open(os.path.join(ROOT, rel), encoding="utf-8").read()
        missing = [n for n in sorted(names) if not re.search(r"pub const %s\s*:" % re.escape(n), txt)]
        if missing:
            print("  FAIL %s 缺 %d 项：%s" % (rel, len(missing), missing[:5]))
            ok = False
    bad = []
    for base in ("kernel/crates", "libsys/src"):
        for pp in walk(os.path.join(ROOT, base), ".rs"):
            r = os.path.relpath(pp, ROOT)
            if r.endswith("abi_generated.rs"):
                continue
            txt = open(pp, encoding="utf-8").read()
            for m in re.finditer(r"pub const ([A-Za-z_][A-Za-z0-9_]*)\s*:\s*[^=;]+?=\s*([^;]+);", txt):
                n = m.group(1)
                if n not in names:
                    continue
                if "abi_generated::" not in m.group(2):
                    bad.append((r, n, m.group(2).strip(), txt[:m.start()].count("\n") + 1))
    for r, n, v, ln in bad[:10]:
        print("  FAIL %s:%d 仍在写死 %s = %s（应引用生成物）" % (r, ln, n, v[:30]))
    if bad:
        ok = False
    print("[abi-mirror] 跨边界 wire 常量：**%d 项**两侧均引用生成物、无字面量" % len(names))
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
        ("跨边界 wire", check_wire_consts()),
    ]
    failed = [n for n, ok in results if not ok]
    if failed:
        print("[abi-mirror] FAIL：%s" % "、".join(failed))
        return 1
    print("[abi-mirror] OK：七类镜像全部一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
