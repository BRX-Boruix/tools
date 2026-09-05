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
    use_pre2: bool = False,
    use_m33: bool = False,
    use_m41: bool = False,
    use_m42: bool = False,
    use_m43: bool = False,
    use_m44: bool = False,
    use_m5: bool = False,
    use_waitpid: bool = False,
    use_signal: bool = False,
    signal_halt: str = "nested",
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

    `use_m42` 为 True 时额外启用 `kernel-test-m42` feature（M4.2 调度器
    停机验收，隐含 kernel-tests）；该测试验收后停机、不返回主流程，默认关闭。

    `use_m43` 为 True 时额外启用 `kernel-test-m43` feature（M4.3 静态 ELF
    加载验收，隐含 kernel-tests）；该测试验收后停机、不返回主流程，默认关闭。

    `use_m44` 为 True 时额外启用 `kernel-test-m44` feature（M4.4 真实用户
    程序验收，隐含 kernel-tests）；该测试验收后停机、不返回主流程，默认关闭。

    `use_m5` 为 True 时额外启用 `kernel-test-m5` feature（M5 写时复制 COW
    验收，隐含 kernel-tests）；纯内存逻辑，返回主流程继续启动，默认关闭。

    `use_waitpid` 为 True 时额外启用 `kernel-test-waitpid` feature（C7.1/#7
    waitpid 真实父子链停机验收，隐含 kernel-tests）；该测试验收后停机、
    不返回主流程，默认关闭。

    `release` 为 True 时以 `--release` 构建（验证正式 release 形态），
    ELF 位于 target/.../release/；否则 debug。
    """
    profile = "release" if release else "debug"
    info(f"编译内核 (target={config.TARGET}, profile={profile})")

    # KM13：符号纪元——本次 SDK 构建的唯一标识，贯穿两遍编译与符号生成。
    # 内核运行时比对"嵌入符号表的纪元"与"本二进制编译纪元"，不一致即
    # 直连 cargo build 用了 checked-in 陈旧快照，启动横幅如实告警。
    import time
    symbols_epoch = int(time.time() * 1000)
    env = dict(os.environ, BORUIX_SYMBOLS_EPOCH=str(symbols_epoch))

    cmd = ["cargo", "build", "--target", config.TARGET]
    if release:
        cmd.append("--release")
    features = []
    if use_tests or use_m33 or use_m41 or use_m42 or use_m43 or use_m44 or use_m5 or use_waitpid or use_pre2 or use_signal:
        features.append("kernel-tests")
    if use_signal:
        # 停机验收互斥：signal_halt 选择启用哪个 halt 测试 feature（handler/fault/nested），
        # 各自独立 build+QEMU 运行（跑完即停）。
        if signal_halt == "handler":
            features.append("kernel-test-signal-handler")
        elif signal_halt == "fault":
            features.append("kernel-test-signal-fault")
        else:
            features.append("kernel-test-signal-nested")
        info(f"ADR-034 S1-13：启用 kernel-test-signal-{signal_halt} feature，停机验收跑完即停")
        info("测试模式：启用 kernel-tests feature（编译带自检测试的内核）")
    if use_pre2:
        features.append("kernel-test-pre2")
        info("ADR-034 PRE-2：启用 kernel-test-pre2 feature（用户态 #PF CR2 透传验收，跑完即停）")
    if use_m33:
        features.append("kernel-test-m33")
        info("M3.3：启用 kernel-test-m33 feature（用户态异常停机验收，跑完即停）")
    if use_m41:
        features.append("kernel-test-m41")
        info("M4.1：启用 kernel-test-m41 feature（syscall 停机验收，跑完即停）")
    if use_m42:
        features.append("kernel-test-m42")
        info("M4.2：启用 kernel-test-m42 feature（调度器停机验收，跑完即停）")
    if use_m43:
        features.append("kernel-test-m43")
        info("M4.3：启用 kernel-test-m43 feature（静态 ELF 加载验收，跑完即停）")
    if use_m44:
        features.append("kernel-test-m44")
        info("M4.4：启用 kernel-test-m44 feature（真实用户程序验收，跑完即停）")
    if use_m5:
        features.append("kernel-test-m5")
        info("M5：启用 kernel-test-m5 feature（写时复制 COW 验收，纯内存逻辑）")
    if use_waitpid:
        features.append("kernel-test-waitpid")
        info("C7.1/#7：启用 kernel-test-waitpid feature（waitpid 父子链停机验收，跑完即停）")
    if features:
        cmd += ["--features", ",".join(features)]
    r = subprocess.run(cmd, cwd=config.KERNEL_DIR, env=env)
    if r.returncode != 0:
        err("内核编译失败")
        return r.returncode
    elf = _kernel_elf(profile)
    if not os.path.isfile(elf):
        err(f"未找到内核 ELF: {elf}")
        return 1

    # 提取符号并重新编译嵌入（供 panic 栈回溯符号化）
    rc = gen_symbols(elf, _symbols_generated(), epoch=symbols_epoch)
    if rc != 0:
        return rc
    info("重新编译以嵌入符号表 ...")
    r = subprocess.run(cmd, cwd=config.KERNEL_DIR, env=env)
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


def _build_userspace() -> int:
    """编译用户程序（libsys + init + shell），生成 ELF 供内核 liveCD 内嵌。

    用户程序是 Rust no_std 独立 bin crate，依赖 libsys 薄封装调 syscall。
    每个编译产物复制到内核源码目录 `crates/kernel/<name>.elf`；内核的
    liveCD payload（`src/binaries_payload.rs`，`_write_binaries_payload` 生成）
    经 include_bytes! 嵌入——无外部盘时系统也能启动（ADR-017）。
    """
    # (源目录, 产物 bin 名)
    programs = [("init", "init"), ("shell", "shell"), ("volumed", "volumed"), ("synce2e", "synce2e"), ("fpcheck", "fpcheck"), ("spinburn", "spinburn"), ("threaddemo", "threaddemo")]
    for src, bin_name in programs:
        dir_ = os.path.join(config.PROJECT_ROOT, src)
        info(f"编译用户程序 ({src} + libsys)")
        cmd = [
            "cargo", "build",
            "--manifest-path", os.path.join(dir_, "Cargo.toml"),
            "--target", config.TARGET,
            "--release",
        ]
        r = subprocess.run(cmd, cwd=config.PROJECT_ROOT)
        if r.returncode != 0:
            err(f"用户程序 {src} 编译失败")
            return r.returncode
        elf = os.path.join(dir_, "target", config.TARGET, "release", bin_name)
        if not os.path.isfile(elf):
            err(f"未找到 {src} ELF: {elf}")
            return 1
        dst = os.path.join(config.KERNEL_DIR, "crates", "kernel", f"{bin_name}.elf")
        shutil.copy(elf, dst)
        info(f"{src} ELF 已复制到内核源码目录: {dst}")
    # T2-0：freestanding C 程序（x86-64 clang/lld 交叉链 + csrc/crt0+crtrt，零 Rust libc）。
    # 经 csrc/build_c.py 编译并复制到 crates/kernel/<name>.elf。
    c_build = os.path.join(config.PROJECT_ROOT, "csrc", "build_c.py")
    # (name, src_dir, extra_rt...) — pthread 程序需 thread.c+pthread.c 运行时。
    c_progs = [
        ("chelldemo", "prog", []),
        ("pthreaddemo", "prog", ["thread.c", "pthread.c"]),
    ]
    c_build_dir = os.path.join(config.PROJECT_ROOT, "csrc", "_build")
    for cprog in c_progs:
        cname, csrcdir, extra_rt = cprog[0], cprog[1], cprog[2]
        info(f"编译 C 程序 ({cname}, freestanding clang/lld)")
        r = subprocess.run(["python", c_build, cname, csrcdir, c_build_dir] + extra_rt, cwd=os.path.join(config.PROJECT_ROOT, "csrc"))
        if r.returncode != 0:
            err(f"C 程序 {cname} 编译失败")
            return r.returncode
        celf = os.path.join(c_build_dir, f"{cname}.elf")
        if not os.path.isfile(celf):
            err(f"未找到 {cname} ELF: {celf}")
            return 1
        cdst = os.path.join(config.KERNEL_DIR, "crates", "kernel", f"{cname}.elf")
        shutil.copy(celf, cdst)
        info(f"{cname} ELF 已复制到内核源码目录: {cdst}")
    return 0


_PAYLOAD_RS = "binaries_payload.rs"


def _write_binaries_payload() -> int:
    """生成 liveCD 内置用户程序 payload 源文件（crates/kernel/src/binaries_payload.rs）。

    数据源 = `_build_userspace` 刚复制到 `crates/kernel/{init,shell}.elf` 的真实
    ELF（S06 真实链路）；缺失即报错拒绝生成，绝不伪造空 payload（S09）。
    源文件用 `include_bytes!(concat!(env!("CARGO_MANIFEST_DIR"), ...))` 引用
    ——相对 cargo 环境、无硬编码绝对路径（S01）。
    """
    kernel_crate = os.path.join(config.KERNEL_DIR, "crates", "kernel")
    src_dir = os.path.join(kernel_crate, "src")
    payloads = [
        ("init.elf", "INIT_ELF"),
        ("shell.elf", "SHELL_ELF"),
        ("volumed.elf", "VOLUMED_ELF"),
        ("synce2e.elf", "SYNCE2E_ELF"),
        ("fpcheck.elf", "FPCHECK_ELF"),
        ("spinburn.elf", "SPINBURN_ELF"),
        ("threaddemo.elf", "THREADDEMO_ELF"),
        ("chelldemo.elf", "CHELLDEMO_ELF"),
        ("pthreaddemo.elf", "PTHREADDEMO_ELF"),
    ]
    missing = [
        n for n, _ in payloads if not os.path.isfile(os.path.join(kernel_crate, n))
    ]
    if missing:
        err(f"liveCD payload 依赖的用户程序 ELF 缺失: {missing}（先执行 _build_userspace）")
        return 1
    lines = [
        "// @generated by sdk/sdk_build/build.py —— liveCD 内置用户程序 payload（ADR-017）。",
        "// 勿手改：每次构建由 SDK 依据 crates/kernel/{init,shell,volumed}.elf 重新生成。",
        "// 语义：无外部盘时内核用此 payload 填充 /programs 完成启动（liveCD）；",
        "// 外部盘 EXT2 挂载成功后整体覆盖 /programs（盘优先）。",
        "// 文件名 binaries_payload.rs 为生成产物契约名，历史沿用（ADR-005 词法 v2）。",
        "#![allow(dead_code)]",
        "",
        "/// liveCD 内置用户程序（ELF 字节镜像）。",
        "pub struct Payload {",
        "    pub name: &'static str,",
        "    pub data: &'static [u8],",
        "}",
        "",
    ]
    for name, ident in payloads:
        lines.append(
            f"pub static {ident}: &[u8] =\n"
            f"    include_bytes!(concat!(env!(\"CARGO_MANIFEST_DIR\"), \"/{name}\"));"
        )
        lines.append("")
    lines.append("/// 按文件名索引的 payload 列表（写入顺序即枚举顺序）。")
    lines.append("pub const PAYLOADS: &[Payload] = &[")
    for name, ident in payloads:
        lines.append(f'    Payload {{ name: "{name}", data: {ident} }},')
    lines.append("];")
    out = os.path.join(src_dir, _PAYLOAD_RS)
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    sizes = ", ".join(
        f"{n}={os.path.getsize(os.path.join(kernel_crate, n))}B" for n, _ in payloads
    )
    info(f"liveCD payload 已生成: {out} ({sizes})")
    return 0


def _make_system_disk(profile: str = "debug", use_fork: bool = False) -> int:
    """生成可引导系统盘 systemdisk.img（ADR-029 安装模式）。

    内容：/boot/kernel=内核 ELF、/boot/limine/limine.conf + limine-bios.sys、
    /programs/{init,shell,volumed,synce2e,fpcheck}.elf（来自 _build_userspace 写入内核
    crates 目录的真实 ELF），随后把 Limine BIOS 引导器装进盘。

    use_fork=True：改用 brxLimine fork 的 stage1/stage2（stage2 内含 EXT2 驱动）
    引导，使系统盘能从 EXT2 分区加载 stage2 并定位内核（stock 引导器不含
    EXT2 驱动，会停在 "Stage 3 file not found"）。
    """
    from . import disk
    kernel_elf = _kernel_elf(profile)
    if not os.path.isfile(kernel_elf):
        err("未找到内核 ELF: " + kernel_elf)
        return 1
    with open(kernel_elf, "rb") as f:
        kernel = f.read()
    programs = {}
    for name in ("init", "shell", "volumed", "synce2e", "fpcheck", "spinburn", "threaddemo"):
        elf = os.path.join(config.KERNEL_DIR, "crates", "kernel", name + ".elf")
        if not os.path.isfile(elf):
            err("未找到用户程序 ELF: " + elf)
            return 1
        with open(elf, "rb") as f:
            programs[name] = f.read()
    if not os.path.isfile(config.LIMINE_CONF):
        err("未找到 limine.conf: " + config.LIMINE_CONF)
        return 1
    with open(config.LIMINE_CONF, "rb") as f:
        limine_conf = f.read()
    if use_fork:
        # brxLimine fork：stage3 sys 与 stage1/2 均来自 fork 构建产物。
        limine_bios_sys = config.BRXLIMINE_BIOS_SYS
        if not os.path.isfile(limine_bios_sys):
            err("未找到 fork limine-bios.sys: " + limine_bios_sys + "（先 limine-build 交叉编译 brxLimine）")
            return 1
        with open(limine_bios_sys, "rb") as f:
            limine_bios = f.read()
        if not os.path.isfile(config.BRXLIMINE_HDD_BIN):
            err("未找到 fork limine-bios-hdd.bin: " + config.BRXLIMINE_HDD_BIN)
            return 1
        with open(config.BRXLIMINE_HDD_BIN, "rb") as f:
            fork_hdd_bin = f.read()
    else:
        limine_bios_sys = os.path.join(config.LIMINE_BINARY_DIR, "limine-bios.sys")
        if not os.path.isfile(limine_bios_sys):
            err("未找到 limine-bios.sys: " + limine_bios_sys + "（先运行 limine 部署）")
            return 1
        with open(limine_bios_sys, "rb") as f:
            limine_bios = f.read()
    disk.create_system_disk_image(
        disk.SYSTEM_DISK_IMG_PATH, kernel, programs, limine_conf, limine_bios
    )
    if use_fork:
        rc = disk.install_fork_limine_bios(disk.SYSTEM_DISK_IMG_PATH, fork_hdd_bin)
    else:
        rc = disk.install_limine_bios(disk.SYSTEM_DISK_IMG_PATH)
    if rc != 0:
        return rc
    info("系统盘已生成: " + disk.SYSTEM_DISK_IMG_PATH)
    return 0



def cmd(args: argparse.Namespace) -> int:
    """编译内核并生成可引导 ISO"""
    release = getattr(args, "release", False)
    profile = "release" if release else "debug"
    # 生产化（boot→init）：无条件先编译用户程序（libsys + init），供内核
    # liveCD payload 嵌入（ADR-017，`_write_binaries_payload` 生成
    # include_bytes! 源文件，编译期需要）。内核生产路径 `start_init` 始终
    # 加载 init.elf，故无论是否测试模式都必须生成，否则编译失败。
    rc = _build_userspace()
    if rc != 0:
        return rc
    rc = _write_binaries_payload()
    if rc != 0:
        return rc
    rc = _cargo_build_kernel(
        use_tests=getattr(args, "test", False),
        use_pre2=getattr(args, "test_pre2", False),
        use_m33=getattr(args, "test_m33", False),
        use_m41=getattr(args, "test_m41", False),
        use_m42=getattr(args, "test_m42", False),
        use_m43=getattr(args, "test_m43", False),
        use_m44=getattr(args, "test_m44", False),
        use_m5=getattr(args, "test_m5", False),
        use_waitpid=getattr(args, "test_waitpid", False),
        use_signal=getattr(args, "test_signal", False),
        signal_halt=getattr(args, "signal_halt", "nested"),
        release=release,
    )
    if rc != 0:
        return rc
    # --systemdisk：产系统盘而非 ISO（ADR-029 安装模式）。
    if getattr(args, "systemdisk", False):
        return _make_system_disk(
            profile,
            use_fork=getattr(args, "brxlimine", False),
        )
    return _make_iso(profile)