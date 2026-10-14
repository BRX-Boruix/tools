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


def render_kernel_errno(doc):
    out = [HEADER.replace("@SRC@", SRC_REL), "// ---------- Error -> errno ----------\n\n"]
    out.append("pub const fn to_errno(e: crate::error::Error) -> i32 {\n    match e {\n")
    for name, e in doc["errors"].items():
        out.append("        crate::error::Error::%s => %d, // %s\n" % (name, e["errno"], e["c"]))
    out.append("    }\n}\n")
    return "".join(out)


def render_libsys_errno(doc):
    out = ["\n// ---------- Error <-> errno（双向） ----------\n\n"]
    out.append("pub const fn to_errno(e: crate::error::Error) -> i32 {\n    match e {\n")
    for name, e in doc["errors"].items():
        out.append("        crate::error::Error::%s => %d, // %s\n" % (name, e["errno"], e["c"]))
    out.append("        crate::error::Error::Unknown(e) => e,\n    }\n}\n\n")
    out.append("pub const fn from_errno(e: i32) -> crate::error::Error {\n    match e {\n")
    for name, e in doc["errors"].items():
        out.append("        %d => crate::error::Error::%s, // %s\n" % (e["errno"], name, e["c"]))
    out.append("        other => crate::error::Error::Unknown(other),\n    }\n}\n")
    return "".join(out)


GEN_FILES = (
    ("kernel:kernel", K_SYSCALL_GEN,
     lambda doc: render_syscalls(doc, "crate::syscall::domain", "crate::syscall::op")
     + render_values(doc, KERNEL_VALUES)),
    ("kernel:klib", K_KLIB_GEN, render_kernel_errno),
    ("kernel:vfs", K_VFS_GEN, lambda doc: HEADER.replace("@SRC@", SRC_REL) + render_values(doc, VFS_VALUES) + render_kernel_path_names(doc)),
    ("kernel:ipc", K_IPC_GEN, lambda doc: HEADER.replace("@SRC@", SRC_REL) + render_values(doc, IPC_VALUES)),
    ("libsys", L_GEN,
     lambda doc: render_syscalls(doc, "crate::nr::domain", "crate::nr::op")
     + render_libsys_errno(doc) + render_values(doc, LIBSYS_VALUES) + render_libsys_paths(doc)),
    ("libc", LIBC_GEN, lambda doc: HEADER.replace("@SRC@", SRC_REL)
     + "use crate::ctypes::{c_int, c_long};\n" + render_values(doc, LIBC_VALUES)),
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

    hdr = open(LIBC_ERRNO_H, encoding="utf-8").read()
    rs = open(LIBC_ERRNO_RS, encoding="utf-8").read()
    for name, e in doc["errors"].items():
        c, num = e["c"], e["errno"]
        mh = re.search(r"#\s*define\s+" + c + r"\s+(\d+)", hdr)
        mr = re.search(r"pub const " + c + r"\s*:\s*i32\s*=\s*(\d+)\s*;", rs)
        if not mh or int(mh.group(1)) != num:
            print("[abi-gen] FAIL libc/include/errno.h：%s（%s）应为 %d，实为 %s"
                  % (c, name, num, mh.group(1) if mh else "缺失"))
            ok = False
        if not mr or int(mr.group(1)) != num:
            print("[abi-gen] FAIL libc/src/errno.rs：%s（%s）应为 %d，实为 %s"
                  % (c, name, num, mr.group(1) if mr else "缺失"))
            ok = False

    if ok:
        print("[abi-gen] OK：%d 份生成物与 JSON 一致；手写 domain/op 一致；errno 映射已委托；"
              "libc 的 %d 个 errno 名同值（syscall %d / error %d / value %d）"
              % (len(GEN_FILES), len(doc["errors"]), len(doc["syscalls"]), len(doc["errors"]),
                 len(doc["values"])))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
