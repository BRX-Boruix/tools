#!/usr/bin/env python3
"""从 tools/abi/constants.json 生成两侧的 syscall 号常量。

## 为什么是"生成"而不是"镜像 + 门禁"

镜像 + 门禁（本项目此前的做法）能**发现**漂移，但发现时人还得去改第二份。
生成把"第二份"变成**产物**：人只改 JSON，两侧由机器落盘，漂移在构造上不可能。

## 生成物（勿手改）

  kernel/crates/kernel/src/abi_generated.rs
  libsys/src/abi_generated.rs

两侧手写文件只保留**每个系统调用的长文档**，数值改为引用生成物：

  pub const SYS_STREAM_CREATE: u32 = crate::abi_generated::SYS_STREAM_CREATE;

## 门禁

  python tools/abi/generate.py --check

检查三件事：
  1. 两侧生成物与 JSON **逐字节**一致（手改生成物会被抓住）；
  2. 两侧手写文件里的 domain/op 模块取值与 JSON 一致（那两处仍手写，因为它们的
     文档是 ABI 布局的说明；数值由本检查钉住）；
  3. 两侧手写文件里**不存在**写死的 SYS_* 数值（不许绕过生成物）。

退出码 0 = 一致；1 = 有漂移（并打印该改哪儿）。
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

# 每侧：side、生成物路径、手写文件路径、该侧 domain/op 模块的路径（生成物引用它们）。
SIDES = (
    ("kernel", os.path.join(ROOT, "kernel", "crates", "kernel", "src", "abi_generated.rs"),
     os.path.join(ROOT, "kernel", "crates", "kernel", "src", "syscall.rs"),
     "crate::syscall::domain", "crate::syscall::op"),
    ("libsys", os.path.join(ROOT, "libsys", "src", "abi_generated.rs"),
     os.path.join(ROOT, "libsys", "src", "nr.rs"),
     "crate::nr::domain", "crate::nr::op"),
)

HEADER = """//! **自动生成，请勿手改。**
//!
//! 源：@SRC@
//! 生成：python tools/abi/generate.py
//! 门禁：python tools/abi/generate.py --check（已登记进 tools/checks/run_all.py）
//!
//! 手改本文件会被门禁发现；要改数值请改 JSON 再重新生成。

"""


def load():
    with open(JSON_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def render(doc, dom_path, op_path):
    """生成物**引用**该侧手写的 domain/op 模块，而不是写死数字。

    为什么这样而不是写死字面量：写死会让 domain/op 两个模块失去唯一使用者、
    变成死代码（并丢掉它们的文档）。改为引用后，两侧的 ABI 布局说明留在手写文件里，
    而**取值**由本检查与 JSON 比对钉住——文档与数值各归其位，且都在门禁之内。
    行尾注释给出解析后的数值，便于人眼核对。
    """
    doms = doc["syscall_domains"]
    ops = doc["syscall_ops"]
    out = [HEADER.replace("@SRC@", "tools/abi/constants.json")]
    for name, e in doc["syscalls"].items():
        d = e["domain"]
        o = e["op"]
        oval = ops[o] if isinstance(o, str) else int(o)
        val = doms[d] | oval
        rhs = "%s::%s" % (dom_path, d)
        rhs += " | %s::%s" % (op_path, o) if isinstance(o, str) else " | 0x%02X" % oval
        out.append("pub const %s: u32 = %s; // 0x%02X\n" % (name, rhs, val))
    return "".join(out)


def parse_handwritten_domop(path):
    """从手写文件里解析 domain/op 模块的取值（那两处仍手写，由本检查钉住）。"""
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


def parse_handwritten_values(path):
    """手写文件里**写死**的 SYS_* 数值（应当一个都没有）。"""
    txt = open(path, encoding="utf-8").read()
    bad = []
    for mm in re.finditer(r"pub const (SYS_[A-Z0-9_]+)\s*:\s*u32\s*=\s*(0x[0-9A-Fa-f_]+|\d+)\s*;", txt):
        bad.append((mm.group(1), mm.group(2)))
    return bad


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=False)
    g.add_argument("--write", action="store_true", help="落盘生成物")
    g.add_argument("--check", action="store_true", help="只检查，不落盘（**不带参数时的默认**，便于登记进 run_all）")
    a = ap.parse_args()
    if not a.write:
        a.check = True

    doc = load()
    ok = True

    for side, gen_path, hand_path, dom_path, op_path in SIDES:
        text = render(doc, dom_path, op_path)
        if a.write:
            with open(gen_path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
            print("[abi-gen] %-7s 已写入 %s" % (side, os.path.relpath(gen_path, ROOT)))
            continue
        cur = open(gen_path, encoding="utf-8", newline="").read() if os.path.isfile(gen_path) else None
        if cur != text:
            print("[abi-gen] FAIL %s：生成物与 %s 不一致 —— 跑 python tools/abi/generate.py --write"
                  % (side, "tools/abi/constants.json"))
            ok = False
        hw = parse_handwritten_domop(hand_path)
        want = {"domain": doc["syscall_domains"], "op": doc["syscall_ops"]}
        for modname in ("domain", "op"):
            if hw[modname] is None:
                print("[abi-gen] FAIL %s：%s 里找不到 pub mod %s（本检查需要它仍在手写文件里）"
                      % (side, os.path.relpath(hand_path, ROOT), modname))
                ok = False
            elif hw[modname] != want[modname]:
                diff = sorted(set(hw[modname].items()) ^ set(want[modname].items()))
                print("[abi-gen] FAIL %s：%s 的 %s 与 JSON 不一致：%s"
                      % (side, os.path.relpath(hand_path, ROOT), modname, diff))
                ok = False
        hard = parse_handwritten_values(hand_path)
        if hard:
            print("[abi-gen] FAIL %s：%s 里还有写死的 SYS_* 数值 %s —— 必须改为引用 abi_generated"
                  % (side, os.path.relpath(hand_path, ROOT), hard[:5]))
            ok = False

    if a.check:
        n = len(doc["syscalls"])
        if ok:
            print("[abi-gen] OK：两侧生成物与 JSON 一致；手写 domain/op 与 JSON 一致；无写死的 SYS_* 数值（%d 项）" % n)
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
