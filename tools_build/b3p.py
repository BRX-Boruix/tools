"""b3p 子命令：构建第三方程序（build third-party programs）。

与 `_build_userspace`（`build.py`）的区别——**这是两个不同的部署通道**：

| | 内置程序（USER_PROGRAMS） | 第三方程序（THIRD_PARTY_PROGRAMS） |
|---|---|---|
| 编译 | cargo build --target x86_64-unknown-none | 同左 |
| 去向 | 拷进 `kernel/crates/kernel/<name>.elf` | 落到 `tools/diskfiles/3p/<name>.elf` |
| 装载 | 内核 `include_bytes!` 编进 liveCD payload | 随数据盘 EXT2 以 `/3p/<name>.elf` 存在 |
| 运行 | `/programs/<name>.elf`（无盘亦可） | `/volumes/BORUIX_DATA/3p/<name>.elf`（需挂盘） |
| 加程序 | 改 build.py 的 USER_PROGRAMS 元组 | 改本文件 THIRD_PARTY_PROGRAMS 元组 |

**为何第三方走盘而不进 payload**：内核 payload 在编译期被 `include_bytes!` 钉死，
加一个程序就要重编内核 + 重出 ISO。数据盘是运行期挂载的 VFS 内容，`sys_exec`
（kernel `syscall.rs:2917`）对非内建索引的 a1 一律当**纯 VFS 路径**解析，因此
`/volumes/<label>/3p/<name>.elf` 与 `/programs/<name>.elf` 在 ABI 上完全等价。
第三方因此不必改系统源码、不必重编内核、不必重出 ISO。

**产出位置即部署位置**：编译产物直接写进 `diskfiles/3p/`，该目录由
`disk.scan_diskfiles` 递归扫描（`os.walk`），故下次 `mkimg` / `--redisk`
构建数据盘时自动被拾取为 `/3p/<name>.elf`。`disk.py` 给普通文件设
`EXT2_S_IFREG | 0o755`（`disk.py:339`），x 位天然具备，无需额外 chmod。

**只读语义**：本子命令是 `diskfiles/` 唯一的写入者，且只写 `3p/` 子目录；
其余 `diskfiles/` 内容仍严格是只读输入。产物 `.elf` 不受版本控制。

用法:
    python main.py b3p [--release|--debug] [--prog NAME ...] [--list]
"""

import argparse
import os
import shutil
import subprocess

from . import config
from .util import err, info

# 第三方程序清单（**单点定义**，S15）。
#
# 元素为源码目录名，同时是产出的 ELF 名：`<name>/` -> `3p/<name>.elf`。
# 目录须在项目根下，形状与内置用户程序一致：Cargo.toml + build.rs +
# linker.ld + src/main.rs，依赖 libsys，导出 `user_main`（见 cowsay/）。
#
# 加一个第三方程序 = 在此追加一项 + 源码目录就位，**无需改动内核或其余系统工具模块**。
THIRD_PARTY_PROGRAMS = (
    "cowsay",
)

# 第三方程序产物在 diskfiles 下的子目录名。
# 与挂载点组合即运行路径：/volumes/BORUIX_DATA/3p/<name>.elf。
THIRD_PARTY_SUBDIR = "3p"

# 构建 profile：第三方程序默认 release。
#
# 选择理由：数据盘上的程序是**交付物**而非开发中间态，opt-level=z + lto 的体积
# 优势直接体现在盘占用与加载时间上；且第三方程序不经内核 payload 的编译期
# 校验，release 构建更接近它最终被分发的形态。需要调试时用 --debug 显式覆盖。
DEFAULT_PROFILE = "release"


# 源码包清单（3P6-5「分发模型扩展」）：**以源码分发、在机编译**的包。
#
# 与 THIRD_PARTY_PROGRAMS 的区别（两条并行的分发通道）：
# | | THIRD_PARTY_PROGRAMS | SOURCE_PACKAGES |
# |---|---|---|
# | 盘上形态 | `3p/<name>.elf`（宿主预编译） | `3p/src/<name>/`（源码 + 构建配方） |
# | 谁来编译 | 宿主 cargo（交叉编译） | **机上的系统内编译器**（tcc） |
# | 适用 | 需要 Rust 工具链的第三方程序 | 能在机编译的 C（及其他）源码包 |
#
# 元素为项目根下的目录名（`3psrc/<name>/`），目录内容被**整体**拷到
# `tools/diskfiles/3p/src/<name>/`。约定（S15 单点，写在包的 BUILD 文件里）：
#   - `<name>.c`：入口源文件；
#   - `BUILD`：在**机内**执行的构建命令（逐行、可直接粘进 shell）。
SOURCE_PACKAGES = (
    "cowsay",
)

