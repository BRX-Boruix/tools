#!/usr/bin/env python3
"""门禁：数学核心的宿主对照验证器必须**真的跑**，且全部函数落在 B 档（≤1 ulp）内。

为什么需要：tools/checks/math_verify/verify.rs 一直存在，但它是个**独立 Rust 程序**，
不在任何自动入口里 —— "存在但没人跑"，而"没跑"与"通过"在结果上无法区分（与
tools/checks/run_all.py 开头记的是同一条教训）。

判据：编译 → 运行 → 解析它自己打印的「超 B 档（>1 ulp）的函数」列表，必须为空。
**不靠退出码**：该程序无论超没超都退 0（它是一份对照报告，不是断言程序）。
"""
import os
import re
import subprocess
import sys
import tempfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SRC = os.path.join(ROOT, "tools", "checks", "math_verify", "verify.rs")


def main():
    if not os.path.isfile(SRC):
        print("[math-verify] FAIL: 找不到 %s" % SRC)
        return 1
    tmp = tempfile.mkdtemp(prefix="math-verify-")
    exe = os.path.join(tmp, "verify.exe")
    log = os.path.join(tmp, "build.log")
    with open(log, "w", encoding="utf-8") as fh:
        rc = subprocess.run(
            ["rustc", "-O", "--edition", "2021", SRC, "-o", exe],
            stdout=fh, stderr=subprocess.STDOUT, timeout=600,
        ).returncode
    if rc != 0 or not os.path.isfile(exe):
        with open(log, encoding="utf-8", errors="replace") as fh:
            print("[math-verify] FAIL: rustc 编译失败（rc=%d）" % rc)
            print(fh.read()[-2000:])
        return 1
    out = os.path.join(tmp, "run.log")
    with open(out, "w", encoding="utf-8") as fh:
        subprocess.run([exe], stdout=fh, stderr=subprocess.STDOUT, timeout=600)
    text = open(out, encoding="utf-8", errors="replace").read()
    m = re.search(r"超 B 档（>1 ulp）的函数：\[(.*?)\]", text)
    if not m:
        print("[math-verify] FAIL: 输出里没有「超 B 档」那一行，无法判定")
        print(text[-1500:])
        return 1
    over = [x.strip() for x in m.group(1).split(",") if x.strip()]
    pass_line = re.search(r"达标函数数 = (\d+) / (\d+)", text)
    if over:
        print("[math-verify] FAIL: 以下函数超出 B 档（>1 ulp）：%s" % ", ".join(over))
        return 1
    print("[math-verify] OK: %s" % (pass_line.group(0) if pass_line else "全部落在 B 档内"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
