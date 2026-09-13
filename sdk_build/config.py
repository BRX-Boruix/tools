"""BORUIX SDK 构建工具的公共配置。

集中管理路径常量与 .env 环境变量读取，避免各子命令重复定义。
"""

import os

# 路径
SDK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(SDK_DIR)
KERNEL_DIR = os.path.join(PROJECT_ROOT, "kernel")
LIMINE_CONF = os.path.join(SDK_DIR, "limine.conf")
ENV_FILE = os.path.join(PROJECT_ROOT, ".env")

# 构建目标（当前仅 x86_64）
TARGET = "x86_64-unknown-none"
QEMU = "qemu-system-x86_64"
OUTPUT_ISO = os.path.join(PROJECT_ROOT, "boruix.iso")

# ---------- 声卡（ICH6 / Intel HDA）----------
#
# BORUIX 的 `intel-hda` 用户态驱动接管的是 **PCI 8086:2668**（ICH6 控制器），
# 即 QEMU 的 `-device intel-hda`（控制器）+ `-device hda-output`（codec/输出）。
# 两者缺一不可：没有 `intel-hda` 就没有控制器，没有 `hda-output` 就没有 codec，
# 驱动探测不到设备就不会注册 `/devices/audio/dsp`，`audiofile` 也无从播放。
#
# 音频落盘成 WAV 而不接宿主声卡：一是无音频设备的环境（CI）也能跑，
# 二是产物可事后比对——「真的录下了什么」比「我听见了」可验证。
SOUND_CARD_CONTROLLER = "intel-hda"
SOUND_CARD_OUTPUT = "hda-output"
AUDIODEV_ID = "snd0"
OUTPUT_WAV = os.path.join(PROJECT_ROOT, "audio-out.wav")


def sound_card_args(path=None):
    """声卡相关 QEMU 参数：audiodev + intel-hda 控制器 + hda-output。

    单点定义（S15）：起机器的所有路径都从这里取，避免各子命令各写一份、
    改一处漏一处（本项目已在用户程序清单上吃过三份副本的亏）。
    `path` 为 WAV 落盘路径，默认 OUTPUT_WAV。
    """
    wav = path or OUTPUT_WAV
    return [
        "-audiodev", "wav,id=%s,path=%s" % (AUDIODEV_ID, wav),
        "-device", SOUND_CARD_CONTROLLER,
        "-device", "%s,audiodev=%s" % (SOUND_CARD_OUTPUT, AUDIODEV_ID),
    ]

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
