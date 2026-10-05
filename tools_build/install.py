"""install 子命令：产出一个可交付给第三方的 sysroot（3P1-2）。

布局（<prefix> 由 --prefix 给定）：
    <prefix>/include/            C 头文件（libc/include/*.h + csrc/*.h）
    <prefix>/lib/libc.a          Rust 实现的 C 标准库（staticlib）
    <prefix>/lib/linker.ld       用户态链接脚本
    <prefix>/lib/user_main.o     C 入口桥接（_start -> user_main -> main）
    <prefix>/lib/                （预留：阶段 5 的共享库）
    <prefix>/bin/boruix-clang    C 驱动（一条命令编出可运行 ELF）
    <prefix>/boruix.json         目标定义（来自 sdk/boruix.json）
    <prefix>/cargo-config.toml   cargo 配置模板（3P1-3）

为什么 cargo-config.toml 与驱动脚本由本命令**生成**而不是直接拷贝：它们必须携带
<prefix> 的绝对路径（链接脚本、sysroot 根）。仓库里的源文件保持机器无关（S01），
机器相关的东西只出现在生成物里——这是 sysroot 这种产物的本分。
"""

import os
import shutil
import subprocess
import sys

from . import config
from .util import err, info

DRIVER_TEMPLATE = r'''#!/usr/bin/env python3
"""boruix-clang - 用本 sysroot 把一个 C 程序编成可运行的 BORUIX ELF。

用法:
    boruix-clang hello.c            # 产出 ./hello.elf（默认名取自源文件）
    boruix-clang hello.c -o out.elf

sysroot 由 `python tools/main.py install --prefix <dir>` 生成；本脚本通过自身路径
定位 sysroot（`<sysroot>/bin/boruix-clang`），因此**整个目录可以整体搬移**。

链接配方（为什么不是 crt0.o）：
  入口 `_start` 由 libc.a 内的 libsys 提供，它调用 `user_main`；C 程序的入口叫 `main`，
  由 <sysroot>/lib/user_main.o 桥接。crt0.S 自带强 `_start`，与 libc.a 的入口互斥
  （实测 duplicate symbol: _start），故 sysroot 不用它。
"""
import os
import shutil
import subprocess
import sys

SYSROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INCLUDE = os.path.join(SYSROOT, "include")
LIB = os.path.join(SYSROOT, "lib")

# 安装时探测到的宿主工具链（绝对路径）。环境变量可显式覆盖（S16：自动探测必须
# 同时提供手动覆盖手段）；两者都不可用时按 PATH 兜底，再不行如实报错。
DEFAULT_CLANG = r"__CLANG__"
DEFAULT_LLD = r"__LLD__"


def _pick(env_key, default, name):
    cand = os.environ.get(env_key) or default
    if not cand or not os.path.isfile(cand):
        cand = shutil.which(name)
    if not cand:
        sys.stderr.write("boruix-clang: cannot find " + name + " (set " + env_key + ")\n")
        sys.exit(1)
    return cand


def main(argv):
    srcs = [a for a in argv if not a.startswith("-") and a.endswith(".c")]
    if not srcs:
        sys.stderr.write(__doc__)
        return 1
    # 默认产物名取**第一个源文件**的名字（foo.c -> foo.elf）。此前写死 hello.elf，于是
    # `boruix-clang wclite.c` 会产出 hello.elf，容易被误当成别的程序。
    out = os.path.splitext(os.path.basename(srcs[0]))[0] + ".elf"
    if "-o" in argv:
        out = argv[argv.index("-o") + 1]
    clang = _pick("BORUIX_CLANG", DEFAULT_CLANG, "clang")
    lld = _pick("BORUIX_LLD", DEFAULT_LLD, "ld.lld")
    cc = [clang, "--target=x86_64-unknown-none", "-ffreestanding", "-fno-builtin",
          "-fno-stack-protector", "-fno-pic", "-O2", "-I", INCLUDE]
    objs = []
    for s in srcs:
        o = os.path.splitext(s)[0] + ".o"
        r = subprocess.run(cc + ["-c", s, "-o", o])
        if r.returncode != 0:
            return r.returncode
        objs.append(o)
    link = [lld, "-o", out, "-e", "_start", "-nostdlib", "--no-dynamic-linker",
            os.path.join(LIB, "user_main.o")] + objs + [
            os.path.join(LIB, "libc.a"), "-z", "noexecstack",
            # **必须 norelro**：ld.lld 默认 -z relro，会为数据段生成 GNU_RELRO，把第一个
            # RW 段拆成两个**共享同一页**的 PT_LOAD（实测：0x445d68 落在 0x445000 页，
            # 与前一 LOAD 同页）→ 内核按页映射两次 → AlreadyExists(17)。静态 ET_EXEC 没有
            # 动态链接器去施加 RELRO，故它本无意义。
            "-z", "norelro",
            "-T", os.path.join(LIB, "linker.ld")]
    r = subprocess.run(link)
    if r.returncode != 0:
        return r.returncode
    print("[boruix-clang] " + out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))'''

