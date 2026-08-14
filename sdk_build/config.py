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
