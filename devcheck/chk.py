"""内核与用户态 crate 的编译检查入口。

用法：
    python tools/devcheck/chk.py kernel          # 完整内核构建（debug）
    python tools/devcheck/chk.py kernel-tests    # 带 kernel-tests feature 的类型检查
    python tools/devcheck/chk.py test-features   # 逐个 `kernel-test*` feature 的 cargo check
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
    # 日志名不能用原始路径：crate 参数可能是 kernel/crates/task 这种相对路径，
    # 分隔符会把文件名拆成子目录。
    safe = name.replace("/", "_").replace("\\", "_")
    log = os.path.join(OUT, "crate_" + safe + ".txt")
    cmd = ["cargo", "build",
           "--manifest-path", os.path.join(config.PROJECT_ROOT, name, "Cargo.toml"),
           "--target", config.TARGET, "--release"]
    with open(log, "w", encoding="utf-8") as fh:
        rc = subprocess.run(cmd, cwd=config.PROJECT_ROOT, env=config.userspace_env(),
                            stdout=fh, stderr=subprocess.STDOUT).returncode
    print("%s rc=%d  (log: %s)" % (name, rc, log))
    return rc


def _kernel_test_features():
    """从 `kernel/Cargo.toml` 的 `[features]` 里读出全部 `kernel-test*` feature。

    为什么从清单读而不是硬编码：硬编码清单本身就是第二个漂移源——新加的停机验收
    feature 会被漏掉，于是它「从来没编译过」也不会有人知道（2026-10-25 实测：
    `kernel-test-m5` 下的 derive-mt 夹具引用了不存在的 `nr`，长期无人发现）。
    """
    import re
    path = os.path.join(config.KERNEL_DIR, "crates", "kernel", "Cargo.toml")
    feats = []
    in_features = False
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            t = line.strip()
            if t.startswith("[") and t.endswith("]"):
                in_features = t == "[features]"
                continue
            if not in_features or not t or t.startswith("#"):
                continue
            m = re.match(r"([A-Za-z0-9_-]+)\s*=", t)
            if m and m.group(1).startswith("kernel-test"):
                feats.append(m.group(1))
    return feats


def _test_features():
    """对每个 `kernel-test*` feature 做一次 `cargo check`。

    用 check 而不是 build：目标缺陷是「条件编译的测试代码编不过」，check 就能抓到，
    且比完整构建快得多；链接期问题由 `kernel-tests` 那条完整构建覆盖。
    """
    feats = _kernel_test_features()
    if not feats:
        print("未在 Cargo.toml 里找到任何 kernel-test* feature——清单解析失效（拒绝报 OK）")
        return 2
    os.makedirs(OUT, exist_ok=True)
    bad = []
    for feat in feats:
        log = os.path.join(OUT, "feat_" + feat + ".txt")
        # 与 build.py 同一契约：build script 要读 BORUIX_SYMBOLS_EPOCH。
        env = dict(os.environ, BORUIX_SYMBOLS_EPOCH="0")
        cmd = ["cargo", "check", "--target", config.TARGET, "--features", feat]
        with open(log, "w", encoding="utf-8") as fh:
            rc = subprocess.run(cmd, cwd=config.KERNEL_DIR, env=env,
                                stdout=fh, stderr=subprocess.STDOUT).returncode
        print("  %-26s rc=%d  (%s)" % (feat, rc, log))
        if rc != 0:
            bad.append(feat)
    print("test-features：%d 个 feature，失败 %d" % (len(feats), len(bad)))
    if bad:
        print("  失败：" + ", ".join(bad))
        return 1
    return 0


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
    if what == "test-features":
        return _test_features()
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
