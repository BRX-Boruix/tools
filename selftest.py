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
    from sdk_build import disk
    disk_path = config.PROJECT_ROOT + os.sep + "disk.img"
    # KA2（自检写盘隔离）：kernel-tests 的 m72 / ata-tail-probe 会向磁盘数据区
    # 写 scratch 标记，disk.img 跨运行持久沿用会让腐蚀在 EXT2 数据区累积——
    # 轻则 /programs 内容被标记覆盖，重则后续 boot 加载损坏 ELF 触发与被测
    # 代码无关的静默复位，污染验收结论。自检每次强制重建空白镜像：scratch
    # 只落在一次性状态上，跨启动不可见。
    if os.path.isfile(disk_path):
        os.remove(disk_path)
    disk.ensure_disk_image_exists(disk_path)

    cmd = [
        qemu,
        "-cdrom", config.OUTPUT_ISO,
        "-hda", disk_path,
        "-boot", "order=d",
        "-m", mem,
        "-display", "none",
        "-serial", "stdio",
        "-netdev", "user,id=net0",
        "-device", "e1000,netdev=net0",
        "-no-reboot",
    ]
    info(f"启动 QEMU: {' '.join(cmd)}")
    start = time.monotonic()
    try:
        with open(LOG_PATH, "w", encoding="utf-8", errors="replace") as out_f:
            subprocess.run(cmd, stdout=out_f, stderr=subprocess.STDOUT, timeout=timeout)
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

    # 内核态异常停机（interrupts.rs halt_forever 前的横幅）。此前未检测：
    # 异常停机与"内核持续运行（测试后不退出）"在退出码上不可区分（均为
    # 超时 kill），曾导致停机被误判为通过。
    res["cpu_exceptions"] = re.findall(r"CPU EXCEPTION[^\n]*", text)

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
    if res["cpu_exceptions"]:
        print(f"  [失败] CPU EXCEPTION（内核态异常停机）{len(res['cpu_exceptions'])} 处:")
        for e in res["cpu_exceptions"][:10]:
            print(f"    {e}")

    # 判定
    #
    # rc 语义：0 = QEMU 自行退出；124 = 运行超时被强制终止；其它 = 异常退出。
    #
    # **约定（本仓库既有传统，多处已成文）**：自检跑完后内核不退出而是常驻空转，
    # 因此 **“收敛后 rc=124” 是正常终态**（drv1.md / loader1.md / klib1.md 均已登记）。
    #
    # 但 **“半途 rc=124” 是真失败**：内核挂死时既无 PANIC 也无 EXCEPTION，
    # 此前判定只看那三个字符串，于是挂死被静默算作“通过”——那是伪绿（S09/S10）。
    #
    # 区分依据：收敛的套件会跑到最后一个测试块。**尾标必须是「当前序列真正
    # 的最后完成标记」**（S09 实证修正，2026-09-27）：旧尾标 ("test-fast4",
    # "test-drv1", "test-loader", "test-vfs-m65") 里后三个是**旧序列的中段
    # 块名**——`any()` 语义下，套件死在它们**之后**、fast4 **之前**（如 SMP
    # 段挂死）时，日志里仍含旧块名 → 伪绿。现行序列的最后完成标记是
    # `[test-fast4] process N exit(code=0) -- 0 = all writes ok`（main.rs
    # 测试序列末段的唯一完成短语，其后的 test_waitpid_e2e 按设计 park 至
    # 看门狗收割，即 rc=124 的「既有常驻空转终态」本体）。若未来序列尾部
    # 变更，**必须同步本尾标**——见 sdk 仓 selftest.py 头部约定。
    if rc == 124:
        tail_markers = ("0 = all writes ok", "[test-waitpid-e2e]")
        reached_tail = any(m in res["text"] for m in tail_markers)
        if not reached_tail:
            err(
                f"判定：测试失败（QEMU 超时 {args.timeout}s 且未触及序列尾部——"
                "套件半途截断，内核可能挂死或预算不足）"
            )
            return 1
        info("判定：套件已收敛至尾部，rc=124 属既有常驻空转终态（非失败）")
    elif rc != 0:
        err(f"判定：测试失败（QEMU 异常退出码 {rc}）")
        return 1

    failed = bool(res["panics"] or res["assert_fails"] or res["cpu_exceptions"])
    if failed:
        err("判定：测试失败（存在 PANIC / assert 失败 / CPU EXCEPTION）")
        return 1
    if not res["test_blocks"]:
        err("判定：日志中未捕获任何 [test-*] 输出（构建可能未启用 kernel-tests）")
        return 2
    info("判定：通过（无 PANIC / assert 失败，且捕获到自检输出）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