CARGO_CONFIG_TEMPLATE = """# BORUIX 用户级 cargo 配置（由 install 生成，3P1-3）。
# 放在工程根 .cargo/config.toml 即可：目标定义、链接脚本与 TLS 模型都在这里固化，
# 工程本身因此不需要 build.rs，也不需要自带 linker.ld。
#
# 目标是**按规范三元组名**使用的（3P2-4）：RUST_TARGET_PATH 指向 sysroot，cargo 在那里
# 找到 x86_64-unknown-boruix.json。rustc 加载自定义目标规格要求 -Zunstable-options。

[build]
target = "x86_64-unknown-boruix"
rustflags = ["-Zunstable-options", "-Clink-arg=-T{ld}", "-Ztls-model=local-exec"]

[env]
RUST_TARGET_PATH = "{prefix}"

[unstable]
# 自定义目标没有预编译的 core/alloc，必须自己构建（内建 x86_64-unknown-none 才有）。
# alloc 是 libsys 的依赖 buddy_system_allocator 所必需——实测只列 core 会报
# "can't find crate for alloc"。
build-std = ["core", "alloc"]
"""


def _run(cmd, cwd=None, env=None):
    r = subprocess.run(cmd, cwd=cwd or config.PROJECT_ROOT, env=env)
    if r.returncode != 0:
        err("命令失败（%d）: %s" % (r.returncode, " ".join(cmd)))
    return r.returncode


def _toolchain():
    """向 csrc/build_c.py 索取已验证可用的 clang/lld（不在本仓重复探测逻辑）。"""
    out = subprocess.run(
        [sys.executable, os.path.join(config.PROJECT_ROOT, "csrc", "build_c.py"),
         "--print-toolchain"],
        capture_output=True, text=True, cwd=os.path.join(config.PROJECT_ROOT, "csrc"),
    )
    if out.returncode != 0:
        return None, None
    clang = lld = None
    for line in out.stdout.splitlines():
        if line.startswith("CLANG="):
            clang = line[len("CLANG="):].strip()
        elif line.startswith("LLD="):
            lld = line[len("LLD="):].strip()
    return clang, lld


