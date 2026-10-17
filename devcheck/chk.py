"""内核与用户态 crate 的编译检查入口。

用法：
    python tools/devcheck/chk.py kernel          # 完整内核构建（debug）
    python tools/devcheck/chk.py kernel-tests    # 带 kernel-tests feature 的类型检查
    python tools/devcheck/chk.py crate <name>    # 单个用户态 crate 的 release 构建

编译日志写入 tools/devcheck/.out/（已 gitignore）。
退出码：0 = 通过，非 0 = 失败。
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(HERE, ".out")

# 工作区根由本文件位置推出，因此不再依赖调用者的 cwd
sys.path.insert(0, os.path.join(ROOT, "tools"))
from tools_build import build, config  # noqa: E402

USAGE_RC = 2


def _crate(name):
    os.makedirs(OUT, exist_ok=True)
    log = os.path.join(OUT, "crate_" + name + ".txt")
    cmd = ["cargo", "build",
           "--manifest-path", os.path.join(config.PROJECT_ROOT, name, "Cargo.toml"),
           "--target", config.TARGET, "--release"]
    with open(log, "w", encoding="utf-8") as fh:
        rc = subprocess.run(cmd, cwd=config.PROJECT_ROOT, env=config.userspace_env(),
                            stdout=fh, stderr=subprocess.STDOUT).returncode
    print("%s rc=%d  (log: %s)" % (name, rc, log))
    return rc


def main(argv):
    if not argv:
        print(__doc__)
        return USAGE_RC
    what = argv[0]
    if what == "kernel":
        rc = build._cargo_build_kernel(release=False)
        print("KERNEL_RC %d" % rc)
        return rc
    if what == "kernel-tests":
        rc = build._cargo_build_kernel(release=False, use_tests=True)
        print("KERNEL_TESTS_RC %d" % rc)
        return rc
    if what == "crate":
        if len(argv) != 2:
            print("用法：chk.py crate <crate 目录名>")
            return USAGE_RC
        return _crate(argv[1])
    print("未知子命令：%s" % what)
    print(__doc__)
    return USAGE_RC


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
