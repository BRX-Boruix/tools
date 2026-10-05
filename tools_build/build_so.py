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
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))  # 工作区根
LIBC = os.path.join(ROOT, "libc")
TARGET = "x86_64-unknown-boruix"
SONAME = "libboruixc.so.1"


def run(cmd, env=None):
    print("+", " ".join(cmd))
    r = subprocess.run(cmd, env=env)
    if r.returncode != 0:
        sys.exit("命令失败（%d）" % r.returncode)


def main():
    profile = "debug" if "--debug" in sys.argv else "release"
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
    lld = os.environ.get("BORUIX_LLD") or "ld.lld"
    # `--whole-archive` 是**必需**的：`-shared` 下链接器只拉取**被引用**的归档成员，
    # 而 version script **不会创建引用**——没有它就几乎没有根，`.so` 会缩到 1.6 KB、只剩 4 个
    # 符号（实测踩过：`.a` 里明明有 printf，`.so` 里却没有）。
    # 拉入全部成员后，由 `--gc-sections` + version script 收敛到 C ABI。
    run([lld, "-shared", "-soname", SONAME, "-z", "norelro", "--gc-sections",
         "--version-script=" + os.path.join(LIBC, "abi-exports.txt"),
         "--whole-archive", a, "--no-whole-archive",
         "-o", out])
    print("[build_so] 产出", out, "(%d KB)" % (os.path.getsize(out) // 1024))


if __name__ == "__main__":
    main()