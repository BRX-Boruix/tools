#!/usr/bin/env python3
"""从 tools/abi/constants.json 生成两侧的跨边界常量与映射。

## 为什么是"生成"而不是"镜像 + 门禁"

镜像 + 门禁能**发现**漂移，但发现时人还得去改第二份。生成把"第二份"变成**产物**：
人只改 JSON，两侧由机器落盘，漂移在构造上不可能。

## 生成物（勿手改）

  kernel/crates/kernel/src/abi_generated.rs    syscall 号 + PATH_MAX + FLOCK_CMD_*
  kernel/crates/klib/src/abi_generated.rs      Error -> errno
  kernel/crates/vfs/src/abi_generated.rs       PAGE_SIZE / NAME_MAX
  kernel/crates/ipc/src/abi_generated.rs       PIPE_BUF
  libsys/src/abi_generated.rs                  syscall 号 + errno 双向 + FLOCK_CMD_*
  libc/src/abi_generated.rs                    PAGE_SIZE / PATH_MAX / NAME_MAX / PIPE_BUF

两侧手写文件只保留**文档**，取值改为引用生成物；libc 的 errno 表是**超集**
（134 个 POSIX 名，其中 23 个有内核对应），故不生成，改为**核对**。

## 门禁

  python tools/abi/generate.py --check      # 不带参数即 --check

1. 各份生成物与 JSON 逐字节一致（手改生成物会被抓住）；
2. 两侧手写 domain/op 取值与 JSON 一致，且没有写死的 SYS_* 数值；
3. 两侧手写 error.rs 的 to_errno/from_errno 必须**委托**生成物，且没有残留的裸映射臂；
4. libc 的 errno.h 与 errno.rs 里，JSON 记的 23 个 C 名必须存在且同值
   （libc 的表是超集，只核对这 23 个——此前**没有任何检查**把内核的
   Error::NotFound => 2 与 libc 的 #define ENOENT 2 连起来）。
"""
import argparse
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
JSON_PATH = os.path.join(HERE, "constants.json")
SRC_REL = "tools/abi/constants.json"

HEADER = """//! **自动生成，请勿手改。**
//!
//! 源：@SRC@
//! 生成：python tools/abi/generate.py
//! 门禁：python tools/abi/generate.py --check（已登记进 tools/checks/run_all.py）
//!
//! 手改本文件会被门禁发现；要改数值请改 JSON 再重新生成。

"""

K_SYSCALL_GEN = os.path.join(ROOT, "kernel", "crates", "kernel", "src", "abi_generated.rs")
K_KLIB_GEN = os.path.join(ROOT, "kernel", "crates", "klib", "src", "abi_generated.rs")
K_VFS_GEN = os.path.join(ROOT, "kernel", "crates", "vfs", "src", "abi_generated.rs")
K_IPC_GEN = os.path.join(ROOT, "kernel", "crates", "ipc", "src", "abi_generated.rs")
L_GEN = os.path.join(ROOT, "libsys", "src", "abi_generated.rs")
LIBC_GEN = os.path.join(ROOT, "libc", "src", "abi_generated.rs")
TOOLS_GEN = os.path.join(ROOT, "tools", "abi", "generated.py")
SHELL_GEN = os.path.join(ROOT, "shell", "src", "abi_generated.rs")

K_SYSCALL_HAND = os.path.join(ROOT, "kernel", "crates", "kernel", "src", "syscall.rs")
L_NR_HAND = os.path.join(ROOT, "libsys", "src", "nr.rs")
K_ERR_HAND = os.path.join(ROOT, "kernel", "crates", "klib", "src", "error.rs")
L_ERR_HAND = os.path.join(ROOT, "libsys", "src", "error.rs")
LIBC_ERRNO_H = os.path.join(ROOT, "libc", "include", "errno.h")
LIBC_ERRNO_RS = os.path.join(ROOT, "libc", "src", "errno.rs")

# 每份生成物要带哪些数值：(JSON 里的名字, 该侧 Rust 类型)
KERNEL_VALUES = (("PATH_MAX", "usize"), ("FLOCK_CMD_SHARED", "u64"),
                 ("FLOCK_CMD_EXCLUSIVE", "u64"), ("FLOCK_CMD_UNLOCK", "u64"))
