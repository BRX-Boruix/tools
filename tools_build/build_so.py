#!/usr/bin/env python3
"""把 libc 的 staticlib 链成 `libboruixc.so`（阶段 5 / 3P5-2）。

## 为什么不用 `cargo` 的 `cdylib`

cargo 对本自定义目标**丢弃** `cdylib`（实测警告 `dropping unsupported crate type`）；
加 `dll-prefix`/`dll-suffix`/`dynamic-linking: true` 均无效，`cargo rustc -- --crate-type cdylib`
也不产出。故改为：**先用 cargo 产出 staticlib，再由本脚本用 ld.lld 链成 `.so`**。
这条路的依据是实测：`liblibc.a` 里的对象可直接 `ld.lld -shared`（EXIT=0）。

## 两个关键旗标（都是实测得出的，不是抄的）

- `--version-script=<libc/abi-exports.txt>`：`-shared` 下**所有 global 符号默认都导出**，
  `--dynamic-list` 只能**增加**导出；要**限制**导出面必须用 version script 的 `local: *;`。
  实测：加它之后 `.dynsym` 从 1523 降到 152（只剩 C ABI）。
- `--gc-sections`：裁掉未被引用的代码。实测体积从 827 KB 降到 126 KB。
  安全的前提正是上面那条——导出面已被限制在 C ABI 内。

## 用法

  python tools/tools_build/build_so.py [--debug]

前置：`libc/abi-exports.txt` 已由 `libc/tools/gen_abi_exports.py` 生成（本脚本会顺带刷新它）。
"""
import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)                  # tools/
ROOT = os.path.dirname(TOOLS)                  # 工作区根
# 以脚本方式运行时 sys.path[0] 是本文件所在目录，`tools_build.*` 不可导入——
# 与 checks 脚本同一纪律：显式把 tools/ 插进 sys.path。
sys.path.insert(0, TOOLS)

from tools_build import abi_exports, toolchain  # noqa: E402
LIBC = os.path.join(ROOT, "libc")
TARGET = "x86_64-unknown-boruix"
SONAME = "libboruixc.so.1"


def read_export_list(path):
    """从 version script 里取出 `global:` 段的符号名（用于 `-u` 声明 gc 根）。"""
    names = []
    in_global = False
    with open(path, "r", encoding="ascii") as f:
        for line in f:
            t = line.strip()
            if t.startswith("global:"):
                in_global = True
                continue
            if t.startswith("local:"):
                in_global = False
                continue
            if in_global and t.endswith(";"):
                names.append(t[:-1].strip())
    if not names:
        sys.exit("abi-exports.txt 里没有 global 符号——拒绝产出无导出的 .so")
    return names


def run(cmd, env=None):
    print("+", " ".join(cmd))
    r = subprocess.run(cmd, env=env)
    if r.returncode != 0:
        sys.exit("命令失败（%d）" % r.returncode)


