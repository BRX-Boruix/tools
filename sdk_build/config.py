"""BORUIX SDK 构建工具的公共配置。

集中管理路径常量与 .env 环境变量读取，避免各子命令重复定义。
"""

import os

# 路径
SDK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(SDK_DIR)
BOOT_DIR = os.path.join(SDK_DIR, "boot")
LIMINE_BINARY_DIR = os.path.join(BOOT_DIR, "limine-binary")
KERNEL_DIR = os.path.join(PROJECT_ROOT, "kernel")
LIMINE_CONF = os.path.join(SDK_DIR, "limine.conf")
LIMINE_TOOL = os.path.join(LIMINE_BINARY_DIR, "limine-tool-windows-x86", "limine.exe")
ENV_FILE = os.path.join(PROJECT_ROOT, ".env")

# Limine GitHub release 二进制下载地址
LIMINE_RELEASES = "https://github.com/Limine-Bootloader/Limine/releases/download"
DEFAULT_LIMINE_VERSION = "12.5.2"

# 构建目标（当前仅 x86_64）
TARGET = "x86_64-unknown-none"
QEMU = "qemu-system-x86_64"
OUTPUT_ISO = os.path.join(PROJECT_ROOT, "boruix.iso")

# 项目 envfiles 目录（工具链等外部依赖的解压产物）
ENVFILES_DIR = os.path.join(PROJECT_ROOT, "envfiles")

# Limine fork 源码根目录（brxLimine）
BRXLIMINE_DIR = os.path.join(PROJECT_ROOT, "brxLimine")
# brxLimine 构建产物目录（含 EXT2 驱动的 BIOS stage1/2）
BRXLIMINE_BIN_DIR = os.path.join(BRXLIMINE_DIR, "bin")
BRXLIMINE_HDD_BIN = os.path.join(BRXLIMINE_BIN_DIR, "limine-bios-hdd.bin")
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