VFS_VALUES = (("PAGE_SIZE", "usize"), ("NAME_MAX", "usize"))
IPC_VALUES = (("PIPE_BUF", "usize"),)
LIBSYS_VALUES = (("FLOCK_CMD_SHARED", "u64"), ("FLOCK_CMD_EXCLUSIVE", "u64"), ("FLOCK_CMD_UNLOCK", "u64"))
LIBC_VALUES = (("PAGE_SIZE", "c_int"), ("PATH_MAX", "c_long"), ("NAME_MAX", "c_long"), ("PIPE_BUF", "c_long"))


def load():
    with open(JSON_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def render_values(doc, entries):
    out = ["\n// ---------- 跨 crate 数值（同一数值只在这里写一次） ----------\n\n"]
    for name, ty in entries:
        out.append("pub const %s: %s = %d;\n" % (name, ty, doc["values"][name]))
    return "".join(out)


def token_values(doc):
    """tokens 节的取值。**只导出「系统契约」；其余留在 Python 侧。**

    三类东西必须分清：

    - **系统契约**：`PROGRAM_DIR`（`/programs`）——系统自己规定的约定路径，任何部署都一样。
      这是**唯一**生成进 Rust 的 token。
    - **Python 侧的取值**：`DATA_VOLUME_LABEL`（`mkimg` 的默认卷标）、`THIRD_PARTY_SUBDIR`
      （`3p` 子目录名）。它们描述**盘上的数据**，只供 tools 的 Python 用，**不生成进 Rust**。
    - **部署事实**（卷标的具体值、有几块盘、盘挂在哪个挂载点）：**任何地方都不编译期烧死**。
      系统运行时从 `/volumes` 的目录项读；Python 侧要用就按自己造的盘去算。
    """
    t = doc["tokens"]
    return {
        "PROGRAM_DIR": t["PROGRAM_DIR"],
        "THIRD_PARTY_SUBDIR": t["THIRD_PARTY_SUBDIR"],
        "DATA_VOLUME_LABEL": t["DATA_VOLUME_LABEL"],
    }


def render_python_tokens(doc):
    """给 tools 侧用的 Python 常量（main.py / disk.py / b3p.py 都从这里取）。"""
    v = token_values(doc)
    return (
        "# **自动生成，请勿手改。**\n"
        "# 源：tools/abi/constants.json\n"
        "# 生成：python tools/abi/generate.py\n"
        "# 门禁：python tools/abi/generate.py --check\n\n"
        'DATA_VOLUME_LABEL = "%s"\n'
        'THIRD_PARTY_SUBDIR = "%s"\n'
        'PROGRAM_DIR = "%s"\n' % (v["DATA_VOLUME_LABEL"], v["THIRD_PARTY_SUBDIR"],
                                    v["PROGRAM_DIR"])
    )


def render_libsys_tokens(doc):
    v = token_values(doc)
    out = ["\n// ---------- 系统标识 token（**只有系统契约**） ----------\n\n"]
    # 只导出 PROGRAM_DIR。卷标 / 盘数 / 3p 子目录名都是**数据**，系统不需要知道——
    # 系统对它们的全部认知是「有一块卷，挂载点 /volumes/<它自己的卷标>」，那是运行时读出来的。
    for k in ("PROGRAM_DIR",):
        out.append('pub const %s: &str = "%s";\n' % (k, v[k]))
    return "".join(out)


# shell 的默认 PATH 也不再生成：见上一条注释（改由 libsys::volume::search_path() 运行期算）。


def render_libsys_paths(doc):
    out = ["\n// ---------- 系统路径（与内核 devfs 同一事实源） ----------\n\n"]
    for name in ("CONSOLE_PATH", "CONSOLES_DIR_PREFIX"):
        out.append('pub const %s: &str = "%s";\n' % (name, doc["paths"][name]))
    return "".join(out)


def render_kernel_path_names(doc):
    """内核 devfs 是**逐段**拼的（add_child("consoles", ...)），故这里只取末段。

    取末段而不是让 JSON 再写一遍段名：段名是完整路径的**派生量**，写第二遍就多一个
    可以漂移的地方。
    """
    out = ["\n// ---------- devfs 段名（由完整路径派生，勿手改） ----------\n\n"]
    for const, key in (("CONSOLE_NODE_NAME", "CONSOLE_PATH"),
                       ("CONSOLES_DIR_NAME", "CONSOLES_DIR_PREFIX")):
        seg = doc["paths"][key].rstrip("/").rsplit("/", 1)[-1]
        out.append('pub const %s: &str = "%s";\n' % (const, seg))
    return "".join(out)


def render_syscalls(doc, dom_path, op_path):
    """生成物**引用**该侧手写的 domain/op 模块，而不是写死数字。

    为什么：写死会让 domain/op 失去唯一使用者、变成死代码，并丢掉它们的文档。
    引用之后，布局说明留在手写文件、取值由门禁与 JSON 比对钉住。
    """
    doms = doc["syscall_domains"]
    ops = doc["syscall_ops"]
    out = [HEADER.replace("@SRC@", SRC_REL), "// ---------- syscall 号 ----------\n\n"]
    for name, e in doc["syscalls"].items():
        d = e["domain"]
        o = e["op"]
        oval = ops[o] if isinstance(o, str) else int(o)
        val = doms[d] | oval
        rhs = "%s::%s" % (dom_path, d)
        rhs += " | %s::%s" % (op_path, o) if isinstance(o, str) else " | 0x%02X" % oval
        out.append("pub const %s: u32 = %s; // 0x%02X\n" % (name, rhs, val))
    return "".join(out)


def render_wire(doc):
    """跨边界 wire 常量（内核 <-> libsys）——两侧**同一事实源**。

    此前这些是"两侧各手写一份 + 注释互指"（S13 的说法），实测 2026-10-15：
    扰动 SIGINT / EVENT_RECORD_SIZE / NICE_BIAS，generate.py 与 abi_mirrors_agree
    **两个工具都不报** —— 注释互指不是机制。现由 JSON 的 wire 段生成，两侧引用。

    `1 << N` 与 `A | B` 这类形态**原样保留**（"第几位"与组合关系是有信息的，
    折成裸数字会丢掉它们）；纯整数字面量也按原样输出。
    """
    out = ["\n// ---------- 跨边界 wire 常量（内核 <-> libsys） ----------\n\n"]
    for name, e in doc["wire"].items():
        if name.startswith("_"):
            continue
        rhs = e["expr"] if "expr" in e else str(e["v"])
        out.append("pub const %s: %s = %s;\n" % (name, e["ty"], rhs))
    return "".join(out)


def render_kernel_errno(doc):
    out = [HEADER.replace("@SRC@", SRC_REL), "// ---------- Error -> errno ----------\n\n"]
    out.append("pub const fn to_errno(e: crate::error::Error) -> i32 {\n    match e {\n")
    for name, e in doc["errors"].items():
        out.append("        crate::error::Error::%s => %d, // %s\n"
                   % (name, doc["errno_table"][e["c"]], e["c"]))
    out.append("    }\n}\n")
    return "".join(out)


def render_libsys_errno(doc):
    out = ["\n// ---------- Error <-> errno（双向） ----------\n\n"]
    out.append("pub const fn to_errno(e: crate::error::Error) -> i32 {\n    match e {\n")
    for name, e in doc["errors"].items():
        out.append("        crate::error::Error::%s => %d, // %s\n"
                   % (name, doc["errno_table"][e["c"]], e["c"]))
    out.append("        crate::error::Error::Unknown(e) => e,\n    }\n}\n\n")
    out.append("pub const fn from_errno(e: i32) -> crate::error::Error {\n    match e {\n")
    for name, e in doc["errors"].items():
        out.append("        %d => crate::error::Error::%s, // %s\n"
                   % (doc["errno_table"][e["c"]], name, e["c"]))
    out.append("        other => crate::error::Error::Unknown(other),\n    }\n}\n")
    return "".join(out)


LIBC_INCLUDE = os.path.join(ROOT, "libc", "include")


def fmt_num(v, fmt, lang):
    """按原书写形态渲染整数：C 的八进制是 `0NNN`，Rust 是 `0oNNN`（其余同形）。"""
    if fmt == "hex":
        return "0x%X" % v
    if fmt == "oct":
        return ("0o%o" if lang == "rust" else "0%o") % v
    return str(v)


def render_c_const(e):
    if "c" in e:
        return e["c"]
    if "expr" in e:
        return e["expr"]
    return fmt_num(e["v"], e["fmt"], "c")


def render_rust_const(e):
    if "rust" in e:
        return e["rust"]
    if "expr" in e:
        return e["expr"]
    return fmt_num(e["v"], e["fmt"], "rust")


def libc_type_imports(doc):
    """libc 生成物需要的 ctypes 导入——**按 c_consts 实际用到的类型算**，不写死。

    写死会随新增常量失效（本轮实测：clock_t / c_uchar / mode_t 三个类型漏了，
    编译直接报 cannot find type）。
    """
    skip = {"usize", "u32", "u64", "i32", "i64", "isize", "mut", "const"}
    # clock_t 不在 ctypes 里（它在 crate::time）——实测漏了它编译直接报 unresolved import。
    elsewhere = {"clock_t": "crate::time"}
    types = {"c_int", "c_long"}
    extra = {}
    for e in doc["c_consts"].values():
        for m in re.finditer(r"\b([a-z_][a-z0-9_]*)\b", e["ty"]):
            n = m.group(1)
            if n in skip:
                continue
            if n in elsewhere:
                extra.setdefault(elsewhere[n], set()).add(n)
            else:
                types.add(n)
    out = "use crate::ctypes::{%s};\n" % ", ".join(sorted(types))
    for mod, ns in sorted(extra.items()):
        out += "use %s::{%s};\n" % (mod, ", ".join(sorted(ns)))
    return out


def render_libc_c_consts(doc):
    """C 头 <-> Rust 常量（errno 之外）——两侧同一事实源。

    三种形态，逐条如实：
      · `v` + `fmt`  纯字面量（保留原书写形态：十进制 / 十六进制 / 八进制）；
      · `expr`             语言中立的表达式（如 `1 << 4`、别名 `FNM_PATHNAME`）——
                                 **不**把它折成裸数字，那会丢掉"第几位"与别名意图；
      · `c` + `rust`     两种语言的形态**本就不同**（指针/函数指针强制转换、
                                `i32::MAX`）——JSON 里同时记两种形态，一处改两处生效。
    """
    out = ["\n// ---------- C 头 <-> Rust 常量（errno 之外） ----------\n\n"]
    for name, e in doc["c_consts"].items():
        out.append("pub const %s: %s = %s;\n" % (name, e["ty"], render_rust_const(e)))
    return "".join(out)


def render_libc_errno(doc):
    """libc 的 134 个 errno 常量（C 头与 Rust 两侧同一事实源）。

    **方向说明**：这一族的"事实源"是 tools/abi/constants.json 的 errno_table，
    由它同时产出 errno.h 的 #define 行（整行重写）与 Rust 常量。
    """
    out = ["\n// ---------- errno（与 <errno.h> 同一事实源） ----------\n\n"]
    for name, val in doc["errno_table"].items():
        out.append("pub const %s: i32 = %d;\n" % (name, val))
    return "".join(out)


# `confstr(_CS_PATH)` 与 shell 的默认 PATH **不再由生成器产出**：它们是**部署事实**
# （卷标 / 有几块盘 / 3p 在哪块盘上），改由 libsys::volume::search_path() 在运行期从
# `/volumes` 的真实挂载点算出。此处保留注释是为了让后来者知道「为什么这里空了」。


# **整行生成**：C 头文件里的一行由生成器重写（`#define` 前后还有大量手写说明，
# 不适合整文件生成）。判据：该行必须与生成结果**逐字节相同**。
#
# **当前为空**：原先这里生成 tcc 的 `CONFIG_TCCDIR`（= `/volumes/<卷标>/3p/tcc`）。
# 那是**盘上的位置**，属于数据，不该由生成器写死；tcc 改为在启动时按 `argv[0]` 推导自己的
# 目录（见 tcc-on-boruix 的 UPSTREAM-PATCHES）。生成器不再管它。
LINE_TARGETS = ()


# **多行目标**：一个文件里的一批 #define 的值由生成器同步（文件名 + JSON 里的表名）。
# 与 LINE_TARGETS 同一理由：头文件前后有大量手写说明，只改**值**，不动结构。
DEFINE_TARGETS = (
    ("libc:errno.h", os.path.join(ROOT, "libc", "include", "errno.h"), "errno_table"),
)


def sync_defines(path, table):
    """返回 (新文本, [(名字, 现值, 期望值)])——现值与期望值不同的都记下来。"""
    txt = open(path, encoding="utf-8", newline="").read()
    bad = []
    for name, val in table.items():
        m = re.search(r"(#\s*define\s+" + name + r"\s+)(-?\d+)([^\n]*)", txt)
        if not m:
            bad.append((name, None, val))
            continue
        if int(m.group(2)) != val:
            bad.append((name, m.group(2), val))
            txt = txt[:m.start()] + m.group(1) + str(val) + m.group(3) + txt[m.end():]
    return txt, bad


def eval_c_text(s):
    """尽力求值一个 C 整型字面量/表达式；求不出返回 None（指针/强制转换形态）。"""
    s = s.strip()
    while s.startswith("(") and s.endswith(")"):
        s = s[1:-1].strip()
    if re.fullmatch(r"0[xX][0-9A-Fa-f]+[uUlL]*", s):
        return int(re.sub(r"[uUlL]+$", "", s), 16)
    if re.fullmatch(r"0[0-7]+[uUlL]*", s) and len(s) > 1:
        return int(re.sub(r"[uUlL]+$", "", s), 8)
    if re.fullmatch(r"-?\d+[uUlL]*", s):
        return int(re.sub(r"[uUlL]+$", "", s))
    if "<<" in s and re.fullmatch(r"[\d\s()<>|&+*\-x]+", s):
        try:
            return eval(s, {"__builtins__": {}}, {})
        except Exception:
            return None
    return None


def sync_c_consts(doc, write):
    """把 libc 各头文件里 #define NAME <值> 的**值**同步成 c_consts 渲染出的形态。

    只动值（连同它前后的空白），**保留尾随注释**——头文件是公开的、有注释的 C ABI 面。
    同名多处定义（如 SEEK_SET 在 stdio.h 与 unistd.h 各一次）全部同步。
    """
    table = doc["c_consts"]
    bad = []
    for dp, dn, fns in os.walk(LIBC_INCLUDE):
        for fn in sorted(fns):
            if not fn.endswith(".h"):
                continue
            path = os.path.join(dp, fn)
            lines = open(path, encoding="utf-8", newline="").read().split("\n")
            changed = False
            for i, line in enumerate(lines):
                m = re.match(r"(\s*#\s*define\s+)([A-Za-z_][A-Za-z0-9_]*)(\s+)(.*)$", line)
                if not m:
                    continue
                name = m.group(2)
                if name not in table:
                    continue
                rest = m.group(4)
                j = rest.find("/*")
                val = (rest[:j] if j >= 0 else rest).strip()
                want = render_c_const(table[name])
                # **值相等就不动**：头文件里的 0040000 与渲染出的 040000 是同一个值，
                # 强行"规范化"只是给公开头文件制造无意义 diff（本仓的 S_IF* 就属这类）。
                if val != want:
                    cv, wv = eval_c_text(val), eval_c_text(want)
                    if cv is not None and cv == wv:
                        continue
                    bad.append((os.path.relpath(path, ROOT), name, val, want))
                    if write:
                        tail = rest[rest.find(val) + len(val):] if j >= 0 else ""
                        lines[i] = m.group(1) + name + m.group(3) + want + tail
                        changed = True
            if write and changed:
                open(path, "w", encoding="utf-8", newline="").write("\n".join(lines))
    return bad


GEN_FILES = (
    ("kernel:kernel", K_SYSCALL_GEN,
     lambda doc: render_syscalls(doc, "crate::syscall::domain", "crate::syscall::op")
     + render_values(doc, KERNEL_VALUES)),
    ("kernel:klib", K_KLIB_GEN, lambda doc: render_kernel_errno(doc) + render_wire(doc)),
    ("kernel:vfs", K_VFS_GEN, lambda doc: HEADER.replace("@SRC@", SRC_REL) + render_values(doc, VFS_VALUES) + render_kernel_path_names(doc)),
    ("kernel:ipc", K_IPC_GEN, lambda doc: HEADER.replace("@SRC@", SRC_REL) + render_values(doc, IPC_VALUES)),
    ("libsys", L_GEN,
     lambda doc: render_syscalls(doc, "crate::nr::domain", "crate::nr::op")
     + render_libsys_errno(doc) + render_values(doc, LIBSYS_VALUES)
     + render_libsys_paths(doc) + render_libsys_tokens(doc) + render_wire(doc)),
    ("libc", LIBC_GEN, lambda doc: HEADER.replace("@SRC@", SRC_REL)
     + libc_type_imports(doc) + render_values(doc, LIBC_VALUES)
     + render_libc_errno(doc) + render_libc_c_consts(doc)),
    ("tools:generated.py", TOOLS_GEN, render_python_tokens),
)

# (标签, 手写文件, 是否检查 domain/op, 是否检查 errno 委托, 是否检查数值引用)
HAND_FILES = (
    ("kernel:syscall.rs", K_SYSCALL_HAND, True, False, ("MAX_USER_PATH_BYTES", "FLOCK_CMD_")),
    ("libsys:nr.rs", L_NR_HAND, True, False, ("FLOCK_CMD_",)),
    ("kernel:klib/error.rs", K_ERR_HAND, False, True, ()),
    ("libsys:error.rs", L_ERR_HAND, False, True, ()),
)


# 这些常量**不得**再写死数字（写死即绕过生成物）。与 abi_mirrors_agree 的第 5 类
# 用同一份清单——变异测试发现：只查 syscall.rs / nr.rs 会漏掉 vfs/ipc/libc 三个站点
# （把 PAGE_SIZE 写回 4096 时 generate.py 报 OK 而门禁报 FAIL，两个工具结论不一致）。
VALUE_HARDCODED = (
    ("kernel/crates/kernel/src/syscall.rs", r"const MAX_USER_PATH_BYTES: usize = \d+;"),
    ("kernel/crates/vfs/src/page_cache.rs", r"pub const PAGE_SIZE: usize = \d+;"),
    ("kernel/crates/vfs/src/mount.rs", r"pub const MAX_NAME_BYTES: usize = \d+;"),
    ("kernel/crates/ipc/src/lib.rs", r"pub const PIPE_CAPACITY: usize = \d+;"),
    ("kernel/crates/kernel/src/syscall.rs", r"pub const FLOCK_CMD_[A-Z]+: u64 = \d+;"),
    ("libsys/src/nr.rs", r"pub const FLOCK_CMD_[A-Z]+: u64 = \d+;"),
    ("libc/src/unistd.rs", r"_PC_(?:PATH_MAX|NAME_MAX|PIPE_BUF) => -?\d+,"),
    ("libc/src/unistd.rs", r"fn getpagesize\(\) -> c_int \{\s*\d+"),
    # 路径：两侧都不得再写死（测试里的硬编码**不算**——那是独立核对，故意不跟随）
    ("libsys/src/event.rs", r'pub const (?:CONSOLE_PATH|CONSOLES_DIR_PREFIX): &str = "'),
    ("kernel/crates/vfs/src/devfs.rs", r'root\.add_child\("(?:console|consoles)"'),
    # token（卷标 / 3p 子目录 / 由它们派生的路径）：各站点都不得再写死
    ("tools/main.py", r'default="BORUIX_DATA"'),
    ("tools/tools_build/disk.py", r'label="BORUIX_DATA"'),
    ("tools/tools_build/disk.py", r'getattr\(args, "label", "BORUIX_DATA"\)'),
    ("tools/tools_build/b3p.py", r'THIRD_PARTY_SUBDIR = "3p"'),
    ("shell/src/env.rs", r'b"/programs:/volumes/BORUIX_DATA/3p"'),
    ("init/src/main.rs", r'"/volumes/BORUIX_DATA/welcome\.txt"'),
    # libc 的 errno：134 个常量现在由 errno_table 生成，errno.rs 不得再写死
    ("libc/src/errno.rs", r"pub const E[A-Z0-9_]+: i32 = \d+;"),
)


def parse_handwritten_domop(path):
    txt = open(path, encoding="utf-8").read()
    out = {}
    for modname in ("domain", "op"):
        m = re.search(r"pub mod " + modname + r"\s*\{(.*?)\n\}", txt, re.S)
        if not m:
            out[modname] = None
            continue
        vals = {}
        for mm in re.finditer(r"pub const ([A-Z_][A-Z0-9_]*)\s*:\s*u32\s*=\s*(0x[0-9A-Fa-f_]+|\d+)\s*;", m.group(1)):
            vals[mm.group(1)] = int(mm.group(2).replace("_", ""), 0)
        out[modname] = vals
    return out


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=False)
    g.add_argument("--write", action="store_true", help="落盘生成物")
    g.add_argument("--check", action="store_true", help="只检查，不落盘（**不带参数时的默认**）")
    a = ap.parse_args()
    if not a.write:
        a.check = True

    doc = load()
    ok = True

    for label, path, render in GEN_FILES:
        text = render(doc)
        if a.write:
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
            print("[abi-gen] %-14s 已写入 %s" % (label, os.path.relpath(path, ROOT)))
            continue
        cur = open(path, encoding="utf-8", newline="").read() if os.path.isfile(path) else None
        if cur != text:
            print("[abi-gen] FAIL %s：生成物与 %s 不一致 —— 跑 python tools/abi/generate.py --write"
                  % (label, SRC_REL))
            ok = False

    # 整行目标（C 头里的一行）
    for label, path, pat, render in LINE_TARGETS:
        txt = open(path, encoding="utf-8", newline="").read()
        want = render(doc)
        m = re.search(pat, txt)
        if a.write:
            if not m:
                print("[abi-gen] FAIL %s：在 %s 里找不到可重写的行（正则 %s）" % (label, path, pat))
                ok = False
            elif m.group(0) != want:
                open(path, "w", encoding="utf-8", newline="").write(
                    txt[:m.start()] + want + txt[m.end():])
                print("[abi-gen] %-14s 已重写 %s" % (label, os.path.relpath(path, ROOT)))
        else:
            if not m:
                print("[abi-gen] FAIL %s：%s 里找不到该行（正则 %s）" % (label, path, pat))
                ok = False
            elif m.group(0) != want:
                print("[abi-gen] FAIL %s：%s 实为 %r，应为 %r"
                      % (label, path, m.group(0), want))
                ok = False

    # 多行目标（头文件里的一批 #define 值）
    for label, path, table in DEFINE_TARGETS:
        txt, bad = sync_defines(path, doc[table])
        if a.write:
            if bad:
                open(path, "w", encoding="utf-8", newline="").write(txt)
                print("[abi-gen] %-14s 同步 %d 处 %s" % (label, len(bad), os.path.relpath(path, ROOT)))
        else:
            for name, cur, want in bad:
                print("[abi-gen] FAIL %s：%s 实为 %s，应为 %s" % (label, name, cur, want))
                ok = False

    # 手写 libc 源里**不得**再定义已生成的常量（生成物自身与测试模块除外）。
    # 与 abi_mirrors_agree 第 3 类的"泄漏"检查同一判据——两个工具必须结论一致
    # （第八阶段踩过：两个工具清单不一致时，只跑一个会得出"没问题"）。
    generated = set(doc["errno_table"]) | set(doc["c_consts"])
    for dp, dn, fns in os.walk(os.path.join(ROOT, "libc", "src")):
        for fn in sorted(fns):
            if not fn.endswith(".rs") or fn == "abi_generated.rs":
                continue
            path = os.path.join(dp, fn)
            txt = open(path, encoding="utf-8").read()
            for m in re.finditer(r"(?:pub\s+)?const ([A-Za-z_][A-Za-z0-9_]*)\s*:", txt):
                if m.group(1) not in generated:
                    continue
                pre = txt[:m.start()]
                if pre.rfind("#[cfg(test)]") > pre.rfind("\n}"):
                    continue
                print("[abi-gen] FAIL %s 里仍在定义已生成的常量 %s（应改为 use crate::abi_generated::%s）"
                      % (os.path.relpath(path, ROOT), m.group(1), m.group(1)))
                ok = False

    # 跨边界 wire 常量：手写站点必须引用生成物，不得再出现字面量。
    # 与 abi_mirrors_agree 第 10 类**同一判据**——两个工具必须结论一致
    # （第八阶段踩过：两个工具清单不一致时，只跑一个会得出"没问题"）。
    # 实测价值：本检查刚上线就抓到一处**第三份拷贝**
    # （kernel/crates/vfs/src/stream.rs 的 EVENT_RECORD_SIZE = 16）。
    wire_names = {k for k in doc["wire"] if not k.startswith("_")}
    for base in ("kernel/crates", "libsys/src"):
        for dp, dn, fns in os.walk(os.path.join(ROOT, base)):
            dn[:] = [x for x in dn if x not in (".git", "target")]
            for fn in sorted(fns):
                if not fn.endswith(".rs") or fn == "abi_generated.rs":
                    continue
                path = os.path.join(dp, fn)
                txt = open(path, encoding="utf-8").read()
                for m in re.finditer(r"pub const ([A-Za-z_][A-Za-z0-9_]*)\s*:\s*[^=;]+?=\s*([^;]+);", txt):
                    if m.group(1) in wire_names and "abi_generated::" not in m.group(2):
                        print("[abi-gen] FAIL %s:%d 仍在写死 wire 常量 %s = %s（应引用生成物）"
                              % (os.path.relpath(path, ROOT), txt[:m.start()].count("\n") + 1,
                                 m.group(1), m.group(2).strip()[:30]))
                        ok = False

    # C 头里 c_consts 的值
    bad = sync_c_consts(doc, a.write)
    if a.write:
        if bad:
            print("[abi-gen] libc 头文件：同步 %d 处 #define 值" % len(bad))
    else:
        for rel, name, cur, want in bad:
            print("[abi-gen] FAIL %s：%s 实为 %r，应为 %r" % (rel, name, cur, want))
            ok = False

    if a.write:
        return 0

    want = {"domain": doc["syscall_domains"], "op": doc["syscall_ops"]}
    for label, path, chk_domop, chk_errno, val_prefixes in HAND_FILES:
        txt = open(path, encoding="utf-8").read()
        if chk_domop:
            hw = parse_handwritten_domop(path)
            for modname in ("domain", "op"):
                if hw[modname] is None:
                    print("[abi-gen] FAIL %s：找不到 pub mod %s（本检查需要它仍在手写文件里）" % (label, modname))
                    ok = False
                elif hw[modname] != want[modname]:
                    diff = sorted(set(hw[modname].items()) ^ set(want[modname].items()))
                    print("[abi-gen] FAIL %s：%s 与 JSON 不一致：%s" % (label, modname, diff))
                    ok = False
            hard = [m.group(1) for m in re.finditer(
                r"pub const (SYS_[A-Z0-9_]+): u32 = (?!crate::abi_generated::)[^;]+;", txt)]
            if hard:
                print("[abi-gen] FAIL %s：还有写死的 SYS_* 数值 %s" % (label, hard[:5]))
                ok = False
        if chk_errno:
            for fn in ("to_errno", "from_errno"):
                body = re.search(r"fn " + fn + r"\([^)]*\)[^{]*\{(.*?)\n    \}", txt, re.S)
                if body is None:
                    continue
                if "crate::abi_generated::" + fn not in body.group(1):
                    print("[abi-gen] FAIL %s：%s 必须委托 crate::abi_generated::%s（不要手写映射）"
                          % (label, fn, fn))
                    ok = False
            arms = re.findall(r"Error::[A-Za-z_][A-Za-z0-9_]*\s*=>\s*-?\d+\s*,", txt)
            if arms:
                print("[abi-gen] FAIL %s：还残留 %d 条裸映射臂 %s" % (label, len(arms), arms[:3]))
                ok = False
        for pre in val_prefixes:
            hard = [m.group(1) for m in re.finditer(
                r"pub const (" + pre + r"[A-Z0-9_]*)\s*:\s*(?:u64|usize)\s*=\s*(?!crate::abi_generated::)\d+\s*;", txt)]
            if hard:
                print("[abi-gen] FAIL %s：数值常量还写死在手写文件里：%s" % (label, hard))
                ok = False

    for rel, pat in VALUE_HARDCODED:
        m = re.search(pat, open(os.path.join(ROOT, rel), encoding="utf-8").read())
        if m:
            print("[abi-gen] FAIL %s 里仍有写死的数值：%s" % (rel, m.group(0)))
            ok = False

    # 注：libc 的 errno.h / errno.rs 与 errno_table 的一致性**已由上面两条覆盖**——
    #   · errno.h 的 134 个 #define 值由 DEFINE_TARGETS 逐行核对；
    #   · errno.rs 的常量由 render_libc_errno 生成（生成物新鲜度由 GEN_FILES 核对）。
    # 原先那段"kernel Error <-> libc ENOENT"的交叉核对因此成为**结构性成立**，
    # 不再是两条独立手写映射的巧合。

    if ok:
        print("[abi-gen] OK：%d 份生成物与 JSON 一致；手写 domain/op 一致；errno 映射已委托；"
              "libc 的 %d 个 errno 名同值（syscall %d / error %d / value %d）"
              % (len(GEN_FILES), len(doc["errors"]), len(doc["syscalls"]), len(doc["errors"]),
                 len(doc["values"])))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
