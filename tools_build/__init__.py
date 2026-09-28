"""BORUIX 系统工具包（tools/，系统集成与验收；非第三方 SDK）。

提供 b3p / build / run / br / disk / limine_build 子命令的实现，由 `main.py` 统一注册入口。
Limine 引导完全走 brxLimine fork，不再依赖官方 limine-binary 下载。
"""

from . import b3p, br, build, disk, limine_build, run

__all__ = ["b3p", "br", "build", "disk", "limine_build", "run"]
