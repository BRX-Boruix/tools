#!/usr/bin/env python3
"""从 tools/abi/constants.json 生成两侧的跨边界常量与映射。

## 为什么是"生成"而不是"镜像 + 门禁"

镜像 + 门禁能**发现**漂移，但发现时人还得去改第二份。生成把"第二份"变成**产物**：
人只改 JSON，两侧由机器落盘，漂移在构造上不可能。

## 生成物（勿手改）

  kernel/crates/kernel/src/abi_generated.rs    syscall 号
  kernel/crates/klib/src/abi_generated.rs      Error -> errno
  libsys/src/abi_generated.rs                  syscall 号 + errno 双向映射

两侧手写文件只保留**文档**，取值改为引用生成物；libc 的 errno 表是**超集**
（134 个 POSIX 名，其中 23 个有内核对应），故不生成，改为**核对**。

## 门禁

  python tools/abi/generate.py --check      # 不带参数即 --check

1. 三份生成物与 JSON 逐字节一致（手改生成物会被抓住）；
2. 两侧手写 domain/op 取值与 JSON 一致，且没有写死的 SYS_* 数值；
3. 两侧手写 error.rs 的 to_errno/from_errno 必须**委托**生成物，且没有残留的裸映射臂；
4. libc 的 errno.h 与 errno.rs 里，JSON 记的 23 个 C 名必须存在且同值
   （libc 的表是超集，只核对这 23 个——今天**没有任何检查**把内核的
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
L_GEN = os.path.join(ROOT, "libsys", "src", "abi_generated.rs")
K_SYSCALL_HAND = os.path.join(ROOT, "kernel", "crates", "kernel", "src", "syscall.rs")
L_NR_HAND = os.path.join(ROOT, "libsys", "src", "nr.rs")
K_ERR_HAND = os.path.join(ROOT, "kernel", "crates", "klib", "src", "error.rs")
L_ERR_HAND = os.path.join(ROOT, "libsys", "src", "error.rs")
LIBC_ERRNO_H = os.path.join(ROOT, "libc", "include", "errno.h")
LIBC_ERRNO_RS = os.path.join(ROOT, "libc", "src", "errno.rs")


def load():
    with open(JSON_PATH, encoding="utf-8") as fh:
        return json.load(fh)


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
    ("kernel:syscalls", K_SYSCALL_GEN,
     lambda doc: render_syscalls(doc, "crate::syscall::domain", "crate::syscall::op")),
    ("kernel:errors", K_KLIB_GEN, render_kernel_errno),
    ("libsys:all", L_GEN,
     lambda doc: render_syscalls(doc, "crate::nr::domain", "crate::nr::op") + render_libsys_errno(doc)),
)

HAND_FILES = (
    ("kernel:syscall.rs", K_SYSCALL_HAND, True, False),
    ("libsys:nr.rs", L_NR_HAND, True, False),
    ("kernel:klib/error.rs", K_ERR_HAND, False, True),
    ("libsys:error.rs", L_ERR_HAND, False, True),
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
            print("[abi-gen] %-16s 已写入 %s" % (label, os.path.relpath(path, ROOT)))
            continue
        cur = open(path, encoding="utf-8", newline="").read() if os.path.isfile(path) else None
        if cur != text:
            print("[abi-gen] FAIL %s：生成物与 %s 不一致 —— 跑 python tools/abi/generate.py --write"
                  % (label, SRC_REL))
            ok = False

    if a.write:
        return 0

    want = {"domain": doc["syscall_domains"], "op": doc["syscall_ops"]}
    for label, path, chk_domop, chk_errno in HAND_FILES:
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
        print("[abi-gen] OK：3 份生成物与 JSON 一致；手写 domain/op 一致；errno 映射已委托；"
              "libc 的 %d 个 errno 名与 JSON 同值（syscall %d 项 / error %d 项）"
              % (len(doc["errors"]), len(doc["syscalls"]), len(doc["errors"])))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
