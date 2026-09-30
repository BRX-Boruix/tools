"""build 子命令：编译内核并生成可引导 ISO。"""

import argparse
import os
import shutil
import subprocess

from . import config, liftoff
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

    # KM13：符号纪元——本次 tools 构建的唯一标识，贯穿两遍编译与符号生成。
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
    if os.environ.get("BORUIX_HDA_PROBE") == "1":
        features.append("hda-probe")
        info("诊断：启用 hda-probe feature（HDA 设备 DMA 前端探针，随常规测试序列运行）")
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


def _make_iso(profile: str = "debug", liftoff_only: bool = False) -> int:
    """用 xorriso 生成 BIOS-only 引导 ISO（完全走 brxLimine fork，不依赖官方 limine-binary）"""
    from . import disk
    iso_root = os.path.join(config.TOOLS_DIR, "iso_root")
    if os.path.isdir(iso_root):
        shutil.rmtree(iso_root)
    os.makedirs(os.path.join(iso_root, "boot", "limine"), exist_ok=True)

    # 拷贝内核
    shutil.copy(_kernel_elf(profile), os.path.join(iso_root, "boot", "kernel"))
    # 拷贝 limine.conf
    shutil.copy(config.LIMINE_CONF, os.path.join(iso_root, "boot", "limine", "limine.conf"))

    # brxLimine fork 产物（BIOS stage1 cd + stage2 sys）
    fork_cd = config.BRXLIMINE_CD_BIN
    fork_sys = config.BRXLIMINE_BIOS_SYS
    # --liftoff：UEFI 从 ESP 引导，ISO 只需文件（/boot/kernel、/programs），与 BIOS 引导码无关
    # → 跳过 fork 产物，也就摆脱了 i686-elf 交叉工具链依赖。
    if not liftoff_only and (not os.path.isfile(fork_cd) or not os.path.isfile(fork_sys)):
        err(f"缺 brxLimine fork 引导产物: {fork_cd} / {fork_sys}\n请先 limine-build 交叉编译 brxLimine 生成 bin/文件")
        return 1
    if not liftoff_only:
        shutil.copy(fork_cd, os.path.join(iso_root, "boot", "limine", "limine-bios-cd.bin"))
        shutil.copy(fork_sys, os.path.join(iso_root, "boot", "limine", "limine-bios.sys"))

    # B2 载体迁移：/programs 变成 **ISO 内真目录**（owner 裁决：介质即系统）。
    # 用户程序 ELF 由 _build_userspace 复制到 crates/kernel/{name}.elf，此处
    # 原样拷入 iso_root/programs/——内核把 ISO 的 /programs 子目录挂为 VFS
    # /programs（零复制、拖入即装），`binaries_payload.rs` 内嵌已退役。
    # 拷贝清单与退役的 payload 完全同口径（USER_PROGRAMS + C 演示程序，
    # S15 单一名单语义），杜绝「编译了但没进 ISO」的运行期漏配。
    extra_programs = (
        "chelldemo",
        "pthreaddemo",
        "pthread_syncdemo",
        "pthread_bench",
        "forkdemo",
    )
    prog_dir = os.path.join(iso_root, "programs")
    os.makedirs(prog_dir, exist_ok=True)
    for name in USER_PROGRAMS + extra_programs:
        elf = os.path.join(config.KERNEL_DIR, "crates", "kernel", name + ".elf")
        if not os.path.isfile(elf):
            err(f"ISO /programs 依赖的用户程序 ELF 缺失: {elf}（先执行 _build_userspace）")
            return 1
        shutil.copy(elf, os.path.join(prog_dir, name + ".elf"))

    xorriso = config.XORRISO
    if not os.path.isfile(xorriso):
        err("未找到 xorriso，无法生成 ISO")
        return 1

    info("用 xorriso 生成 ISO ...")
    # 用相对路径并指定 cwd=TOOLS_DIR，避免 xorriso 在 Windows 上处理绝对路径出错
    #
    # -file-mode 0555 / -dir-mode 0755（xorriso 扩展，mkisofs 兼容模式可用）：
    # Windows 源文件无 Unix 执行位，xorriso 默认照搬（644）——PX mode 无 x
    # 会让内核 A1-3 EXEC 强制拒绝执行介质程序（实测 login 崩于 spawn shell）。
    # 系统介质的权限语义 = 「人人可读可执行、无可写」（与退役 payload 的
    # 0o555 同一口径，S15：语义不因载体迁移漂移）。Rock Ridge PX 消费侧
    #（iso9660 驱动）读到 0555 即如实执行。
    cmd = [
        xorriso, "-as", "mkisofs",
        "-file-mode", "0555", "-dir-mode", "0755",
    ]
    if not liftoff_only:
        # BIOS El Torito 引导项（--liftoff 不需要：UEFI 从 ESP 引导）
        cmd += [
            "-b", "boot/limine/limine-bios-cd.bin",
            "-no-emul-boot", "-boot-load-size", "4", "-boot-info-table",
            "--protective-msdos-label",
        ]
    cmd += ["iso_root", "-o", config.OUTPUT_ISO]
    r = subprocess.run(cmd, cwd=config.TOOLS_DIR)
    if r.returncode != 0:
        err("xorriso 生成 ISO 失败")
        return r.returncode

    # 把 fork stage1（isohybrid MBR 启动区）写进 ISO：等价于 `limine bios-install`，但数据来自 fork，不依赖官方 limine.exe
    if not liftoff_only:
        with open(fork_cd, "rb") as f:
            fork_cd_bin = f.read()
        rc = disk.install_fork_limine_iso(config.OUTPUT_ISO, fork_cd_bin)
        if rc != 0:
            return rc

    shutil.rmtree(iso_root)
    info(f"ISO 已生成: {config.OUTPUT_ISO}")
    return 0