def cmd(args) -> int:
    prefix = os.path.abspath(args.prefix)
    profile = "debug" if args.debug else "release"
    lib_dir = os.path.join(prefix, "lib")
    inc_dir = os.path.join(prefix, "include")
    bin_dir = os.path.join(prefix, "bin")
    for d in (lib_dir, inc_dir, bin_dir):
        os.makedirs(d, exist_ok=True)

    # **必须用用户态目标构建 libc.a**：C 程序由 clang 按**硬件 SSE 浮点 ABI** 编译；若库用内核的
    # soft-float 目标（x86_64-unknown-none，`-sse...+soft-float`）构建，则任何跨 C↔Rust 边界的
    # double 都是坏的——实测 sqrt/floor/ceil/fabs/pow 与 printf("%.1f") 全部 FAIL，而同程序的
    # ctype/string/stdlib 全过（是 ABI 不是符号缺失）。
    target_name = "x86_64-unknown-boruix"
    target_dir = os.path.join(config.PROJECT_ROOT, "sdk")
    if not os.path.isfile(os.path.join(target_dir, target_name + ".json")):
        err("未找到用户态目标规格: " + os.path.join(target_dir, target_name + ".json"))
        return 1
    env = dict(os.environ)
    env["RUST_TARGET_PATH"] = target_dir
    # 目标域 rustflags：自定义目标要 -Zunstable-options；TLS 模型是本系统正确性的硬要求。
    env["CARGO_TARGET_X86_64_UNKNOWN_BORUIX_RUSTFLAGS"] = (
        "-Zunstable-options -Ztls-model=local-exec"
    )
    info("编译 libc.a (%s, 目标 %s)" % (profile, target_name))
    rc = _run(["cargo", "build",
               "--manifest-path", os.path.join(config.PROJECT_ROOT, "libc", "Cargo.toml"),
               "-Z", "build-std=core,alloc",
               "--target", target_name] + (["--release"] if profile == "release" else []),
              env=env)
    if rc != 0:
        return rc
    src_a = os.path.join(config.PROJECT_ROOT, "libc", "target", target_name, profile, "liblibc.a")
    if not os.path.isfile(src_a):
        err("未找到 liblibc.a: " + src_a)
        return 1
    shutil.copy(src_a, os.path.join(lib_dir, "libc.a"))

    info("编译 C 运行时对象 (user_main.o)")
    rc = _run([sys.executable, os.path.join(config.PROJECT_ROOT, "csrc", "build_c.py"),
               "--rt-only", lib_dir], cwd=os.path.join(config.PROJECT_ROOT, "csrc"))
    if rc != 0:
        return rc

    # 头文件：**只取 libc/include/**（与 lib/libc.a 配套的那一套）。
    #
    # 为什么不连 csrc/*.h 一起拷：两个目录存在**同名但内容不同**的文件（实测：
    # csrc/boruix.h 是 freestanding 运行时的 int 0x80 声明，libc/include/boruix.h 是
    # POSIX 聚合头）。合并进同一个 include/ 会静默覆盖其一——宁可少给一份，也不给错的一份。
    # freestanding C 运行时（crtrt.c 那一族）由 csrc/build_c.py 自带 -I 使用，不经 sysroot。
    inc_src = os.path.join(config.PROJECT_ROOT, "libc", "include")
    for name in sorted(os.listdir(inc_src)):
        if name.endswith(".h"):
            shutil.copy(os.path.join(inc_src, name), os.path.join(inc_dir, name))
    shutil.copy(os.path.join(config.PROJECT_ROOT, "csrc", "linker.ld"),
                os.path.join(lib_dir, "linker.ld"))

    # 目标规格以**规范三元组名**落在 sysroot 根：这样 RUST_TARGET_PATH=<prefix> 即可按名使用
    # （3P2-4 端点 B 的本地 Tier-3 形态），不再依赖 --target <path.json>。
    shutil.copy(os.path.join(config.PROJECT_ROOT, "sdk", "x86_64-unknown-boruix.json"),
                os.path.join(prefix, "x86_64-unknown-boruix.json"))

    with open(os.path.join(prefix, "cargo-config.toml"), "w", encoding="utf-8") as f:
        f.write(CARGO_CONFIG_TEMPLATE.format(
            prefix=prefix.replace(os.sep, "/"),
            ld=os.path.join(lib_dir, "linker.ld").replace(os.sep, "/"),
        ))

    clang, lld = _toolchain()
    driver = DRIVER_TEMPLATE.replace("__CLANG__", clang or "").replace("__LLD__", lld or "")
    drv = os.path.join(bin_dir, "boruix-clang")
    with open(drv, "w", encoding="utf-8", newline="\n") as f:
        f.write(driver)
    if os.name == "nt":
        with open(drv + ".cmd", "w", encoding="utf-8", newline="\r\n") as f:
            f.write("@echo off\r\npython \"%~dp0boruix-clang\" %*\r\n")

    info("sysroot 就绪: " + prefix)
    for root, _dirs, files in os.walk(prefix):
        for name in sorted(files):
            rel = os.path.relpath(os.path.join(root, name), prefix)
            print("  " + rel.replace(os.sep, "/"))
    return 0