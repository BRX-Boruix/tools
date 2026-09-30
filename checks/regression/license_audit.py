#!/usr/bin/env python3
"""第三方许可证披露审计（判据见 kernel/crates/kernel/src/licenses.rs 模块文档）。

从 workspace 的 `kernel` 包出发，只沿**普通依赖**边遍历 cargo metadata 的解析图：
排除 dev / build 专属边；**过程宏及其宿主端依赖子树不计**（编译期运行于宿主，代码
不进目标二进制）。列出代码确实进入内核二进制的第三方 crate，并核对是否已登记在
`licenses.rs` 的 COMPONENTS 表中（文件名规则：`<package.name>.txt`）。

用法:
    python license_audit.py [--list]

退出码: 0=全部已披露  1=存在未披露  2=环境/解析错误
"""

import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS_DIR = os.path.dirname(os.path.dirname(_HERE))
PROJECT_ROOT = os.path.dirname(_TOOLS_DIR)
KERNEL_DIR = os.path.join(PROJECT_ROOT, "kernel")
LICENSES_RS = os.path.join(KERNEL_DIR, "crates", "kernel", "src", "licenses.rs")
TARGET = "x86_64-unknown-none"


def registered():
    """从 licenses.rs 解析 COMPONENTS 表中的 file_name 字面量。"""
    with open(LICENSES_RS, encoding="utf-8") as f:
        text = f.read()
    names = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("file_name:"):
            v = s.split(":", 1)[1].strip().rstrip(",").strip()
            if v.startswith('"') and v.endswith('"'):
                names.append(v[1:-1])
    return names


def in_binary():
    proc = subprocess.run(
        ["cargo", "metadata", "--format-version", "1", "--filter-platform", TARGET],
        cwd=KERNEL_DIR, capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        print("cargo metadata 失败:\n" + proc.stderr[:2000], file=sys.stderr)
        sys.exit(2)
    md = json.loads(proc.stdout)
    by_id = {p["id"]: p for p in md["packages"]}
    nodes = {n["id"]: n for n in md["resolve"]["nodes"]}
    roots = [p for p in md["packages"] if p["name"] == "kernel" and p["source"] is None]
    if len(roots) != 1:
        print("无法唯一定位 kernel 包", file=sys.stderr)
        sys.exit(2)

    def is_pm(p):
        return any("proc-macro" in t.get("kind", []) for t in p["targets"])

    inbin, host, seen = [], [], set()
    stack = [(roots[0]["id"], False)]
    while stack:
        pid, is_host = stack.pop()
        if pid in seen:
            continue
        seen.add(pid)
        p = by_id[pid]
        (host if (is_host or is_pm(p)) else inbin).append(p)
        child_host = is_host or is_pm(p)
        for dep in nodes[pid]["deps"]:
            if any(dk.get("kind") in (None, "normal") for dk in dep["dep_kinds"]):
                stack.append((dep["pkg"], child_host))

    def ext(ps):
        return sorted([p for p in ps if p["source"] is not None], key=lambda p: p["name"])

    return ext(inbin), ext(host)


def main() -> int:
    do_list = "--list" in sys.argv
    reg = set(registered())
    inbin, host = in_binary()

    print(f"已披露组件（licenses.rs COMPONENTS）: {len(reg)}")
    for n in sorted(reg):
        print(f"  + {n}")

    print()
    print(f"代码进入内核二进制的第三方 crate: {len(inbin)}")
    missing = []
    for p in inbin:
        covered = (p["name"] + ".txt") in reg
        mark = "OK  " if covered else "MISS"
        if not covered:
            missing.append(p)
        print(f'  [{mark}] {p["name"]} {p["version"]:<10} {p.get("license") or "<NONE>"}')

    if do_list:
        print()
        print(f"宿主端/过程宏（不进二进制，无需披露）: {len(host)}")
        for p in host:
            print(f'  - {p["name"]} {p["version"]:<10} {p.get("license") or "<NONE>"}')

    print()
    if missing:
        print(f"判定：存在 {len(missing)} 个未披露的进二进制 crate：")
        for p in missing:
            print(f'  {p["name"]} {p["version"]} ({p.get("license") or "<NONE>"})')
        print("请在 kernel/crates/kernel/src/licenses.rs 的 COMPONENTS 中登记，")
        print("并同步 kernel/NOTICE.md（缺口与补齐方案见该文件）。")
        return 1
    print("判定：通过——进二进制的第三方 crate 均已登记披露。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
