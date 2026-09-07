"""BORUIX SDK 构建工具包。

提供 build / run / br / disk / limine_build 子命令的实现，由 `main.py` 统一注册入口。
Limine 引导完全走 brxLimine fork，不再依赖官方 limine-binary 下载。
"""

from . import br, build, run

__all__ = ["br", "build", "run"]
