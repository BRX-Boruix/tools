"""从内核 ELF 提取符号表，生成 panic 栈回溯用的 symbols_generated.rs。

用法:
    python -m tools_build.symbols <内核ELF路径>

用 llvm-nm --demangle 解析内核二进制的函数符号，输出按地址升序排列的
`(起始地址, 函数名)` 静态数组，供 `kernel/src/symbols.rs` include。

仅保留 .text 段内的符号（文本段，t/T 类型），即真正"可调用"的函数入口，
避免把 .rodata/.data 里的对象符号误当作栈帧返回点。
"""

import os
import shutil
import subprocess
import sys

# 内核虚拟地址空间边界（见 kernel/linker.ld：基址 0xffffffff80000000）。
# 用它做保守过滤，避免把用户态/其它区域符号混入。
_TEXT_BASE = 0xFFFFFFFF80000000

# 与 llvm-nm 类型列中"文本段"对应的符号：小写 t 为局部，大写 T 为全局。
_TEXT_TYPES = {"t", "T"}


def find_nm() -> str:
    """查找 llvm-nm：优先 rustup 自带的，回退 PATH 中的 nm。"""
    candidates = []
    rustup = os.environ.get("RUSTUP_HOME") or os.path.expanduser("~/.rustup")
    toolchains = os.path.join(rustup, "toolchains")
    if os.path.isdir(toolchains):
        for tc in sorted(os.listdir(toolchains)):
            p = os.path.join(
                toolchains, tc, "lib", "rustlib",
                "x86_64-pc-windows-msvc", "bin", "llvm-nm.exe",
            )
            if os.path.isfile(p):
                candidates.append(p)
    if not candidates:
        p = shutil.which("llvm-nm")
        if p:
            candidates.append(p)
    if not candidates:
        p = shutil.which("nm")
        if p:
            candidates.append(p)
    if not candidates:
        sys.exit("[tools] 错误: 未找到 llvm-nm/nm，无法生成符号表")
    return candidates[0]


def parse_nm(lines):
    """解析 llvm-nm 输出，返回 [(addr, name)]（仅文本段符号）。"""
    syms = []
    for line in lines:
        line = line.rstrip("\n")
        parts = line.split(maxsplit=2)
        if len(parts) < 3:
            continue
        addr_s, typ, name = parts[0], parts[1], parts[2]
        if typ not in _TEXT_TYPES:
            continue
        try:
            addr = int(addr_s, 16)
        except ValueError:
            continue
        # 仅保留内核 .text 段范围内的符号
        if addr < _TEXT_BASE:
            continue
        if not name:
            continue
        syms.append((addr, name))
    # 按地址升序，同地址保留较短名（优先真正函数而非泛型实例）
    syms.sort(key=lambda x: (x[0], len(x[1])))
    return syms


def gen(elf: str, out: str, epoch: int = 0) -> int:
    if not os.path.isfile(elf):
        sys.exit(f"[tools] 错误: 内核 ELF 不存在: {elf}")

    nm = find_nm()
    cmd = [nm, "--demangle", "--numeric-sort", elf]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"[tools] 错误: llvm-nm 执行失败: {r.stderr}")

    syms = parse_nm(r.stdout.splitlines())
    lines = [
        "// 本文件由 tools/tools_build/symbols.py 自动生成，请勿手动编辑。",
        "// 内容为按地址升序排列的符号表：(起始地址, 函数名)。",
        f"// 提取自: {os.path.basename(elf)}，共 {len(syms)} 个函数符号。",
        "// KM13：符号纪元——与本二进制编译时的 BORUIX_SYMBOLS_BUILD_EPOCH 比对，",
        "// 不一致即快照陈旧（直连 cargo build 使用了 checked-in 快照）。",
        f"pub const SYMBOLS_EPOCH: u64 = {epoch};",
        "pub static SYMBOLS: &[(u64, &str)] = &[",
    ]
    for addr, name in syms:
        # 转义字符串中的引号/反斜杠
        esc = name.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'    (0x{addr:016x}, "{esc}"),')
    lines.append("];")

    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"[tools] 符号表已生成: {out} ({len(syms)} 个符号)")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    elf = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else None
    return gen(elf, out)


if __name__ == "__main__":
    sys.exit(main())
