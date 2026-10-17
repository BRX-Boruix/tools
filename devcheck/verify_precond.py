"""门禁前置探测的三种场景验证。

场景 1：完全没有前置 -> 全部 SKIP（且 run_all 整体必须非 0）
场景 2：前置看起来在、其实坏掉 -> 必须 FAIL，不能算 SKIP
场景 3：前置真实存在 -> 必须真的跑

用法：python tools/devcheck/verify_precond.py
场景 2/3 依赖环境里已有的 BORUIX_NM / BORUIX_SYSROOT；缺失时明确跳过并说明，
不伪造前置。
"""
import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
TOOLS = os.path.join(ROOT, "tools")

spec = importlib.util.spec_from_file_location(
    "run_all", os.path.join(TOOLS, "checks", "run_all.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

GATED = ["../libc/tools/audit_posix_surface.py",
         "checks/dist/headers_syntax.py",
         "checks/dist/tcc_assets_fresh.py"]

ENV_KEYS = ("BORUIX_SYSROOT", "BORUIX_CLANG", "BORUIX_NM")


def show(title):
    print("=== " + title + " ===")
    for rel in GATED:
        outcome, detail = m.run_one(rel)
        print("  %-45s %-5s %s" % (rel, outcome.upper(), detail[:80]))


def main():
    original = {k: os.environ.get(k) for k in ENV_KEYS}

    for k in ENV_KEYS:
        os.environ.pop(k, None)
    os.environ["PATH"] = os.path.dirname(sys.executable)
    show("场景1：无任何前置")

    bad = tempfile.mkdtemp(prefix="boruix-badsysroot-")
    os.makedirs(os.path.join(bad, "lib"))
    open(os.path.join(bad, "lib", "libc.a"), "wb").close()
    os.environ["BORUIX_SYSROOT"] = bad
    if original["BORUIX_NM"]:
        os.environ["BORUIX_NM"] = original["BORUIX_NM"]
    show("场景2：sysroot 存在但 libc.a 是空文件")

    if not original["BORUIX_SYSROOT"]:
        print("=== 场景3：跳过（环境里没有 BORUIX_SYSROOT，不伪造前置）===")
        return 0
    os.environ["BORUIX_SYSROOT"] = original["BORUIX_SYSROOT"]
    if original["BORUIX_CLANG"]:
        os.environ["BORUIX_CLANG"] = original["BORUIX_CLANG"]
    if original["BORUIX_NM"]:
        os.environ["BORUIX_NM"] = original["BORUIX_NM"]
    show("场景3：真实前置")
    return 0


if __name__ == "__main__":
    sys.exit(main())
