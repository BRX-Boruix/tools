"""BORUIX 系统工具（tools/）的公共配置。

集中管理路径常量与 .env 环境变量读取，避免各子命令重复定义。
"""

import os
import shutil

# 路径
TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(TOOLS_DIR)
KERNEL_DIR = os.path.join(PROJECT_ROOT, "kernel")
LIMINE_CONF = os.path.join(TOOLS_DIR, "limine.conf")
ENV_FILE = os.path.join(PROJECT_ROOT, ".env")

# ISO 里内核 ELF 的路径分量。引导器按 ISO9660 读的是同一份；诊断工具必须**按路径查**，
# 不能写死逻辑块号——那是某一次构建的实测值，ISO 一变就静默指向错误位置（S13/S15：
# 单点定义，且语义常量不散落在调用方）。
KERNEL_ISO_COMPONENTS = ("boot", "kernel")

# 构建目标（当前仅 x86_64）
TARGET = "x86_64-unknown-none"
QEMU = "qemu-system-x86_64"

# 用户态程序的 TLS 模型（3P4-1）：local-exec。
#
# 为何必须显式指定：本 target 的默认模型是 general-dynamic，会产出
# R_X86_64_DTPOFF32 并要求 __tls_get_addr 与动态重定位——本系统没有动态链接器，
# 那种形态装载不了。local-exec 的偏移在**链接期**解析（R_X86_64_TPOFF32），
# 运行时零依赖，静态加载器可直接支持。
#
# 注入方式：经 CARGO_TARGET_<TRIPLE>_RUSTFLAGS（**目标域**）而非 RUSTFLAGS——
# 后者会连带作用于宿主 build script，而 -Z 旗标在宿主上无意义。
TARGET_RUSTFLAGS = "-Ztls-model=local-exec"


def userspace_env(base=None) -> dict:
    """用户态程序构建环境：在 base（默认 os.environ）上注入目标域 RUSTFLAGS。

    已有同名环境变量时**追加**而非覆盖：调用方显式设的旗标必须保留
    （自动逻辑可手动覆盖），而 TLS 模型是本系统正确性的硬要求，不能被抹掉。
    """
    env = dict(os.environ if base is None else base)
    key = "CARGO_TARGET_" + TARGET.upper().replace("-", "_") + "_RUSTFLAGS"
    env[key] = (env.get(key, "") + " " + TARGET_RUSTFLAGS).strip()
    return env
# ISO 输出路径。默认 <root>/boruix.iso（S17：与所有既有脚本/e2e 的接线一致）。
# 可用 BORUIX_ISO_OUT 显式覆盖（S16：构建产物路径可配置——多工作区/CI 矩阵
# 与「目标文件被System 持锁」这类环境事故下的显式逃生门；覆盖是全局的，
# e2e 脚本同样读 config.OUTPUT_ISO，无第二份真值）。
OUTPUT_ISO = os.environ.get("BORUIX_ISO_OUT") or os.path.join(
    PROJECT_ROOT, "boruix.iso"
)

# ---------- 声卡（ICH6 / Intel HDA）----------
#
# BORUIX 的 `intel-hda` 用户态驱动接管的是 **PCI 8086:2668**（ICH6 控制器），
# 即 QEMU 的 `-device intel-hda`（控制器）+ `-device hda-output`（codec/输出）。
# 两者缺一不可：没有 `intel-hda` 就没有控制器，没有 `hda-output` 就没有 codec，
# 驱动探测不到设备就不会注册 `/devices/audio/dsp`，`audiofile` 也无从播放。
#
# `-audiodev` 决定声卡的输出端接到哪里，即「喇叭是谁」：
#   dsound -> 宿主 Windows 的本机喇叭（默认，用于真的听声音）
#   wav    -> 落盘成文件（`--silent`，用于无声卡环境/留档比对）
# 硬件侧（寄存器、DMA 环、codec 配置）与选哪个无关，两条路走的是同一套代码。
SOUND_CARD_CONTROLLER = "intel-hda"
SOUND_CARD_OUTPUT = "hda-output"
AUDIODEV_ID = "snd0"
# 宿主音频后端：dsound = 本机喇叭。
HOST_AUDIODEV = "dsound"
# --silent 时的落盘路径。
OUTPUT_WAV = os.path.join(PROJECT_ROOT, "audio-out.wav")