# 源码包在**本仓**（tools）下的目录名。
#
# 为什么放在 tools 仓而不是项目根：tools 仓已经是「要分发什么」的唯一持有者
# （diskfiles/ 就是盘内容来源），源码包同理——放这里既版本化、又能随本仓推送，
# 不必为每个包新开一个仓。
SOURCE_PACKAGE_ROOT = os.path.join(config.TOOLS_DIR, "3psrc")


def _diskfiles_3p_dir() -> str:
    """第三方程序在 diskfiles 下的产出目录（`tools/diskfiles/3p`）。"""
    return os.path.join(config.TOOLS_DIR, "diskfiles", THIRD_PARTY_SUBDIR)


def _diskfiles_3p_src_dir() -> str:
    """源码包在 diskfiles 下的产出目录（`tools/diskfiles/3p/src`）。"""
    return os.path.join(_diskfiles_3p_dir(), "src")


def stage_source(name: str) -> int:
    """把一个**源码包**整体铺到 `diskfiles/3p/src/<name>/`。返回 0 成功。

    **只拷源码，不编译**——这正是本通道的意义：编译发生在 BORUIX 机内
    （由系统内编译器执行包里的 `BUILD` 配方），宿主只负责分发源码。
    """
    src_dir = os.path.join(SOURCE_PACKAGE_ROOT, name)
    if not os.path.isdir(src_dir):
        err(f"源码包目录不存在: {src_dir}")
        return 1
    entry = os.path.join(src_dir, name + ".c")
    if not os.path.isfile(entry):
        err(f"源码包缺少入口源文件: {entry}")
        return 1
    if not os.path.isfile(os.path.join(src_dir, "BUILD")):
        err(f"源码包缺少构建配方 BUILD: {src_dir}")
        return 1
    dst = os.path.join(_diskfiles_3p_src_dir(), name)
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src_dir, dst)
    n = sum(len(f) for _r, _d, f in os.walk(dst))
    info(f"源码包 {name} -> {dst} ({n} 个文件，未编译；编译在机内按 BUILD 执行)")
    return 0


def stage_sources(only=None) -> int:
    """铺全部（或指定的）源码包。返回 0 表示全部成功。"""
    names = list(SOURCE_PACKAGES)
    if only:
        unknown = [n for n in only if n not in SOURCE_PACKAGES]
        if unknown:
            err(f"不在源码包清单中的名字: {unknown}")
            err(f"清单: {list(SOURCE_PACKAGES)}")
            return 1
        names = [n for n in names if n in set(only)]
    if not names:
        info("源码包清单为空，无事可做")
        return 0
    for name in names:
        rc = stage_source(name)
        if rc != 0:
            return rc
    return 0


def _elf_path(name: str, profile: str) -> str:
    """第三方程序源码目录下 cargo 的产物路径。"""
    return os.path.join(
        config.PROJECT_ROOT, name, "target", config.TARGET, profile, name
    )


def build_one(name: str, profile: str) -> int:
    """编译单个第三方程序并落到 `diskfiles/3p/`。返回 0 成功。

    失败一律如实报错并中止（S09）：绝不产出「编译失败但盘里有个旧 ELF」的假象。
    """
    src_dir = os.path.join(config.PROJECT_ROOT, name)
    manifest = os.path.join(src_dir, "Cargo.toml")
    if not os.path.isfile(manifest):
        err(f"第三方程序 {name} 缺少 Cargo.toml: {manifest}")
        return 1

    info(f"编译第三方程序 {name} ({profile})")
    cmd = [
        "cargo", "build",
        "--manifest-path", manifest,
        "--target", config.TARGET,
    ]
    if profile == "release":
        cmd.append("--release")
    r = subprocess.run(cmd, cwd=config.PROJECT_ROOT, env=config.userspace_env())
    if r.returncode != 0:
        err(f"第三方程序 {name} 编译失败")
        return r.returncode

    elf = _elf_path(name, profile)
    if not os.path.isfile(elf):
        err(f"未找到 {name} 的 ELF 产物: {elf}")
        return 1

    out_dir = _diskfiles_3p_dir()
    os.makedirs(out_dir, exist_ok=True)
    dst = os.path.join(out_dir, f"{name}.elf")
    shutil.copy(elf, dst)
    info(f"{name}.elf -> {dst} ({os.path.getsize(dst)}B)")
    return 0


