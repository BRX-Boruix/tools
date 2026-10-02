#!/usr/bin/env python3
"""离线自检：`tools_build/config.py` 的路径是否**派生**而非写死（PRE-3，**S01**）。

为什么需要：S01 要求"零硬编码路径" —— 但**靠人看代码是会漏的**。
这个检查把它变成**机器可判**的，其中最关键的一条是**行为性**的：
**换一个工作目录，`PROJECT_ROOT` 必须一模一样**（写死相对路径或依赖 cwd 的实现会在这里露馅）。

退出码：0 = 全部通过；1 = 有失败。
"""

import os
import re
import subprocess
import sys
import tempfile

TOOLS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, TOOLS_ROOT)

from tools_build import config  # noqa: E402

CONFIG_SOURCE = os.path.join(TOOLS_ROOT, "tools_build", "config.py")

# 绝对路径字面量：Windows 盘符、Unix 家目录/系统目录。
ABSOLUTE_LITERAL = re.compile(r"""["'](?:[A-Za-z]:[\\/]|/(?:home|usr|Users|opt)/)""")


def main() -> int:
    failures = []

    def check(label, condition, detail=""):
        if condition:
            print("  ok   " + label)
        else:
            print("  FAIL " + label + ("  " + detail if detail else ""))
            failures.append(label)

    with open(CONFIG_SOURCE, encoding="utf-8") as handle:
        source = handle.read()

    print("== 源码里没有绝对路径字面量 ==")
    hit = ABSOLUTE_LITERAL.search(source)
    check("没有 `C:\\...` / `/home/...` 之类的字面量", hit is None,
          ("实得 %r" % hit.group(0)) if hit else "")

    print("== 根目录派生自 __file__ ==")
    check("源码里出现 __file__", "__file__" in source, "没有 __file__，说明根目录可能写死了")

    print("== 关键常量必须是绝对路径（不依赖 cwd）==")
    for name in ("TOOLS_DIR", "PROJECT_ROOT", "OUTPUT_ISO", "ENVFILES_DIR"):
        value = getattr(config, name, None)
        check("%s 是绝对路径" % name, bool(value) and os.path.isabs(value), "实得 %r" % (value,))

    print("== PROJECT_ROOT 下确实有该有的东西 ==")
    # **布局要说对**：`tools_build` 在 `TOOLS_DIR` 下，不是直接在 `PROJECT_ROOT` 下
    # （我第一次就写错了这条断言）。`PROJECT_ROOT` 下应有仓库根的那些子目录。
    for name in ("docs",):
        check("PROJECT_ROOT 下有 %s" % name,
              os.path.isdir(os.path.join(config.PROJECT_ROOT, name)),
              "实得 %r" % (config.PROJECT_ROOT,))
    check("TOOLS_DIR 下就是 tools_build",
          os.path.isdir(os.path.join(config.TOOLS_DIR, "tools_build")),
          "实得 %r" % (config.TOOLS_DIR,))

    print("== **行为性**：换 cwd 结果不变 ==")
    probe = "import sys; sys.path.insert(0, %r); from tools_build import config; print(config.PROJECT_ROOT)" % TOOLS_ROOT
    with tempfile.TemporaryDirectory() as elsewhere:
        result = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=elsewhere, capture_output=True, text=True,
        )
        if result.returncode != 0:
            check("在别的目录下也能导入 config", False, result.stderr.strip()[-200:])
        else:
            check("在别的目录下也能导入 config", True)
            check("**PROJECT_ROOT 与当前一致**",
                  result.stdout.strip() == config.PROJECT_ROOT,
                  "别处得到 %r，这里是 %r" % (result.stdout.strip(), config.PROJECT_ROOT))

    if failures:
        print("FAIL: %d 项未通过" % len(failures))
        return 1
    print("PASS: config 路径派生（S01）离线自检全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