def sound_card_args(silent=False, path=None):
    """声卡相关 QEMU 参数：audiodev + intel-hda 控制器 + hda-output。

    默认把声音送到**宿主本机喇叭**（dsound）。`silent=True` 时改为落盘成 WAV，
    供没有音频设备的机器（CI）或需要事后留档的场合使用。

    单点定义（S15）：起机器的所有路径都从这里取，避免各子命令各写一份、
    改一处漏一处（本项目已在用户程序清单上吃过三份副本的亏）。
    """
    if silent:
        audiodev = "wav,id=%s,path=%s" % (AUDIODEV_ID, path or OUTPUT_WAV)
    else:
        audiodev = "%s,id=%s" % (HOST_AUDIODEV, AUDIODEV_ID)
    return [
        "-audiodev", audiodev,
        "-device", SOUND_CARD_CONTROLLER,
        "-device", "%s,audiodev=%s" % (SOUND_CARD_OUTPUT, AUDIODEV_ID),
    ]


def audiodev_desc(silent=False):
    """声卡输出端的一句话描述（打印用，避免日志与实际参数不符）。"""
    if silent:
        return "intel-hda + hda-output -> %s" % os.path.basename(OUTPUT_WAV)
    return "intel-hda + hda-output -> 本机喇叭 (%s)" % HOST_AUDIODEV

# 项目 envfiles 目录（工具链等外部依赖的解压产物）
ENVFILES_DIR = os.path.join(PROJECT_ROOT, "envfiles")

# Limine fork 源码根目录（brxLimine）
BRXLIMINE_DIR = os.path.join(PROJECT_ROOT, "brxLimine")
# brxLimine 构建产物目录（含 EXT2 驱动的 BIOS stage1/2）
BRXLIMINE_BIN_DIR = os.path.join(BRXLIMINE_DIR, "bin")
BRXLIMINE_HDD_BIN = os.path.join(BRXLIMINE_BIN_DIR, "limine-bios-hdd.bin")
BRXLIMINE_CD_BIN = os.path.join(BRXLIMINE_BIN_DIR, "limine-bios-cd.bin")
BRXLIMINE_BIOS_SYS = os.path.join(BRXLIMINE_BIN_DIR, "limine-bios.sys")


def load_env() -> dict:
    """读取项目根目录 .env 文件为 dict。"""
    env = {}
    if os.path.isfile(ENV_FILE):
        with open(ENV_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip().strip('"').strip("'")
    return env


# i686-elf 交叉编译器目录（用于 Limine BIOS stage2 交叉编译）。
# 优先取 .env 的 I686_ELF_GCC_DIR，否则回退到 envfiles/i686-elf-tools。
_ENV = load_env()
I686_ELF_GCC_DIR = _ENV.get("I686_ELF_GCC_DIR") or os.path.join(ENVFILES_DIR, "i686-elf-tools")
I686_ELF_GCC = os.path.join(I686_ELF_GCC_DIR, "bin", "i686-elf-gcc.exe")

# xorriso（生成 ISO 的组装器）：PATH → 项目自备 MSYS2 → ffmpeg 附带。
# 单一真值（S15）：build.py 只读本常量，不各自 which。
def _find_xorriso() -> str:
    found = shutil.which("xorriso")
    if found:
        return found
    msys2 = _ENV.get("MSYS2_DIR")
    if msys2:
        p = os.path.join(msys2, "usr", "bin", "xorriso.exe")
        if os.path.isfile(p):
            return p
    # 最后手段：**交给 PATH**—— 此前这里写死了 `C:\ffmpeg\bin\xorriso.exe`，
    # 那是**本机特有**的路径（S01 禁止：换一台机器就得改代码）。
    # 需要指定非 PATH 的安装位置时，用 `BORUIX_XORRISO` 覆盖
    # （技能要求：自动探测必须同时提供**显式覆盖**手段）。
    override = os.environ.get("BORUIX_XORRISO")
    if override and os.path.isfile(override):
        return override
    return "xorriso"


XORRISO = _find_xorriso()