def build_all(profile: str = DEFAULT_PROFILE, only=None) -> int:
    """编译清单中的第三方程序。`only` 非空时只编译其中指定的那些。

    返回 0 表示**全部**成功；任一失败立即返回非 0，不继续往下编。
    这是刻意的：部分成功的构建会让盘里出现新旧混杂的一组程序，
    调用方无法从返回值判断哪些是新鲜的。
    """
    names = list(THIRD_PARTY_PROGRAMS)
    if only:
        # 拼写错误必须报错而非静默跳过（否则 --prog cowasy 会「成功但什么都没编」）。
        unknown = [n for n in only if n not in THIRD_PARTY_PROGRAMS]
        if unknown:
            err(f"不在第三方程序清单中的名字: {unknown}")
            err(f"清单: {list(THIRD_PARTY_PROGRAMS)}")
            return 1
        names = [n for n in names if n in set(only)]

    if not names:
        info("第三方程序清单为空，无事可做")
        return 0

    for name in names:
        rc = build_one(name, profile)
        if rc != 0:
            return rc
    return 0




# ---------- --new：生成最小可编译骨架（3P1-6）----------
#
# 生成的是**现代形态**：Cargo.toml（git 依赖 libsys）+ src/main.rs + .cargo/config.toml
# （取自 sysroot）。**不含 build.rs、不含 linker.ld**——目标定义、链接脚本与 TLS 模型都由
# sysroot 的 cargo 配置提供（3P1-3）。因此必须指明 sysroot：--sysroot <prefix> 或环境变量
# BORUIX_SYSROOT。

NEW_MAIN_RS = """//! {name} - BORUIX 用户态程序（由 `b3p --new` 生成）。
//!
//! 工程里只有本文件 + Cargo.toml + .cargo/config.toml：目标定义、链接脚本与 TLS 模型都由
//! sysroot 提供（见 docs/TODO/3p.md 阶段 1）。改完 `cargo build`，产物在
//! `target/boruix/<profile>/{name}`。
#![no_std]
#![no_main]

// panic_handler 由 libsys 提供（其 cfg 已覆盖 os="boruix"），此处不得重复定义。

#[unsafe(no_mangle)]
pub extern "C" fn user_main(_argc: isize, _argv: *const *const u8) -> i32 {{
    let _ = libsys::write(1, b"hello from {name}\n");
    0
}}
"""

NEW_CARGO_TOML = """[package]
name = "{name}"
version = "0.1.0"
edition = "2024"

[dependencies]
# 3P1-5：git 依赖（工程目录独立于系统源码树）。
libsys = {{ git = "https://github.com/BRX-Boruix/libsys" }}

[profile.dev]
panic = "abort"
[profile.release]
panic = "abort"
"""


def new_project(name: str, sysroot: str, parent: str) -> int:
    """生成最小可编译骨架。返回 0 成功。已存在同名目录即如实拒绝（绝不覆盖）。"""
    src_cfg = os.path.join(sysroot, "cargo-config.toml")
    if not os.path.isfile(src_cfg):
        err("sysroot 不完整，缺少 cargo-config.toml: " + sysroot)
        err("先用 `python tools/main.py install --prefix <dir>` 产出一个 sysroot。")
        return 1
    dest = os.path.join(parent, name)
    if os.path.exists(dest):
        err("目标目录已存在，拒绝覆盖: " + dest)
        return 1
    os.makedirs(os.path.join(dest, "src"))
    os.makedirs(os.path.join(dest, ".cargo"))
    with open(os.path.join(dest, "Cargo.toml"), "w", encoding="utf-8", newline="\n") as f:
        f.write(NEW_CARGO_TOML.format(name=name))
    with open(os.path.join(dest, "src", "main.rs"), "w", encoding="utf-8", newline="\n") as f:
        f.write(NEW_MAIN_RS.format(name=name))
    shutil.copy(src_cfg, os.path.join(dest, ".cargo", "config.toml"))
    info("已生成工程: " + dest)
    print("  Cargo.toml")
    print("  src/main.rs")
    print("  .cargo/config.toml  (来自 sysroot: " + sysroot + ")")
    info("构建: cd " + dest + " && cargo build   产物: target/boruix/debug/" + name)
    return 0


def cmd(args: argparse.Namespace) -> int:
    """b3p 子命令入口。"""
    new_name = getattr(args, "new", None)
    if new_name:
        sysroot = getattr(args, "sysroot", None) or os.environ.get("BORUIX_SYSROOT")
        if not sysroot:
            err("b3p --new 需要 sysroot：传 --sysroot <prefix> 或设 BORUIX_SYSROOT。")
            return 1
        parent = getattr(args, "dir", None) or os.getcwd()
        return new_project(new_name, sysroot, parent)
    if getattr(args, "list", False):
        for n in THIRD_PARTY_PROGRAMS:
            print(n)
        for n in SOURCE_PACKAGES:
            print(n + "  (源码包)")
        return 0
    # --src：走"源码包"通道——只铺源码，编译在 BORUIX 机内做（3P6-5）。
    if getattr(args, "src", False):
        return stage_sources(only=getattr(args, "prog", None))
    profile = "debug" if getattr(args, "debug", False) else DEFAULT_PROFILE
    return build_all(profile, only=getattr(args, "prog", None))
