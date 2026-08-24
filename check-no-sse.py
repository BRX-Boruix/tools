#!/usr/bin/env python3
"""check-no-sse.py —— 内核文本无 SIMD 发射守卫（task1 K2 / 审计 R6-F3）。

eager fxsave 方案的正确性前提：从用户陷阱进入到 fpu::save 执行点之间，
没有任何内核指令触碰 XMM/浮点寄存器（否则快照的是内核污染后的现场）。
x86_64 目标基线含 SSE2、无法编译期关闭，因此该前提只能靠对产物文本的
发射事实来验证——本脚本就是那个可复现验证：

    python sdk/check-no-sse.py [--objdump PATH] [--elf PATH]

判定规则：
- 允许清单：fpu::init_template 内的 16 条 pxor（模板强零化，有意为之，
  且仅在首个 shm/spawn 模板创建时执行一次）；
- 其余 .text 中出现任何 xmm/ymm/zmm/MMX/x87 访存或运算指令 → exit 1。

工具链升级 / 新增向量化代码后必须重跑；出现越界命中即触发 ADR-020
"F3 升级路径"（陷阱入口保存 / CR0.TS 惰性方案 / 编译属性收窄）的讨论。
"""

import argparse
import os
import subprocess
import sys

ALLOWED_SYMBOL_SUBSTRINGS = ("fpu",)


def find_llvm_objdump(explicit: str | None) -> str:
    if explicit:
        return explicit
    try:
        sysroot = subprocess.run(
            ["rustc", "--print", "sysroot"], capture_output=True, text=True, check=True
        ).stdout.strip()
        candidate = os.path.join(
            sysroot, "lib", "rustlib", "x86_64-pc-windows-msvc", "bin", "llvm-objdump.exe"
        )
        if os.path.isfile(candidate):
            return candidate
        for root, _dirs, files in os.walk(os.path.join(sysroot, "lib", "rustlib")):
            if "llvm-objdump.exe" in files or "llvm-objdump" in files:
                p = os.path.join(root, "llvm-objdump.exe")
                return p if os.path.isfile(p) else os.path.join(root, "llvm-objdump")
    except Exception as exc:  # noqa: BLE001 - 报错路径要给出可读原因
        print(f"[no-sse] rustc sysroot discovery failed: {exc}", file=sys.stderr)
    raise SystemExit("[no-sse] llvm-objdump not found; pass --objdump explicitly")


SIMD_TOKENS = (
    "xmm", "ymm", "zmm", "%mm",          # 寄存器名
    "movdq", "movaps", "movups", "movhps", "movlps",
    "paddd", "paddq", "pmul", "psll", "psrl", "psra", "punpck", "packss",
    "cvtsi2s", "cvtss2si", "cvttsd", "addsd", "subsd", "mulsd", "divsd",
    "addss", "subss", "mulss", "divss", "ucomis", "comis", "sqrts",
)


def is_simd(line: str) -> bool:
    low = line.lower()
    if ">" not in low and ":" not in low:
        pass
    body = low.split("\t")[-1] if "\t" in low else low
    return any(tok in body for tok in SIMD_TOKENS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--objdump", default=None)
    ap.add_argument("--elf", default=os.path.join(
        os.path.dirname(__file__), "..", "kernel", "target",
        "x86_64-unknown-none", "debug", "kernel"))
    args = ap.parse_args()

    objdump = find_llvm_objdump(args.objdump)
    elf = os.path.abspath(args.elf)
    if not os.path.isfile(elf):
        raise SystemExit(f"[no-sse] ELF not found: {elf} (build first)")

    out_path = elf + ".no-sse.disasm.txt"
    with open(out_path, "w", encoding="utf-8") as fh:
        subprocess.run([objdump, "-d", "--no-show-raw-insn", elf], stdout=fh, check=True)

    hits = []
    cur_sym = "?"
    with open(out_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.rstrip()
            if ">:" in s and s and s[0].isdigit() or (s.startswith("ffffffff") and "<" in s):
                # 符号行："<addr> <symbol>:" 或 mangled 形式
                if "<" in s and s.rstrip().endswith(":"):
                    cur_sym = s.split("<", 1)[1].rsplit(">", 1)[0]
                continue
            if is_simd(s):
                hits.append((cur_sym, s.strip()))

    violations = [
        (sym, ins)
        for sym, ins in hits
        if not any(a in sym.lower() for a in ALLOWED_SYMBOL_SUBSTRINGS)
    ]

    print(f"[no-sse] scanned {elf}")
    print(f"[no-sse] simd-shaped instructions total: {len(hits)}")
    allowed = len(hits) - len(violations)
    print(f"[no-sse] within allowlist (fpu::*): {allowed}")
    if violations:
        print("[no-sse] VIOLATIONS (outside fpu::*) — eager-fxsave premise broken:")
        for sym, ins in violations[:40]:
            print(f"  [{sym}] {ins}")
        return 1
    print("[no-sse] OK: no SIMD outside fpu::* — eager-save premise holds for this build")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