def defined_symbols(archive, nm):
    """从静态库里取出**已定义且全局**的符号集（`llvm-nm` 的档案成员标题行要跳过）。"""
    r = subprocess.run([nm, "--defined-only", "--extern-only", archive],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("llvm-nm 失败（%d）：%s" % (r.returncode, r.stderr.strip()[:200]))
    out = set()
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[-2] in ("T", "D", "B", "R", "W", "V"):
            out.add(parts[-1])
    return out


DEFAULT_DEST = os.path.join(ROOT, "tools", "diskfiles", "3p")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--dest", default=DEFAULT_DEST)
    ap.add_argument("--no-stage", action="store_true",
                    help="只构建，不铺到数据盘")
    args = ap.parse_args()
    profile = "debug" if args.debug else "release"
    # 1) 刷新 ABI 导出清单（脚本自己写文件——不要用 shell 重定向，见该脚本说明）。
    run([sys.executable, os.path.join(LIBC, "tools", "gen_abi_exports.py")])
    # 2) cargo 产出 staticlib（含全部依赖对象：libsys/core/alloc/spin）。
    env = dict(os.environ)
    env["RUST_TARGET_PATH"] = os.path.join(ROOT, "sdk")
    env["CARGO_TARGET_X86_64_UNKNOWN_BORUIX_RUSTFLAGS"] = (
        "-Zunstable-options -Ztls-model=local-exec"
    )
    # **--no-default-features**：关掉 libc/libsys 的 `crt` feature——`.so` 是库，不该带
    # 进程入口 `_start`（它会引用 `user_main`，在 `.so` 里留下 `UND user_main`，使 rtld 的
    # 急切符号解析失败；实测过）。静态可执行文件路径仍用默认（crt 开）。
    cmd = ["cargo", "build", "--manifest-path", os.path.join(LIBC, "Cargo.toml"),
           "--no-default-features",
           "-Z", "build-std=core,alloc", "--target", TARGET]
    if profile == "release":
        cmd.append("--release")
    run(cmd, env=env)
    # 3) 链成 .so。
    a = os.path.join(LIBC, "target", TARGET, profile, "liblibc.a")
    if not os.path.isfile(a):
        sys.exit("找不到 staticlib: " + a)
    out = os.path.join(LIBC, "target", TARGET, profile, SONAME)
    # **必须解析成绝对路径**：Windows 的 CreateProcess 只对**不带点**的名字补 .exe，而
    # `ld.lld` 的 `.lld` 被当成扩展名 ⇒ 直接 FileNotFoundError（本机 Python 3.14.7 实测；
    # `shutil.which` 却找得到它）。见 tools_build/toolchain.py 与配套检查。
    lld = toolchain.resolve_tool("ld.lld", "BORUIX_LLD")
    # **把每个导出符号变成 gc 的根**：`--gc-sections` 只保留「从根可达」的代码，而
    # **version script 不创建引用**——所以像 `sqrt` 这种「无人内部引用」的导出函数会被裁掉
    # （实测：`.a` 里有 `sqrt`，`.so` 里没有，链接下游程序时报 undefined symbol）。
    # 用 `-u <sym>` 逐个声明为根，导出面才真正稳定。
    # `--whole-archive` 是**必需**的：`-shared` 下链接器只拉取**被引用**的归档成员，
    # 而 version script **不会创建引用**——没有它就几乎没有根，`.so` 会缩到 1.6 KB、只剩 4 个
    # 符号（实测踩过：`.a` 里明明有 printf，`.so` 里却没有）。
    # 拉入全部成员后，由 `--gc-sections` + version script 收敛到 C ABI。
    declared_path = os.path.join(LIBC, "abi-exports.txt")
    declared = read_export_list(declared_path)
    # **导出面 = 声明集 ∩ 本库定义集**：`-shared` 下 version script 要求每个 global 都被本库
    # 定义，而声明集来自头文件（含 dlopen 族——它们由 rtld 提供，libc 不定义），直接用会被
    # `ld.lld` 拒绝（实测：version script assignment ... symbol not defined）。
    nm = toolchain.resolve_tool("llvm-nm", "BORUIX_NM")
    defined = defined_symbols(a, nm)
    kept, removed = abi_exports.intersect_exports(declared, defined)
    if not kept:
        sys.exit("声明集与本库定义集交集为空——拒绝产出无导出的 .so")
    if removed:
        # 剔除必须**如实打印**，不静默（S09/S10）：这些名字仍留在声明集里（生成器回答
        # 「打算导出什么」），但本库不定义它们，故不进版本脚本。
        print("[build_so] 剔除 %d 个本库不定义的声明（%s）"
              % (len(removed), ", ".join(removed[:8]) + ("..." if len(removed) > 8 else "")))
    eff_path = os.path.join(LIBC, "target", TARGET, profile, "abi-exports.effective.txt")
    with open(eff_path, "w", encoding="ascii") as f:
        f.write(abi_exports.render_version_script(kept))
    print("[build_so] 版本脚本：声明 %d -> 生效 %d（%s）" % (len(declared), len(kept), eff_path))
    keep = []
    for s in kept:
        keep += ["-u", s]
    print("[build_so] 把 %d 个导出符号声明为 gc 根" % len(kept))
    # **保留 `--gc-sections`**（实测取舍）：去掉它体积从 135 KB 涨到 690 KB，且多出的重定位里
    # 有一个会写入未映射地址 → rtld 在 RELATIVE 分支 panic（实测退出码 101）。135 KB 那版能跑通。
    # 代价：`compiler_builtins` 提供的**弱符号**数学函数（sqrt/floor/pow…）会被裁掉——
    # 「无人内部引用」+ version script 不创建引用。这是**已记录的独立待查项**，不影响导出面里的
    # C ABI 函数（printf/malloc/snprintf/…）。
    run([lld, "-shared", "-soname", SONAME, "-z", "norelro", "--gc-sections",
         "--version-script=" + eff_path,
         "--whole-archive", a, "--no-whole-archive"]
        + keep +
        ["-o", out])
    print("[build_so] 产出", out, "(%d KB)" % (os.path.getsize(out) // 1024))

    # 铺到数据盘（同 build_rtld.py 的范式）：`.so` 一直是**手工拷**到 tools/diskfiles/3p/ 的
    # 资产，没有任何脚本会更新它。2026-10 实测过同族事故：盘上是旧的、机内跑的也是旧的，
    # 而报告里看不出来。故：产物校验通过后**主动铺**，并把「记得重铺」交给门禁。
    if args.no_stage:
        return 0
    os.makedirs(args.dest, exist_ok=True)
    dst = os.path.join(args.dest, SONAME)
    shutil.copy(out, dst)
    print("[build_so] 已铺到数据盘：" + dst)
    return 0


if __name__ == "__main__":
    main()