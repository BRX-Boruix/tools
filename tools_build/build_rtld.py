#!/usr/bin/env python3
"""构建 rtld 并把产物**铺到数据盘**（`tools/diskfiles/3p/rtld.elf`）。

## 为什么需要它（真实事故，不是预防性洁癖）

`rtld.elf` 和 `tcc.elf` 一样，一直是**手工拷**到 `tools/diskfiles/3p/` 的资产：
仓库里没有任何脚本会更新它。2026-10 就因此出过一次**测量作废**——改完 rtld 的源码后
忘了拷，机上跑的仍是旧二进制（`docs/TODO/3p.md` 有完整记录）。`tcc.elf` 已并入
`tcc-on-boruix/boruix/stage_assets.py` + 新鲜度门禁；本脚本补上 rtld 这一半。

## 为什么用 cargo-boruix 而不是裸 cargo

rtld 的 `src/main.rs` **不声明** `#![no_std]`/`#![no_main]`——这两个 crate 属性、
TLS 模型与链接脚本都由 `cargo-boruix` 经 `--config` 注入（见
`sdk/boruix_std/cargo-boruix/src/main.rs`）。**单一事实源是那个程序**，本脚本只负责
「调它 + 铺料」，不复制它的旗标拼装逻辑（S15：同一件事不留两份定义）。

## 为什么是 debug 而不是 release

`rtld/Cargo.toml` 只给 `[profile.dev]` 设了 `panic = "abort"`；release 会走
unwind，而本目标是 `no_std`（无 unwinder）。故与既有产物一致走 debug。

## 用法

  python tools/tools_build/build_rtld.py [--sysroot <dir>] [--dest <dir>] [--no-stage]

前置：`python tools/main.py install --prefix <dir>` 产出 sysroot（脚本会校验它完整）。
"""
import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
RTLD = os.path.join(ROOT, "rtld")
TARGET = "x86_64-unknown-boruix"
BUILT = os.path.join(RTLD, "target", TARGET, "debug", "rtld")
CARGO_BORUIX_MANIFEST = os.path.join(ROOT, "sdk", "boruix_std", "cargo-boruix", "Cargo.toml")
CARGO_BORUIX_EXE = os.path.join(ROOT, "sdk", "boruix_std", "target", "debug", "cargo-boruix")
DEFAULT_DEST = os.path.join(ROOT, "tools", "diskfiles", "3p")


def die(msg):
    sys.stderr.write("build_rtld: " + msg + "\n")
    sys.exit(1)


def info(msg):
    print("[build_rtld] " + msg)


def run(cmd, cwd=None, env=None):
    print("+", " ".join(cmd))
    r = subprocess.run(cmd, cwd=cwd, env=env)
    if r.returncode != 0:
        die("命令失败（%d）：%s" % (r.returncode, " ".join(cmd)))


def cargo_boruix():
    """返回可执行的 cargo-boruix 路径；缺失时先构建它。

    **不假设它已存在**：它是 `sdk/boruix_std` 的构建产物（gitignore），
    干净检出里没有。缺了就现建——否则脚本会在别人机器上神秘失败。
    """
    for cand in (CARGO_BORUIX_EXE, CARGO_BORUIX_EXE + ".exe"):
        if os.path.isfile(cand):
            return cand
    info("未找到 cargo-boruix，先构建它（宿主侧）")
    run(["cargo", "build", "--manifest-path", CARGO_BORUIX_MANIFEST])
    for cand in (CARGO_BORUIX_EXE, CARGO_BORUIX_EXE + ".exe"):
        if os.path.isfile(cand):
            return cand
    die("构建后仍未找到 cargo-boruix（期望在 " + CARGO_BORUIX_EXE + "）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sysroot", default=os.environ.get("BORUIX_SYSROOT"))
    ap.add_argument("--dest", default=DEFAULT_DEST)
    ap.add_argument("--no-stage", action="store_true",
                    help="只构建，不铺到数据盘（供只想看编译结果时用）")
    a = ap.parse_args()

    if not a.sysroot or not os.path.isdir(a.sysroot):
        die("需要 --sysroot（或 BORUIX_SYSROOT）指向已安装的 sysroot")
    # **前置检查先于任何写入**（同 stage_assets.py 的「不半更新」纪律）：
    # sysroot 不完整时立刻停，绝不先拷一个旧产物过去冒充新构建。
    for rel in (TARGET + ".json", os.path.join("lib", "linker.ld")):
        p = os.path.join(a.sysroot, rel)
        if not os.path.isfile(p):
            die("sysroot 不完整：缺 " + p + "（先跑 python tools/main.py install --prefix <dir>）")

    cb = cargo_boruix()
    env = dict(os.environ)
    env["BORUIX_SYSROOT"] = a.sysroot
    run([cb, "build"], cwd=RTLD, env=env)

    if not os.path.isfile(BUILT):
        die("构建成功但找不到产物：" + BUILT)
    with open(BUILT, "rb") as f:
        magic = f.read(4)
    if magic != b"\x7fELF":
        die("产物不是 ELF（magic=%r）：%s" % (magic, BUILT))
    size = os.path.getsize(BUILT)
    info("产物 %s（%d 字节，ELF 校验通过）" % (BUILT, size))

    if a.no_stage:
        return 0
    os.makedirs(a.dest, exist_ok=True)
    dst = os.path.join(a.dest, "rtld.elf")
    shutil.copy(BUILT, dst)
    info("已铺到数据盘：" + dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
