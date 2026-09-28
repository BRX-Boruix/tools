"""BORUIX 系统工具公共工具函数。"""

import sys


def info(msg: str) -> None:
    print(f"[tools] {msg}")


def err(msg: str) -> None:
    print(f"[tools] 错误: {msg}", file=sys.stderr)
