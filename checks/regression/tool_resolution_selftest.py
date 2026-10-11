#!/usr/bin/env python3
"""离线自检：`tools_build/toolchain.py`（**不需要 QEMU**）。

为什么需要：工具名直接交给 `subprocess` 在 Windows 上不可靠——`CreateProcess` 只对**不带点**的
名字补 `.exe`。`cargo` 正常，而 `ld.lld` 的 `.lld` 被当成扩展名、不再补 `.exe`，于是
`subprocess.run(["ld.lld", ...])` 直接 `FileNotFoundError`（本机 Python 3.14.7 实测；
`shutil.which("ld.lld")` 却找得到它）。本检查用**临时目录里的假工具**复现该形状，
不依赖本机装了什么。

退出码：0 = 全部通过；1 = 有失败。
"""
import os
import shutil
import sys
import tempfile

TOOLS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, TOOLS_ROOT)

from tools_build import toolchain  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print("[ok]   %s" % name)
    else:
        print("[FAIL] %s %s" % (name, detail))
        FAILS.append(name)


def main():
    with tempfile.TemporaryDirectory() as d:
        # 造一个**带点**的假工具（形状同 ld.lld）：只有 .exe 实体，没有同名无扩展名文件。
        exe = os.path.join(d, "fake.tool.exe")
        with open(exe, "w") as f:
            f.write("")
        os.chmod(exe, 0o755)
        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = d + os.pathsep + old_path
        try:
            got = toolchain.resolve_tool("fake.tool")
            check("带点的名字解析到绝对路径", os.path.isabs(got), "got=%r" % (got,))
            check("解析结果确实存在", os.path.isfile(got), "got=%r" % (got,))
            check("解析结果就是那个 .exe",
                  os.path.normcase(got) == os.path.normcase(exe),
                  "got=%r want=%r" % (got, exe))

            # 不存在的工具：必须给可操作的报错，而不是裸 traceback。
            try:
                toolchain.resolve_tool("definitely.not.here")
                check("缺失工具抛 RuntimeError", False, "没有抛异常")
            except RuntimeError as e:
                check("缺失工具抛 RuntimeError", True)
                check("报错含工具名", "definitely.not.here" in str(e), "msg=%r" % (str(e),))

            # 显式覆盖：指向存在 / 不存在的文件。
            os.environ["FAKE_TOOL_OVERRIDE"] = exe
            check("覆盖生效",
                  os.path.normcase(toolchain.resolve_tool("whatever", "FAKE_TOOL_OVERRIDE"))
                  == os.path.normcase(exe))
            os.environ["FAKE_TOOL_OVERRIDE"] = os.path.join(d, "nope.exe")
            try:
                toolchain.resolve_tool("whatever", "FAKE_TOOL_OVERRIDE")
                check("覆盖指向不存在文件时抛错", False, "没有抛异常")
            except RuntimeError:
                check("覆盖指向不存在文件时抛错", True)
        finally:
            os.environ["PATH"] = old_path
            os.environ.pop("FAKE_TOOL_OVERRIDE", None)

    if FAILS:
        print("[tool_resolution] FAILED: %d" % len(FAILS))
        return 1
    print("[tool_resolution] PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())