# 用户程序清单（**单点定义**）。
#
# 此前同一份名单在 build.py 里出现两次（一次用于编译、一次用于装进系统盘），
# 增删程序时必须同时改两处，漏一处就会在运行期表现为「程序莫名不存在」。
# 收敛为一个常量后，两处消费同一来源（S15 单点定义）。
#
# 顺序即 liveCD payload 的排列顺序；列表内容 = 内核 crates/kernel/ 下的 <name>.elf。
USER_PROGRAMS = (
    "init",
    "shell",
    "volumed",
    "synce2e",
    "acee2e",
    "trave2e",
    "pwde2e",
    "login",
    "fpcheck",
    "tokendemo",
    # `focusdemo`：ADR-048 T3 焦点门禁的**对抗验收**——以默认用户身份
    # 调 FOCUS_SET(1)，内核必须 EACCES 拒绝（CAP_SYSTEM 门禁真拦）。
    # 见 docs/adr/048-multi-terminal-console-instances-focus.md §3.1。
    "focusdemo",
    "spinburn",
    # `yielder`：纯忙-yield 压测进程（不 sleep、不阻塞），用于判定实验——
    # 验证「唯一就绪进程 busy-yield」是否会饿死其它进程。
    # 见 docs/TODO/terminal-input.md 6.12.8。
    "yielder",
    # `evdemo`：I-EVENTS 阶段 2 的事件流端到端验收程序——直接 open/read
    # `/devices/input/events`，经 `libsys::event` 转换层回显每个按键。
    # 证明「事件流可被用户态消费、产出正确字节，且空读在内核阻塞而非自旋」。
    # 见 docs/TODO/terminal-input.md §6.13。
    "evdemo",
    # `evsrcdemo`：`libline::EventSource`（**组件路径**）的真机验收。
    # 与 `evdemo` 的差别：evdemo 是**诊断形态**，手搓 open/read/parse/feed，
    # 绕开了 `EventSource`；故 `EventSource` 此前只有宿主单测、从未上真机。
    # 本题补上该缺口——阶段 3「最小形态」要让 shell/login 改用 `EventSource`，
    # 组件若不先在真机验过，阶段 3 一上线就炸。
    # 见 docs/TODO/terminal-input.md §6.14.4g。
    "evsrcdemo",
    # `blkdemo`：**诊断对照**——前台阻塞在 stdin（旧字节路径）。
    # 与 `evdemo` 的唯一差别是等待源（`KBD_WAITER` vs `IN_EVENT_WAITER`），
    # 用来判定 §6.13 的 CPU 缺陷归属。见 docs/TODO/terminal-input.md §6.13。
    "blkdemo",
    # `consoled`：I-EVENTS 阶段 3 甲-a（ADR-045）——常驻字节生产者：事件流 →
    # libsys keymap → /devices/console。P4 切换前无读者消费其产出，
    # 上线本身零行为变化（见 docs/TODO/terminal-input.md §6.15.3）。
    "consoled",
    # `consoled-e2e`：console 环端到端阻塞-唤醒验收（writer/consumer 双角色），
    # 经真实 syscall 跑完 CONSOLE_WAITER 的 park/wake 全往返。
    # 见 docs/TODO/terminal-input.md §6.15.3。
    "consoled-e2e",
    # `openvt`: B3-C3 用户入口——写请求文件 /system/console-requests/<n>，
    # init 巡检消费（文件协议，零新 syscall）。见 docs/TODO/terminal-input.md §8。
    "openvt",
    "threaddemo",
    "userdrv",
    "driverd",
    "userd",
    "intel-hda",
    "audioe2e",
    "audiod",
    "audiofile",
    "selftest",
)

