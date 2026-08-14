"""BORUIX SDK 构建工具公共工具函数。"""

import sys


def info(msg: str) -> None:
    print(f"[sdk] {msg}")


def err(msg: str) -> None:
    print(f"[sdk] 错误: {msg}", file=sys.stderr)
