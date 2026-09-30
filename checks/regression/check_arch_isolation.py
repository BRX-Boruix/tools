#!/usr/bin/env python3
"""PRE-3: 静态检查——中立层不得依赖具体实现（ADR-050 / ADR-007）。

规则：中立层目录下的 `.rs` 与 `Cargo.toml` 不得出现对具体实现的依赖：
`use efi::` / `use x86_64::` / `extern crate efi` / 清单里的 `efi = ...`、`x86_64 = ...`。

用法：check_arch_isolation.py [--root <仓库根>]（默认按脚本位置推断 liftoff 仓库）
退出码：0 = 干净；1 = 发现违规（逐条打印 文件:行号:内容）。
"""

import argparse
import re
import sys
from pathlib import Path

NEUTRAL_DIRS = [
    # 只扫抽象本身；嵌套的 `crates/firmware/current` 是**选择器层**，本来就该依赖实现。
    'crates/firmware/src',
    'crates/firmware/Cargo.toml',
    'crates/arch/arch',
    'crates/mm',
    'crates/fs',
    'crates/driver',
    'crates/loader',
    'crates/utils',
    'crates/protocol/limine',
]

FORBIDDEN = [
    (re.compile(r'\buse\s+efi\s*::'), 'use efi::（中立层不得依赖 UEFI 实现）'),
    (re.compile(r'\buse\s+x86_64\s*::'), 'use x86_64::（中立层不得依赖架构实现）'),
    (re.compile(r'\bextern\s+crate\s+efi\b'), 'extern crate efi'),
    (re.compile(r'\bextern\s+crate\s+x86_64\b'), 'extern crate x86_64'),
    (re.compile(r'^\s*efi\s*='), 'Cargo.toml 依赖 efi'),
    (re.compile(r'^\s*x86_64\s*='), 'Cargo.toml 依赖 x86_64'),
]


def scan(root: Path) -> list[str]:
    problems = []
    for rel in NEUTRAL_DIRS:
        base = root / rel
        if base.is_file():
            targets = [base]
        elif base.is_dir():
            targets = sorted(p for p in base.rglob('*') if p.is_file())
        else:
            continue
        for path in targets:
            if path.suffix not in ('.rs', '.toml') or not path.is_file():
                continue
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                for pattern, why in FORBIDDEN:
                    if pattern.search(line):
                        problems.append('%s:%d: %s  <- %s' % (path.relative_to(root), number, line.strip(), why))
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    default_root = Path(__file__).resolve().parents[3] / 'liftoff'
    parser.add_argument('--root', default=str(default_root))
    args = parser.parse_args()
    root = Path(args.root)
    if not root.is_dir():
        print('FAIL: 仓库根不存在: ' + str(root))
        return 1
    problems = scan(root)
    if problems:
        for problem in problems:
            print('  VIOLATION ' + problem)
        print('FAIL: 中立层出现 ' + str(len(problems)) + ' 处实现依赖')
        return 1
    print('PASS: 中立层无实现依赖（扫描 ' + str(len(NEUTRAL_DIRS)) + ' 个目录）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