def _build_userspace() -> int:
    """编译用户程序（libsys + init + shell），生成 ELF 供内核 liveCD 内嵌。

    用户程序是 Rust no_std 独立 bin crate，依赖 libsys 薄封装调 syscall。
    每个编译产物复制到内核源码目录 `crates/kernel/<name>.elf`；内核的
    liveCD payload（`src/binaries_payload.rs`，`_write_binaries_payload` 生成）
    经 include_bytes! 嵌入——无外部盘时系统也能启动（ADR-017）。
    """
    # (源目录, 产物 bin 名)
    # 源目录名与产物名目前一一对应；用同一份 USER_PROGRAMS 派生，
    # 避免「编译了但没进 payload」这类只在运行期才暴露的漏配。
    programs = [(name, name) for name in USER_PROGRAMS]
    for src, bin_name in programs:
        dir_ = os.path.join(config.PROJECT_ROOT, src)
        info(f"编译用户程序 ({src} + libsys)")
        cmd = [
            "cargo", "build",
            "--manifest-path", os.path.join(dir_, "Cargo.toml"),
            "--target", config.TARGET,
            "--release",
        ]
        # init 的构建期开关（见 init/build.rs）：内核以空 argv spawn init，
        # 且本仓无 kernel cmdline，故 init 的运行期开关只能靠**构建期**注入。
        # 这里让 init 释放后仍进入交互 shell（**不**自动跑 selftest）——自动化验收
        # 另用 `BORUIX_INIT_ARGS` 环境变量覆盖，正常构建行为完全不变。
        env = dict(os.environ)
        if src == "init":
            env.setdefault("BORUIX_INIT_ARGS", "")
        r = subprocess.run(cmd, cwd=config.PROJECT_ROOT, env=env)
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
        ("pthread_syncdemo", "prog", ["thread.c", "pthread.c", "pthread_sync.c"]),
        ("pthread_bench", "prog", ["thread.c", "pthread.c", "pthread_sync.c", "stdio.c"]),
        # ADR-038 U1/D5：真实 C 用户态 fork()+waitpid() 端到端验收（零 Rust libc）。
        ("forkdemo", "prog", []),
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



