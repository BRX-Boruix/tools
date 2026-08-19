#!/usr/bin/env python3
"""BORUIX 内核自动化测试脚本。

流程：
  1. 调用 main.py build --test 构建带自检测试（kernel-tests feature）的内核 + ISO；
  2. 用 QEMU 无头运行（-display none，串口输出重定向到文件）；
  3. 解析串口日志，统计各 [test-*] 模块输出，检测 PANIC / assert 失败，判定通过与否。

QEMU 运行阶段默认超时 60 秒（--timeout 可调），超时自动终止进程。

用法:
    python selftest.py [--timeout 60] [--rebuild]
      --timeout   QEMU 运行阶段超时秒数（默认 60）
      --rebuild   强制完整重建（默认增量构建）
      --mem       QEMU 内存大小（默认 128M）
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import time

from sdk_build import build, config
from sdk_build.util import err, info

LOG_PATH = os.path.join(config.PROJECT_ROOT, "_selftest_qemu.log")
QEMU = "qemu-system-x86_64"


def find_qemu() -> str:
    env = config.load_env()
    qemu_dir = env.get("QEMU_DIR")
    exe = QEMU + ".exe"
    if qemu_dir:
        cand = os.path.join(qemu_dir, exe)
        if os.path.isfile(cand):
            return cand
    on_path = shutil.which(QEMU)
    if on_path:
        return on_path
    return ""


def run_qemu(qemu: str, mem: str, timeout: int) -> tuple:
    """启动 QEMU 无头运行，串口写入 LOG_PATH；超时 kill。返回 (rc, elapsed)。"""
    if os.path.isfile(LOG_PATH):
        os.remove(LOG_PATH)
    # -serial file: 在 Windows 下对路径分隔符敏感，统一用正斜杠
    log_arg = os.path.normpath(LOG_PATH).replace("\\", "/")
    cmd = [
        qemu,
        "-cdrom", config.OUTPUT_ISO,
        "-m", mem,
        "-display", "none",
        "-serial", f"file:{log_arg}",
        "-no-reboot",
    ]
    info(f"启动 QEMU: {' '.join(cmd)}")
    info(f"超时 {timeout}s，串口输出 -> {LOG_PATH}")
    start = time.monotonic()
    try:
        subprocess.run(cmd, timeout=timeout)
        rc = 0
    except subprocess.TimeoutExpired:
        info(f"QEMU 运行超时（>{timeout}s），自动终止")
        # Windows 上 timeout 抛异常时子进程可能仍在运行，尝试结束
        subprocess.run(
            ["taskkill", "/F", "/IM", QEMU + ".exe"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        rc = 124
    except KeyboardInterrupt:
        err("用户中断")
        rc = 130
    elapsed = time.monotonic() - start
    return rc, elapsed


def analyze_log() -> dict:
    """解析串口日志，返回统计信息。"""
    res = {
        "panics": [],
        "assert_fails": [],
        "test_blocks": [],
        "passed_blocks": [],
        "failed_blocks": [],
        "text": "",
    }
    if not os.path.isfile(LOG_PATH):
        return res
    with open(LOG_PATH, encoding="utf-8", errors="replace") as f:
        text = f.read()
    res["text"] = text

    # PANIC / 异常捕获
    res["panics"] = re.findall(r"KERNEL PANIC[^\n]*|PANIC[^\n]*|panicked at[^\n]*", text)

    # assert 失败（Rust 惯用格式）
    res["assert_fails"] = re.findall(r"assertion[^\n]*failed[^\n]*", text)

    # 各测试块：[xxx] 前缀
    blocks = set(re.findall(r"\[([a-z][\w-]*)\]", text))
    res["test_blocks"] = sorted(b for b in blocks if b.startswith("test"))

    # 显式 PASS 标志
    res["passed_blocks"] = sorted(
        set(re.findall(r"\[test-[\w-]+\][^\n]*PASS", text))
    )
    return res


def main() -> int:
    parser = argparse.ArgumentParser(description="BORUIX 内核自动化测试")
    parser.add_argument("--timeout", type=int, default=60, help="QEMU 超时秒数（默认 60）")
    parser.add_argument("--rebuild", action="store_true", help="强制完整重建")
    parser.add_argument("--mem", default="128M", help="QEMU 内存（默认 128M）")
    args = parser.parse_args()

    # 1. 构建带自检的内核 + ISO
    build_args = argparse.Namespace(test=True)
    info("=" * 60)
    info("步骤 1/2：构建带自检测试的内核 + ISO")
    info("=" * 60)
    if args.rebuild:
        info("强制完整重建（--rebuild）")
    t0 = time.monotonic()
    rc = build.cmd(build_args)
    if rc != 0:
        err("构建失败，中止测试")
        return rc
    info(f"构建完成，耗时 {time.monotonic() - t0:.1f}s")

    # 2. 定位 QEMU 并运行
    info("=" * 60)
    info(f"步骤 2/2：QEMU 无头运行（超时 {args.timeout}s）")
    info("=" * 60)
    qemu = find_qemu()
    if not qemu:
        err(f"未找到 {QEMU}，请检查 .env 的 QEMU_DIR 或 PATH")
        return 1

    rc, elapsed = run_qemu(qemu, args.mem, args.timeout)
    info(f"QEMU 退出码 {rc}，运行耗时 {elapsed:.1f}s")

    # 3. 分析结果
    info("=" * 60)
    info("分析串口日志")
    info("=" * 60)
    res = analyze_log()
    print(f"  测试块: {len(res['test_blocks'])} 个 -> {res['test_blocks']}")
    print(f"  显式 PASS: {len(res['passed_blocks'])} 处")
    for p in res["passed_blocks"]:
        print(f"    {p}")
    if res["panics"]:
        print(f"  [失败] PANIC {len(res['panics'])} 处:")
        for p in res["panics"][:10]:
            print(f"    {p}")
    if res["assert_fails"]:
        print(f"  [失败] assert 失败 {len(res['assert_fails'])} 处:")
        for a in res["assert_fails"][:10]:
            print(f"    {a}")

    # 判定
    failed = bool(res["panics"] or res["assert_fails"])
    if failed:
        err("判定：测试失败（存在 PANIC 或 assert 失败）")
        return 1
    if not res["test_blocks"]:
        err("判定：日志中未捕获任何 [test-*] 输出（构建可能未启用 kernel-tests）")
        return 2
    info("判定：通过（无 PANIC / assert 失败，且捕获到自检输出）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
