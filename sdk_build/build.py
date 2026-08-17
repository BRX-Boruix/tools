"""build 子命令：编译内核并生成可引导 ISO。"""

import argparse
import os
import shutil
import subprocess

from . import config
from .symbols import gen as gen_symbols
from .util import err, info


def _kernel_elf(profile: str = "debug") -> str:
    return os.path.join(config.KERNEL_DIR, "target", config.TARGET, profile, "kernel")


def _symbols_generated() -> str:
    return os.path.join(config.KERNEL_DIR, "crates", "kernel", "src", "symbols_generated.rs")


def _cargo_build_kernel(
    use_tests: bool = False,
    use_m33: bool = False,
    use_m41: bool = False,
    release: bool = False,
) -> int:
    """编译内核为 ELF，并在链接后提取符号表二次编译嵌入。

    两阶段原因：符号表数据取自内核二进制，必须先编译出 ELF 才能提取符号。
    由于符号表 `SYMBOLS` 属于 .rodata 段，不影响 .text 布局，两次编译的
    函数符号地址一致，故嵌入后符号表依然准确。

    `use_tests` 为 True 时启用 `kernel-tests` feature（编译带自检测试的
    内核，供开发/验证用）；默认关闭（生产构建不含测试代码）。

    `use_m33` 为 True 时额外启用 `kernel-test-m33` feature（M3.3 用户态
    异常停机验收，隐含 kernel-tests）；该测试验收后停机、不返回主流程，
    默认关闭以便 `--test` 跑完常规测试后继续打印版本横幅。

    `use_m41` 为 True 时额外启用 `kernel-test-m41` feature（M4.1 syscall
    停机验收，隐含 kernel-tests）；该测试验收后停机、不返回主流程，默认关闭。

    `release` 为 True 时以 `--release` 构建（验证正式 release 形态），
    ELF 位于 target/.../release/；否则 debug。
    """
    profile = "release" if release else "debug"
    info(f"编译内核 (target={config.TARGET}, profile={profile})")
    cmd = ["cargo", "build", "--target", config.TARGET]
    if release:
        cmd.append("--release")
    features = []
    if use_tests or use_m33 or use_m41:
        features.append("kernel-tests")
        info("测试模式：启用 kernel-tests feature（编译带自检测试的内核）")
    if use_m33:
        features.append("kernel-test-m33")
        info("M3.3：启用 kernel-test-m33 feature（用户态异常停机验收，跑完即停）")
    if use_m41:
        features.append("kernel-test-m41")
        info("M4.1：启用 kernel-test-m41 feature（syscall 停机验收，跑完即停）")
    if features:
        cmd += ["--features", ",".join(features)]
    r = subprocess.run(cmd, cwd=config.KERNEL_DIR)
    if r.returncode != 0:
        err("内核编译失败")
        return r.returncode
    elf = _kernel_elf(profile)
    if not os.path.isfile(elf):
        err(f"未找到内核 ELF: {elf}")
        return 1

    # 提取符号并重新编译嵌入（供 panic 栈回溯符号化）
    rc = gen_symbols(elf, _symbols_generated())
    if rc != 0:
        return rc
    info("重新编译以嵌入符号表 ...")
    r = subprocess.run(cmd, cwd=config.KERNEL_DIR)
    if r.returncode != 0:
        err("嵌入符号表后的二次编译失败")
        return r.returncode
    info(f"内核 ELF: {elf}")
    return 0


def _make_iso(profile: str = "debug") -> int:
    """用 xorriso 生成 BIOS+UEFI 混合引导 ISO"""
    iso_root = os.path.join(config.SDK_DIR, "iso_root")
    if os.path.isdir(iso_root):
        shutil.rmtree(iso_root)
    os.makedirs(os.path.join(iso_root, "boot", "limine"), exist_ok=True)
    os.makedirs(os.path.join(iso_root, "EFI", "BOOT"), exist_ok=True)

    # 拷贝内核
    shutil.copy(_kernel_elf(profile), os.path.join(iso_root, "boot", "kernel"))
    # 拷贝 limine.conf
    shutil.copy(config.LIMINE_CONF, os.path.join(iso_root, "boot", "limine", "limine.conf"))

    lb = config.LIMINE_BINARY_DIR
    # BIOS
    shutil.copy(os.path.join(lb, "limine-bios-cd.bin"), os.path.join(iso_root, "boot", "limine", "limine-bios-cd.bin"))
    shutil.copy(os.path.join(lb, "limine-bios.sys"), os.path.join(iso_root, "boot", "limine", "limine-bios.sys"))
    # UEFI
    shutil.copy(os.path.join(lb, "limine-uefi-cd.bin"), os.path.join(iso_root, "boot", "limine", "limine-uefi-cd.bin"))
    shutil.copy(os.path.join(lb, "BOOTX64.EFI"), os.path.join(iso_root, "EFI", "BOOT", "BOOTX64.EFI"))

    xorriso = shutil.which("xorriso") or r"C:\ffmpeg\bin\xorriso.exe"
    if not os.path.isfile(xorriso):
        err("未找到 xorriso，无法生成 ISO")
        return 1

    info("用 xorriso 生成 ISO ...")
    # 用相对路径并指定 cwd=SDK_DIR，避免 xorriso 在 Windows 上处理绝对路径出错
    cmd = [
        xorriso, "-as", "mkisofs",
        "-b", "boot/limine/limine-bios-cd.bin",
        "-no-emul-boot", "-boot-load-size", "4", "-boot-info-table",
        "--efi-boot", "boot/limine/limine-uefi-cd.bin",
        "-efi-boot-part", "--efi-boot-image", "--protective-msdos-label",
        "iso_root", "-o", config.OUTPUT_ISO,
    ]
    r = subprocess.run(cmd, cwd=config.SDK_DIR)
    if r.returncode != 0:
        err("xorriso 生成 ISO 失败")
        return r.returncode

    # BIOS 引导安装
    if not os.path.isfile(config.LIMINE_TOOL):
        err(f"未找到 limine 工具: {config.LIMINE_TOOL}")
        return 1
    info("运行 limine bios-install ...")
    r = subprocess.run([config.LIMINE_TOOL, "bios-install", config.OUTPUT_ISO])
    if r.returncode != 0:
        err("limine bios-install 失败")
        return r.returncode

    shutil.rmtree(iso_root)
    info(f"ISO 已生成: {config.OUTPUT_ISO}")
    return 0


def cmd(args: argparse.Namespace) -> int:
    """编译内核并生成可引导 ISO"""
    release = getattr(args, "release", False)
    profile = "release" if release else "debug"
    rc = _cargo_build_kernel(
        use_tests=getattr(args, "test", False),
        use_m33=getattr(args, "test_m33", False),
        use_m41=getattr(args, "test_m41", False),
        release=release,
    )
    if rc != 0:
        return rc
    return _make_iso(profile)