def _make_system_disk(profile: str = "debug", liftoff_only: bool = False) -> int:
    """生成可引导系统盘 systemdisk.img（ADR-029 安装模式）。

    内容：/boot/kernel=内核 ELF、/boot/limine/limine.conf + limine-bios.sys、
    /programs/{USER_PROGRAMS 全清单}.elf（来自 _build_userspace 写入内核
    crates 目录的真实 ELF），随后把 Limine BIOS 引导器装进盘。
    B2 载体迁移后这是 **SYSTEMDISK 选项**的程序载体（EXT2 系统盘内真目录）；
    ISO 载体的对应面见 _make_iso 的 iso_root/programs/。数据盘不参与。

    完全走 brxLimine fork 的 stage1/stage2（stage2 内含 EXT2 驱动）引导，
    使系统盘能从 EXT2 分区加载 stage2 并定位内核（stock 引导器不含 EXT2
    驱动，会停在 "Stage 3 file not found"）。不依赖官方 limine-binary。
    """
    from . import disk
    kernel_elf = _kernel_elf(profile)
    if not os.path.isfile(kernel_elf):
        err("未找到内核 ELF: " + kernel_elf)
        return 1
    with open(kernel_elf, "rb") as f:
        kernel = f.read()
    programs = {}
    for name in USER_PROGRAMS:
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
    # brxLimine fork：stage3 sys 与 stage1/2 均来自 fork 构建产物。
    # --liftoff：liftoff 直接读 EXT2 的 /boot/kernel，不需要盘上的 BIOS 引导码。
    limine_bios_sys = config.BRXLIMINE_BIOS_SYS
    if not liftoff_only and not os.path.isfile(limine_bios_sys):
        err("未找到 fork limine-bios.sys: " + limine_bios_sys + "（先 limine-build 交叉编译 brxLimine）")
        return 1
    limine_bios = b""
    if os.path.isfile(limine_bios_sys):
        with open(limine_bios_sys, "rb") as f:
            limine_bios = f.read()
    if not liftoff_only and not os.path.isfile(config.BRXLIMINE_HDD_BIN):
        err("未找到 fork limine-bios-hdd.bin: " + config.BRXLIMINE_HDD_BIN)
        return 1
    disk.create_system_disk_image(
        disk.SYSTEM_DISK_IMG_PATH, kernel, programs, limine_conf, limine_bios
    )
    if not liftoff_only:
        with open(config.BRXLIMINE_HDD_BIN, "rb") as f:
            fork_hdd_bin = f.read()
        rc = disk.install_fork_limine_bios(disk.SYSTEM_DISK_IMG_PATH, fork_hdd_bin)
        if rc != 0:
            return rc
    info("系统盘已生成: " + disk.SYSTEM_DISK_IMG_PATH)
    return 0



def cmd(args: argparse.Namespace) -> int:
    """编译内核并生成可引导 ISO"""
    release = getattr(args, "release", False)
    profile = "release" if release else "debug"
    # 生产化（boot→init）：无条件先编译用户程序（libsys + init）。B2 载体
    # 迁移后 ELF 不再内嵌内核（binaries_payload 退役），改为进入 ISO 的
    # /programs/ 真目录（_make_iso）或系统盘 EXT2（_make_system_disk）。
    # 内核生产路径 `start_init` 始终加载 init.elf，无论是否测试模式都必须
    # 先编译用户程序，否则 ISO 组装失败。
    rc = _build_userspace()
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
    # --systemdisk：产系统盘而非 ISO（ADR-029 安装模式，恒走 brxLimine fork）。
    liftoff_only = bool(getattr(args, "liftoff", False))
    if getattr(args, "systemdisk", False):
        rc = _make_system_disk(profile, liftoff_only=liftoff_only)
    else:
        rc = _make_iso(profile, liftoff_only=liftoff_only)
    if rc != 0:
        return rc
    # --liftoff：介质不变（ISO/systemdisk 里已有 /boot/kernel 与 /programs），
    # 只追加 liftoff.efi 与 ESP；brxLimine 的 BIOS 路径原样保留（同一张盘双启）。
    if getattr(args, "liftoff", False):
        liftoff.build_efi()
        esp = liftoff.stage_esp()
        info("liftoff ESP: " + esp + " (EFI/BOOT/BOOTX64.EFI)")
    return rc
